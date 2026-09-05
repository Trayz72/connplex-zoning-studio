"""Basic regression coverage for layout_engine.py — the auto-layout
generator and the manual "Add Zone" placer. Not exhaustive; targets the real
behaviors this session's work depends on (screens-only auto-layout,
zero-gap screen adjacency, place_single_zone's collision-safety and
division-by-zero guard) so they can't silently regress."""
import layout_engine

# A plain 100x60 ft rectangle, far bigger than the smallest auditorium
# preset (35_SEAT needs 24x35 min) — enough room for several screens without
# needing a real uploaded floor plan.
RECT_BOUNDARY = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]


def _usable():
    return layout_engine.compute_usable_area(RECT_BOUNDARY, [])


def test_generate_candidates_returns_two_strategies():
    candidates = layout_engine.generate_candidates(RECT_BOUNDARY, [], {})
    assert len(candidates) == 2
    strategies = {c["strategy"] for c in candidates}
    assert strategies == {"MAX_SEATS_PER_SCREEN", "MAX_SCREEN_COUNT"}


def test_auto_layout_places_real_support_zone_geometry_not_just_a_number():
    """This round's redesign: generate_candidate now places screens first,
    then Box Office/F&B/Washroom/BOH with real geometry (not just an
    aggregate circulation_area_sqft number), then Foyer as the true
    leftover remainder. PASSAGE stays auto-layout-excluded (Foyer now
    serves its old connective purpose) — it's still available via manual
    Add Zone (place_single_zone)."""
    for candidate in layout_engine.generate_candidates(RECT_BOUNDARY, [], {}):
        room_types = {r["room_type"] for r in candidate["rooms"]}
        assert any(rt.startswith("AUDITORIUM") for rt in room_types), "expected at least one auditorium to fit in a 100x60 rect"
        for support_type in ("BOX_OFFICE", "FNB", "WASHROOM", "BOH"):
            assert support_type in room_types, f"expected auto-layout to place a real {support_type}, got room types {room_types}"
        assert "PASSAGE" not in room_types, "PASSAGE should stay excluded from auto-layout — Foyer is now the connective remainder"
        for room in candidate["rooms"]:
            assert len(room["geometry_points_ft"]) >= 3, f"{room['room_type']} has no real placed geometry"


def test_adjacent_auditoriums_share_a_wall_not_an_aisle_gap():
    """_neighbor_gap_ft: two auditoriums should end up touching (or within a
    couple feet, given the grid-scan step size), not separated by the full
    AISLE_CLEARANCE_FT (3.5ft) the way every other room-type pairing is."""
    candidate = next(
        c for c in layout_engine.generate_candidates(RECT_BOUNDARY, [], {"max_auditoriums": 4})
        if c["strategy"] == "MAX_SCREEN_COUNT"
    )
    rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert len(rooms) >= 2, "need at least 2 screens placed to test adjacency"

    polys = [layout_engine.poly_from_points(r["geometry_points_ft"]) for r in rooms]
    min_gap = min(
        polys[i].distance(polys[j])
        for i in range(len(polys)) for j in range(i + 1, len(polys))
    )
    assert min_gap < layout_engine.AISLE_CLEARANCE_FT, (
        f"closest two auditoriums are {min_gap}ft apart — expected near-zero (shared wall), "
        f"not the full {layout_engine.AISLE_CLEARANCE_FT}ft aisle clearance"
    )


def test_place_single_zone_screen_avoids_existing_room():
    usable = _usable()
    first, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert first is not None and warning is None

    placed_polys = [layout_engine.poly_from_points(first["geometry_points_ft"])]
    placed_types = ["AUDITORIUM"]
    second, warning2 = layout_engine.place_single_zone(
        usable, usable, [], placed_polys, placed_types, (0, 0, 100, 60), "FOYER", {}
    )
    assert second is not None and warning2 is None
    # A real collision check, not just "it returned something" — Add Zone's
    # whole point this session was replacing a blind placement that silently
    # overlapped whatever was already there.
    first_poly = placed_polys[0]
    second_poly = layout_engine.poly_from_points(second["geometry_points_ft"])
    assert first_poly.intersection(second_poly).area < 1e-6


def test_place_single_zone_honest_rejection_when_full():
    """Product Principle #4: never invent a placement that doesn't fit —
    filling the whole boundary with one auditorium leaves no room for a
    second, and place_single_zone must say so, not fabricate an overlap."""
    usable = _usable()
    huge_room = {
        "geometry_points_ft": [[0, 0], [100, 0], [100, 60], [0, 60]],
    }
    placed_polys = [layout_engine.poly_from_points(huge_room["geometry_points_ft"])]
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], placed_polys, ["AUDITORIUM"], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert room is None
    assert warning and "No space" in warning


