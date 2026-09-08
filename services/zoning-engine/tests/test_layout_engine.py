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

def test_screen_wall_derived_from_entry_point_opposite_the_near_wall():
    """An auditorium placed with a marked entry point should get its actual
    projection screen on the wall OPPOSITE the entry — a real, reported
    defect this guards against: an earlier version put the screen on the
    same wall a patron enters from, meaning they'd walk in right next to
    it. Real cinema design has patrons enter from the back/near wall and
    see the screen at the far end."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}  # far left, mid-height
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["screen_wall"] == "max_x", "screen should be on the FAR wall from the entry, not the near one"


def test_generated_auditorium_never_carries_an_auto_generated_door():
    """No auto-placed screen — via place_single_zone (manual Add Zone) or
    the full auto-layout pipeline — should ever arrive with a door glyph
    the architect never asked for. Doors are drawn by hand afterward
    (EditableCanvas's own "+ Door" tool); see
    layout_engine._strip_auto_generated_doors' own docstring for why door
    POSITION is still computed and used internally (connectivity/Foyer
    door-touch logic) even though it's never exposed on the room itself."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["doors"] == []


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


def test_custom_fit_backtracking_can_relax_the_position_gate_when_explicitly_asked():
    """Unit-level coverage of _fill_remaining_auditoriums_with_backtracking's
    OWN capability to fully relax the interior-position gate when a caller
    explicitly passes edge_tolerance_ft=None — no real call site actually
    does this anymore for auditoriums (see _place_auditoriums_inner and
    place_single_zone, which both always pass a real aud_edge_tolerance_ft
    now — a real client-reported defect where a custom-fit screen silently
    swallowed columns scattered anywhere in its interior). This test
    exercises the raw function directly with the gate off, to prove the
    capability still exists at that level should a future caller need it,
    not that any current code path uses it."""
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


def test_column_edge_split_footprints_recurses_past_a_second_stranded_column():
    """Real, measured limitation this recursion exists to fix: a free
    rectangle with TWO separate interior-violating columns needed two
    separate cuts before any resulting piece was actually clean — cutting
    at the first column's edges alone still left a piece containing the
    second column, stranded just as deep in the piece's own interior as it
    was in the original rectangle. A 60x30 rect with columns at x=15 and
    x=35 (both >2ft from every wall): a single cut (max_depth=1) at the
    x=15 column's edges leaves a ~44ft-wide remainder that still contains
    the x=35 column just as deep inside it — zero clean candidates. A
    second cut (max_depth=2) at that second column's own edges finally
    isolates a genuinely clean ~25ft-wide piece to its right."""
    from shapely.geometry import box
    col_a = box(14.5, 14, 15.5, 16)
    col_b = box(34.5, 14, 35.5, 16)
    column_polys = [col_a, col_b]

    one_cut = layout_engine._column_edge_split_footprints(0, 0, 60, 30, column_polys, 700, 24, 80.0, 2.0, max_depth=1)
    assert one_cut == [], "expected a single cut to be insufficient with two separately-stranded columns"

    two_cuts = layout_engine._column_edge_split_footprints(0, 0, 60, 30, column_polys, 700, 24, 80.0, 2.0, max_depth=2)
    assert two_cuts, "expected a second cut to isolate a clean piece past the second column"
    for ox, oy, pw, ph in two_cuts:
        assert layout_engine._deepest_interior_column(ox, oy, pw, ph, column_polys, 2.0) is None


def test_custom_fit_backtracking_prefers_a_column_free_candidate_over_a_larger_column_tolerant_one():
    """Real, reported defect: a client-facing live project showed screens
    enclosing structural columns even though clean, column-free positions
    were available right next to them. Root cause — candidates_for_slot
    (inside _fill_remaining_auditoriums_with_backtracking) mixed strict
    (column-free) and fallback (column-tolerant) candidates into one list
    sorted purely by area, so a bigger fallback rectangle (unfragmented by
    the column's own hole) could win over a smaller-but-clean strict one,
    even though every OTHER placement path in this module deliberately
    tries column-free positions first regardless of size (see
    _scan_place_ranked_with_fallback's own docstring).

    Here a small column sits near the right edge of a 60x24 boundary. The
    fallback (column-ignored) polygon offers the WHOLE 60x24 rectangle
    (1440 sqft) as one candidate; the strict (column-subtracted) polygon
    can only offer the clean 45x24 area to the column's left (1080 sqft) —
    smaller, but genuinely column-free. The filler must pick the clean,
    smaller one over the bigger, column-enclosing one."""
    boundary = [[0, 0], [60, 0], [60, 24], [0, 24], [0, 0]]
    column = {"points_ft": [[46, 11], [48, 11], [48, 13], [46, 13]], "classification": "COLUMN"}
    usable = layout_engine.compute_usable_area(boundary, [column])
    fallback = layout_engine.compute_usable_area(boundary, [column], exclude_classifications=("COLUMN",))
    column_polys = [layout_engine.poly_from_points(column["points_ft"])]
    bbox = (0, 0, 60, 24)
    results = layout_engine._fill_remaining_auditoriums_with_backtracking(
        usable, fallback, column_polys, bbox, [], [], 1, 900, 0.05, False, False,
        aud_edge_tolerance_ft=None, min_short_side_ft=24
    )
    assert len(results) == 1
    x, y, w, h, used_fallback = results[0]
    assert used_fallback is False, (
        f"expected the column-free 45x24 area to be picked over the bigger column-enclosing 60x24 one, "
        f"got {results[0]}"
    )
    placed_rect = layout_engine._rect(x, y, w, h)
    column_poly = column_polys[0]
    assert placed_rect.intersection(column_poly).area < 1e-6, "placed screen must not enclose the column at all"


def test_generate_candidate_never_places_a_screen_over_an_interior_column_through_auto_layout():
    """Integration check for the client-facing policy this round enforces
    uniformly: a custom-fit screen may tolerate a bit more column AREA than
    a preset match (custom_fit_column_cap, see _place_auditoriums_inner's
    own comment), but the POSITION gate (aud_edge_tolerance_ft) is never
    relaxed for it — a column stranded in the room's interior, not near any
    wall, must still be rejected. Real, reported defect this guards
    against: a custom-fit screen was silently swallowing an entire floor's
    worth of columns scattered through its interior, because only the area
    ratio was ever checked for custom-fit rooms. A dead-center column on a
    40x40 boundary blocks every possible position (any preset, and any
    custom-fit footprint big enough to matter, is wider/taller than half
    the boundary, so it can't clear the column while also reaching every
    wall) — the auto-layout path must honestly place ZERO auditoriums here
    rather than fabricate one enclosing the column."""
    boundary = [[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]
    column = {"points_ft": [[19.5, 19.5], [20.5, 19.5], [20.5, 20.5], [19.5, 20.5]], "classification": "COLUMN"}
    usable = layout_engine.compute_usable_area(boundary, [column])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 1}, [column])
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert len(aud_rooms) == 0, "expected no screen to be placed rather than one enclosing the dead-center column"


