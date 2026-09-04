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
    """An auditorium placed with a marked entry point should get its
    screen_wall on the edge nearest that entry point (see
    layout_engine._screen_wall_for_rect), with one ENTRY + one EXIT door on
    that same wall — matching the real reference floor plans this feature
    was designed against, where every auditorium's entry/exit cluster sits
    on the screen-adjacent wall."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}  # far left, mid-height
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["screen_wall"] == "min_x"
    kinds = sorted(d["kind"] for d in room["doors"])
    assert kinds == ["ENTRY", "EXIT"]
    for door in room["doors"]:
        assert door["wall"] == "min_x"
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


# ---------- entry/exit common-path flow segments ----------

def _aud_room(x, y, w, h, doors):
    return {"room_type": "AUDITORIUM_1", "origin_ft": [x, y], "width_ft": w, "depth_ft": h, "doors": doors}


def test_flow_segments_connect_entry_to_each_auditorium_entry_door():
    entry = (5, -5)
    room = _aud_room(0, 0, 24, 40, [{"kind": "ENTRY", "wall": "min_y", "offset_ft": 2, "width_ft": 3.5}])
    segments = layout_engine._entry_exit_flow_segments([room], entry, [])
    assert len(segments) == 1
    assert segments[0]["kind"] == "ENTRY"
    assert segments[0]["from"] == [5, -5]
    # The door-side endpoint is just outside the min_y wall (y slightly < 0).
    assert segments[0]["to"][1] < 0


def test_flow_segments_connect_exit_door_to_the_nearest_marked_exit():
    room = _aud_room(0, 0, 24, 40, [{"kind": "EXIT", "wall": "max_y", "offset_ft": 2, "width_ft": 3.5}])
    near_exit, far_exit = (5, 45), (500, 500)
    segments = layout_engine._entry_exit_flow_segments([room], None, [far_exit, near_exit])
    assert len(segments) == 1
    assert segments[0]["kind"] == "EXIT"
    assert segments[0]["to"] == [5, 45]


def test_flow_segments_skip_non_auditorium_rooms():
    support = {"room_type": "BOX_OFFICE", "origin_ft": [0, 0], "width_ft": 10, "depth_ft": 6,
               "doors": [{"kind": "ENTRY", "wall": "min_y", "offset_ft": 1, "width_ft": 3}]}
    segments = layout_engine._entry_exit_flow_segments([support], (5, -5), [(5, 45)])
    assert segments == []


def test_flow_segments_empty_when_no_entry_or_exit_marked():
    """The real, confirmed live-project case: entry_point_ft/exit_points_ft
    can both be null. Must degrade to an empty list, never crash."""
    room = _aud_room(0, 0, 24, 40, [
        {"kind": "ENTRY", "wall": "min_y", "offset_ft": 2, "width_ft": 3.5},
        {"kind": "EXIT", "wall": "max_y", "offset_ft": 2, "width_ft": 3.5},
    ])
    assert layout_engine._entry_exit_flow_segments([room], None, []) == []
    assert layout_engine._entry_exit_flow_segments([room], None, None) == []
