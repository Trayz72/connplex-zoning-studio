"""Regression coverage for placement/free_rectangles.py — the maximal-
rectangle detection this session's placement-engine upgrade is built on.
Hand-verified against known answers (a textbook histogram example, and
synthetic L-shaped/notched polygons where the correct maximal rectangles
are obvious by inspection) rather than just "the call doesn't crash"."""
import numpy as np
from shapely.geometry import box

from placement.free_rectangles import (
    _rectangles_from_histogram_row,
    maximal_free_rectangles,
    rasterize,
    free_rectangles_ft,
)


def test_histogram_sweep_finds_the_known_textbook_answer():
    """[2,1,5,6,2,3] is the standard "largest rectangle in histogram"
    worked example — the real answer is area 10 (bars index 2-3, heights
    5 and 6, width 2, min height 5 -> 5*2=10)."""
    heights = np.array([2, 1, 5, 6, 2, 3])
    rects = _rectangles_from_histogram_row(heights)
    areas = [h * w for h, left, w in rects]
    assert max(areas) == 10


def test_full_rectangle_grid_finds_itself_as_the_only_maximal_rectangle():
    grid = np.ones((4, 4), dtype=bool)
    rects = maximal_free_rectangles(grid)
    assert rects == [(0, 0, 4, 4)]


def test_l_shape_finds_both_real_maximal_strips_not_a_subsumed_guess():
    """A 4x4 grid missing its top-right 2x2 quadrant (an L) has exactly two
    real maximal rectangles of equal area 8: the full-width bottom 2 rows,
    and the full-height left 2 columns — neither is contained in the
    other, and neither alone covers the whole L. A naive single first-fit
    scan would only ever find one of these; real maximal-rectangle
    detection must find both."""
    grid = np.ones((4, 4), dtype=bool)
    grid[2:4, 2:4] = False
    rects = maximal_free_rectangles(grid)
    areas = {(r[2] - r[0]) * (r[3] - r[1]) for r in rects}
    assert 8 in areas
    assert (0, 0, 2, 4) in rects  # bottom strip, full width
    assert (0, 0, 4, 2) in rects  # left strip, full height
    # No rectangle should be a strict subset of another kept one.
    for i, a in enumerate(rects):
        for j, b in enumerate(rects):
            if i == j:
                continue
            subsumed = b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]
            assert not subsumed, f"{a} is redundant, already covered by {b}"


def test_rasterize_and_free_rectangles_ft_against_a_real_notched_polygon():
    """An L-shaped real polygon (in feet, not grid cells): a 60x60 square
    with its top-right 30x30 corner removed. The two real maximal
    rectangles are the bottom 60x30 strip and the left 30x60 strip (area
    1800 each) — confirms the whole rasterize -> maximal_free_rectangles
    -> to_ft_rect pipeline recovers real, correctly-scaled geometry, not
    just correct grid-cell indices."""
    boundary = [[0, 0], [60, 0], [60, 30], [30, 30], [30, 60], [0, 60], [0, 0]]
    poly = box(0, 0, 60, 60).difference(box(30, 30, 60, 60))
    bbox = (0.0, 0.0, 60.0, 60.0)

    rects = free_rectangles_ft(poly, bbox, cell_ft=1.0)
    areas = sorted((round(w * h) for x, y, w, h in rects), reverse=True)
    assert areas[0] == 1800
    assert areas[1] == 1800
    # A real, meaningfully large rectangle should exist near each real strip.
    assert any(abs(w - 60) < 1.5 and abs(h - 30) < 1.5 for x, y, w, h in rects)
    assert any(abs(w - 30) < 1.5 and abs(h - 60) < 1.5 for x, y, w, h in rects)


def test_every_returned_rectangle_is_actually_verified_contained():
    """Real regression found via live testing: a raw raster-cell-to-feet
    conversion can be very slightly outside the true polygon near an edge
    (a cell is marked "free" from its CENTER point alone — see
    rasterize's own docstring), which downstream silently produced a
    placed room layout_engine.validate_rooms flagged as
    OUTSIDE_BOUNDARY. Every rectangle free_rectangles_ft returns must
    genuinely, exactly contain-check against the real polygon — not just
    be "close enough" per the raster's own resolution. A rotated (non-
    axis-aligned-with-the-grid) triangle-ish polygon is a real, hard case
    likely to produce raster edge quantization."""
    from shapely.geometry import Polygon
    from placement.free_rectangles import free_rectangles_ft

    poly = Polygon([(0, 0), (37.3, 2.1), (41.7, 58.9), (3.4, 61.2), (0, 0)])
    bbox = poly.bounds
    rects = free_rectangles_ft(poly, bbox, cell_ft=1.0)
    assert len(rects) > 0
    for x, y, w, h in rects:
        assert poly.contains(box(x, y, x + w, y + h)), f"rectangle ({x},{y},{w},{h}) is not genuinely contained"


def test_rasterize_bounds_cell_count_for_a_pathological_bbox():
    """A real crash class this project has hit before (see
    layout_engine._grid_step_for_bbox's own docstring: a mis-scaled DXF
    produced a boundary millions of sqft in size) — rasterize must degrade
    to a coarser cell size instead of allocating a huge grid."""
    poly = box(0, 0, 1_000_000, 1_000_000)
    bbox = (0.0, 0.0, 1_000_000.0, 1_000_000.0)
    grid, cell_ft, minx, miny = rasterize(poly, bbox, cell_ft=1.0)
    assert grid.size <= 200_000 * 1.01  # MAX_RASTER_CELLS, with tiny rounding slack
    assert cell_ft > 1.0  # had to scale up from the requested 1ft