# ---------- column face alignment (screens flush against a nearby column) ----------

def test_column_face_alignment_lines_returns_real_column_face_coordinates():
    """Real, reported defect: a screen wall could pass every existing gate
    (area ratio under the cap, column within edge_tolerance_ft of some
    wall) while still landing an arbitrary fraction of a foot short of the
    column's own face — geometrically compliant but reading as sloppy/
    unaligned, since a real wall is drawn flush against (or built into) the
    column it runs past. _column_face_alignment_lines offers the column's
    own real face coordinates (not its centroid — see _column_grid_lines,
    a different, coarser mechanism) as extra scan candidates."""
    from shapely.geometry import box
    col = box(23.3, 10.0, 24.7, 11.4)  # deliberately not on the 2ft GRID_STEP_FT scan sequence
    xs, ys = layout_engine._column_face_alignment_lines([col], (0, 0, 100, 60))
    assert sorted(round(v, 2) for v in xs) == [23.3, 24.7]
    assert sorted(round(v, 2) for v in ys) == [10.0, 11.4]


def test_column_face_alignment_lines_mirrors_correctly_for_flipped_scans():
    """Auditorium placement can run its scan mirrored about the bbox center
    (see _mirror_for_scan/_entry_exit_scan_flip) to bias toward the marked
    entry/exit side — column_polys stay in real (unmirrored) coordinates
    throughout (see _column_enclosure_ok's own docstring), so a face line
    must be mirrored into the same scan-space flip_x/flip_y puts placement
    candidates in, or it would line candidates up against the wrong side
    of the floor plate entirely."""
    from shapely.geometry import box
    col = box(10.0, 10.0, 12.0, 12.0)
    bbox = (0, 0, 100, 60)  # center at (50, 30)
    xs, ys = layout_engine._column_face_alignment_lines([col], bbox, flip_x=True, flip_y=False)
    assert sorted(round(v, 2) for v in xs) == [88.0, 90.0]  # 2*50 - {10, 12}
    assert sorted(round(v, 2) for v in ys) == [10.0, 12.0]  # y untouched


