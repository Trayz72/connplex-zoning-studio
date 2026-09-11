"""Basic regression coverage for layout_engine.py — the auto-layout
generator and the manual "Add Zone" placer. Not exhaustive; targets the real
behaviors this session's work depends on (screens-only auto-layout,
zero-gap screen adjacency, place_single_zone's collision-safety and
division-by-zero guard) so they can't silently regress."""
import layout_engine
import seat_engine
from shapely.geometry import Polygon
from fixtures.dhule_real_building import DHULE_BOUNDARY_FT, DHULE_OBSTACLES

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
    then Box Office/Manager Room/F&B/Washroom/BOH with real geometry (not
    just an aggregate circulation_area_sqft number), then Passage as the true
    leftover remainder. FOYER stays auto-layout-excluded (Passage now
    serves its old connective purpose) — it's still available via manual
    Add Zone (place_single_zone).

    Uses its own larger boundary, not the shared RECT_BOUNDARY other tests
    in this file rely on for their own (different) assertions — WASHROOM's
    real minimum is now 450 sqft (the team's own placement standards, up
    from the old 60 sqft placeholder), which the compact 100x60 RECT_BOUNDARY
    can no longer guarantee room for alongside 2 auditoriums and every other
    standard support zone."""
    large_boundary = [[0, 0], [160, 0], [160, 90], [0, 90], [0, 0]]
    for candidate in layout_engine.generate_candidates(large_boundary, [], {}):
        room_types = {r["room_type"] for r in candidate["rooms"]}
        assert any(rt.startswith("AUDITORIUM") for rt in room_types), "expected at least one auditorium to fit in a 160x90 rect"
        for support_type in ("BOX_OFFICE", "MANAGER_ROOM", "FNB", "WASHROOM", "BOH"):
            assert support_type in room_types, f"expected auto-layout to place a real {support_type}, got room types {room_types}"
        assert "FOYER" not in room_types, "FOYER should stay excluded from auto-layout — Passage is now the connective remainder"
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
        usable, usable, [], placed_polys, placed_types, (0, 0, 100, 60), "WASHROOM", {}
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


def test_generated_auditorium_carries_its_real_computed_doors():
    """A manually-placed screen (place_single_zone / Add Zone) keeps the
    real entry/exit doors _doors_for_screen_wall computes for it — on the
    door wall (opposite the screen wall, nearest the marked entry), matching
    every real reference floor plan. This reverses this project's earlier
    'strip every auto-placed door' behavior for AUDITORIUM rooms specifically
    (see _strip_auto_generated_doors' own docstring, and
    test_generate_candidate_never_auto_generates_doors_on_any_room below for
    the equivalent full-pipeline case) — a screen's doors are placed by a
    real, documented rule, not a placement-pipeline-internal proxy, so the
    architect gets them as an editable starting point instead of redrawing
    from scratch."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["screen_wall"] == "max_x"
    door_wall = layout_engine._OPPOSITE_WALL[room["screen_wall"]]
    assert door_wall == "min_x"
    door_width_ft = layout_engine.rules_registry.planning_norm("AUDITORIUM_DOOR_WIDTH_FT") or 3.5
    expected_doors = layout_engine._doors_for_screen_wall(room["width_ft"], room["depth_ft"], door_wall, door_width_ft)
    assert room["doors"] == expected_doors
    assert len(room["doors"]) == 2
    assert {d["kind"] for d in room["doors"]} == {"ENTRY", "EXIT"}
    assert all(d["wall"] == door_wall for d in room["doors"])


def test_screen_wall_defaults_to_the_room_s_own_longer_axis_without_entry_point():
    """No entry point marked: screen_wall must still land on whichever wall
    pair spans the room's own longer (real seating-depth) axis — never the
    literal 'min_y' fallback regardless of shape, which was a real,
    confirmed defect (see _screen_wall_for_rect's restrict_to_depth_axis
    docstring): a room placed wider than deep would otherwise get its
    seating depth computed from the SHORT axis, undercounting or zeroing
    out real seats even with no entry point involved at all. This 100x60
    usable area's own default placement comes out 70ft wide x 50ft deep, so
    the longer axis is the width (x-axis) and screen_wall must be min_x."""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["width_ft"] > room["depth_ft"], "test assumes this placement comes out wider than deep"
    assert room["screen_wall"] == "min_x"


# ---------- _seat_axis_dims: seat math must follow the real screen wall ----------

def test_seat_axis_dims_swaps_for_a_vertical_screen_wall():
    """seat_engine.estimate_seats always treats its first argument as
    screen-parallel (the row's width) — correct by construction only when
    screen_wall is min_y/max_y, since that's the only case where the room's
    own w matches that axis. A min_x/max_x screen wall means the room was
    rotated 90 degrees relative to that assumption; _seat_axis_dims must
    swap w/h in that case, and leave them alone in every other."""
    assert layout_engine._seat_axis_dims(40, 70, "min_x") == (70, 40)
    assert layout_engine._seat_axis_dims(40, 70, "max_x") == (70, 40)
    assert layout_engine._seat_axis_dims(40, 70, "min_y") == (40, 70)
    assert layout_engine._seat_axis_dims(40, 70, "max_y") == (40, 70)


def test_placed_auditorium_with_vertical_screen_wall_gets_axis_corrected_seat_estimate():
    """Live regression case for the axis bug this round's Phase 0 fixes:
    before the fix, a room whose entry point forced a min_x/max_x screen
    wall got its seat estimate computed against the wrong axis (packing rows
    across the narrow dimension instead of the long one). Boundary is a
    100x30 strip with the entry on the SHORT (top/bottom) wall, so the
    nearest-to-entry wall is min_y — screen ends up on the opposite short
    wall (max_y)... to force a min_x/max_x screen wall instead, mark the
    entry on a LONG wall of a room shaped so screen_wall lands on min_x/
    max_x: use a tall, narrow boundary (30 wide x 100 deep) with entry on
    the bottom (min_y) wall — screen_wall is then max_y (still horizontal).
    To actually exercise the min_x/max_x branch, mark entry near the LEFT
    (min_x) wall of a wide, shallow boundary instead — screen_wall becomes
    max_x, a vertical wall — and confirm the seat estimate matches
    estimate_seats called with width/depth swapped relative to the room's
    raw box w/h."""
    usable = _usable()
    requirements = {"entry_point_ft": [0, 30]}  # nearest the left (min_x) wall
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", requirements
    )
    assert room is not None, warning
    assert room["screen_wall"] == "max_x"
    cfg = room["seat_config"]
    expected = seat_engine.estimate_seats(
        room["depth_ft"], room["width_ft"],  # swapped: room's real h becomes the screen-parallel span
        primary_seat_type_id=cfg["primary_seat_type_id"], secondary_seat_type_id=cfg["secondary_seat_type_id"],
        primary_ratio_pct=cfg["primary_ratio_pct"], front_row_count=cfg["front_row_count"],
    )
    assert room["seat_estimate"]["rows"] == expected["rows"]
    assert room["seat_estimate"]["seats_per_row"] == expected["seats_per_row"]
    assert room["seat_estimate"]["seat_count"] == expected["seat_count"]


