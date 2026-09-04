"""Regression coverage for placement/connectivity.py — the hand-rolled
flood-fill reachability gate used by layout_engine's post-auditorium
support-zone placement to keep the entry point and every placed room's
door mutually reachable (no candidate may block the common path)."""
from shapely.geometry import box
from shapely.ops import unary_union

from placement import connectivity


def test_would_sever_flags_a_candidate_that_disconnects_a_previously_reachable_pair():
    """The real gate used by _place_single_support_zone_connectivity_aware:
    a candidate that blocks the only neck between two open halves must be
    flagged as severing — the two halves' reference points were reachable
    before, not after."""
    floor = box(0, 0, 40, 20)
    pt_a, pt_b = (1, 10), (39, 10)
    blocking_candidate = box(15, 0, 25, 20)
    free_after = floor.difference(blocking_candidate)
    assert connectivity.would_sever(floor, free_after, floor.bounds, [pt_a, pt_b])

    safe_candidate = box(1, 15, 6, 19)
    free_after_safe = floor.difference(safe_candidate)
    assert not connectivity.would_sever(floor, free_after_safe, floor.bounds, [pt_a, pt_b])


def test_would_sever_ignores_a_pre_existing_disconnection():
    """The real bug this function exists to avoid: two reference points that
    were ALREADY unreachable from each other before any candidate (e.g. a
    genuine confirmed WALL already splits the floor) must never be flagged
    as severed by a candidate that didn't cause that — an absolute
    "everything reachable" test would incorrectly reject every candidate
    forever in this case, since nothing could ever satisfy an
    already-broken baseline."""
    left = box(0, 0, 18, 20)
    right = box(22, 0, 40, 20)
    already_split_floor = unary_union([left, right])  # a real wall gap at x=[18,22]
    pt_a, pt_b = (1, 10), (39, 10)

    # Sanity: confirm the baseline really is disconnected.
    assert not connectivity.reachable_between(already_split_floor, (0, 0, 40, 20), [pt_a, pt_b])

    # A candidate placed entirely within the left half changes nothing about
    # the pre-existing split — must NOT be flagged as severing.
    candidate = box(1, 1, 3, 3)
    free_after = already_split_floor.difference(candidate)
    assert not connectivity.would_sever(already_split_floor, free_after, (0, 0, 40, 20), [pt_a, pt_b])


def test_flood_fill_finds_reachable_component():
    """Two points in the same open rectangle are reachable."""
    free_space = box(0, 0, 40, 20)
    bbox = free_space.bounds
    assert connectivity.reachable_between(free_space, bbox, [(1, 1), (39, 19)])


def test_candidate_that_would_wall_off_a_door_is_rejected():
    """A 40x20 floor with a narrow (~10ft) neck at x=[15,25] connecting a
    left half and a right half. A door on the right half's far wall must
    stay reachable from the entry on the left half's near wall — UNLESS a
    candidate rect fills the entire neck, which must sever it."""
    floor = box(0, 0, 40, 20)
    entry = (1, 10)
    door = (39, 10)

    # No obstruction: reachable.
    assert connectivity.reachable_between(floor, floor.bounds, [entry, door])

    # A candidate that blocks the whole neck (x=[15,25], full height) severs it.
    blocking_candidate = box(15, 0, 25, 20)
    free_after = floor.difference(blocking_candidate)
    assert not connectivity.reachable_between(free_after, floor.bounds, [entry, door])

    # A candidate placed well away from the neck (e.g. a corner) does not.
    safe_candidate = box(1, 15, 6, 19)
    free_after_safe = floor.difference(safe_candidate)
    assert connectivity.reachable_between(free_after_safe, floor.bounds, [entry, door])


def test_null_entry_point_does_not_crash_and_degrades_to_door_only_reachability():
    """With no entry point, reachability is judged purely on already-placed
    doors — must not crash, and must still correctly detect a severed
    connection between two doors."""
    floor = box(0, 0, 40, 20)
    door_a = (1, 10)
    door_b = (39, 10)
    assert connectivity.reachable_between(floor, floor.bounds, [door_a, door_b])

    severed = floor.difference(box(15, 0, 25, 20))
    assert not connectivity.reachable_between(severed, floor.bounds, [door_a, door_b])

    # Zero or one reference point (e.g. no entry point and nothing placed
    # yet) must be trivially True, never crash.
    assert connectivity.reachable_between(floor, floor.bounds, [])
    assert connectivity.reachable_between(floor, floor.bounds, [door_a])


def test_narrow_egress_passage_resolves_at_the_chosen_cell_size():
    """An exactly-8.25ft-wide corridor (EGRESS_PASSAGE_MIN_WIDTH_FT)
    connecting two open rooms must register as connected at
    CONNECTIVITY_CELL_FT — proving the resolution choice is real, not
    assumed."""
    room_a = box(0, 0, 20, 20)
    room_b = box (28.25, 0, 48.25, 20)
    corridor = box(20, 6, 28.25, 6 + 8.25)
    free_space = unary_union([room_a, room_b, corridor])
    bbox = free_space.bounds
    pt_a = (2, 10)
    pt_b = (46, 10)
    assert connectivity.reachable_between(free_space, bbox, [pt_a, pt_b])