def test_column_face_alignment_lines_empty_with_no_columns():
    xs, ys = layout_engine._column_face_alignment_lines([], (0, 0, 100, 60))
    assert xs == [] and ys == []


def test_scan_place_ranked_offers_a_candidate_flush_against_a_column_face():
    """End-to-end proof the mechanism actually reaches the scan: a column
    whose face sits at a non-grid-step coordinate must still appear as a
    real candidate x-position once its face lines are passed through as
    extra_lines_x — not just computed and discarded."""
    from shapely.geometry import box
    usable = _usable()
    col = box(23.3, 0, 24.7, 60)  # spans the room's full height, off the 2ft grid
    face_lines_x, face_lines_y = layout_engine._column_face_alignment_lines([col], (0, 0, 100, 60))
    ranked = layout_engine._scan_place_ranked(
        usable, [], [], "AUDITORIUM", 24, 35, (0, 0, 100, 60),
        extra_lines_x=face_lines_x, extra_lines_y=face_lines_y
    )
    xs_seen = {round(c[0][0], 2) for c in ranked}
    assert 24.7 in xs_seen, f"expected a candidate flush against the column's own face (24.7), got x values {sorted(xs_seen)}"


# ---------- no auto-generated doors (architect draws every door by hand) ----------

def test_generate_candidate_never_auto_generates_doors_on_any_room():
    """Real product decision this round enforces: an auto-placed room
    (screen or support zone) never arrives with a door glyph the architect
    never asked for — doors are added by hand afterward via the edit
    canvas's own "+ Door" tool. Door POSITION is still computed and used
    internally by the placement pipeline itself (connectivity gating,
    Foyer's door-touch tiebreak — see _strip_auto_generated_doors' own
    docstring), but must never leak into the returned room list."""
    candidate = layout_engine.generate_candidate(
        _usable(), RECT_BOUNDARY, "MAX_SEATS_PER_SCREEN",
        {"max_auditoriums": 4, "entry_point_ft": [0, 30]}, []
    )
    assert len(candidate["rooms"]) > 0
    for room in candidate["rooms"]:
        assert room["doors"] == [], f"{room['room_type']} carries an auto-generated door: {room['doors']}"


# ---------- top_k starvation on a dense, real column layout (entry+exit marked) ----------

# Real boundary + confirmed-COLUMN geometry from a live client floor plate
# (coordinates shifted to a local origin, otherwise unchanged) — a real,
# measured case where marking an entry+exit point collapsed a floor plate
# that fits 4 real screens (confirmed by both this engine with a large
# enough top_k and by the architect's own hand-drawn zoning sheet for this
# exact floor) down to a single, absurd 14.9x80ft custom-fit sliver.
_REAL_DENSE_COLUMN_BOUNDARY_FT = [
    [0.0, 16.78], [0.0, 8.96], [0.23, 8.96], [0.23, 8.96], [0.23, 8.96], [0.23, 0.02],
    [23.65, 0.02], [23.65, 0.02], [26.11, 0.02], [26.11, 0.02], [49.05, 0.02], [49.05, 0.02],
    [51.51, 0.02], [51.51, 0.02], [74.44, 0.02], [74.44, 0.02], [76.9, 0.02], [76.9, 0.02],
    [85.19, 0.02], [85.19, 0.02], [87.16, 0.02], [87.16, 0.02], [102.23, 0.02], [102.24, 0.0],
    [102.72, 0.13], [100.74, 7.24], [99.74, 10.85], [99.26, 10.72], [98.73, 12.61], [99.21, 12.75],
    [95.96, 24.43], [95.48, 24.3], [94.96, 26.2], [95.43, 26.33], [93.23, 34.23], [93.23, 34.23],
    [93.01, 35.06], [93.01, 35.06], [92.87, 35.55], [92.71, 36.12], [92.71, 36.12], [92.68, 36.23],
    [92.21, 36.1], [91.68, 37.99], [92.15, 38.12], [91.84, 39.24], [87.95, 53.26], [87.47, 53.13],
    [86.94, 55.02], [87.42, 55.15], [84.83, 64.47], [84.35, 64.34], [83.83, 66.23], [84.3, 66.37],
    [80.31, 80.71], [79.84, 80.58], [79.31, 82.47], [79.79, 82.61], [77.98, 89.09], [76.4, 94.79],
    [75.93, 94.66], [75.93, 94.66], [75.47, 96.31], [50.77, 96.31], [50.77, 94.84], [49.79, 94.84],
    [49.79, 96.31], [25.38, 96.31], [25.38, 94.84], [24.39, 94.84], [24.39, 96.31], [0.23, 96.31],
    [0.23, 94.84], [0.0, 94.84], [0.0, 82.99], [0.23, 82.99], [0.23, 80.53], [0.0, 80.53],
    [0.0, 66.75], [0.23, 66.75], [0.23, 66.75], [0.23, 66.75], [0.23, 16.78], [0.23, 16.78],
    [0.0, 16.78], [0.0, 16.78],
]