# ---------- side-wall door -> seat exclusion mapping (_side_door_exclusions) ----------

def test_side_door_exclusions_ignores_screen_and_door_walls():
    """A door on the screen wall or the door(entry) wall isn't a 'side'
    door — only the two walls perpendicular to the screen carry this kind
    of exclusion (see _screen_wall_door_conflict_note for the separate,
    already-illegal screen-wall-door case)."""
    doors = [
        {"kind": "ENTRY", "wall": "min_y", "offset_ft": 10, "width_ft": 3.5},  # screen wall itself
        {"kind": "EXIT", "wall": "max_y", "offset_ft": 10, "width_ft": 3.5},   # the door wall
    ]
    assert layout_engine._side_door_exclusions(40, 70, "min_y", doors, 2.5) == []


def test_side_door_exclusions_near_screen_for_a_near_wall_screen():
    """screen_wall='min_y' (screen at the room's own y=0 origin wall): a side
    door's offset_ft already IS its distance from the screen, no mirroring
    needed."""
    doors = [{"kind": "ENTRY", "wall": "min_x", "offset_ft": 20, "width_ft": 4}]
    exclusions = layout_engine._side_door_exclusions(40, 70, "min_y", doors, 2.5)
    assert len(exclusions) == 1
    assert exclusions[0]["side"] == "left"
    assert exclusions[0]["depth_start_ft"] == 17.5  # 20 - 2.5
    assert exclusions[0]["depth_end_ft"] == 26.5     # 20 + 4 + 2.5


def test_side_door_exclusions_mirrors_for_a_far_wall_screen():
    """screen_wall='max_y' (screen at the FAR wall, y=depth): a side door's
    offset_ft is still measured from the wall's own near-origin corner
    (per _doors_for_screen_wall's fixed convention), which now runs AWAY
    from the screen — must be mirrored (depth = raw_depth_span - offset)
    to get real distance-from-screen, or the exclusion lands on the wrong
    rows entirely."""
    doors = [{"kind": "ENTRY", "wall": "max_x", "offset_ft": 20, "width_ft": 4}]
    exclusions = layout_engine._side_door_exclusions(40, 70, "max_y", doors, 2.5)
    assert len(exclusions) == 1
    assert exclusions[0]["side"] == "right"
    # raw_depth_span = 70 (h, since screen_wall is min_y/max_y); door spans
    # raw [20, 24] -> mirrored depth [70-24, 70-20] = [46, 50] -> +/- 2.5 clearance
    assert exclusions[0]["depth_start_ft"] == 43.5
    assert exclusions[0]["depth_end_ft"] == 52.5


def test_side_door_exclusions_for_a_vertical_screen_wall():
    """screen_wall='min_x' (a 90-degree-reoriented screen): side walls are
    now min_y/max_y, and the depth axis runs along the room's own w (per
    _seat_axis_dims) — confirms the mirroring logic generalizes to the
    other axis, not just min_y/max_y screens."""
    doors = [{"kind": "ENTRY", "wall": "min_y", "offset_ft": 5, "width_ft": 3}]
    exclusions = layout_engine._side_door_exclusions(40, 70, "min_x", doors, 2.5)
    assert len(exclusions) == 1
    assert exclusions[0]["side"] == "left"
    assert exclusions[0]["depth_start_ft"] == 2.5   # 5 - 2.5
    assert exclusions[0]["depth_end_ft"] == 10.5     # 5 + 3 + 2.5


# ---------- _clamp_doors_to_room ----------

def test_clamp_doors_to_room_shrinks_an_oversized_door_after_a_resize():
    """A door drawn on a room before it was shrunk can end up wider than the
    new wall (or offset past its end) — _clamp_doors_to_room must re-apply
    the same bound _doors_for_screen_wall uses at creation time."""
    room = {"width_ft": 10, "depth_ft": 40, "doors": [
        {"kind": "ENTRY", "wall": "min_y", "offset_ft": 8, "width_ft": 6},  # wall_len is now only 10ft
    ]}
    layout_engine._clamp_doors_to_room(room)
    door = room["doors"][0]
    assert door["width_ft"] <= 10 / 2.5
    assert door["offset_ft"] + door["width_ft"] <= 10 + 1e-9


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


# ---------- FOYER ----------
#
# Room type identifiers FOYER/PASSAGE were swapped 2026-09-10 at the
# client's request (see rules_registry_v1.json's support_zone_defaults
# entries): FOYER is now the manually-placed room, PASSAGE is now the
# derived leftover-remainder room. The "connects to the derived circulation
# space and the nearest screen" proximity heuristic moved with the
# manually-placed identity (now FOYER); the elongated-corridor shape rule
# in _support_zone_dims deliberately did NOT move — a lobby isn't a
# corridor, so a newly-placed FOYER keeps the generic square-ish shape
# every other support zone uses (see _support_zone_dims's own docstring).

