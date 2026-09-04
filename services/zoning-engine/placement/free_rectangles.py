"""Real maximal-rectangle detection against an arbitrary (possibly
irregular/notched, obstacle-subtracted) usable-area polygon.

Why this exists: layout_engine.py's original scan (_scan_place) walks a
fixed grid step and takes the first position where a FIXED-SIZE candidate
fits — a real, honest first-fit heuristic, but one with no idea which
positions leave more usable room for what comes after. On a real irregular
floor plate this can "checkmate" itself: two individually-valid placements
can together strand most of the remaining usable area (measured directly
on a real uploaded file: 74% of usable area — 5,194 of 6,979 sqft — left
completely untouched this way, see LOG.md).

This module computes the REAL maximal empty rectangles inside a usable
polygon — the standard "maximal rectangle in a binary matrix" technique
(per-row height histogram + monotonic stack), generalized to collect every
rectangle the stack sweep produces at every row (not just the single
largest) — a real, richer candidate-position source for this package's
other modules (the custom-fit fallback, backtracking, and the CP-SAT
solver) to choose from, computed fresh against whatever's actually placed
so far, rather than guessed at.

Resolution is bounded (MAX_RASTER_CELLS) the same way
layout_engine._grid_step_for_bbox already bounds its own scan step for a
pathological boundary — a real crash class this project has hit before
(see that function's own docstring) — so a huge or mis-scaled boundary
degrades to a coarser (but still correct) raster instead of hanging.
"""
import math

import numpy as np
import shapely

MAX_RASTER_CELLS = 200_000


def _cell_size_for_bbox(bbox, target_cell_ft):
    minx, miny, maxx, maxy = bbox
    w, h = maxx - minx, maxy - miny
    if w <= 0 or h <= 0:
        return target_cell_ft
    natural_cells = (w / target_cell_ft) * (h / target_cell_ft)
    if natural_cells <= MAX_RASTER_CELLS:
        return target_cell_ft
    return target_cell_ft * math.sqrt(natural_cells / MAX_RASTER_CELLS)


def rasterize(usable_poly, bbox, cell_ft=1.0):
    """Returns (grid, actual_cell_ft, minx, miny). grid is a 2D boolean
    numpy array; grid[row, col] is True when that cell's CENTER point
    falls inside usable_poly (shapely.contains_xy — real point-in-polygon
    testing, not a bounding-box approximation). Row 0 is the bottom (miny)
    row: cell (r, c)'s center is at (minx + (c+0.5)*cell_ft, miny +
    (r+0.5)*cell_ft). actual_cell_ft may be larger than the requested
    cell_ft if the naive cell count would be pathological (see
    MAX_RASTER_CELLS)."""
    minx, miny, maxx, maxy = bbox
    cell_ft = _cell_size_for_bbox(bbox, cell_ft)
    n_cols = max(int(math.ceil((maxx - minx) / cell_ft)), 1)
    n_rows = max(int(math.ceil((maxy - miny) / cell_ft)), 1)
    xs = minx + (np.arange(n_cols) + 0.5) * cell_ft
    ys = miny + (np.arange(n_rows) + 0.5) * cell_ft
    xx, yy = np.meshgrid(xs, ys)  # shape (n_rows, n_cols)
    grid = shapely.contains_xy(usable_poly, xx, yy)
    return grid, cell_ft, minx, miny


def _rectangles_from_histogram_row(heights):
    """The classic "largest rectangle in a histogram" monotonic-stack
    sweep, generalized to collect EVERY rectangle the stack produces as it
    pops (not just the single tallest×widest one) — each popped bar's
    rectangle is a real maximal rectangle whose bottom edge is this row and
    whose height is exactly that bar's histogram value. Standard,
    well-known algorithm (index-based stack, heights[stack] strictly
    increasing); this is the textbook version, not a novel invented one.
    Returns a list of (height, left_col, width) in histogram-column units."""
    rects = []
    stack = []  # indices into heights, with heights[stack] increasing
    n = len(heights)
    for i in range(n + 1):
        h = heights[i] if i < n else 0
        while stack and heights[stack[-1]] >= h:
            height = heights[stack.pop()]
            left = (stack[-1] + 1) if stack else 0
            width = i - left
            if height > 0 and width > 0:
                rects.append((height, left, width))
        stack.append(i)
    return rects