def test_place_single_zone_support_zone_no_auditoriums_yet_no_crash():
    """Real, reproducible crash found via earlier testing (see this
    function's docstring in layout_engine.py): target_area computed from 0
    total auditorium area used to divide by zero. Placing a support zone
    with zero auditoriums placed yet must fall back to the preset's own
    minimum instead of crashing."""
    usable = _usable()
    room, warning_or_none = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "WASHROOM", {}
    )
    assert room is not None
    assert room["area_sqft"] > 0


def test_validate_rooms_catches_real_overlap():
    room_a = {
        "room_id": "a", "display_name": "Room A",
        "geometry_points_ft": [[0, 0], [20, 0], [20, 20], [0, 20]]
    }
    room_b = {
        "room_id": "b", "display_name": "Room B",
        "geometry_points_ft": [[10, 10], [30, 10], [30, 30], [10, 30]]
    }
    result = layout_engine.validate_rooms(RECT_BOUNDARY, [], [room_a, room_b])
    assert result["valid"] is False
    assert any(e["issue"] == "ROOM_OVERLAP" for e in result["errors"])


def test_validate_rooms_accepts_real_non_overlapping_layout():
    room_a = {
        "room_id": "a", "display_name": "Room A",
        "geometry_points_ft": [[0, 0], [20, 0], [20, 20], [0, 20]]
    }
    room_b = {
        "room_id": "b", "display_name": "Room B",
        "geometry_points_ft": [[25, 0], [45, 0], [45, 20], [25, 20]]
    }
    result = layout_engine.validate_rooms(RECT_BOUNDARY, [], [room_a, room_b])
    assert result["valid"] is True
    assert result["errors"] == []


# ---------- screen_wall / doors (component-placement upgrade) ----------