def test_place_single_zone_foyer_connects_passage_and_auditorium():
    """A FOYER should be placed close to both the derived Passage remainder
    and the nearest already-placed Screen (see place_single_zone's FOYER
    branch) — real, evidence-based behavior from the reference floor plans
    this feature was designed against, not just "wherever a plain first-fit
    scan happens to land." Passage/auditorium are pushed to the far side
    (x=200+) of a wide boundary, with a large empty region at x=0 that a
    plain scan (no proximity heuristic) would fill first — so a placement
    near x=200 specifically proves the heuristic ran, rather than
    coinciding with first-fit's own default bottom-left-first order the way
    a tighter test geometry could."""
    boundary = [[0, 0], [300, 0], [300, 100], [0, 100], [0, 0]]
    usable = layout_engine.compute_usable_area(boundary, [])
    auditorium = layout_engine._rect(200, 0, 70, 50)
    passage = layout_engine._rect(200, 60, 30, 20)
    placed_polys = [auditorium, passage]
    placed_types = ["AUDITORIUM", "PASSAGE"]

    foyer, warning = layout_engine.place_single_zone(
        usable, usable, [], placed_polys, placed_types, (0, 0, 300, 100), "FOYER", {"max_auditoriums": 1}
    )
    assert foyer is not None, warning
    foyer_poly = layout_engine.poly_from_points(foyer["geometry_points_ft"])
    real_distance_sum = foyer_poly.distance(auditorium) + foyer_poly.distance(passage)
    # A plain first-fit scan (no heuristic) lands at the boundary's own
    # (0, 0) corner here — real, empirically confirmed, not a guess.
    # Compare against a same-*size* rect placed at that corner (not an
    # arbitrary marker) so the comparison isolates position, not shape.
    first_fit_corner = layout_engine._rect(0, 0, foyer["width_ft"], foyer["depth_ft"])
    first_fit_distance_sum = first_fit_corner.distance(auditorium) + first_fit_corner.distance(passage)
    assert real_distance_sum < first_fit_distance_sum, (
        f"expected the foyer closer to the passage/auditorium (distance sum {real_distance_sum}) than a "
        f"same-size placement at the far (0,0) corner would be ({first_fit_distance_sum}), origin was "
        f"{foyer['origin_ft']} — looks like the proximity heuristic didn't run"
    )
    # Generic square-ish shape (aspect ~1.6), NOT the elongated corridor
    # shape PASSAGE's own placeholder minimum uses — see this section's own
    # header comment for why that shape rule deliberately didn't transfer.
    assert max(foyer["width_ft"], foyer["depth_ft"]) / min(foyer["width_ft"], foyer["depth_ft"]) < 2.0


# ---------- new placement standards round: real minimums, Box Office sightline,
# F&B route-to-auditorium, Manager Room, Electrical Room ----------

def test_place_single_zone_washroom_respects_new_450_sqft_minimum():
    """Team's own placement standards set a real, much larger washroom
    minimum (450 sqft, up from the old 60 sqft engineering placeholder) —
    confirms place_single_zone actually enforces it end-to-end, not just
    that the SUPPORT_ZONE_DEFAULTS constant changed."""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "WASHROOM", {}
    )
    assert room is not None, warning
    assert room["area_sqft"] >= 450.0


def test_place_single_zone_box_office_respects_new_50_sqft_minimum():
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "BOX_OFFICE", {}
    )
    assert room is not None, warning
    assert room["area_sqft"] >= 50.0


def test_place_single_zone_manager_room_and_electrical_are_placeable():
    """Confirms the generic SUPPORT_ZONE_DEFAULTS-driven dispatch already in
    place_single_zone picks up both new zone types with no special-casing
    needed beyond the table entry itself (same mechanism BOX_OFFICE/FNB/etc.
    already use)."""
    usable = _usable()
    manager_room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "MANAGER_ROOM", {}
    )
    assert manager_room is not None, warning
    assert manager_room["area_sqft"] >= 100.0
    assert manager_room["display_name"] == "Manager Room"

    electrical, warning2 = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "ELECTRICAL", {}
    )
    assert electrical is not None, warning2
    assert electrical["display_name"] == "Electrical Room"


def test_manager_room_is_auto_placed_electrical_is_not():
    """Manager Room: standard auto-placed zone, same standing as Box
    Office/F&B/Washroom/BOH. Electrical Room: opt-in only (Add Zone) until a
    real minimum area exists — see SUPPORT_ZONE_DEFAULTS' own note on it."""
    assert "MANAGER_ROOM" in layout_engine.SUPPORT_ZONE_AUTO_ORDER
    assert "ELECTRICAL" not in layout_engine.SUPPORT_ZONE_AUTO_ORDER


def test_box_office_heuristic_has_both_distance_score_and_sightline_preference():
    """New this round: BOX_OFFICE used to share PASSAGE's plain distance-to-
    entry score_fn with no sightline check at all — "immediately visible on
    arrival" (team's own placement standards) means a visible-but-slightly-
    farther spot should beat a closer-but-blocked one. Confirms both halves
    are wired: a real prefer_fn now exists (PASSAGE, by contrast, still gets
    none), and it actually behaves like a sightline check — true for a clear
    line to a candidate on the entry's own side of a full-height wall, false
    for one on the far side of it. (PASSAGE here is the identifier used by
    the entry-distance-only branch of _support_zone_heuristic — since the
    2026-09-10 FOYER/PASSAGE swap this branch is unreachable via manual
    placement, mirroring how it was reachable-but-unused for FOYER before
    the swap; see rules_registry_v1.json's support_zone_defaults entries.)"""
    usable = _usable()
    entry_point = (0, 30)
    blocker = layout_engine._rect(10, 0, 20, 60)  # full-height wall, x=10..30
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "BOX_OFFICE", entry_point, [], usable, usable, [blocker], ["AUDITORIUM"], None
    )
    assert score_fn is not None, "BOX_OFFICE should still prefer being close to the entry"
    assert prefer_fn is not None, "BOX_OFFICE should now also prefer a real sightline from the entry"
    visible_candidate = (2, 25, 5, 5)   # inside the open x<10 strip, in view of the entry
    blocked_candidate = (50, 25, 5, 5)  # on the far side of the wall, out of view
    assert prefer_fn(visible_candidate) is True
    assert prefer_fn(blocked_candidate) is False

    passage_score_fn, passage_prefer_fn, _passage_hard_filter_fn = layout_engine._support_zone_heuristic(
        "PASSAGE", entry_point, [], usable, usable, [blocker], ["AUDITORIUM"], None
    )
    assert passage_score_fn is not None
    assert passage_prefer_fn is None, "PASSAGE should be unaffected by this round — distance-only, as before"


