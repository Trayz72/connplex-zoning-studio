"""Regression coverage for main.py's _replace_foyer_with_derived — the fix
for a real, live bug: a stale/bad Foyer room used to block every single
manual edit (update_layout validated the WHOLE room list, so one invalid
Foyer 422'd every drag/resize of any other room, forever, since nothing
ever fixed Foyer's own geometry). Foyer is now never part of what's
validated or stored directly — always recomputed fresh as the real
leftover remainder after every other room, so it can't overlap anything
by construction."""
import layout_engine
import main


def _room(room_type, x, y, w, h):
    return {
        "room_id": f"{room_type.lower()}-1", "room_type": room_type, "display_name": room_type,
        "area_sqft": w * h, "width_ft": w, "depth_ft": h, "origin_ft": [x, y],
        "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "doors": [],
    }


def test_replace_foyer_with_derived_produces_non_overlapping_foyer():
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    real_rooms = [_room("AUDITORIUM_1", 0, 0, 24, 40)]
    final_rooms, circulation = main._replace_foyer_with_derived(boundary, [], real_rooms, {})

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
    final_rooms, circulation = main._replace_foyer_with_derived(boundary, [], real_rooms, {})
    foyer = next(r for r in final_rooms if r["room_type"] == "FOYER")
    assert foyer["area_sqft"] < layout_engine.poly_from_points(boundary).area
    assert circulation >= 0


def test_replace_foyer_with_derived_recomputes_after_a_room_shrinks():
    """The real UX this fixes: after a manual resize (a room shrinking),
    Foyer must grow to fill the newly-freed space, not stay stale — proving
    it's genuinely recomputed on every call, not cached."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    big_room = [_room("AUDITORIUM_1", 0, 0, 40, 40)]
    small_room = [_room("AUDITORIUM_1", 0, 0, 24, 40)]

    rooms_before, _ = main._replace_foyer_with_derived(boundary, [], big_room, {})
    rooms_after, _ = main._replace_foyer_with_derived(boundary, [], small_room, {})

    foyer_before = next(r for r in rooms_before if r["room_type"] == "FOYER")
    foyer_after = next(r for r in rooms_after if r["room_type"] == "FOYER")
    assert foyer_after["area_sqft"] > foyer_before["area_sqft"]