def test_screen_wall_and_doors_derived_from_entry_point():
    """An auditorium placed with a marked entry point should get its doors
    on the edge nearest that entry point, and its actual projection screen
    on the OPPOSITE wall — a real, reported defect this guards against: an
    earlier version put both on the same wall, meaning a patron would have
    to walk in right next to the screen. Real cinema design has patrons
    enter from the back/near wall and see the screen at the far end."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}  # far left, mid-height
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["screen_wall"] == "max_x", "screen should be on the FAR wall from the entry, not the near one"
    kinds = sorted(d["kind"] for d in room["doors"])
    assert kinds == ["ENTRY", "EXIT"]
    for door in room["doors"]:
        assert door["wall"] == "min_x", "doors belong on the near-entry wall, never the screen wall"
        assert door["width_ft"] > 0


def test_screen_wall_defaults_to_min_y_without_entry_point():
    """No entry point marked: screen_wall defaults to 'min_y' — this app's
    original hardcoded frontend assumption — so a layout with no entry data
    renders identically to before this field existed."""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["screen_wall"] == "min_y"


# ---------- per-room-type column tolerance ----------

def test_auditorium_rejects_column_enclosure_above_tolerance():
    """A column covering way more than AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO
    (2%) of the only footprint available must be rejected — a column
    mid-seating-bowl is a real defect, not something an auditorium should
    silently absorb the way a foyer can. Boundary is sized so exactly one
    35_SEAT preset fits with zero slack, forcing the engine to either use
    the column-covered fallback tier or genuinely fail — proving the cap is
    actually enforced, not just present."""
    boundary = [[0, 0], [24, 0], [24, 35], [0, 35], [0, 0]]
    big_column = {
        "points_ft": [[10, 10], [14, 10], [14, 25], [10, 25]],  # 4x15 = 60 sqft, way over 2% of ~840
        "classification": "COLUMN",
    }
    usable = layout_engine.compute_usable_area(boundary, [big_column])
    fallback = layout_engine.compute_usable_area(boundary, [big_column], exclude_classifications=("COLUMN",))
    column_polys = [layout_engine.poly_from_points(big_column["points_ft"])]
    room, warning = layout_engine.place_single_zone(
        usable, fallback, column_polys, [], [], (0, 0, 24, 35), "AUDITORIUM", {}
    )
    assert room is None
    assert warning and "No space" in warning


def test_auditorium_accepts_small_column_within_tolerance():
    """The mirror case: a small column, comfortably under the 2% cap AND
    within AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT of a wall (near the left
    wall here), should still be accepted via the column-tolerant fallback
    tier — the cap/edge rule must not have been set so aggressively it
    breaks the existing "an auditorium may enclose a small, wall-adjacent
    column" behavior."""
    boundary = [[0, 0], [24, 0], [24, 35], [0, 35], [0, 0]]
    small_column = {
        "points_ft": [[0.5, 17], [1.5, 17], [1.5, 18], [0.5, 18]],  # 1 sqft, ~0.5ft from the x=0 wall
        "classification": "COLUMN",
    }
    usable = layout_engine.compute_usable_area(boundary, [small_column])
    fallback = layout_engine.compute_usable_area(boundary, [small_column], exclude_classifications=("COLUMN",))
    column_polys = [layout_engine.poly_from_points(small_column["points_ft"])]
    room, warning = layout_engine.place_single_zone(
        usable, fallback, column_polys, [], [], (0, 0, 24, 35), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert "obstacle_note" in room


def test_auditorium_rejects_interior_column_even_under_area_ratio_cap():
    """The new, position-aware rule this round adds: a column comfortably
    under the 2% area-ratio cap (same 1 sqft size as the tolerance test
    above) but stranded in the room's true interior — more than
    AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT from every one of the room's own
    four walls — must be rejected outright, regardless of how small its
    area share is. This is the literal proof for the user's own
    requirement: "don't add screen if column doesn't appear on the
    boundary and appears inside." Before this rule existed, this exact
    dead-center geometry was accepted (see git history of this test) —
    area-ratio alone said nothing about a column sitting in the middle of
    the seating field."""
    boundary = [[0, 0], [24, 0], [24, 35], [0, 35], [0, 0]]
    center_column = {
        "points_ft": [[11.5, 17], [12.5, 17], [12.5, 18], [11.5, 18]],  # 1 sqft, dead center of the 24x35 room
        "classification": "COLUMN",
    }
    usable = layout_engine.compute_usable_area(boundary, [center_column])
    fallback = layout_engine.compute_usable_area(boundary, [center_column], exclude_classifications=("COLUMN",))
    column_polys = [layout_engine.poly_from_points(center_column["points_ft"])]
    room, warning = layout_engine.place_single_zone(
        usable, fallback, column_polys, [], [], (0, 0, 24, 35), "AUDITORIUM", {}
    )
    assert room is None, "a dead-center column must reject the placement even though its area ratio is tiny"
    assert warning and "No space" in warning


# ---------- column-grid-aware placement ----------

def test_grid_snapping_aligns_placement_to_column_grid_lines():
    """place_single_zone should snap a candidate's leading edge to a real
    detected column-grid line (layout_engine._column_grid_lines) instead of
    the fixed GRID_STEP_FT(=2.0) scan step, once at least 2 distinct grid
    lines exist per axis. The grid line here (x=21) is deliberately not a
    multiple of 2.0, and a hard obstacle blocks everything left of x=21, so
    a plain fixed-step scan would land at x=22 (the next 2ft-step position
    clear of the obstacle) while a grid-snapped scan lands exactly at
    x=21 — an unambiguous, non-coincidental proof the grid drove the
    result."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    blocker = layout_engine.poly_from_points([[0, 0], [21, 0], [21, 60], [0, 60]])
    usable = layout_engine.poly_from_points(boundary).difference(blocker)

    def col(cx, cy):
        return layout_engine.poly_from_points([[cx - 0.5, cy - 0.5], [cx + 0.5, cy - 0.5], [cx + 0.5, cy + 0.5], [cx - 0.5, cy + 0.5]])

    column_polys = [col(21, 15), col(21, 45), col(81, 15), col(81, 45)]  # 2 grid lines per axis: x={21,81}, y={15,45}

    room, warning = layout_engine.place_single_zone(
        usable, usable, column_polys, [], [], (0, 0, 100, 60), "WASHROOM", {}
    )
    assert room is not None, warning
    assert room["origin_ft"][0] == 21.0, (
        f"expected the room to snap to the x=21 column-grid line, got x={room['origin_ft'][0]} "
        f"(x=22 would mean the fixed-step scan ran instead of grid-snapping)"
    )


# ---------- PASSAGE ----------

def test_place_single_zone_passage_connects_foyer_and_auditorium():
    """A PASSAGE should be placed close to both the Foyer and the nearest
    already-placed Screen (see place_single_zone's PASSAGE branch) — real,
    evidence-based behavior from the reference floor plans this feature was
    designed against, not just "wherever a plain first-fit scan happens to
    land." Foyer/auditorium are pushed to the far side (x=200+) of a wide
    boundary, with a large empty region at x=0 that a plain scan (no
    proximity heuristic) would fill first — so a placement near x=200
    specifically proves the heuristic ran, rather than coinciding with
    first-fit's own default bottom-left-first order the way a tighter test
    geometry could."""
    boundary = [[0, 0], [300, 0], [300, 100], [0, 100], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    auditorium = layout_engine._rect(200, 0, 70, 50)
    foyer = layout_engine._rect(200, 60, 30, 20)
    placed_polys = [auditorium, foyer]
    placed_types = ["AUDITORIUM", "FOYER"]

    passage, warning = layout_engine.place_single_zone(
        usable, usable, [], placed_polys, placed_types, (0, 0, 300, 100), "PASSAGE", {"max_auditoriums": 1}
    )
    assert passage is not None, warning
    passage_poly = layout_engine.poly_from_points(passage["geometry_points_ft"])
    real_distance_sum = passage_poly.distance(auditorium) + passage_poly.distance(foyer)
    # A plain first-fit scan (no heuristic) lands at the boundary's own
    # (0, 0) corner here — real, empirically confirmed, not a guess.
    # Compare against a same-*size* rect placed at that corner (not an
    # arbitrary marker) so the comparison isolates position, not shape.
    first_fit_corner = layout_engine._rect(0, 0, passage["width_ft"], passage["depth_ft"])
    first_fit_distance_sum = first_fit_corner.distance(auditorium) + first_fit_corner.distance(foyer)
    assert real_distance_sum < first_fit_distance_sum, (
        f"expected the passage closer to the foyer/auditorium (distance sum {real_distance_sum}) than a "
        f"same-size placement at the far (0,0) corner would be ({first_fit_distance_sum}), origin was "
        f"{passage['origin_ft']} — looks like the proximity heuristic didn't run"
    )
    # A real corridor shape, not a square-ish room — min(w, h) should equal
    # the configured minimum passage width, not the generic aspect=1.6 shape
    # every other support zone uses.
    min_width_ft = layout_engine.rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT")
    assert abs(min(passage["width_ft"], passage["depth_ft"]) - min_width_ft) < 0.5


# ---------- default seat mix from the matched preset (real-file gap-closure round) ----------

def test_default_seat_config_35_seat_has_no_front_row():
    """35_SEAT's own seating_mix is PREMIUM_RECLINER + DUO_LOUNGER, not
    FRONT_LOUNGER — it must stay 100% its own primary type, not silently
    get a front-lounger row that doesn't match its real design intent."""
    preset = next(p for p in layout_engine.rules_registry.auditorium_presets() if p["id"] == "35_SEAT")
    primary, secondary, front_rows = layout_engine._default_seat_config(preset)
    assert primary == "PREMIUM_RECLINER"
    assert secondary is None
    assert front_rows is None


def test_default_seat_config_60_seat_gets_one_front_lounger_row():
    """60_SEAT's seating_mix includes FRONT_LOUNGER — matches the real
    convention observed in every real Connplex reference file this
    project's design work has been grounded in (Swati Trinity, Keshav
    Landmark, Maruti Nandan): exactly one front lounger row, bulk seating
    behind it."""
    preset = next(p for p in layout_engine.rules_registry.auditorium_presets() if p["id"] == "60_SEAT")
    primary, secondary, front_rows = layout_engine._default_seat_config(preset)
    assert primary == "FRONT_LOUNGER"
    assert secondary == "SLIDER_SOFA"
    assert front_rows == 1


def test_placed_auditorium_uses_preset_seating_mix_not_a_hardcoded_default():
    """End-to-end: a real placed auditorium's seat_estimate should actually
    reflect the matched preset's own seating_mix, not silently default to
    SLIDER_SOFA regardless of preset — the real, measured defect this round
    fixes (a 35_SEAT-tier screen getting Sofa Slider counts instead of its
    own Premium Recliner mix undercounted real seats on an actual uploaded
    file)."""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["seat_config"]["primary_seat_type_id"] in ("PREMIUM_RECLINER", "FRONT_LOUNGER")
    assert room["seat_estimate"]["seat_breakdown"]["SOFA_SLIDER"] == 0 or room["seat_config"]["secondary_seat_type_id"] == "SLIDER_SOFA"


# ---------- custom-fit fallback when no preset fits (real-file gap-closure round) ----------

def test_custom_fit_screen_used_when_no_preset_fits_but_real_area_remains():
    """A real, directly-measured defect: on a real uploaded file, the engine
    left 5,194 of 6,979 sqft of usable area (74%) completely untouched
    because no fixed preset footprint happened to fit what remained, even
    though real usable area did. Reproduced here with a 28x33 boundary —
    too short (33ft) for 35_SEAT's own length_min (35ft) and too narrow
    (28ft) for 60_SEAT's own width_min (30ft), so no preset can fit, but
    the custom-fit fallback should still use the real ~924 sqft available
    rather than placing nothing. (28x33, not the narrower shapes this test
    used before this round: a custom-fit screen's own short side must now
    clear the same 24ft floor as every real preset — see
    test_custom_fit_screen_rejects_unrealistically_narrow_shape below —
    so the boundary here is sized to be realistic AND still preset-free.)"""
    boundary = [[0, 0], [28, 0], [28, 33], [0, 33], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 28, 33), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["preset_id"] is None
    assert room["preset_name"] == "Custom-fit screen"
    assert "area_basis_note" in room
    assert room["area_sqft"] > 900  # the smallest real preset's own min_area_sqft floor


def test_custom_fit_screen_rejects_unrealistically_narrow_shape():
    """The new rule this round adds: a custom-fit auditorium's own short
    side must clear the smallest configured preset's own width_min_ft
    (24ft) — a boundary narrower than that (here, 20ft) must place NO
    screen at all, not an architecturally absurd sliver. Before this rule
    existed, this exact 20x100 boundary (see git history of this test)
    produced a real, ~13-16ft-deep custom-fit "screen" no human would draw
    — a real, measured defect on a live project this round fixes. The 2,000
    sqft of real usable area doesn't vanish: with no screen placed, it
    becomes real Foyer/circulation space instead (see
    _place_support_zones_and_foyer / _build_foyer_room), never silently
    lost the way it would have been before Foyer-as-remainder existed."""
    boundary = [[0, 0], [20, 0], [20, 100], [0, 100], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 20, 100), "AUDITORIUM", {}
    )
    assert room is None, "a 20ft-wide boundary must not produce any screen, custom-fit or otherwise"
    assert warning and "No space" in warning


def test_best_seat_estimate_never_seats_fewer_than_the_bulk_only_option():
    """The front-lounger default isn't always a net win — FRONT_LOUNGER's
    row step (5.67ft) is bigger than SLIDER_SOFA's (4.25ft), so in a
    genuinely depth-starved room (e.g. a large screen_width_ft eating most
    of the depth) swapping one row to a lounger can cost more seats than it
    gains. Real, measured regression found via live testing this round:
    a 70x50 125_SEAT-tier room with screen_width_ft=30 (SOP-mandated big
    front setback) went from 80 seats (100% Sofa Slider) to 63 with a
    blindly-applied front-lounger row — a real regression against this
    module's own locked "maximize total seat count" objective.
    _best_seat_estimate must self-correct back to the bulk-only option
    whenever the mix would seat fewer, since maximizing seats is the
    actual goal, not applying the mix unconditionally."""
    preset = next(p for p in layout_engine.rules_registry.auditorium_presets() if p["id"] == "125_SEAT")
    seat_config, seat_est = layout_engine._best_seat_estimate(preset, 70, 50, 0.0, 30.0)
    assert seat_config["front_row_count"] is None
    assert seat_config["primary_seat_type_id"] == "SLIDER_SOFA"
    assert seat_est["seat_count"] == 80


def test_best_seat_estimate_uses_front_row_mix_when_it_genuinely_seats_more():
    """The normal (non-depth-starved) case: the front-lounger mix really
    does seat more than 100% Sofa Slider, and should be used."""
    preset = next(p for p in layout_engine.rules_registry.auditorium_presets() if p["id"] == "125_SEAT")
    seat_config, seat_est = layout_engine._best_seat_estimate(preset, 70, 50, 0.0, None)
    assert seat_config["front_row_count"] == 1
    assert seat_config["primary_seat_type_id"] == "FRONT_LOUNGER"
    bulk_only = layout_engine.seat_engine.estimate_seats(70, 50, primary_seat_type_id="SLIDER_SOFA")
    assert seat_est["seat_count"] >= bulk_only["seat_count"]


def test_generate_candidate_uses_custom_fit_in_auto_layout_too():
    """The same fallback applies inside auto-layout's own _place_auditoriums,
    not just the manual Add-Zone path — both call sites share it. Same
    28x33 no-preset-fits-but-realistically-shaped boundary as
    test_custom_fit_screen_used_when_no_preset_fits_but_real_area_remains."""
    boundary = [[0, 0], [28, 0], [28, 33], [0, 33], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 1}, [])
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert len(aud_rooms) == 1
    assert aud_rooms[0]["preset_id"] is None