def test_box_office_heuristic_also_prefers_flanking_the_entry():
    """New this round: real reference floor plans (Keshav Landmark Vadodara,
    Maruti Nandan Dhule) show Box Office immediately beside the Cinema
    Entry/Exit, not just anywhere with a clear sightline — a candidate on
    the far side of the same open room, equally visible, is a real floor
    plan the team would never actually draw. prefer_fn now requires both a
    clear sightline AND landing within BOX_OFFICE_ENTRY_ADJACENCY_MAX_FT of
    the entry (12ft placeholder, REQUIRES_APPROVAL — see rules_registry_v1.json)."""
    usable = _usable()
    entry_point = (0, 30)
    # No blocker this time — isolating the new adjacency term from the
    # existing sightline term (already covered by the test above).
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "BOX_OFFICE", entry_point, [], usable, usable, [], ["AUDITORIUM"], None
    )
    # Offset in y from entry_point's own y=30 (not straddling it) so this
    # candidate isn't also rejected by the separate "not directly ahead of
    # the entry" check added 2026-09-10 — see
    # test_box_office_heuristic_rejects_landing_directly_ahead_of_the_entry
    # below, which isolates that check on its own.
    near_candidate = (2, 33, 5, 5)   # centroid ~7.1ft from entry, offset along the wall — within the 12ft default
    far_candidate = (2, 55, 5, 5)    # centroid ~25.7ft from entry — same open room, equally visible, too far
    assert prefer_fn(near_candidate) is True
    assert prefer_fn(far_candidate) is False, "a far-but-visible candidate should no longer satisfy prefer_fn"


def test_box_office_heuristic_rejects_landing_directly_ahead_of_the_entry():
    """Client decision, 2026-09-10 ("box office should not be directly in
    front of entry, it should either be in left or right wall align"): a
    candidate that straddles the entry's own straight-ahead line — the ray
    perpendicular to the wall the entry sits on — must be excluded by
    hard_filter_fn even when it's near and has a clear sightline, since
    standing there would put Box Office directly in a customer's walking
    path rather than flanking the door. This is a HARD filter, not the soft
    prefer_fn — see hard_filter_fn's own docstring in _support_zone_heuristic
    for why: a soft prefer_fn term can still be overridden by the "nothing
    preferred, use the full pool" fallback, which would silently resurface a
    blocking placement on a floor plate where it's the only near-and-visible
    spot. An equally-near candidate offset along the same wall (not
    straddling that line) must still pass the hard filter and be preferred
    by prefer_fn."""
    usable = _usable()
    entry_point = (0, 30)  # on the x=0 wall of RECT_BOUNDARY; "into the room" is +x
    score_fn, prefer_fn, hard_filter_fn = layout_engine._support_zone_heuristic(
        "BOX_OFFICE", entry_point, [], usable, usable, [], ["AUDITORIUM"], None
    )
    assert hard_filter_fn is not None, "BOX_OFFICE should have a hard 'don't block the entry' filter when a direction is known"
    directly_ahead = (2, 27, 5, 5)  # y:[27,32] straddles the entry's own y=30 — blocks the straight-in path
    flanking = (2, 33, 5, 5)        # y:[33,38] — offset along the wall, same distance class, doesn't block it
    assert hard_filter_fn(directly_ahead) is False, "a candidate straddling the entry's straight-ahead line should be hard-rejected"
    assert hard_filter_fn(flanking) is True
    # Sightline/adjacency (prefer_fn) are unaffected by the ray check now
    # that it lives in hard_filter_fn instead — both of these still pass on
    # sightline+adjacency grounds alone; blocking exclusion happens upstream
    # in the candidate pool, not here.
    assert prefer_fn(directly_ahead) is True
    assert prefer_fn(flanking) is True


def test_fnb_heuristic_now_scores_by_route_to_passage_and_auditorium():
    """New this round: FNB used to carry only a sightline-from-entry
    prefer_fn, with no positional score_fn at all — any visible spot ranked
    the same as any other visible spot. "Conveniently located along the
    route to auditoriums" (team's own placement standards) needs a real
    score, the exact same dual-distance-to-passage-and-nearest-screen
    pattern FOYER already uses."""
    usable = _usable()
    entry_point = (0, 30)
    auditorium = layout_engine._rect(70, 0, 20, 40)
    passage = layout_engine._rect(40, 0, 10, 10)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "FNB", entry_point, [], usable, usable, [auditorium, passage], ["AUDITORIUM", "PASSAGE"], passage
    )
    assert prefer_fn is not None
    assert score_fn is not None, "FNB should now also score candidates by distance to passage + nearest auditorium"
    near_route = (45, 15, 5, 5)      # close to both the passage and the auditorium
    far_from_route = (0, 55, 5, 5)   # far corner, away from both
    assert score_fn(near_route) < score_fn(far_from_route)


def test_manager_room_heuristic_prefers_proximity_to_box_office():
    usable = _usable()
    box_office = layout_engine._rect(50, 0, 10, 10)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "MANAGER_ROOM", None, [], usable, usable, [box_office], ["BOX_OFFICE"], None
    )
    assert prefer_fn is None
    assert score_fn is not None
    near = (55, 12, 5, 5)
    far = (0, 55, 5, 5)
    assert score_fn(near) < score_fn(far)

    # No Box Office placed/known yet — no preference at all, same
    # None-tolerant fallback pattern passage_rect already gets elsewhere.
    score_fn2, prefer_fn2, _hard_filter_fn2 = layout_engine._support_zone_heuristic(
        "MANAGER_ROOM", None, [], usable, usable, [], [], None
    )
    assert score_fn2 is None and prefer_fn2 is None


def test_electrical_heuristic_prefers_distance_from_entry_and_washroom():
    usable = _usable()
    entry_point = (0, 30)
    washroom = layout_engine._rect(20, 20, 10, 10)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "ELECTRICAL", entry_point, [], usable, usable, [washroom], ["WASHROOM"], None
    )
    assert prefer_fn is None
    assert score_fn is not None
    near_both = (5, 25, 5, 5)        # close to entry AND close to the washroom
    far_from_both = (90, 55, 5, 5)   # far from both
    assert score_fn(far_from_both) < score_fn(near_both)  # lower (more negative) score wins


# ---------- duct-aware Washroom, Projector Room (real placement-standards round 2) ----------

def test_washroom_heuristic_prefers_proximity_to_a_confirmed_duct():
    """New this round: real DUCT-classified obstacles (cad_extraction.py's
    DUCT_LAYER_HINTS) now feed WASHROOM's own placement preference — the
    team's own placement standards prefer a washroom near a plumbing duct/
    shaft when one is confirmed on the drawing. Before this, WASHROOM only
    ever had the existing sightline prefer_fn, no positional score_fn at
    all."""
    usable = _usable()
    entry_point = (0, 30)
    duct = layout_engine._rect(60, 30, 4, 4)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "WASHROOM", entry_point, [], usable, usable, [], [], None, duct_polys=[duct]
    )
    assert prefer_fn is not None, "the existing sightline preference must be unaffected"
    assert score_fn is not None, "WASHROOM should now also score candidates by distance to a confirmed duct"
    near_duct = (58, 28, 5, 5)
    far_from_duct = (0, 55, 5, 5)
    assert score_fn(near_duct) < score_fn(far_from_duct)


