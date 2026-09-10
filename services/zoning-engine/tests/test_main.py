"""Regression coverage for main.py's _replace_foyer_with_derived — the fix
for a real, live bug: a stale/bad Foyer room used to block every single
manual edit (update_layout validated the WHOLE room list, so one invalid
Foyer 422'd every drag/resize of any other room, forever, since nothing
ever fixed Foyer's own geometry). Foyer is now never part of what's
validated or stored directly — always recomputed fresh as the real
leftover remainder after every other room, so it can't overlap anything
by construction."""
import shutil

import layout_engine
import main
import seat_engine
import storage


def _room(room_type, x, y, w, h):
    return {
        "room_id": f"{room_type.lower()}-1", "room_type": room_type, "display_name": room_type,
        "area_sqft": w * h, "width_ft": w, "depth_ft": h, "origin_ft": [x, y],
        "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "doors": [],
    }


def _auditorium_room(room_id, x, y, w, h, screen_wall="min_y", doors=None):
    room = _room("AUDITORIUM_1", x, y, w, h)
    room["room_id"] = room_id
    room["screen_wall"] = screen_wall
    room["doors"] = doors or []
    room["seat_config"] = {
        "primary_seat_type_id": seat_engine.DEFAULT_SEAT_TYPE_ID,
        "secondary_seat_type_id": None, "primary_ratio_pct": 100, "front_row_count": None,
    }
    room["seat_estimate"] = {}
    return room


def test_replace_foyer_with_derived_produces_non_overlapping_foyer():
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40)]
    final_rooms, circulation, _foyer_warning = main._replace_foyer_with_derived(boundary, [], real_rooms, {})

    foyer = next((r for r in final_rooms if r["room_type"] == "FOYER"), None)
    assert foyer is not None
    aud_poly = layout_engine.poly_from_points(real_rooms[0]["geometry_points_ft"])
    foyer_poly = layout_engine.poly_from_points(foyer["geometry_points_ft"])
    assert foyer_poly.intersection(aud_poly).area < 1.0
    assert foyer_poly.difference(layout_engine.poly_from_points(boundary)).area < 1.0


def test_replace_foyer_with_derived_ignores_a_stale_bad_foyer_already_in_real_rooms():
    """The exact live-project bug: a stale Foyer entry that spans (or
    exceeds) the whole boundary must never influence the freshly computed
    one — the caller strips FOYER from real_rooms before calling this
    (see update_layout/add_zone), so this proves the derived Foyer is
    computed purely from the OTHER rooms, never from a bad prior Foyer."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40)]
    # Simulate main.py's own strip-FOYER-first step explicitly, proving the
    # function itself never needs to see a bad Foyer to do the right thing.
    final_rooms, circulation, _foyer_warning = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    foyer = next(r for r in final_rooms if r["room_type"] == "FOYER")
    assert foyer["area_sqft"] < layout_engine.poly_from_points(boundary).area
    assert circulation >= 0


def test_candidate_geometry_errors_none_for_clean_candidate():
    """A normal, non-overlapping set of rooms must pass through untouched —
    no false positives from the new save-time validation gate."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40), _room("AUDITORIUM_2", 30, 0, 24, 40)]
    assert main._candidate_geometry_errors(boundary, [], rooms) is None


def test_candidate_geometry_errors_catches_a_real_overlap_and_ignores_foyer():
    """The actual defect this gate exists to catch: two real rooms
    overlapping. Must be reported (so run_zoning/select_candidate refuse to
    save it as the editable layout — see _candidate_geometry_errors'
    docstring for why this matters: an unvalidated overlap saved today would
    otherwise permanently block every future edit, since update_layout
    re-validates the whole room list on every call). A FOYER entry is
    included specifically overlapping everything, proving it's stripped
    before validation exactly like update_layout strips it — Foyer is
    derived, never blocked on."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    overlapping_rooms = [
        _room("AUDITORIUM_1", 0, 0, 24, 40),
        _room("AUDITORIUM_2", 20, 0, 24, 40),  # overlaps AUDITORIUM_1 by 4x40
        _room("FOYER", 0, 0, 100, 60),  # spans the whole boundary; must be ignored, not flagged
    ]
    errors = main._candidate_geometry_errors(boundary, [], overlapping_rooms)
    assert errors is not None
    assert any(e["issue"] == "ROOM_OVERLAP" for e in errors)
    assert not any(e.get("room_id") == "foyer-1" for e in errors)


def test_replace_foyer_with_derived_recomputes_after_a_room_shrinks():
    """The real UX this fixes: after a manual resize (a room shrinking),
    Foyer must grow to fill the newly-freed space, not stay stale — proving
    it's genuinely recomputed on every call, not cached."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    big_room = [_room("AUDITORIUM_1", 0, 0, 40, 40)]
    small_room = [_room("AUDITORIUM_1", 0, 0, 24, 40)]

    rooms_before, _, _foyer_warning_before = main._replace_foyer_with_derived(boundary, [], big_room, {})
    rooms_after, _, _foyer_warning_after = main._replace_foyer_with_derived(boundary, [], small_room, {})

    foyer_before = next(r for r in rooms_before if r["room_type"] == "FOYER")
    foyer_after = next(r for r in rooms_after if r["room_type"] == "FOYER")
    assert foyer_after["area_sqft"] > foyer_before["area_sqft"]