def test_custom_fit_uses_real_maximal_rectangle_not_a_geometric_guess():
    """Real-world regression this exists to catch: a naive geometric-decay
    guess (aspect 1.5, shrink toward the center) can miss a real, large,
    off-aspect rectangle entirely. An L-shaped usable area (60x60 minus its
    top-right 30x30 corner) has a real 30x60=1800 sqft strip available on
    the left — free_rectangles-based search must find and use it, not
    settle for a smaller, more "aspect-normal" guess."""
    boundary = [[0, 0], [60, 0], [60, 30], [30, 30], [30, 60], [0, 60], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    bbox = (0.0, 0.0, 60.0, 60.0)
    result, used_fallback = layout_engine._find_largest_fitting_custom_screen(
        usable, usable, [], [], bbox, min_area_sqft=900
    )
    assert result is not None
    x, y, w, h = result
    assert round(w * h) >= 1800 - 1  # the real 30x60 (or 60x30) strip, not a smaller guess


def test_multiple_custom_fit_screens_place_in_one_auto_layout_run():
    """The outer per-screen loop in _place_auditoriums already retries
    custom-fit on every iteration — since each call now computes real
    remaining free rectangles against whatever's actually left (not a
    fixed decay guess), a floor plate with two disconnected large-enough
    leftover areas should get TWO custom-fit screens in one run, not stop
    after the first. A "dumbbell" boundary: two 28x33 (~924 sqft) blocks
    joined by a thin 20x2ft bridge — each block clears the new realistic-
    shape floor (min short side 24ft) but is too short (33ft) for
    35_SEAT's own 35ft length_min and too narrow (28ft) for 60_SEAT's own
    30ft width_min, so no preset fits either block; both must come from
    the custom-fit fallback, and the bridge is too thin to merge them into
    one bigger rectangle."""
    boundary = [(0, 0), (28, 0), (48, 0), (76, 0), (76, 33), (48, 33),
                (48, 2), (28, 2), (28, 33), (0, 33), (0, 0)]
    usable = layout_engine.compute_usable_area(boundary, [])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 4}, [])
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    custom_fit_rooms = [r for r in aud_rooms if r["preset_id"] is None]
    assert len(custom_fit_rooms) == 2, (
        f"expected both 1000 sqft blocks to be used as separate custom-fit screens, got "
        f"{[(r['preset_id'], r['area_sqft']) for r in aud_rooms]}"
    )
    assert all(r["area_sqft"] >= 900 for r in custom_fit_rooms)