def test_washroom_heuristic_has_no_duct_score_when_none_confirmed():
    """No ducts confirmed on the drawing: behavior unchanged from before this
    round — no score_fn at all, sightline prefer_fn only."""
    usable = _usable()
    entry_point = (0, 30)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "WASHROOM", entry_point, [], usable, usable, [], [], None, duct_polys=[]
    )
    assert prefer_fn is not None
    assert score_fn is None


def test_projector_heuristic_prefers_touching_the_screen_wall_not_the_door_wall():
    """New this round: Projector Room should sit behind ANY one auditorium's
    screen (one room per complex, served via cable/network — see the
    document's own resolution of the previously-unconfirmed question).
    Recomputes that auditorium's screen wall the exact same way it was
    really derived at placement time (_screen_wall_for_rect + _OPPOSITE_WALL)
    — proving the preference reads the *opposite* wall from the entry, not
    just "any wall of the room.\""""
    usable = _usable()
    entry_point = (0, 30)  # entry is nearest the auditorium's min_x wall
    # 40ft wide (x) x 30ft deep (y) — wider than deep, so the room's real
    # depth axis is x (see _screen_wall_for_rect's restrict_to_depth_axis)
    # and screen_wall correctly lands on min_x/max_x, not min_y/max_y.
    auditorium = layout_engine._rect(20, 0, 40, 30)  # door_wall=min_x (x=20) -> screen_wall=max_x (x=60)
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "PROJECTOR", entry_point, [], usable, usable, [auditorium], ["AUDITORIUM"], None
    )
    assert prefer_fn is not None
    on_screen_wall = (60, 15, 3, 3)   # touches x=60, the real screen wall
    on_door_wall = (17, 15, 3, 3)     # touches x=20, the door wall — must NOT count
    assert prefer_fn(on_screen_wall) is True
    assert prefer_fn(on_door_wall) is False


def test_projector_heuristic_has_no_preference_with_no_auditoriums_placed():
    usable = _usable()
    score_fn, prefer_fn, _hard_filter_fn = layout_engine._support_zone_heuristic(
        "PROJECTOR", None, [], usable, usable, [], [], None
    )
    assert score_fn is None and prefer_fn is None