_REAL_DENSE_COLUMN_OBSTACLES = [
    {"points_ft": [[50.77, 13.16], [49.79, 13.16], [49.79, 10.7], [50.77, 10.7], [50.77, 13.16]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 13.16], [24.39, 13.16], [24.39, 10.7], [25.38, 10.7], [25.38, 13.16]], "classification": "COLUMN"},
    {"points_ft": [[76.16, 13.16], [75.18, 13.16], [75.18, 10.7], [76.16, 10.7], [76.16, 13.16]], "classification": "COLUMN"},
    {"points_ft": [[76.16, 26.61], [75.18, 26.61], [75.18, 24.15], [76.16, 24.15], [76.16, 26.61]], "classification": "COLUMN"},
    {"points_ft": [[50.77, 26.61], [49.79, 26.61], [49.79, 24.15], [50.77, 24.15], [50.77, 26.61]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 26.61], [24.39, 26.61], [24.39, 24.15], [25.38, 24.15], [25.38, 26.61]], "classification": "COLUMN"},
    {"points_ft": [[50.77, 38.91], [49.79, 38.91], [49.79, 36.45], [50.77, 36.45], [50.77, 38.91]], "classification": "COLUMN"},
    {"points_ft": [[76.16, 38.91], [75.18, 38.91], [75.18, 36.45], [76.16, 36.45], [76.16, 38.91]], "classification": "COLUMN"},
    {"points_ft": [[63.47, 55.54], [62.49, 55.54], [62.49, 53.08], [63.47, 53.08], [63.47, 55.54]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 38.91], [24.39, 38.91], [24.39, 36.45], [25.38, 36.45], [25.38, 38.91]], "classification": "COLUMN"},
    {"points_ft": [[50.77, 55.54], [49.79, 55.54], [49.79, 53.08], [50.77, 53.08], [50.77, 55.54]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 55.54], [24.39, 55.54], [24.39, 53.08], [25.38, 53.08], [25.38, 55.54]], "classification": "COLUMN"},
    {"points_ft": [[50.77, 66.75], [49.79, 66.75], [49.79, 64.29], [50.77, 64.29], [50.77, 66.75]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 66.75], [24.39, 66.75], [24.39, 64.29], [25.38, 64.29], [25.38, 66.75]], "classification": "COLUMN"},
    {"points_ft": [[63.47, 66.75], [62.49, 66.75], [62.49, 64.29], [63.47, 64.29], [63.47, 66.75]], "classification": "COLUMN"},
    {"points_ft": [[50.77, 82.99], [49.79, 82.99], [49.79, 80.53], [50.77, 80.53], [50.77, 82.99]], "classification": "COLUMN"},
    {"points_ft": [[25.38, 82.99], [24.39, 82.99], [24.39, 80.53], [25.38, 80.53], [25.38, 82.99]], "classification": "COLUMN"},
    {"points_ft": [[63.47, 82.99], [62.49, 82.99], [62.49, 80.53], [63.47, 80.53], [63.47, 82.99]], "classification": "COLUMN"},
]

_REAL_DENSE_COLUMN_ENTRY_FT = [0.19, 39.69]
_REAL_DENSE_COLUMN_EXIT_FT = [-0.01, 44.89]


def test_marked_entry_and_exit_does_not_starve_auditorium_placement_on_a_dense_column_floor():
    """The exact regression this fixture was pulled from a live client file
    to guard: with no entry/exit marked, this floor plate places 4 real
    screens; with a real entry+exit marked near one corner (both close
    together, forcing the auditorium scan to run mirrored — see
    _entry_exit_scan_flip), the scan used to rank its top 12 fallback
    candidates entirely inside the confirmed-column field (all rejected by
    the column-enclosure gate) while dozens of genuinely valid,
    column-clear candidates existed a few ranks further down — invisible
    to the old top_k=12 cutoff in _try_place_auditorium_with_column_check.
    That collapsed every preset tier down to Phase 2's custom-fit fallback,
    which produced one absurd ~15x80ft sliver screen instead of 4 real
    ones. Marking an entrance must never make placement worse than not
    marking one at all."""
    requirements = {
        "max_auditoriums": 4,
        "entry_point_ft": _REAL_DENSE_COLUMN_ENTRY_FT,
        "exit_points_ft": [_REAL_DENSE_COLUMN_EXIT_FT],
    }
    candidates = layout_engine.generate_candidates(
        _REAL_DENSE_COLUMN_BOUNDARY_FT, _REAL_DENSE_COLUMN_OBSTACLES, requirements
    )
    for candidate in candidates:
        aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
        assert len(aud_rooms) >= 3, (
            f"{candidate['strategy']}: expected several real screens on this floor plate, got only "
            f"{len(aud_rooms)}: {[(r['area_sqft'], r['width_ft'], r['depth_ft']) for r in aud_rooms]}"
        )
        for room in aud_rooms:
            assert room["preset_id"] is not None, (
                f"{candidate['strategy']}: {room['room_type']} fell through to a non-standard custom-fit "
                f"footprint ({room['width_ft']}x{room['depth_ft']}) even though real SOP-preset positions exist"
            )