# ---------- entry vestibule reservation (component-placement upgrade) ----------

def test_reserve_entry_vestibule_shrinks_usable_area_around_the_entry_point():
    usable = _usable()
    entry = (0, 30)
    reserved_usable, reserved_fallback = layout_engine._reserve_entry_vestibule(usable, usable, entry)
    assert reserved_usable.area < usable.area
    assert reserved_fallback.area < usable.area
    from shapely.geometry import Point
    clearance_ft = layout_engine.rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT") or 8.25
    assert not reserved_usable.contains(Point(entry).buffer(1))
    # A point well clear of the entry keeps its area untouched.
    assert reserved_usable.contains(Point(50, 30))


def test_reserve_entry_vestibule_is_a_noop_without_a_marked_entry():
    usable = _usable()
    reserved_usable, reserved_fallback = layout_engine._reserve_entry_vestibule(usable, usable, None)
    assert reserved_usable is usable
    assert reserved_fallback is usable


def test_auto_layout_keeps_auditoriums_clear_of_the_marked_entry():
    """The real, live-project defect this exists to fix: a custom-fit
    screen's own wall landed 0.56ft from the marked entry point, leaving no
    real Foyer space to walk into. No auditorium's own rectangle should
    come closer than the real SOP passage-width clearance to the entry —
    guaranteed by geometry (_reserve_entry_vestibule), not just discouraged."""
    boundary = RECT_BOUNDARY
    usable = layout_engine.compute_usable_area(boundary, [])
    entry = (0, 30)
    candidate = layout_engine.generate_candidate(
        usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 4, "entry_point_ft": list(entry)}, []
    )
    clearance_ft = layout_engine.rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT") or 8.25
    from shapely.geometry import Point
    entry_pt = Point(entry)
    for room in candidate["rooms"]:
        if not room["room_type"].startswith("AUDITORIUM"):
            continue
        room_poly = layout_engine.poly_from_points(room["geometry_points_ft"])
        assert room_poly.distance(entry_pt) >= clearance_ft - 1e-6, (
            f"{room['room_type']} sits {room_poly.distance(entry_pt):.2f}ft from the marked entry, "
            f"closer than the required {clearance_ft}ft clearance"
        )