def test_place_single_zone_projector_is_placeable_but_opt_in_only():
    """Confirms the generic SUPPORT_ZONE_DEFAULTS-driven dispatch already in
    place_single_zone picks up PROJECTOR with no special-casing beyond the
    table entry itself (same mechanism every other zone type uses), and
    that it stays opt-in (Add Zone only), same as ELECTRICAL — no real area
    figure exists yet for either."""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "PROJECTOR", {}
    )
    assert room is not None, warning
    assert room["display_name"] == "Projector Room"
    assert "PROJECTOR" not in layout_engine.SUPPORT_ZONE_AUTO_ORDER


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
    file). Checked against the matched preset's OWN real seating_mix from
    the registry, not a fixed expected type — the exact preset/dimensions a
    default (0, 0, 100, 60) placement produces is allowed to legitimately
    shift with unrelated engine changes (e.g. which wall the screen lands
    on doesn't change which preset matches), so what actually matters here
    is "reflects the real preset," not "always resolves to this one preset
    tier's mix.\""""
    usable = _usable()
    room, warning = layout_engine.place_single_zone(
        usable, usable, [], [], [], (0, 0, 100, 60), "AUDITORIUM", {}
    )
    assert room is not None, warning
    assert room["preset_id"] is not None, "test assumes a real SOP preset matches, not a custom-fit screen"
    preset = next(p for p in layout_engine.rules_registry.auditorium_presets() if p["id"] == room["preset_id"])
    assert room["seat_config"]["primary_seat_type_id"] in preset["seating_mix"], (
        f"primary_seat_type_id {room['seat_config']['primary_seat_type_id']!r} is not in matched preset "
        f"{preset['id']}'s own seating_mix {preset['seating_mix']} — looks hardcoded, not preset-driven"
    )


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
    becomes real Passage/circulation space instead (see
    _place_support_zones_and_passage / _build_passage_room), never silently
    lost the way it would have been before Passage-as-remainder existed."""
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
    real Passage space to walk into. No auditorium's own rectangle should
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


def test_reserve_entry_vestibule_also_shrinks_usable_area_around_exit_points():
    """Client decision, 2026-09-10 (Cinema_Layout_Notes.pdf groups "Entry &
    Exit" together as both not being given proper space): a marked exit
    point gets the same walkable-buffer treatment the entry already did —
    an exit is often an auditorium's own fire-exit wall, but that wall
    still needs an unobstructed few feet on the inside to actually reach
    and open it."""
    usable = _usable()
    exit_pt = (100, 30)
    reserved_usable, reserved_fallback = layout_engine._reserve_entry_vestibule(usable, usable, None, [exit_pt])
    assert reserved_usable.area < usable.area
    assert reserved_fallback.area < usable.area
    from shapely.geometry import Point
    assert not reserved_usable.contains(Point(exit_pt).buffer(1))
    # A point well clear of the exit keeps its area untouched.
    assert reserved_usable.contains(Point(50, 30))


def test_reserve_entry_vestibule_combines_entry_and_multiple_exits_without_double_counting_overlap():
    usable = _usable()
    entry = (0, 30)
    exits = [(100, 30), (100, 40)]  # close enough together that their disks overlap
    entry_only, _ = layout_engine._reserve_entry_vestibule(usable, usable, entry, [])
    both, _ = layout_engine._reserve_entry_vestibule(usable, usable, entry, exits)
    assert both.area < entry_only.area, "marking exits on top of an existing entry should carve out more area, not less/same"
    # Carved area is the union of the three disks, not a naive sum (which would double-count the overlap
    # between the two nearby exit disks) — so it must be strictly less than three independent disks' worth.
    clearance_ft = layout_engine.rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT") or 8.25
    import math
    one_disk_area = math.pi * clearance_ft ** 2
    carved = usable.area - both.area
    assert carved < 3 * one_disk_area


def test_reserve_entry_vestibule_is_a_noop_without_entry_or_exits():
    usable = _usable()
    reserved_usable, reserved_fallback = layout_engine._reserve_entry_vestibule(usable, usable, None, [])
    assert reserved_usable is usable
    assert reserved_fallback is usable


def test_auto_layout_keeps_auditoriums_clear_of_a_marked_exit():
    """Same real defect class _reserve_entry_vestibule fixes for the entry
    (a placed screen's wall landing inches from the marked point), now
    checked for an exit with no entry marked at all."""
    boundary = RECT_BOUNDARY
    usable = layout_engine.compute_usable_area(boundary, [])
    exit_pt = (0, 30)
    candidate = layout_engine.generate_candidate(
        usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 4, "exit_points_ft": [list(exit_pt)]}, []
    )
    clearance_ft = layout_engine.rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT") or 8.25
    from shapely.geometry import Point
    exit_point = Point(exit_pt)
    for room in candidate["rooms"]:
        if not room["room_type"].startswith("AUDITORIUM"):
            continue
        room_poly = layout_engine.poly_from_points(room["geometry_points_ft"])
        assert room_poly.distance(exit_point) >= clearance_ft - 1e-6, (
            f"{room['room_type']} sits {room_poly.distance(exit_point):.2f}ft from the marked exit, "
            f"closer than the required {clearance_ft}ft clearance"
        )


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

def test_generate_candidate_strips_support_zone_doors_but_keeps_auditorium_doors():
    """Support zones (Passage/F&B/Washroom/Box Office/etc.) still never arrive
    with a door glyph the architect never asked for — those are added by
    hand afterward via the edit canvas's own "+ Door" tool, since their
    computed door position is only ever a placement-pipeline-internal proxy
    (connectivity gating, Passage's door-touch tiebreak — see
    _strip_auto_generated_doors' own docstring). AUDITORIUM rooms are the
    deliberate exception this round adds: a screen's entry/exit pair is
    placed by a real, documented rule (_doors_for_screen_wall), so it's kept
    as a real, editable starting point instead of being thrown away."""
    candidate = layout_engine.generate_candidate(
        _usable(), RECT_BOUNDARY, "MAX_SEATS_PER_SCREEN",
        {"max_auditoriums": 4, "entry_point_ft": [0, 30]}, []
    )
    assert len(candidate["rooms"]) > 0
    auditoriums = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
    non_auditoriums = [r for r in candidate["rooms"] if not r["room_type"].startswith("AUDITORIUM")]
    assert auditoriums, "expected at least one auditorium in this candidate"
    for room in non_auditoriums:
        assert room["doors"] == [], f"{room['room_type']} carries an auto-generated door: {room['doors']}"
    for room in auditoriums:
        assert room["doors"], f"{room['room_type']} should carry its real computed doors"
        assert all(d["wall"] == layout_engine._OPPOSITE_WALL[room["screen_wall"]] for d in room["doors"]), \
            f"{room['room_type']}'s doors should be on its door wall (opposite the screen), not the screen wall itself"


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


# ---------- second and third real client buildings, pulled from live project
# storage the same way the dense-column fixture above was. Neither of these
# was ever locked into an automated test before — they were just data sitting
# in services/zoning-engine/storage/, only ever checked by a human running the
# app and looking at it. Both baselines below were verified against the exact
# stored geometry before being written as assertions, not assumed. ----------

_CHAUDHARY_PALANPUR_BOUNDARY_FT = [
    [0.0, 146.79], [48.63, 146.79], [48.63, 126.79], [47.66, 126.79], [47.53, 125.82], [64.33, 125.82],
    [64.33, 101.2], [62.65, 101.2], [62.65, 99.99], [65.07, 99.99], [65.07, 100.46], [79.89, 100.48],
    [79.89, 100.24], [81.08, 100.24], [81.08, 79.86], [79.89, 79.86], [79.89, 78.89], [80.86, 78.89],
    [24.55, 0.0], [21.38, 0.0], [21.38, 0.22], [19.45, 0.22], [19.45, 0.0], [14.2, 0.0],
    [14.2, 0.22], [12.27, 0.22], [12.27, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 146.79],
]

_CHAUDHARY_PALANPUR_OBSTACLES = [
    {"points_ft": [[33.75, 35.32], [31.35, 35.32], [31.35, 37.72], [33.75, 37.72], [33.75, 35.32]], "classification": "COLUMN"},
    {"points_ft": [[45.75, 35.92], [45.75, 37.12], [47.55, 37.12], [47.55, 35.92], [45.75, 35.92]], "classification": "COLUMN"},
    {"points_ft": [[31.45, 37.85], [33.87, 37.85], [33.87, 35.44], [31.45, 35.44], [31.45, 37.85]], "classification": "COLUMN"},
    {"points_ft": [[45.69, 36.04], [45.69, 37.25], [47.63, 37.25], [47.63, 36.04], [45.69, 36.04]], "classification": "COLUMN"},
    {"points_ft": [[54.84, 48.85], [54.84, 50.06], [56.77, 50.06], [56.77, 48.85], [54.84, 48.85]], "classification": "COLUMN"},
    {"points_ft": [[31.43, 63.47], [33.85, 63.47], [33.85, 61.05], [31.43, 61.05], [31.43, 63.47]], "classification": "COLUMN"},
    {"points_ft": [[33.75, 61.12], [31.35, 61.12], [31.35, 63.52], [33.75, 63.52], [33.75, 61.12]], "classification": "COLUMN"},
    {"points_ft": [[-0.75, 74.32], [-0.75, 75.82], [1.65, 75.82], [1.65, 74.32], [-0.75, 74.32]], "classification": "COLUMN"},
    {"points_ft": [[33.75, 86.62], [31.35, 86.62], [31.35, 89.02], [33.75, 89.02], [33.75, 86.62]], "classification": "COLUMN"},
    {"points_ft": [[31.43, 89.09], [33.85, 89.09], [33.85, 86.67], [31.43, 86.67], [31.43, 89.09]], "classification": "COLUMN"},
    {"points_ft": [[31.44, 114.7], [33.85, 114.7], [33.85, 112.29], [31.44, 112.29], [31.44, 114.7]], "classification": "COLUMN"},
    {"points_ft": [[33.75, 112.42], [31.35, 112.42], [31.35, 114.82], [33.75, 114.82], [33.75, 112.42]], "classification": "COLUMN"},
    {"points_ft": [[15.47, 141.73], [16.68, 141.73], [16.68, 139.79], [15.47, 139.79], [15.47, 141.73]], "classification": "COLUMN"},
    {"points_ft": [[33.38, 139.79], [31.93, 139.79], [31.93, 141.73], [33.38, 141.73], [33.38, 139.79]], "classification": "COLUMN"},
    {"points_ft": [[33.45, 139.72], [31.95, 139.72], [31.95, 141.82], [33.45, 141.82], [33.45, 139.72]], "classification": "COLUMN"},
]

_CHAUDHARY_PALANPUR_ENTRY_FT = [48.75, 138.92]
_CHAUDHARY_PALANPUR_EXIT_FT = [48.75, 129.62]


def test_chaudhary_palanpur_real_floor_places_only_real_presets_never_a_sliver():
    """A second, unrelated real client building (Chaudhary, Palanpur) —
    currently healthy in production but never locked into a test before.
    Verified directly against the stored geometry: MAX_SCREEN_COUNT places 4
    real-preset screens (35_SEAT each), MAX_SEATS_PER_SCREEN places 3
    (60_SEAT each) — both real, standard tiers, never a custom-fit sliver on
    this floor plate, with or without an entry+exit marked. Exists purely to
    catch a future regression before a human has to notice it in a
    screenshot, the way the dense-column starvation bug above was found."""
    for requirements in (
        {"max_auditoriums": 4},
        {
            "max_auditoriums": 4,
            "entry_point_ft": _CHAUDHARY_PALANPUR_ENTRY_FT,
            "exit_points_ft": [_CHAUDHARY_PALANPUR_EXIT_FT],
        },
    ):
        candidates = layout_engine.generate_candidates(
            _CHAUDHARY_PALANPUR_BOUNDARY_FT, _CHAUDHARY_PALANPUR_OBSTACLES, requirements
        )
        for candidate in candidates:
            aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
            assert len(aud_rooms) >= 3, (
                f"{candidate['strategy']} (entry marked={'entry_point_ft' in requirements}): "
                f"expected at least 3 real screens, got {len(aud_rooms)}"
            )
            for room in aud_rooms:
                assert room["preset_id"] is not None, (
                    f"{candidate['strategy']}: {room['room_type']} fell through to a custom-fit "
                    f"footprint ({room['width_ft']}x{room['depth_ft']}) on a floor plate that should "
                    "place only real SOP presets"
                )


_SWATI_TRINITY_BOUNDARY_FT = [
    [0.0, 66.12], [0.0, 57.88], [0.98, 57.88], [0.98, 53.94], [0.0, 53.94], [0.0, 38.31],
    [0.98, 38.31], [0.98, 34.38], [0.0, 34.38], [0.0, 26.12], [0.98, 26.12], [0.98, 22.19],
    [0.0, 22.19], [0.0, 7.23], [0.0, 3.94], [0.98, 3.94], [0.98, 0.38], [9.19, 0.38],
    [9.19, 3.22], [11.21, 3.22], [14.0, 3.22], [14.0, 3.94], [14.98, 3.94], [14.98, 1.48],
    [14.0, 1.48], [14.0, 0.0], [14.55, 0.0], [14.37, 0.38], [23.45, 0.38], [23.45, 3.22],
    [25.47, 3.22], [28.37, 3.22], [31.54, 3.22], [33.55, 3.22], [33.55, 0.38], [37.0, 0.38],
    [41.65, 0.38], [41.65, 2.95], [42.74, 2.95], [42.74, 20.22], [42.14, 20.22], [42.14, 26.12],
    [43.12, 26.12], [43.12, 24.13], [57.12, 24.13], [57.12, 26.12], [57.88, 26.12], [57.88, 24.13],
    [71.99, 24.13], [71.99, 26.62], [71.99, 29.08], [71.99, 31.91], [71.99, 34.38], [70.4, 34.38],
    [70.4, 37.33], [71.99, 37.33], [71.99, 39.67], [76.78, 39.67], [76.78, 44.61], [71.12, 44.61],
    [71.12, 54.92], [68.92, 54.92], [68.92, 57.12], [68.67, 57.12], [68.67, 57.88], [68.92, 57.88],
    [68.92, 57.88], [71.87, 57.88], [79.37, 57.88], [89.87, 57.88], [92.83, 57.88], [93.07, 57.88],
    [93.07, 57.12], [92.83, 57.12], [92.83, 54.92], [90.25, 54.92], [90.25, 38.31], [91.35, 38.31],
    [91.35, 34.38], [90.25, 34.38], [90.25, 26.21], [90.86, 26.21], [90.86, 24.13], [95.61, 24.13],
    [104.62, 24.13], [118.62, 24.13], [118.62, 26.12], [119.61, 26.12], [119.61, 18.74], [119.0, 18.74],
    [119.0, 5.91], [119.61, 5.91], [119.61, 3.22], [122.28, 3.22], [123.92, 3.22], [124.3, 3.22],
    [124.3, 2.84], [124.3, 0.38], [129.55, 0.38], [133.0, 0.38], [136.82, 0.38], [142.56, 0.38],
    [142.56, 2.84], [142.56, 3.22], [142.94, 3.22], [144.58, 3.22], [147.37, 3.22], [147.37, 9.22],
    [147.37, 9.6], [147.37, 23.17], [146.27, 23.17], [146.27, 25.75], [145.02, 25.75], [145.02, 34.75],
    [146.27, 34.75], [146.27, 37.33], [147.37, 37.33], [147.37, 47.81], [147.75, 47.81], [147.75, 54.92],
    [146.27, 54.92], [146.27, 57.12], [146.03, 57.12], [146.03, 57.88], [146.27, 57.88], [146.27, 57.88],
    [147.75, 57.88], [147.75, 66.12], [147.37, 66.12], [90.63, 66.12], [89.87, 66.12], [71.87, 66.12],
    [71.12, 66.12], [14.75, 66.12], [14.0, 66.12], [0.0, 66.12], [0.0, 66.12],
]

_SWATI_TRINITY_OBSTACLES = [
    {"points_ft": [[117.83, 37.33], [119.79, 37.33], [119.79, 34.38], [117.83, 34.38], [117.83, 37.33]], "classification": "COLUMN"},
    {"points_ft": [[106.74, 35.19], [106.44, 35.19], [106.44, 38.79], [102.54, 38.79], [102.54, 35.19], [101.94, 35.19], [101.94, 39.09], [104.34, 39.09], [106.74, 39.09], [106.74, 35.79], [106.74, 35.19]], "classification": "COLUMN"},
    {"points_ft": [[117.33, 57.88], [120.29, 57.88], [120.29, 54.92], [117.33, 54.92], [117.33, 57.88]], "classification": "COLUMN"},
    {"points_ft": [[26.29, 26.12], [28.75, 26.12], [28.75, 23.17], [26.29, 23.17], [26.29, 26.12]], "classification": "COLUMN"},
    {"points_ft": [[41.95, 37.33], [43.92, 37.33], [43.92, 34.38], [41.95, 34.38], [41.95, 37.33]], "classification": "COLUMN"},
    {"points_ft": [[43.14, 35.49], [43.14, 39.39], [47.04, 39.39], [47.04, 35.49], [45.54, 35.49], [45.54, 35.19], [44.04, 35.19], [44.04, 35.49], [43.14, 35.49]], "classification": "COLUMN"},
    {"points_ft": [[26.04, 57.88], [28.99, 57.88], [28.99, 54.92], [26.04, 54.92], [26.04, 57.88]], "classification": "COLUMN"},
    {"points_ft": [[41.95, 57.88], [43.92, 57.88], [43.92, 54.92], [41.95, 54.92], [41.95, 57.88]], "classification": "COLUMN"},
    {"points_ft": [[14.0, 24.65], [14.98, 24.65], [14.98, 22.19], [14.0, 22.19], [14.0, 24.65]], "classification": "COLUMN"},
    {"points_ft": [[14.0, 32.38], [14.98, 32.38], [14.98, 29.91], [14.0, 29.91], [14.0, 32.38]], "classification": "COLUMN"},
    {"points_ft": [[14.0, 57.88], [14.98, 57.88], [14.98, 54.92], [14.0, 54.92], [14.0, 57.88]], "classification": "COLUMN"},
]


def test_swati_trinity_tight_column_floor_uses_disclosed_sliver_not_silent_starvation():
    """A third real client building (Swati Trinity, Ahmedabad) with a
    genuinely tight column grid: 11 columns packed into ~7,100 sqft. Directly
    verified (including with a real entry point marked, ruling out the
    top_k/mirroring regression above) that only 2 screens fit via honest
    placement — this is real geometry, not an algorithm gap. The second
    screen falls back to a disclosed non-standard sliver rather than being
    silently dropped or silently left as unlabeled Passage slack. This test
    guards the disclosure itself: if a future change makes this floor
    plate's fallback silent (no warning, or the note goes missing off the
    room), that's a real regression in honesty even though the screen count
    doesn't change."""
    requirements = {"max_auditoriums": 4}
    candidates = layout_engine.generate_candidates(
        _SWATI_TRINITY_BOUNDARY_FT, _SWATI_TRINITY_OBSTACLES, requirements
    )
    for candidate in candidates:
        aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
        assert len(aud_rooms) >= 2, (
            f"{candidate['strategy']}: expected at least the 2 screens this real floor plate can honestly hold, "
            f"got {len(aud_rooms)}"
        )
        real_preset_rooms = [r for r in aud_rooms if r["preset_id"] is not None]
        custom_fit_rooms = [r for r in aud_rooms if r["preset_id"] is None]
        assert real_preset_rooms, f"{candidate['strategy']}: expected at least one real-preset screen"
        if custom_fit_rooms:
            assert any("realism floor" in w for w in candidate.get("warnings", [])), (
                f"{candidate['strategy']}: placed a non-standard custom-fit screen "
                f"({[(r['width_ft'], r['depth_ft']) for r in custom_fit_rooms]}) without disclosing it via "
                "a candidate-level warning — must never silently ship a sliver"
            )


# ---------- a fourth real client building: the densest floor tested so far ----------

def test_dhule_dense_obstacle_floor_places_real_presets_with_no_collisions():
    """A fourth real client building (Dhule) — the largest and densest
    floor tested: 1,033 obstacles (372 columns, 47 walls, 315 furniture,
    271 unclassified, 28 staircases) across a confirmed 125,353 sqft
    boundary. The stored layout_current.json for this project was missing
    all 4 support zones and had a suspiciously small Passage (2,100 sqft on a
    125k sqft floor) — turned out to be a stale, manually-edited save from
    testing, not the algorithm's real output (same pattern as the Swati
    Trinity fixture above). A fresh run produces 4 real-preset screens plus
    all 4 support zones plus a correctly enormous leftover Passage, under
    both strategies, with zero geometric overlap between any placed screen
    and any real blocking obstacle (wall/staircase/unclassified — verified
    directly with shapely, not assumed)."""
    requirements = {"max_auditoriums": 4}
    candidates = layout_engine.generate_candidates(DHULE_BOUNDARY_FT, DHULE_OBSTACLES, requirements)
    blocking_polys = []
    for o in DHULE_OBSTACLES:
        if o.get("classification") in ("COLUMN", "FURNITURE"):
            continue
        pts = o.get("points_ft", [])
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        blocking_polys.append(poly if poly.is_valid else poly.buffer(0))

    for candidate in candidates:
        aud_rooms = [r for r in candidate["rooms"] if r["room_type"].startswith("AUDITORIUM")]
        support_rooms = [r for r in candidate["rooms"] if r["room_type"] in ("BOX_OFFICE", "FNB", "WASHROOM", "BOH")]
        assert len(aud_rooms) == 4, f"{candidate['strategy']}: expected all 4 auditoriums to place, got {len(aud_rooms)}"
        assert len(support_rooms) == 4, f"{candidate['strategy']}: expected all 4 support zones to place, got {len(support_rooms)}"
        for room in aud_rooms:
            assert room["preset_id"] is not None, (
                f"{candidate['strategy']}: {room['room_type']} fell through to a custom-fit footprint "
                "on a floor plate that has real room for standard presets"
            )
            poly = Polygon(room["geometry_points_ft"])
            if not poly.is_valid:
                poly = poly.buffer(0)
            overlap_area = sum(poly.intersection(bp).area for bp in blocking_polys if poly.intersects(bp))
            assert overlap_area < 0.5, (
                f"{candidate['strategy']}: {room['room_type']} overlaps a real wall/staircase/unclassified "
                f"obstacle by {overlap_area:.1f} sqft — this floor plate has 346 of them, easy to clip if the "
                "usable-area subtraction regresses"
            )