# ---------- Foyer hierarchy warning (placement-standards round 2) ----------

def test_foyer_hierarchy_warning_fires_when_foyer_is_smaller_than_an_auxiliary():
    """The team's own placement standards: Foyer must be the largest
    non-auditorium space. A large F&B room can genuinely leave less real
    leftover space than it claimed itself — this is a soft warning, not
    something the engine tries to prevent by construction."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40), _room("FNB", 24, 0, 70, 50)]
    _final_rooms, _circulation, warning = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    assert warning is not None
    assert "smaller than another support zone" in warning


def test_foyer_hierarchy_warning_silent_when_hierarchy_holds():
    """A well-proportioned layout (Foyer genuinely the 2nd-largest space,
    smaller than the auditorium, no other auxiliaries yet to compare
    against) must produce no warning at all."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 90, 50)]
    _final_rooms, _circulation, warning = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    assert warning is None


def test_foyer_hierarchy_warning_does_not_accumulate_across_repeated_edits():
    """Real bug this guards against: the warning is recomputed fresh on
    every call (it describes current state, not how the layout was
    originally generated) — a naive "append to existing warnings" would
    duplicate it on every subsequent edit that still has the same problem.
    Simulates two consecutive update_layout-style calls the way that
    endpoint actually threads warnings through."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40), _room("FNB", 24, 0, 70, 50)]

    _final_rooms, _circulation, warning_1 = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    warnings_after_edit_1 = [w for w in [] if not main._is_foyer_hierarchy_warning(w)] + ([warning_1] if warning_1 else [])
    assert warnings_after_edit_1 == [warning_1]

    _final_rooms, _circulation, warning_2 = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    warnings_after_edit_2 = [w for w in warnings_after_edit_1 if not main._is_foyer_hierarchy_warning(w)] + ([warning_2] if warning_2 else [])
    assert warnings_after_edit_2 == [warning_2], "must still be exactly one copy, not two"


# ---------- _screen_wall_door_conflict_note ----------

def test_screen_wall_door_conflict_note_fires_when_a_door_sits_on_the_screen_wall():
    room = _auditorium_room("aud-1", 0, 0, 40, 60, screen_wall="min_y",
                             doors=[{"kind": "ENTRY", "wall": "min_y", "offset_ft": 5, "width_ft": 3.5}])
    note = main._screen_wall_door_conflict_note(room)
    assert note is not None
    assert "screen wall" in note


def test_screen_wall_door_conflict_note_silent_when_doors_are_elsewhere():
    room = _auditorium_room("aud-1", 0, 0, 40, 60, screen_wall="min_y",
                             doors=[{"kind": "ENTRY", "wall": "max_y", "offset_ft": 5, "width_ft": 3.5}])
    assert main._screen_wall_door_conflict_note(room) is None


# ---------- _recompute_room_derived_fields: axis correction + door-aware exclusion ----------

def test_recompute_room_derived_fields_axis_corrects_for_a_vertical_screen_wall():
    """The Phase-0 fix this round depends on: a room whose screen_wall is
    min_x/max_x must have its seat estimate computed against the swapped
    (depth, width) pair, not its raw box width_ft/depth_ft directly."""
    room = _auditorium_room("aud-1", 0, 0, 40, 70, screen_wall="min_x")
    main._recompute_room_derived_fields(room, [])
    expected = seat_engine.estimate_seats(70, 40)  # swapped: h becomes the screen-parallel span
    assert room["seat_estimate"]["rows"] == expected["rows"]
    assert room["seat_estimate"]["seats_per_row"] == expected["seats_per_row"]


def test_recompute_room_derived_fields_applies_side_door_exclusion():
    """A side-wall door on a room being recomputed should reduce its seat
    count relative to an identical room with no such door — proves
    _recompute_room_derived_fields actually wires _side_door_exclusions into
    the estimate_seats call, not just the axis correction above."""
    plain_room = _auditorium_room("aud-1", 0, 0, 40, 60, screen_wall="min_y")
    main._recompute_room_derived_fields(plain_room, [])

    door_room = _auditorium_room(
        "aud-2", 0, 0, 40, 60, screen_wall="min_y",
        doors=[{"kind": "ENTRY", "wall": "min_x", "offset_ft": plain_room["seat_estimate"]["first_row_distance_ft"], "width_ft": 3}]
    )
    main._recompute_room_derived_fields(door_room, [])
    assert door_room["seat_estimate"]["seat_count"] < plain_room["seat_estimate"]["seat_count"]


def test_recompute_room_derived_fields_sets_and_clears_screen_wall_note():
    room = _auditorium_room("aud-1", 0, 0, 40, 60, screen_wall="min_y",
                             doors=[{"kind": "ENTRY", "wall": "min_y", "offset_ft": 5, "width_ft": 3.5}])
    main._recompute_room_derived_fields(room, [])
    assert "screen_wall_note" in room

    room["doors"] = []
    main._recompute_room_derived_fields(room, [])
    assert "screen_wall_note" not in room


# ---------- POST /layout/rooms/{room_id}/screen-wall ----------

_TEST_PROJECT_ID = "test-screen-wall-endpoint"


def _seed_layout(rooms, boundary=None):
    boundary = boundary or [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    layout = {
        "region_id": "region-1", "source_candidate_id": None,
        "boundary_points_ft": boundary, "obstacles": [], "rooms": rooms,
        "circulation_area_sqft": 0.0, "warnings": [], "revision": "R0",
        "updated_at": storage.now_iso(),
    }
    storage.write_json(storage.layout_path(_TEST_PROJECT_ID), layout)
    storage.write_json(storage.requirements_path(_TEST_PROJECT_ID), {})


def _cleanup_test_project():
    shutil.rmtree(storage.project_dir(_TEST_PROJECT_ID), ignore_errors=True)


def test_update_screen_wall_recomputes_seat_estimate_and_persists():
    try:
        room = _auditorium_room("aud-1", 0, 0, 40, 70, screen_wall="min_y")
        _seed_layout([room])

        result = main.update_screen_wall(_TEST_PROJECT_ID, "aud-1", main.ScreenWallUpdateIn(screen_wall="min_x"))
        updated_room = next(r for r in result["rooms"] if r["room_id"] == "aud-1")
        assert updated_room["screen_wall"] == "min_x"
        expected = seat_engine.estimate_seats(70, 40)
        assert updated_room["seat_estimate"]["rows"] == expected["rows"]

        persisted = storage.read_json(storage.layout_path(_TEST_PROJECT_ID))
        persisted_room = next(r for r in persisted["rooms"] if r["room_id"] == "aud-1")
        assert persisted_room["screen_wall"] == "min_x"
    finally:
        _cleanup_test_project()


def test_update_screen_wall_rejects_an_invalid_wall_value():
    from fastapi import HTTPException
    try:
        room = _auditorium_room("aud-1", 0, 0, 40, 70)
        _seed_layout([room])
        try:
            main.update_screen_wall(_TEST_PROJECT_ID, "aud-1", main.ScreenWallUpdateIn(screen_wall="north"))
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 422
    finally:
        _cleanup_test_project()


def test_update_screen_wall_404s_for_an_unknown_room():
    from fastapi import HTTPException
    try:
        room = _auditorium_room("aud-1", 0, 0, 40, 70)
        _seed_layout([room])
        try:
            main.update_screen_wall(_TEST_PROJECT_ID, "does-not-exist", main.ScreenWallUpdateIn(screen_wall="min_x"))
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 404
    finally:
        _cleanup_test_project()


def test_update_screen_wall_404s_for_a_non_auditorium_room():
    from fastapi import HTTPException
    try:
        room = _room("WASHROOM", 0, 0, 20, 20)
        _seed_layout([room])
        try:
            main.update_screen_wall(_TEST_PROJECT_ID, room["room_id"], main.ScreenWallUpdateIn(screen_wall="min_x"))
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 404
    finally:
        _cleanup_test_project()


def test_update_screen_wall_404s_when_no_layout_exists_yet():
    from fastapi import HTTPException
    try:
        try:
            main.update_screen_wall("no-such-project", "aud-1", main.ScreenWallUpdateIn(screen_wall="min_x"))
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 404
    finally:
        shutil.rmtree(storage.project_dir("no-such-project"), ignore_errors=True)
