"""Reachability check: does a candidate room placement sever the path
between the entry point and any already-placed room's door?

Hand-rolled 4-connectivity flood fill over placement.free_rectangles'
existing boolean raster — no scipy/networkx dependency (neither is declared
in requirements.txt, and no BFS/pathfinding utility exists anywhere else in
this codebase). Used by layout_engine's new post-auditorium support-zone
placement pass to implement "no component may block the common path
between components" as a real, testable geometric gate rather than an
after-the-fact visual check.
"""
from collections import deque

import numpy as np

from placement import free_rectangles

# Resolves EGRESS_PASSAGE_MIN_WIDTH_FT (8.25ft) as ~4 cells wide under
# 4-connectivity — comfortably clear of the diagonal-pinch failure mode —
# while keeping BFS cost bounded (this runs per-candidate, per support-zone
# type, across all 3 auto-layout candidates).
CONNECTIVITY_CELL_FT = 2.0


def _point_to_cell(pt, cell_ft, minx, miny, grid, search_radius=3):
    """Nearest True cell to a real-space point, spiralling outward up to
    search_radius cells if the point's own cell rasterizes False (a door's
    probe point can sit right at a wall/boundary edge, a hair outside what
    the raster considers 'inside'). Returns None — not a crash, not a
    guess — if nothing True is found nearby; the caller treats an
    unresolvable reference point as one to skip, not a failure."""
    n_rows, n_cols = grid.shape
    col0 = int((pt[0] - minx) / cell_ft)
    row0 = int((pt[1] - miny) / cell_ft)
    for radius in range(search_radius + 1):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if max(abs(dr), abs(dc)) != radius:
                    continue
                r, c = row0 + dr, col0 + dc
                if 0 <= r < n_rows and 0 <= c < n_cols and grid[r, c]:
                    return r, c
    return None


def _bfs_reachable(grid, start_rc):
    """Plain deque-based 4-connectivity flood fill from start_rc. grid is a
    2D boolean numpy array (True = walkable). Returns a same-shape boolean
    array marking every cell reachable from start_rc."""
    n_rows, n_cols = grid.shape
    reached = np.zeros_like(grid, dtype=bool)
    if not grid[start_rc]:
        return reached
    reached[start_rc] = True
    q = deque([start_rc])
    while q:
        r, c = q.popleft()
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < n_rows and 0 <= nc < n_cols and grid[nr, nc] and not reached[nr, nc]:
                reached[nr, nc] = True
                q.append((nr, nc))
    return reached


def reachable_between(free_space_poly, bbox, ref_points_ft, cell_ft=CONNECTIVITY_CELL_FT):
    """True iff every ref point in ref_points_ft that resolves to a real
    walkable cell lies in the same connected component of free_space_poly.
    Points that fail to resolve are skipped, not treated as a failure — see
    _point_to_cell. 0 or 1 resolvable points is trivially True (nothing to
    sever yet); this is what lets a null entry_point_ft (a real, confirmed
    case on at least one live project) degrade gracefully instead of
    crashing or forcing a special-cased branch in every caller."""
    if free_space_poly is None or free_space_poly.is_empty or len(ref_points_ft) < 2:
        return True
    grid, actual_cell_ft, minx, miny = free_rectangles.rasterize(free_space_poly, bbox, cell_ft)
    if not grid.any():
        return True
    resolved = [
        _point_to_cell(pt, actual_cell_ft, minx, miny, grid)
        for pt in ref_points_ft
    ]
    resolved = [rc for rc in resolved if rc is not None]
    if len(resolved) < 2:
        return True
    reached = _bfs_reachable(grid, resolved[0])
    return all(reached[rc] for rc in resolved[1:])


def would_sever(free_space_before, free_space_after, bbox, ref_points_ft, cell_ft=CONNECTIVITY_CELL_FT):
    """True iff placing a candidate (the only difference between "before"
    and "after" free space) disconnects some pair of ref_points_ft that
    WAS mutually reachable before. Deliberately relative, not absolute
    ("are all points reachable?") — on a real, irregular floor plate with a
    genuine confirmed WALL, two already-placed rooms can legitimately be on
    opposite sides of it with NO path between them before any candidate is
    even considered (a real, confirmed case on a live project). An
    absolute all-reachable check would then reject every single candidate
    forever, since nothing could ever satisfy a baseline that was already
    disconnected — that's not a candidate blocking anything, it's a
    pre-existing condition no candidate could fix. This only flags a
    candidate that makes things WORSE than they already were."""
    if len(ref_points_ft) < 2:
        return False
    grid_b, cell_b, minx_b, miny_b = free_rectangles.rasterize(free_space_before, bbox, cell_ft)
    grid_a, cell_a, minx_a, miny_a = free_rectangles.rasterize(free_space_after, bbox, cell_ft)
    resolved_b = [_point_to_cell(pt, cell_b, minx_b, miny_b, grid_b) for pt in ref_points_ft]
    resolved_a = [_point_to_cell(pt, cell_a, minx_a, miny_a, grid_a) for pt in ref_points_ft]

    reach_cache_b, reach_cache_a = {}, {}
    for i in range(len(ref_points_ft)):
        rb_i, ra_i = resolved_b[i], resolved_a[i]
        if rb_i is None or ra_i is None:
            continue
        if rb_i not in reach_cache_b:
            reach_cache_b[rb_i] = _bfs_reachable(grid_b, rb_i)
        reached_b = reach_cache_b[rb_i]
        for j in range(len(ref_points_ft)):
            if j == i:
                continue
            rb_j, ra_j = resolved_b[j], resolved_a[j]
            if rb_j is None or ra_j is None or not reached_b[rb_j]:
                continue
            if ra_i not in reach_cache_a:
                reach_cache_a[ra_i] = _bfs_reachable(grid_a, ra_i)
            if not reach_cache_a[ra_i][ra_j]:
                return True
    return False


def door_outside_point(room, door, epsilon_ft=1.0):
    """Converts a room's door dict into a real-space point just outside the
    wall it's on — a reachability probe point, not a drawing glyph — pushed
    epsilon_ft along the door's outward normal. Mirrors the same
    origin_ft/width_ft/depth_ft + wall/offset_ft/width_ft convention
    layout_engine._doors_for_screen_wall already produces and
    export_dxf.py/export_pdf.py already consume for door glyphs."""
    x, y = room["origin_ft"]
    w, h = room["width_ft"], room["depth_ft"]
    wall, off, dw = door["wall"], door["offset_ft"], door["width_ft"]
    mid = off + dw / 2
    base, along, outward = {
        "min_y": ((x, y), (1, 0), (0, -1)),
        "max_y": ((x, y + h), (1, 0), (0, 1)),
        "min_x": ((x, y), (0, 1), (-1, 0)),
        "max_x": ((x + w, y), (0, 1), (1, 0)),
    }[wall]
    return (
        base[0] + along[0] * mid + outward[0] * epsilon_ft,
        base[1] + along[1] * mid + outward[1] * epsilon_ft,
    )
