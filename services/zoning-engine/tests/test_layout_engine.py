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


def test_auto_layout_places_auditoriums_only():
    """The screen-first redesign this session: generate_candidate must never
    auto-place a support zone (FOYER/FNB/WASHROOM/BOX_OFFICE/BOH) — those
    are only ever added later via place_single_zone."""
    for candidate in layout_engine.generate_candidates(RECT_BOUNDARY, [], {}):
        assert len(candidate["rooms"]) > 0, "expected at least one auditorium to fit in a 100x60 rect"
        for room in candidate["rooms"]:
            assert room["room_type"].startswith("AUDITORIUM"), (
                f"auto-layout placed a non-auditorium room: {room['room_type']}"
            )


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
    """The mirror case: a small column, comfortably under the 2% cap,
    should still be accepted via the column-tolerant fallback tier — the
    cap must not have been set so aggressively it breaks the existing
    "an auditorium may enclose a small column" behavior."""
    boundary = [[0, 0], [24, 0], [24, 35], [0, 35], [0, 0]]
    small_column = {
        "points_ft": [[11.5, 17], [12.5, 17], [12.5, 18], [11.5, 18]],  # 1 sqft
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
    though real usable area did. Reproduced here with a narrow 20x100
    corridor-shaped boundary — every real preset needs at least 24ft in its
    narrow dimension (35_SEAT's own width_min_ft), so none can fit, but the
    custom-fit fallback should still use the real 2,000 sqft available
    rather than placing nothing."""
    boundary = [[0, 0], [20, 0], [20, 100], [0, 100], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 20, 100), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["preset_id"] is None
    assert room["preset_name"] == "Custom-fit screen"
    assert "area_basis_note" in room
    assert room["area_sqft"] > 900  # the smallest real preset's own min_area_sqft floor


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
    not just the manual Add-Zone path — both call sites share it."""
    boundary = [[0, 0], [20, 0], [20, 100], [0, 100], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    candidate = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 1}, [])
    assert len(candidate["rooms"]) == 1
    assert candidate["rooms"][0]["preset_id"] is None