def _is_subsumed(a, b):
    """True if rectangle a fits entirely inside rectangle b — a placement
    candidate a offers nothing b doesn't already cover, so it's real
    clutter, not a genuinely different option."""
    return b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]


def maximal_free_rectangles(grid, max_candidates=300):
    """Sweeps every row as a potential bottom edge, collecting every
    rectangle the histogram+stack sweep produces there — real maximal
    rectangles (each is the tallest possible at its exact width for that
    bottom edge), not one single "the largest" answer. A single sweep
    naturally produces many rectangles nested inside a larger one already
    found (e.g. a fully-open grid's own sub-rectangles) — those are
    dropped (see _is_subsumed) before the max_candidates cap, so the cap
    is spent on genuinely distinct options, not near-duplicates. Returns a
    list of (row0, col0, row1, col1) cell ranges (row1/col1 exclusive),
    sorted by area descending."""
    if grid.size == 0:
        return []
    n_rows, n_cols = grid.shape
    heights = np.zeros(n_cols, dtype=int)
    all_rects = []
    for r in range(n_rows):
        heights = np.where(grid[r], heights + 1, 0)
        for h, col0, w in _rectangles_from_histogram_row(heights):
            row1 = r + 1
            row0 = row1 - h
            all_rects.append((row0, col0, row1, col0 + w))
    all_rects.sort(key=lambda rr: (rr[2] - rr[0]) * (rr[3] - rr[1]), reverse=True)

    kept = []
    for rect in all_rects:
        if len(kept) >= max_candidates:
            break
        if any(_is_subsumed(rect, k) for k in kept):
            continue
        kept.append(rect)
    return kept


def to_ft_rect(cell_rect, cell_ft, minx, miny):
    row0, col0, row1, col1 = cell_rect
    x = minx + col0 * cell_ft
    y = miny + row0 * cell_ft
    w = (col1 - col0) * cell_ft
    h = (row1 - row0) * cell_ft
    return x, y, w, h


def _shrink_to_verified_fit(usable_poly, x, y, w, h, cell_ft, max_iterations=8):
    """A rasterized cell is marked "free" from its CENTER point alone
    (rasterize's own contract) — near a polygon edge, a cell's own full
    footprint can extend a fraction of a foot past the true boundary even
    though its center is genuinely inside, which a raw cell-to-ft
    conversion would silently carry through as a rectangle that's very
    slightly outside usable_poly (found via real testing: a real placed
    room came back 0.5 sqft outside its boundary, tripping
    layout_engine.validate_rooms' own OUTSIDE_BOUNDARY check). Verifies the
    actual rectangle against the real polygon and, only if it doesn't
    genuinely fit, uniformly insets by a small step and re-checks — a
    genuinely-fitting rectangle (the common case) is returned completely
    unchanged; one that needs correction loses only as many small steps as
    it actually takes to verify, not a single blanket conservative margin
    applied to every rectangle regardless of whether it needed it. Returns
    (x, y, w, h) or None if it can't be made to fit within max_iterations
    small steps."""
    from shapely.geometry import box
    step = cell_ft * 0.1
    for _ in range(max_iterations):
        if w <= 0 or h <= 0:
            return None
        rect = box(x, y, x + w, y + h)
        if usable_poly.contains(rect):
            return x, y, w, h
        x += step / 2
        y += step / 2
        w -= step
        h -= step
    rect = box(x, y, x + w, y + h) if w > 0 and h > 0 else None
    return (x, y, w, h) if rect is not None and usable_poly.contains(rect) else None


def free_rectangles_ft(usable_poly, bbox, cell_ft=1.0, max_candidates=300):
    """End-to-end convenience: rasterize + find maximal rectangles +
    convert back to real (x, y, w, h) feet tuples, largest area first,
    each one VERIFIED (not just assumed from the raster) to genuinely fit
    inside usable_poly — see _shrink_to_verified_fit. A rectangle that
    can't be verified even after trimming is dropped rather than returned
    as a false promise."""
    grid, actual_cell_ft, minx, miny = rasterize(usable_poly, bbox, cell_ft)
    cell_rects = maximal_free_rectangles(grid, max_candidates=max_candidates)
    out = []
    for cr in cell_rects:
        x, y, w, h = to_ft_rect(cr, actual_cell_ft, minx, miny)
        verified = _shrink_to_verified_fit(usable_poly, x, y, w, h, actual_cell_ft)
        if verified is not None:
            out.append(verified)
    return out