def test_place_auditoriums_falls_back_without_vestibule_when_it_starves_all_placement():
    """SOP-adjustment path: a floor plate exactly the size of the smallest
    auditorium preset (35_SEAT: 24x35ft), with the entry marked right at
    the corner that preset needs — reserving the walkable buffer there
    would leave no room for any screen at all. Must fall back to placing
    without the buffer rather than silently returning zero auditoriums,
    and must disclose the adjustment as a warning (never a silent SOP
    override — see _place_auditoriums' own docstring)."""
    boundary = [[0, 0], [24, 0], [24, 35], [0, 35], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    presets = layout_engine.rules_registry.auditorium_presets()
    placed, placed_polys, warnings, undersized = layout_engine._place_auditoriums(
        usable, usable, [], (0, 0, 24, 35), presets, 1, lambda p: p, entry_point=(0, 0)
    )
    assert len(placed) == 1, f"expected the fallback to still place one screen, got {len(placed)}"
    assert any("SOP adjustment" in w for w in warnings), f"expected a disclosed SOP-adjustment warning, got {warnings}"


# ---------- scan candidate coverage / narrow-screen SOP adjustment (real-file remediation round) ----------

def test_scan_axis_positions_grid_lines_are_additive_not_exclusive():
    """A real, confirmed defect: detected column-grid lines used to REPLACE
    the plain fixed-step scan once >=2 clustered values existed on an axis,
    so a genuine open position away from those specific lines could be
    missed entirely — this happened on a real uploaded floor plan where
    several individual, non-grid columns (not a true structural bay grid)
    got misread as "a grid" by the same >=2-clustered-values test any real
    grid also satisfies, and starved auditorium placement of every valid
    position across an entire 7,000+ sqft wing. Grid lines (and extra_lines)
    must only ADD candidates, never remove the ones the plain step scan
    already offers."""
    positions = layout_engine._scan_axis_positions(0, 100, 10, 10, grid_lines=[5, 95])
    for expected in range(0, 91, 10):
        assert expected in positions, f"{expected} missing — grid lines wrongly replaced the plain step scan"
    assert 5 in positions, "grid line itself should still be offered as a bonus candidate"


def test_auto_layout_places_a_below_floor_screen_when_nothing_wider_fits_anywhere():
    """SOP-adjustment path, mirroring the entry-vestibule fallback: the
    min_short_side_ft realism floor (24ft — see
    _find_largest_fitting_custom_screen's own docstring) can leave a real,
    disconnected leftover block with NO way to ever clear it — unlike a
    preset ladder that can retry a smaller footprint within the SAME area,
    each free rectangle here is independently fixed-size, so a rectangle
    below the floor would otherwise never contribute a screen at all. A
    dumbbell boundary: a 28x33 block (clears the floor) and a 45x20 block
    (900 sqft, exactly the minimum preset area, but short side 20 < 24ft)
    joined by a thin bridge too narrow to merge them. Must place BOTH as
    custom-fit screens and disclose the narrower one as an SOP adjustment,
    not silently drop 900 real sqft on the floor."""
    boundary = [(0, 0), (28, 0), (48, 0), (93, 0), (93, 20), (48, 20),
                (48, 2), (28, 2), (28, 33), (0, 33), (0, 0)]
    usable = layout_engine.compute_usable_area(boundary, [])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 2}, [])
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert len(aud_rooms) == 2, f"expected both blocks to be used as screens, got {[(r['area_sqft']) for r in aud_rooms]}"
    areas = sorted(r["area_sqft"] for r in aud_rooms)
    assert areas == [900.0, 924.0]
    assert any("SOP adjustment" in w for w in candidate["warnings"]), (
        f"expected a disclosed SOP-adjustment warning for the below-floor screen, got {candidate['warnings']}"
    )