def test_narrower_top_k_reproduces_the_starvation_this_fixture_guards_against():
    """Confirms the fixture above actually exercises the regression — with
    the old top_k=12 default, this exact floor plate + entry/exit really
    did collapse to a single screen. If this assertion ever stops holding
    (e.g. the fixture bit-rots against unrelated scan changes), the
    positive test above stops being meaningful and both should be
    revisited together."""
    import functools
    original = layout_engine._try_place_auditorium_with_column_check

    def forced_old_top_k(*args, **kwargs):
        kwargs["top_k"] = 12
        return original(*args, **kwargs)

    layout_engine._try_place_auditorium_with_column_check = forced_old_top_k
    try:
        requirements = {
            "max_auditoriums": 4,
            "entry_point_ft": _REAL_DENSE_COLUMN_ENTRY_FT,
            "exit_points_ft": [_REAL_DENSE_COLUMN_EXIT_FT],
        }
        candidates = layout_engine.generate_candidates(
            _REAL_DENSE_COLUMN_BOUNDARY_FT, _REAL_DENSE_COLUMN_OBSTACLES, requirements
        )
        screen_counts = [
            len([r for r in c["rooms"] if r["room_type"].startswith("AUDITORIUM")]) for c in candidates
        ]
        assert all(n <= 1 for n in screen_counts), (
            f"expected top_k=12 to reproduce the known starvation (<=1 screen), got {screen_counts} — "
            "the fixture may no longer exercise the original regression"
        )
    finally:
        layout_engine._try_place_auditorium_with_column_check = original


# ---------- screen_width_ft narrower-than-requested disclosure ----------

def test_screen_width_note_appears_when_no_preset_can_carry_the_marked_screen_width():
    """Real, measured case: an architect marks screen_width_ft=30 in
    Requirements, but the confirmed column layout leaves no 30ft-wide
    preset position anywhere — every screen ends up placed at the 24ft-wide
    35_SEAT tier instead. FIRST_ROW_DISTANCE_RULE still forces the front-row
    setback out to 30ft regardless of the room's actual width (see
    seat_engine.estimate_seats), badly undersizing the reported seat count
    for a reason that isn't a placement defect — must be disclosed on the
    room, not left for the architect to puzzle out from a low seat count."""
    requirements = {
        "max_auditoriums": 4,
        "entry_point_ft": _REAL_DENSE_COLUMN_ENTRY_FT,
        "exit_points_ft": [_REAL_DENSE_COLUMN_EXIT_FT],
        "screen_width_ft": 30.0,
    }
    candidates = layout_engine.generate_candidates(
        _REAL_DENSE_COLUMN_BOUNDARY_FT, _REAL_DENSE_COLUMN_OBSTACLES, requirements
    )
    for candidate in candidates:
        aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
        narrow_rooms = [r for r in aud_rooms if r["width_ft"] < 30.0]
        assert narrow_rooms, "expected at least one auditorium narrower than the marked screen_width_ft on this floor plate"
        for room in narrow_rooms:
            assert "screen_width_note" in room, (
                f"{room['room_type']} is {room['width_ft']}ft wide (< marked 30ft screen_width_ft) but carries "
                "no screen_width_note explaining the resulting seat undercount"
            )
            assert "30" in room["screen_width_note"]


def test_screen_width_note_absent_when_the_room_is_wide_enough():
    """No false positives — a room already at least as wide as the marked
    screen_width_ft must not carry the narrower-than-requested note."""
    candidate = layout_engine.generate_candidate(
        _usable(), RECT_BOUNDARY, "MAX_SEATS_PER_SCREEN",
        {"max_auditoriums": 2, "screen_width_ft": 24.0}, []
    )
    aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    assert aud_rooms
    for room in aud_rooms:
        assert room["width_ft"] >= 24.0
        assert "screen_width_note" not in room
