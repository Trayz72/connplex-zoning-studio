"""Regression coverage for placement/column_enclosure.py — the shared
area-ratio + interior-position column gate used by both the greedy
(layout_engine.py) and CP-SAT (placement/solver.py) placement paths."""
from placement import column_enclosure

RECT = (0, 0, 20, 20)  # x, y, w, h


def _col(cx, cy, half=0.5):
    """A small square column polygon centered at (cx, cy)."""
    from shapely.geometry import box
    return box(cx - half, cy - half, cx + half, cy + half)


def test_column_dead_center_rejected_even_under_ratio_cap():
    """A tiny (1x1) column at the rect's true centroid — comfortably under
    a generous 50% ratio cap, but 9ft from every wall of a 20x20 rect, far
    past a 2ft edge tolerance. Position, not area, must be what rejects it."""
    col = _col(10, 10)
    assert column_enclosure.enclosed_ratio(*RECT, [col]) < 0.01
    assert not column_enclosure.enclosure_ok(*RECT, [col], max_ratio=0.5, edge_tolerance_ft=2.0)


def test_column_dead_center_still_accepted_in_ratio_only_mode():
    """The identical geometry as above, but with edge_tolerance_ft=None
    (support-zone convention) — proves the two gates are genuinely
    independent, not the same check wearing a different name. Support
    zones keep the old ratio-only behavior unchanged."""
    col = _col(10, 10)
    assert column_enclosure.enclosure_ok(*RECT, [col], max_ratio=0.5, edge_tolerance_ft=None)


def test_column_near_wall_accepted_within_tolerance():
    """A column sitting well inside the 2ft tolerance band along the x=0
    wall must be accepted (area ratio is also tiny here)."""
    col = _col(0.5, 10)
    assert column_enclosure.enclosure_ok(*RECT, [col], max_ratio=0.02, edge_tolerance_ft=2.0)


def test_column_just_past_tolerance_is_rejected():
    """A column centered comfortably past the tolerance band (4ft from the
    nearest wall, tolerance=2ft) is rejected even though it's the same
    tiny size as the accepted near-wall case."""
    col = _col(4, 10)
    assert not column_enclosure.enclosure_ok(*RECT, [col], max_ratio=0.02, edge_tolerance_ft=2.0)


def test_ratio_cap_still_rejects_a_large_wall_adjacent_column():
    """Being near a wall doesn't bypass the area-ratio cap — a large column
    hugging the wall (comfortably within edge tolerance) but covering way
    more than the ratio cap must still be rejected. The two gates are an
    AND, not an OR."""
    from shapely.geometry import box
    big_wall_column = box(0, 5, 3, 15)  # 3x10 = 30 sqft of a 400 sqft rect = 7.5%
    assert column_enclosure.enclosed_ratio(*RECT, [big_wall_column]) > 0.02
    assert not column_enclosure.enclosure_ok(*RECT, [big_wall_column], max_ratio=0.02, edge_tolerance_ft=2.0)


def test_no_columns_always_ok():
    assert column_enclosure.enclosure_ok(*RECT, [], max_ratio=0.02, edge_tolerance_ft=2.0)