# ---------- multi-screen partition split + relaxed custom-fit column tolerance (gap-closing round) ----------

def test_split_or_whole_footprints_keeps_a_well_proportioned_rectangle_whole():
    pieces = layout_engine._split_or_whole_footprints(30, 45, min_area_sqft=900, min_short_side_ft=24, max_dim_ft=80)
    assert pieces == [(0, 0, 30, 45)]


def test_split_or_whole_footprints_splits_an_elongated_rectangle_when_both_halves_clear_the_floor():
    """The real, measured case this exists to fix: a human architect turns
    one oversized, oddly-elongated leftover area into two properly-
    proportioned screens sharing a wall, instead of one long corridor-
    shaped room (a real live project's own 70.8x13.8ft "screen", aspect
    5.1 — no human would draw that). 80x30 (aspect 2.67, over the 2.5
    threshold) splits along its longer (80ft) axis into two 40x30 halves —
    each independently well within the realism floor."""
    pieces = layout_engine._split_or_whole_footprints(80, 30, min_area_sqft=900, min_short_side_ft=24, max_dim_ft=80)
    assert pieces == [(0, 0, 40, 30), (40, 0, 40, 30)]


def test_split_or_whole_footprints_falls_back_to_whole_when_the_split_would_violate_the_floor():
    """80x20 (aspect 4.0) is elongated enough to trigger a split attempt,
    but each 40x20 half would have a 20ft short side — below the 24ft
    floor. Never force a worse shape than the original: fall back to the
    whole rectangle (also floor-checked in its own right)."""
    pieces = layout_engine._split_or_whole_footprints(80, 20, min_area_sqft=900, min_short_side_ft=24, max_dim_ft=80)
    assert pieces == []  # the whole itself also fails the 24ft floor (short side 20)
    pieces_no_floor = layout_engine._split_or_whole_footprints(80, 20, min_area_sqft=900, min_short_side_ft=0, max_dim_ft=80)
    assert pieces_no_floor == [(0, 0, 80, 20)]  # with no floor, the whole rectangle is offered instead of a bad split


