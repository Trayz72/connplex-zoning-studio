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