def test_custom_fit_backtracking_tolerates_interior_column_via_relaxed_gate():
    """A custom-fit screen already carries its own "review before
    finalizing" note (see _build_auditorium_room) — unlike a preset match,
    which must guarantee a clean SOP bowl shape, it isn't held to the
    preset-level interior-position gate either. Real, measured fix: a
    2,542 sqft, well-proportioned (aspect 1.5) rectangle on a live project
    was rejected outright for enclosing a column just 0.95% of its own
    area, purely because that column sat past the strict 2ft-from-any-wall
    band. A tiny column dead-center of an otherwise-viable 40x40
    rectangle — far from every wall — must still be usable here, with the
    interior-position gate fully relaxed (edge_tolerance_ft=None) and only
    the wider 5% area-ratio cap enforced."""
    boundary = [[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]
    column = {"points_ft": [[19.5, 19.5], [20.5, 19.5], [20.5, 20.5], [19.5, 20.5]], "classification": "COLUMN"}
    usable = layout_engine.compute_usable_area(boundary, [column])
    fallback = layout_engine.compute_usable_area(boundary, [column], exclude_classifications=("COLUMN",))
    column_polys = [layout_engine.poly_from_points(column["points_ft"])]
    bbox = (0, 0, 40, 40)
    results = layout_engine._fill_remaining_auditoriums_with_backtracking(
        usable, fallback, column_polys, bbox, [], [], 1, 900, 0.05, False, False,
        aud_edge_tolerance_ft=None, min_short_side_ft=24
    )
    assert len(results) == 1, "expected the custom-fit screen to tolerate a dead-center column under the relaxed gate"


def test_generate_candidate_wires_the_relaxed_custom_fit_gate_through_auto_layout():
    """Integration check that _place_auditoriums_inner actually PASSES the
    relaxed custom-fit column tolerance down to its own backtracking call
    — the unit test above proves _fill_remaining_auditoriums_with_backtracking
    itself can honor a relaxed gate when asked, but not that the auto-
    layout path actually asks for one. A boundary too small for any
    preset (forcing custom-fit) with the same dead-center column: must
    still place a screen through the full generate_candidate path."""
    boundary = [[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]
    column = {"points_ft": [[19.5, 19.5], [20.5, 19.5], [20.5, 20.5], [19.5, 20.5]], "classification": "COLUMN"}
    usable = layout_engine.compute_usable_area(boundary, [column])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 1}, [column])
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert len(aud_rooms) == 1, f"expected a custom-fit screen to tolerate the dead-center column, got {candidate['warnings']}"
