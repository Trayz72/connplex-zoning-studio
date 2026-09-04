"""
Generic auto-layout generator (spec Sec 7.2 / Sec 8.5): places auditoriums
(only) inside an arbitrary usable-area polygon, avoiding confirmed obstacles,
without any per-project hardcoding. Every other room type (foyer/F&B/
washroom/box office/back-of-house) is deliberately NOT auto-placed — those
are added one at a time via place_single_zone, called from the Edit step's
"Add zone" toolbar once the architect has actually seen where the screens
landed, rather than guessed at up front.

Algorithm (the staged greedy packer spec Sec 7.2 explicitly recommends for v1,
rather than a full constraint solver):
  1. Subtract confirmed obstacles (+ a clearance buffer) from the boundary to get
     the usable area.
  2. Scan-and-fit: try candidate rectangle placements on a grid across the usable
     area's bounding box, in a fixed deterministic order, and take the first
     position where the rectangle is fully contained in the remaining usable area
     and does not overlap anything already placed (+ a clearance — see
     _neighbor_gap_ft: zero between two auditoriums, since real cinemas share a
     demising wall between adjacent screens; the real aisle clearance against
     everything else). This is a standard first-fit rectangle-packing heuristic —
     not optimal, but real, deterministic (same input -> same output, per the
     project's reproducibility requirement), and honest about not fitting
     something that doesn't fit.
  3. Auditoriums are tried largest-preset-first at each step (this is what
     operationalizes "maximize total seat count"), and the scan is biased to
     start near the marked entrance and proceed toward the exit side (see
     _entry_exit_scan_flip) when one is marked in Requirements.

Two real strategies are generated (not cosmetic variants of one layout):
  MAX_SEATS_PER_SCREEN — always tries the largest preset first (fewer, bigger screens)
  MAX_SCREEN_COUNT      — always tries the smallest preset first (more, smaller screens)
Both are genuinely different placements, scored the same way as the M8 rescoring
(seats-per-screen against the Feasibility Manual's 60-seat/screen threshold).
"""
import math
import uuid

from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.affinity import rotate as shapely_rotate
from shapely.affinity import scale as shapely_scale

import rules_registry
import seat_engine
from placement import free_rectangles, backtracking, solver, column_enclosure, connectivity

GRID_STEP_FT = 2.0
AISLE_CLEARANCE_FT = 3.5   # matches CENTRAL_AISLE_MIN_FT — used generically as the minimum gap between placed zones
OBSTACLE_BUFFER_FT = 0.5
MAX_SCAN_CELLS = 40000     # see _grid_step_for_bbox — real crash found via real testing, not a hypothetical

PERIMETER_TOUCH_TOLERANCE_FT = 2.0  # how close a placement must sit to the boundary's own edge to count as "at the perimeter" below


def _grid_step_for_bbox(bbox):
    """A boundary this scan runs against is normally a real, human-scale
    floor plate (tens to low thousands of sqft), where GRID_STEP_FT=2.0 is
    fine-grained enough to matter and cheap enough to run. Real testing with
    a real uploaded file (a DXF whose $INSUNITS was unspecified, so the
    boundary heuristic latched onto a sheet-border/title-block frame instead
    of the actual building outline — see cad_extraction.py's
    MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT for the actual fix) produced a bounding
    box millions of square feet in size. At GRID_STEP_FT=2.0 that's millions
    of grid cells, each doing a real shapely polygon containment check —
    the "Run Auto-Layout" button never returning was this, not a hang bug in
    the request/response plumbing. Scaling the step up so the total cell
    count stays bounded means a pathological boundary degrades to a coarse,
    fast, honest "doesn't fit" instead of running for hours."""
    minx, miny, maxx, maxy = bbox
    w, h = maxx - minx, maxy - miny
    if w <= 0 or h <= 0:
        return GRID_STEP_FT
    natural_cells = (w / GRID_STEP_FT) * (h / GRID_STEP_FT)
    if natural_cells <= MAX_SCAN_CELLS:
        return GRID_STEP_FT
    return GRID_STEP_FT * math.sqrt(natural_cells / MAX_SCAN_CELLS)

SUPPORT_ZONE_DEFAULTS = [
    # (room_type, display_name, target_area_sqft, min_area_sqft, source)
    ("FOYER", "Foyer", None, 150.0, "derived from franchise tier foyer:screen ratio, or 30% of auditorium area if no tier given (ENGINEERING_ASSUMPTION)"),
    ("FNB", "Food & Beverage / Concession", None, 80.0, "ENGINEERING_ASSUMPTION default 8% of usable area — SOP does not give an exact company-approved percentage (Master Context Sec 35 uses 8% only as an illustrative example, not a decided rule)"),
    ("WASHROOM", "Washrooms", 100.0, 60.0, "ENGINEERING_ASSUMPTION — SOP requires washrooms but does not give a minimum area figure"),
    ("BOX_OFFICE", "Box Office / Ticketing", 60.0, 40.0, "ENGINEERING_ASSUMPTION"),
    ("BOH", "Back-of-House (Electrical / Server / Store)", 90.0, 60.0, "ENGINEERING_ASSUMPTION — SOP lists these as required foyer sub-functions but gives no area figures"),
    ("PASSAGE", "Passage / Corridor", None, 80.0, "ENGINEERING_ASSUMPTION default 8% of auditorium area, same as FNB — sized to connect the Foyer to the nearest Screen at EGRESS_PASSAGE_MIN_WIDTH_FT clear width; the SOP evidences a real corridor width from a reference drawing, not a target area")
]


def poly_from_points(points_ft):
    p = Polygon(points_ft)
    return p if p.is_valid else p.buffer(0)


def _label_point_ft(geometry_points_ft):
    """A point GUARANTEED to fall inside the room's own polygon — unlike a
    bounding-box center, which lands outside a concave shape (a real,
    confirmed defect: Foyer's own leftover-remainder polygon can be
    concave/keyhole-cut, and a bbox-center label rendered visibly outside
    it, floating over unrelated rooms). Every room carries this so the
    frontend/PDF/DXF label renderers never have to guess at polygon
    geometry themselves — for a plain rectangle (every room type except
    Foyer) this is equivalent to the bbox center, so nothing changes for
    them; it only matters for a genuinely non-convex shape."""
    poly = poly_from_points(geometry_points_ft)
    if poly.is_empty:
        b = Polygon(geometry_points_ft).bounds
        return [round((b[0] + b[2]) / 2, 2), round((b[1] + b[3]) / 2, 2)]
    pt = poly.representative_point()
    return [round(pt.x, 2), round(pt.y, 2)]


def _rect(x, y, w, h):
    return box(x, y, x + w, y + h)


def _exterior_lines(poly):
    """The real outer-boundary ring(s) of a usable-area polygon, deliberately
    excluding any interior ring (an obstacle's own hole boundary isn't the
    building's perimeter). Obstacle subtraction in compute_usable_area can
    split one boundary into several disjoint pieces (a MultiPolygon), which
    has no single .exterior — found via real testing against the Dhule
    reference drawing, whose usable area is genuinely a MultiPolygon."""
    if poly.geom_type == "Polygon":
        return poly.exterior
    from shapely.geometry import MultiLineString
    return MultiLineString([p.exterior for p in poly.geoms])


def compute_usable_area(boundary_points_ft, confirmed_obstacles, exclude_classifications=()):
    """confirmed_obstacles: list of {"points_ft":..., "classification":...} dicts
    (cad_extraction.py already attaches classification to every obstacle), or
    bare point-lists for backward compatibility (treated as classification-less,
    i.e. always subtracted). exclude_classifications lets a caller build a
    "tolerant" usable area that doesn't treat certain obstacle types as holes —
    used for the column-tolerant fallback polygon in _place_auditoriums/
    place_single_zone below, since a room is allowed to be placed over a
    confirmed COLUMN (but never a wall/stair/washroom/etc) when no column-free
    placement exists."""
    boundary = poly_from_points(boundary_points_ft)
    if not confirmed_obstacles:
        return boundary
    polys = []
    for o in confirmed_obstacles:
        if isinstance(o, dict):
            pts, classification = o.get("points_ft"), o.get("classification")
        else:
            pts, classification = o, None
        if classification in exclude_classifications:
            continue
        polys.append(poly_from_points(pts).buffer(OBSTACLE_BUFFER_FT))
    if not polys:
        return boundary
    obstacle_union = unary_union(polys)
    usable = boundary.difference(obstacle_union)
    return usable if not usable.is_empty else boundary


def _entry_exit_scan_flip(bbox, entry_point, exit_points_ft):
    """Which axes to mirror the usable area across before running the
    auditorium placement scan (see _place_auditoriums), so screens are
    filled starting from the entrance side of the floor plate and
    proceeding toward the exit side, instead of the scan's fixed
    bottom-left starting corner (which has no relationship to the real
    entrance). This is a real, geometric reading of the SOP's "entry ->
    foyer -> auditorium" sequencing (spec Sec 2.8) applied to placement
    *order* — not full circulation-path routing, which this rectangle
    packer was never going to do honestly.

    With both an entry and at least one exit marked, the flip direction is
    the real vector from the entrance to the exits' centroid. With only an
    entry marked, the target is the point reflected through the floor
    plate's own center — i.e. "start near the door, work toward the far
    side" — so entry alone still has a real effect instead of none, which
    was the case before this function existed (only the support-zone pass
    used entry_point at all; auditorium placement ignored it completely).

    Returns (flip_x, flip_y): booleans, independent per axis."""
    if entry_point is None:
        return False, False
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    if exit_points_ft:
        target_x = sum(p[0] for p in exit_points_ft) / len(exit_points_ft)
        target_y = sum(p[1] for p in exit_points_ft) / len(exit_points_ft)
    else:
        target_x, target_y = 2 * cx - entry_point[0], 2 * cy - entry_point[1]
    flip_x = entry_point[0] > target_x
    flip_y = entry_point[1] > target_y
    return flip_x, flip_y


def _mirror_for_scan(poly, bbox, flip_x, flip_y):
    """Mirrors `poly` about the bbox's own center along whichever axes
    flip_x/flip_y select. Mirroring about the bbox's own center (rather
    than an arbitrary origin) keeps the mirrored polygon's bounding box
    numerically identical to the original bbox, so callers can keep using
    the same bbox for the scan without recomputing it."""
    if not flip_x and not flip_y:
        return poly
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    return shapely_scale(poly, xfact=-1 if flip_x else 1, yfact=-1 if flip_y else 1, origin=(cx, cy))


def _unmirror_rect(x, y, w, h, bbox, flip_x, flip_y):
    """Inverse of _mirror_for_scan for a single axis-aligned (x, y, w, h)
    placement result — a closed-form corner remap (mirroring flips which
    corner is the rect's "bottom-left"), cheaper and exactly as correct as
    running the affine transform on the box and re-reading its bounds."""
    if not flip_x and not flip_y:
        return x, y
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    rx = (2 * cx - x - w) if flip_x else x
    ry = (2 * cy - y - h) if flip_y else y
    return rx, ry


def _neighbor_gap_ft(candidate_type, other_type):
    """The real clearance to keep between a candidate placement and one
    already-placed room, by type pairing. Two auditoriums are allowed to sit
    with zero gap between them — real cinemas share a demising wall between
    adjacent screens (see the 35_SEAT preset's own source note: measured
    directly from a real client file built this way), not the same open-air
    aisle clearance a corridor or a support zone needs. Every other pairing
    (auditorium-vs-support-zone, support-vs-support) keeps the real
    circulation clearance."""
    if candidate_type == "AUDITORIUM" and other_type == "AUDITORIUM":
        return 0.0
    return AISLE_CLEARANCE_FT


def _fits_with_clearance(cand, placed_polys, placed_types, candidate_type):
    for p, t in zip(placed_polys, placed_types):
        gap = _neighbor_gap_ft(candidate_type, t)
        if gap > 0:
            if cand.buffer(gap / 2).intersects(p):
                return False
        elif cand.intersection(p).area > 1e-6:
            # gap == 0 (two auditoriums): touching along a shared wall is fine,
            # real overlap is not.
            return False
    return True


def _scan_axis_positions(minv, maxv, min_extent, step, grid_lines):
    """Candidate scan start-positions along one axis: the plain fixed-step
    sequence used everywhere before column-grid-awareness existed, unless
    real structural grid lines are known for this axis (see
    _column_grid_lines) — in which case candidates are those grid-line
    coordinates instead, since a real architect's room edges land on the
    building's own bay lines, not an arbitrary 2ft scan step. minv itself is
    always included alongside the grid lines: the boundary's own edge
    frequently doesn't sit exactly on the innermost column line, and a real
    design is free to start there too."""
    if not grid_lines:
        vals = []
        v = minv
        while v + min_extent <= maxv:
            vals.append(v)
            v += step
        return vals
    return sorted(v for v in set([minv] + list(grid_lines)) if minv <= v and v + min_extent <= maxv)


def _scan_place(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True,
                 grid_lines_x=None, grid_lines_y=None):
    """First-fit deterministic scan: returns (x, y, w_used, h_used) of the first
    valid placement, or None. Tries both orientations if allow_rotate.
    grid_lines_x/grid_lines_y, when given, are real structural column-line
    coordinates (see _column_grid_lines) — candidate positions snap to them
    instead of the fixed GRID_STEP_FT scan step."""
    minx, miny, maxx, maxy = bbox
    step = _grid_step_for_bbox(bbox)
    orientations = [(w, h)]
    if allow_rotate and abs(w - h) > 1e-6:
        orientations.append((h, w))
    min_extent = min(h, w)

    for y in _scan_axis_positions(miny, maxy, min_extent, step, grid_lines_y):
        for x in _scan_axis_positions(minx, maxx, min_extent, step, grid_lines_x):
            for ow, oh in orientations:
                if x + ow > maxx or y + oh > maxy:
                    continue
                cand = _rect(x, y, ow, oh)
                if not usable_poly.contains(cand.buffer(-0.01)):
                    continue
                if not _fits_with_clearance(cand, placed_polys, placed_types, candidate_type):
                    continue
                return x, y, ow, oh
    return None


def _has_sightline(usable_poly, placed_polys, from_point, rect):
    """A straight, unobstructed line from from_point to rect's centroid:
    stays inside the usable area (not blocked by a wall/column — obstacles
    are already holes in usable_poly, so a line crossing one leaves the
    polygon) and doesn't cross anything already placed."""
    from shapely.geometry import LineString
    c = rect.centroid
    line = LineString([from_point, (c.x, c.y)])
    if not usable_poly.contains(line):
        return False
    return not any(line.intersects(p) for p in placed_polys)


def _scan_place_ranked(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True, score_fn=None, prefer_fn=None, max_candidates=80,
                        grid_lines_x=None, grid_lines_y=None):
    """Same first-fit grid scan as _scan_place, but collects up to
    max_candidates valid positions and returns the FULL best-first ranked
    list — [(x, y, ow, oh), satisfied_preference), ...] — instead of
    collapsing to one winner. Preferred+scored candidates (per prefer_fn/
    score_fn) come first, followed by the rest of the pool, so a caller
    that needs to veto the top choice (e.g. it would sever reachability —
    see placement/connectivity.py) can fall through to the next-best
    position instead of failing outright. _scan_place_best below is just
    ranked[0] of this — same selection logic, unchanged behavior.
    grid_lines_x/grid_lines_y: see _scan_place."""
    minx, miny, maxx, maxy = bbox
    step = _grid_step_for_bbox(bbox)
    orientations = [(w, h)]
    if allow_rotate and abs(w - h) > 1e-6:
        orientations.append((h, w))
    min_extent = min(h, w)

    candidates = []
    for y in _scan_axis_positions(miny, maxy, min_extent, step, grid_lines_y):
        if len(candidates) >= max_candidates:
            break
        for x in _scan_axis_positions(minx, maxx, min_extent, step, grid_lines_x):
            if len(candidates) >= max_candidates:
                break
            for ow, oh in orientations:
                if x + ow > maxx or y + oh > maxy:
                    continue
                cand = _rect(x, y, ow, oh)
                if not usable_poly.contains(cand.buffer(-0.01)):
                    continue
                if not _fits_with_clearance(cand, placed_polys, placed_types, candidate_type):
                    continue
                candidates.append((x, y, ow, oh))
                if len(candidates) >= max_candidates:
                    break

    if not candidates:
        return []
    if score_fn is None and prefer_fn is None:
        return [(c, False) for c in candidates]

    pool = candidates
    satisfied_preference = False
    if prefer_fn:
        preferred = [c for c in candidates if prefer_fn(c)]
        if preferred:
            pool = preferred
            satisfied_preference = True

    ranked_pool = sorted(pool, key=score_fn) if score_fn else pool
    ranked = [(c, satisfied_preference) for c in ranked_pool]
    if satisfied_preference:
        rest = [c for c in candidates if c not in pool]
        if score_fn:
            rest = sorted(rest, key=score_fn)
        ranked += [(c, False) for c in rest]
    return ranked


def _scan_place_best(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True, score_fn=None, prefer_fn=None, max_candidates=80,
                      grid_lines_x=None, grid_lines_y=None):
    """Same first-fit grid scan as _scan_place, but collects up to
    max_candidates valid positions instead of stopping at the first one, so a
    placement can be chosen for *where* it sits, not just *that* it fits.
    prefer_fn is a soft constraint (e.g. "has a sightline from the entry") —
    placement still succeeds using the unfiltered candidates if none satisfy
    it, per Product Principle #7 (never silently invent a placement that
    contradicts real geometry, but never silently drop a room either).
    grid_lines_x/grid_lines_y: see _scan_place."""
    ranked = _scan_place_ranked(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate, score_fn, prefer_fn, max_candidates, grid_lines_x, grid_lines_y)
    if not ranked:
        return None, False
    return ranked[0]


def _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True,
                               grid_lines_x=None, grid_lines_y=None):
    """Try the strict (all-obstacles-subtracted) polygon first — a column-free
    placement is always preferred when one exists, this changes nothing about
    today's behavior in that case. Only if that fails does it retry against
    fallback_poly (obstacles minus COLUMN — see compute_usable_area), which
    allows the rectangle to cover a confirmed structural column but nothing
    else. Returns (placement_or_None, used_fallback: bool)."""
    result = _scan_place(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate, grid_lines_x, grid_lines_y)
    if result:
        return result, False
    if fallback_poly is not None and fallback_poly is not usable_poly:
        result = _scan_place(fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate, grid_lines_x, grid_lines_y)
        if result:
            return result, True
    return None, False


def _scan_place_ranked_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True,
                                      score_fn=None, prefer_fn=None, top_k=1, max_candidates=80, grid_lines_x=None, grid_lines_y=None):
    """Ranked strict-then-column-tolerant retry: strict-tier ranked
    candidates always precede fallback-tier ones (a column-free placement
    beats a column-tolerant one regardless of score), each tagged with
    used_fallback, combined list capped to top_k. The fallback-tier scan is
    only run when the strict tier alone doesn't already offer top_k
    candidates — same laziness _scan_place_best_with_fallback (now just
    ranked[0] of this, top_k=1) always had: a column-tolerant scan is never
    even attempted when the strict tier already has enough to work with.
    Returns [((x, y, ow, oh), satisfied_preference, used_fallback), ...]."""
    ranked = [(c, satisfied, False) for c, satisfied in
              _scan_place_ranked(usable_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate, score_fn, prefer_fn, max_candidates, grid_lines_x, grid_lines_y)]
    if len(ranked) < top_k and fallback_poly is not None and fallback_poly is not usable_poly:
        ranked += [(c, satisfied, True) for c, satisfied in
                   _scan_place_ranked(fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate, score_fn, prefer_fn, max_candidates, grid_lines_x, grid_lines_y)]
    return ranked[:top_k]


def _scan_place_best_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate=True,
                                    score_fn=None, prefer_fn=None, max_candidates=80, grid_lines_x=None, grid_lines_y=None):
    """Same strict-then-column-tolerant retry as _scan_place_with_fallback,
    for the score_fn/prefer_fn-driven placements (foyer-near-entry etc)."""
    ranked = _scan_place_ranked_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, candidate_type, w, h, bbox, allow_rotate,
                                               score_fn, prefer_fn, top_k=1, max_candidates=max_candidates, grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y)
    if not ranked:
        return None, False, False
    return ranked[0]


def _enclosed_obstacle_area(rect, column_polys):
    """How much of rect's own area is covered by confirmed COLUMN obstacles —
    used to honestly discount a seat estimate and to flag which rooms need
    the enclosed-obstacle note, only meaningful when a placement actually
    used the column-tolerant fallback tier above."""
    if not column_polys:
        return 0.0
    return sum(rect.intersection(cp).area for cp in column_polys)


def _cluster_axis_lines(values, cluster_tolerance_ft=1.0):
    """Groups nearby coordinates on one axis into distinct grid-line values —
    real column grids are regular but rarely pixel-exact. Shared by
    estimate_column_grid_spacing (gap-measuring, for viability checks) and
    _column_grid_lines (line-coordinates, for placement snapping) below."""
    if not values:
        return []
    values = sorted(values)
    lines = [values[0]]
    for v in values[1:]:
        if v - lines[-1] > cluster_tolerance_ft:
            lines.append(v)
    return lines


def _column_grid_lines(column_polys, cluster_tolerance_ft=1.0):
    """Real structural column-line coordinates (not gaps — see
    estimate_column_grid_spacing for that), for snapping candidate room
    placements to the same bay lines a real architect designs around.
    Per-axis: only returned when at least 2 distinct lines exist on that
    axis (the same conservatism estimate_column_grid_spacing already uses)
    — fewer than that isn't enough to call it "a grid" on that axis, so
    placement falls back to the plain fixed-step scan for it instead of
    snapping every candidate to one column's coordinate."""
    if not column_polys:
        return None, None
    centroids = [(p.centroid.x, p.centroid.y) for p in column_polys]
    x_lines = _cluster_axis_lines([c[0] for c in centroids], cluster_tolerance_ft)
    y_lines = _cluster_axis_lines([c[1] for c in centroids], cluster_tolerance_ft)
    return (x_lines if len(x_lines) >= 2 else None), (y_lines if len(y_lines) >= 2 else None)


def _mirror_axis_values(values, minv, maxv, flip):
    """Mirrors a list of real-space axis coordinates the same way
    _mirror_for_scan mirrors a polygon about the bbox's own center — needed
    so grid_lines computed in real space still snap candidates correctly
    when _place_auditoriums runs its scan in mirrored (entry-biased) space."""
    if not values or not flip:
        return values
    return [(minv + maxv) - v for v in values]


def _column_enclosure_ok(scan_result, bbox, flip_x, flip_y, column_polys, max_ratio, edge_tolerance_ft=None):
    """Whether a fallback (column-tolerant) placement's own confirmed-COLUMN
    coverage stays within max_ratio of its footprint — the per-room-type
    column tolerance policy (see AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO /
    SUPPORT_ZONE_MAX_ENCLOSED_COLUMN_RATIO) — AND, when edge_tolerance_ft is
    given (auditoriums only; see AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT), that
    no part of an enclosed column sits stranded in the room's interior far
    from every one of its own walls. scan_result is in whatever space the
    scan actually ran in (mirrored, for _place_auditoriums; real, for
    place_single_zone, where flip_x/flip_y are always False) — unmirrored
    back to real coordinates before measuring, since column_polys are always
    real-space. The real gate math lives in placement.column_enclosure, so
    placement/solver.py's own CP-SAT candidate generation shares the exact
    same logic instead of a second implementation that could drift."""
    if not column_polys or not scan_result:
        return True
    sx, sy, w, h = scan_result
    x, y = _unmirror_rect(sx, sy, w, h, bbox, flip_x, flip_y)
    return column_enclosure.enclosure_ok(x, y, w, h, column_polys, max_ratio, edge_tolerance_ft)


# Real seat-config selection lives in seat_engine.py (default_seat_config /
# best_seat_estimate) — moved there so placement/solver.py can reuse the
# exact same logic without importing layout_engine.py back (which imports
# placement.solver, and a cycle isn't worth the alternative of duplicating
# this). Re-exported here under their old private names since this
# module's own tests and every existing call site already use them this
# way — a real rename, not a new indirection layer.
_default_seat_config = seat_engine.default_seat_config
_best_seat_estimate = seat_engine.best_seat_estimate


def _find_largest_fitting_custom_screen(usable_poly, fallback_poly, placed_polys, placed_types, bbox,
                                         min_area_sqft, max_dim_ft=80.0, min_short_side_ft=0.0):
    """When no registered auditorium preset fits anywhere, don't give up
    while real usable area still remains — a real, directly measured defect
    this exists to fix: on a real uploaded file, the engine placed 2
    undersized screens and then stopped with 5,194 of 6,979 sqft of usable
    area (74%) completely untouched, because none of the four fixed preset
    footprints happened to fit what was left, even though plenty of real
    area did.

    Uses placement.free_rectangles' real maximal-rectangle detection
    instead of guessing toward a size — the true largest empty rectangle
    at whatever's actually left (usable_poly, obstacles already excluded,
    minus whatever's already been placed_polys this run), not a shrink
    sequence hoping to land on something that fits. Each dimension is
    capped at max_dim_ft (a real auditorium is never a 150ft sliver — a
    maximal rectangle can legitimately be a long thin leftover strip;
    using only a sane sub-rectangle of it, anchored at its own corner,
    keeps the result a plausible room instead of a technically-valid but
    absurd shape) but never invents a screen smaller than min_area_sqft
    (the smallest *configured* preset's own floor). Tries the strict
    usable_poly first, then the column-tolerant fallback_poly — same
    two-tier convention every other placement in this module uses. Still
    an axis-aligned rectangle — real non-rectangular, boundary-hugging
    room shapes (what a human actually draws on an irregular floor plate)
    are a separate, much larger effort (see Module D: pre-drawn room
    detection, which sidesteps this for a real file that already has one).

    min_short_side_ft rejects a free rectangle whose short side falls below
    it outright — a real, measured defect this guards against: without it,
    a genuinely narrow leftover strip (e.g. 70.8x13.8ft) could still clear
    min_area_sqft and get built as a "screen" no human would ever draw
    (real cinema auditoriums are never that shallow). Safe to reject
    outright, not just discourage, because that strip's area doesn't
    vanish — it becomes real Foyer/circulation space instead (see
    _build_foyer_room), never silently lost usable area.

    Returns the same (result, used_fallback) shape _scan_place_with_fallback
    does, or (None, False)."""
    placed_union = unary_union(placed_polys) if placed_polys else None

    for poly, used_fallback in ((usable_poly, False), (fallback_poly, True)):
        if poly is None or (used_fallback and poly is usable_poly):
            continue
        remaining = poly.difference(placed_union) if placed_union is not None else poly
        if remaining.is_empty:
            continue
        for x, y, w, h in free_rectangles.free_rectangles_ft(remaining, bbox, cell_ft=1.0, max_candidates=40):
            cw, ch = min(w, max_dim_ft), min(h, max_dim_ft)
            if min(cw, ch) < min_short_side_ft:
                continue
            if cw * ch < min_area_sqft:
                continue
            cand = _rect(x, y, cw, ch)
            if not remaining.contains(cand.buffer(-0.01)):
                continue
            if not _fits_with_clearance(cand, placed_polys, placed_types, "AUDITORIUM"):
                continue
            return (x, y, cw, ch), used_fallback
    return None, False


def _screen_wall_for_rect(x, y, w, h, entry_point):
    """Which edge of a placed auditorium rect is the screen wall —
    geometry-relative labels (never compass directions: this project has
    already shipped one real Y-axis orientation bug this session, and
    reusing N/S/E/W on top of a codebase with a documented history of
    Y-flip confusion is asking for a repeat). Chosen as the edge nearest the
    marked entry point — real cinema design puts the entry/exit doors on
    the screen-adjacent wall (confirmed against two real Connplex reference
    floor plans during this feature's design pass: the projector booth,
    which must face the screen from the opposite end of the room, sits at
    the true building perimeter, while entry/exit are on the wall nearest
    the shared circulation core). Defaults to "min_y" — today's hardcoded
    frontend assumption — when no entry point is marked, so existing
    layouts render identically to before this field existed."""
    if entry_point is None:
        return "min_y"
    from shapely.geometry import Point, LineString
    ex, ey = entry_point
    edges = {
        "min_y": LineString([(x, y), (x + w, y)]),
        "max_y": LineString([(x, y + h), (x + w, y + h)]),
        "min_x": LineString([(x, y), (x, y + h)]),
        "max_x": LineString([(x + w, y), (x + w, y + h)]),
    }
    pt = Point(ex, ey)
    return min(edges, key=lambda k: edges[k].distance(pt))


def _doors_for_screen_wall(w, h, screen_wall, door_width_ft):
    """One ENTRY + one EXIT door on the screen wall, near its two ends —
    matches the reference floor plans, where every auditorium's entry/exit
    cluster sits on the screen-adjacent wall near its corners (SOP:
    SEPARATE_ENTRY_EXIT_FLOW — separate entry & exit flow per auditorium).
    offset_ft is measured along the wall from its start corner — (x, y) for
    a min_y/max_y wall, (x, y) for a min_x/max_x wall — in the direction of
    increasing X (min_y/max_y) or increasing Y (min_x/max_x); a renderer
    combines this with the room's own geometry_points_ft + screen_wall to
    get the door's real position."""
    wall_len = w if screen_wall in ("min_y", "max_y") else h
    if wall_len <= 0:
        return []
    dw = min(door_width_ft, wall_len / 2.5)
    inset = max(dw * 0.6, 0.5)
    exit_offset = max(wall_len - inset - dw, inset)
    return [
        {"kind": "ENTRY", "wall": screen_wall, "offset_ft": round(inset, 2), "width_ft": round(dw, 2)},
        {"kind": "EXIT", "wall": screen_wall, "offset_ft": round(exit_offset, 2), "width_ft": round(dw, 2)},
    ]


def _build_auditorium_room(x, y, w, h, index, used_preset, used_fallback, column_polys,
                            screen_width_ft, entry_point, door_width_ft):
    """Builds one placed-auditorium room dict — shared by _place_auditoriums'
    preset loop, its backtracking-based custom-fit filler, and
    place_single_zone's own AUDITORIUM branch, so all three paths stay in
    sync on exactly what fields a placed auditorium carries. used_preset is
    None for a custom-fit (non-standard-tier) placement."""
    rect = _rect(x, y, w, h)
    enclosed_area = _enclosed_obstacle_area(rect, column_polys) if used_fallback else 0.0
    seat_config, seat_est = _best_seat_estimate(used_preset, w, h, enclosed_area, screen_width_ft)
    screen_wall = _screen_wall_for_rect(x, y, w, h, entry_point)
    room = {
        "room_id": f"auditorium-{uuid.uuid4().hex[:8]}",
        "room_type": f"AUDITORIUM_{index}",
        "display_name": f"Screen {index} (Auditorium)",
        "preset_id": used_preset["id"] if used_preset else None,
        "preset_name": used_preset["name"] if used_preset else "Custom-fit screen",
        "area_sqft": round(w * h, 2),
        "width_ft": round(w, 2),
        "depth_ft": round(h, 2),
        "origin_ft": [round(x, 2), round(y, 2)],
        "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "label_point_ft": [round(x + w / 2, 2), round(y + h / 2, 2)],
        "seat_estimate": seat_est,
        "seat_config": seat_config,
        "screen_wall": screen_wall,
        "doors": _doors_for_screen_wall(w, h, screen_wall, door_width_ft)
    }
    if used_preset is None:
        room["area_basis_note"] = (
            "No standard SOP auditorium preset fit the remaining usable area — sized to the largest "
            "rectangle that does fit, rather than leaving real usable floor area unplaced. Not a "
            "standard preset tier; review before finalizing."
        )
    if seat_est.get("note"):
        room["obstacle_note"] = seat_est["note"]
    return room


def _fill_remaining_auditoriums_with_backtracking(usable_poly, fallback_poly, column_polys, bbox,
                                                    placed_polys, placed_types, remaining_slots,
                                                    min_area_sqft, aud_column_cap, flip_x, flip_y,
                                                    max_dim_ft=80.0, aud_edge_tolerance_ft=None,
                                                    min_short_side_ft=0.0):
    """Fills up to remaining_slots more custom-fit auditorium footprints
    using placement.backtracking's bounded search instead of committing to
    the single largest free rectangle at each step irrevocably (which is
    what _find_largest_fitting_custom_screen alone does, and still does for
    place_single_zone's one-room-at-a-time Add Zone path, where there's no
    "later slot" to backtrack for). Lets an earlier custom-fit choice be
    reconsidered — the next-largest free rectangle instead of the largest —
    when the largest one would leave too little room for a later screen,
    instead of stopping the instant a plain greedy forward pass gets stuck.
    Returns a list of (x, y, w, h, used_fallback) tuples in the SAME
    (mirrored or real) coordinate space usable_poly/placed_polys are
    already in — the caller is responsible for un-mirroring, same as every
    other placement result in this module."""
    base_placed_union = unary_union(placed_polys) if placed_polys else None

    def candidates_for_slot(depth, committed):
        committed_polys = [_rect(c[0], c[1], c[2], c[3]) for c in committed]
        all_placed = ([base_placed_union] if base_placed_union is not None else []) + committed_polys
        placed_union = unary_union(all_placed) if all_placed else None
        cands = []
        for poly, used_fb in ((usable_poly, False), (fallback_poly, True)):
            if poly is None or (used_fb and poly is usable_poly):
                continue
            remaining = poly.difference(placed_union) if placed_union is not None else poly
            if remaining.is_empty:
                continue
            for x, y, w, h in free_rectangles.free_rectangles_ft(remaining, bbox, cell_ft=1.0, max_candidates=12):
                cw, ch = min(w, max_dim_ft), min(h, max_dim_ft)
                if min(cw, ch) < min_short_side_ft:
                    continue
                if cw * ch < min_area_sqft:
                    continue
                cands.append((x, y, cw, ch, used_fb, remaining))
        cands.sort(key=lambda c: c[2] * c[3], reverse=True)  # largest real area first, same convention as every other placement here
        return cands

    def try_candidate(cand):
        x, y, cw, ch, used_fb, remaining = cand
        rect = _rect(x, y, cw, ch)
        if not remaining.contains(rect.buffer(-0.01)):
            return None
        if used_fb and not _column_enclosure_ok((x, y, cw, ch), bbox, flip_x, flip_y, column_polys, aud_column_cap, aud_edge_tolerance_ft):
            return None
        return (x, y, cw, ch, used_fb)

    return backtracking.search_with_backtracking(
        remaining_slots, candidates_for_slot, try_candidate, max_backtrack=2, max_total_attempts=40
    )


def _place_auditoriums(usable_poly, fallback_poly, column_polys, bbox, presets, max_count, preset_order,
                        entry_point=None, exit_points_ft=None, screen_width_ft=None):
    placed = []
    placed_polys = []           # real-space, returned to the caller
    warnings = []
    undersized_count = 0  # how many auditoriums couldn't get this strategy's most-preferred preset tier — real evidence for the utilization warning below, not a guess

    # See _entry_exit_scan_flip's own docstring: this is what makes screen
    # placement actually start near the entrance and proceed toward the
    # exit side instead of an arbitrary fixed corner. Mirrored once here,
    # not per-auditorium — the scan itself runs entirely in mirrored space
    # (scan_placed_polys below), and every result is mapped back to real
    # coordinates via _unmirror_rect before it's used for anything else
    # (seat estimation, the returned room record, collision-checking
    # against any support zones the architect adds afterward via
    # place_single_zone).
    flip_x, flip_y = _entry_exit_scan_flip(bbox, entry_point, exit_points_ft)
    scan_usable = _mirror_for_scan(usable_poly, bbox, flip_x, flip_y)
    scan_fallback = _mirror_for_scan(fallback_poly, bbox, flip_x, flip_y)
    scan_placed_polys = []      # mirrored-space, used only for the scan's own collision checks
    scan_placed_types = []      # parallel to scan_placed_polys — every entry is "AUDITORIUM" here, so
                                 # _neighbor_gap_ft lets consecutive screens sit with zero gap (shared wall)

    # Real structural column-grid lines (see _column_grid_lines), mirrored
    # into the same scan space as scan_usable/scan_fallback above, so
    # candidate positions snap to real bay lines instead of the fixed
    # GRID_STEP_FT scan step whenever a real grid is detected.
    minx, miny, maxx, maxy = bbox
    grid_lines_x, grid_lines_y = _column_grid_lines(column_polys)
    scan_grid_x = _mirror_axis_values(grid_lines_x, minx, maxx, flip_x)
    scan_grid_y = _mirror_axis_values(grid_lines_y, miny, maxy, flip_y)

    aud_column_cap = rules_registry.planning_norm("AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO")
    if aud_column_cap is None:
        aud_column_cap = 0.02
    aud_edge_tolerance_ft = rules_registry.planning_norm("AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT")
    if aud_edge_tolerance_ft is None:
        aud_edge_tolerance_ft = 2.0
    door_width_ft = rules_registry.planning_norm("AUDITORIUM_DOOR_WIDTH_FT") or 3.5
    min_preset_area_sqft = min((p["min_area_sqft"] for p in presets), default=0)
    min_short_side_ft = min((p["width_min_ft"] for p in presets), default=0)

    # Phase 1: real SOP presets only, largest-fits-first, exactly as before.
    # The instant a preset fails to fit anywhere, stop this loop — every
    # later screen would face the same or less usable space, so no later
    # preset attempt could succeed either. What used to be a single
    # geometric-decay custom-fit guess tried once per stalled iteration is
    # now Phase 2 below: a proper backtracking-aware fill for every
    # remaining slot at once.
    ordered_presets = preset_order(presets)
    presets_exhausted = False
    for _ in range(max_count):
        placement = None
        used_preset = None
        for preset in ordered_presets:
            # Try the preset's largest allowed footprint first (falls back to
            # its own min axis when a max isn't declared for that axis — e.g.
            # 60_SEAT/90_SEAT only declare a max on one axis) — this is what
            # actually uses the space a preset is allowed to occupy instead of
            # always taking its smallest legal footprint, directly increasing
            # both seats (the locked v1 objective) and area utilization.
            w_max = preset.get("width_max_ft", preset["width_min_ft"])
            h_max = preset.get("length_max_ft", preset["length_min_ft"])
            result, used_fallback = _scan_place_with_fallback(scan_usable, scan_fallback, scan_placed_polys, scan_placed_types, "AUDITORIUM", w_max, h_max, bbox,
                                                                grid_lines_x=scan_grid_x, grid_lines_y=scan_grid_y)
            # A fallback (column-tolerant) placement is only acceptable if the
            # enclosed column stays within the auditorium's own, much
            # stricter tolerance (see AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO) —
            # a column mid-seating-bowl is a real defect, not something to
            # silently absorb the way a foyer wraps one. Rejecting here just
            # falls through to the next (smaller) footprint/preset below,
            # same as a genuine no-fit — this v1 only retries the preset's
            # own two declared footprints, not every other position the
            # fallback polygon might offer; a real but bounded scope cut.
            if result and used_fallback and not _column_enclosure_ok(result, bbox, flip_x, flip_y, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                result = None
            if not result and (w_max, h_max) != (preset["width_min_ft"], preset["length_min_ft"]):
                result, used_fallback = _scan_place_with_fallback(scan_usable, scan_fallback, scan_placed_polys, scan_placed_types, "AUDITORIUM", preset["width_min_ft"], preset["length_min_ft"], bbox,
                                                                    grid_lines_x=scan_grid_x, grid_lines_y=scan_grid_y)
                if result and used_fallback and not _column_enclosure_ok(result, bbox, flip_x, flip_y, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                    result = None
            if result:
                placement = result
                used_preset = preset
                break

        if not placement:
            presets_exhausted = True
            break

        if used_preset is not ordered_presets[0]:
            undersized_count += 1

        sx, sy, w, h = placement
        scan_placed_polys.append(_rect(sx, sy, w, h))
        scan_placed_types.append("AUDITORIUM")
        x, y = _unmirror_rect(sx, sy, w, h, bbox, flip_x, flip_y)
        placed_polys.append(_rect(x, y, w, h))
        # used_fallback means no column-free placement existed for this
        # preset tier at this step — the winning rect is allowed to cover a
        # confirmed structural column (never any other obstacle type; see
        # compute_usable_area's exclude_classifications), same as a real
        # architect designing an auditorium around an existing column in a
        # retrofit building. Seat count is discounted honestly, not
        # optimistically ignored — see seat_engine.estimate_seats.
        placed.append(_build_auditorium_room(x, y, w, h, len(placed) + 1, used_preset, used_fallback,
                                              column_polys, screen_width_ft, entry_point, door_width_ft))

    # Phase 2: no registered preset fits anywhere — before giving up, check
    # whether real usable area still remains that non-preset custom
    # footprints could use, with bounded backtracking across however many
    # slots are left (not just one greedy guess per stalled iteration). See
    # _fill_remaining_auditoriums_with_backtracking's own docstring: a real,
    # directly-measured defect (a real uploaded file left 74% of its usable
    # area untouched this way) motivated both this and the free-rectangle
    # search it's built on.
    remaining_slots = max_count - len(placed)
    if remaining_slots > 0:
        backtrack_results = _fill_remaining_auditoriums_with_backtracking(
            scan_usable, scan_fallback, column_polys, bbox, scan_placed_polys, scan_placed_types,
            remaining_slots, min_preset_area_sqft, aud_column_cap, flip_x, flip_y,
            aud_edge_tolerance_ft=aud_edge_tolerance_ft, min_short_side_ft=min_short_side_ft
        )
        for sx, sy, w, h, used_fallback in backtrack_results:
            scan_placed_polys.append(_rect(sx, sy, w, h))
            scan_placed_types.append("AUDITORIUM")
            x, y = _unmirror_rect(sx, sy, w, h, bbox, flip_x, flip_y)
            placed_polys.append(_rect(x, y, w, h))
            placed.append(_build_auditorium_room(x, y, w, h, len(placed) + 1, None, used_fallback,
                                                  column_polys, screen_width_ft, entry_point, door_width_ft))
        if not backtrack_results and presets_exhausted:
            warnings.append(f"Could not fit another auditorium after placing {len(placed)} — no remaining preset or custom-fit footprint fits available usable space.")

    return placed, placed_polys, warnings, undersized_count


def _support_zone_dims(room_type, area):
    """Target (w, h) footprint for a support zone of the given target area.
    Every type except PASSAGE uses the generic aspect=1.6 square-ish shape
    every support zone has always used. PASSAGE is deliberately different —
    a corridor is a real, elongated shape, not a square-ish room, sized by
    the observed EGRESS_PASSAGE_MIN_WIDTH_FT (real Connplex reference
    drawing) as its fixed width, with length derived from area — a passage
    with the generic aspect would just be a wide, useless room."""
    if room_type == "PASSAGE":
        min_width_ft = rules_registry.planning_norm("EGRESS_PASSAGE_MIN_WIDTH_FT") or 8.25
        hh = min_width_ft
        ww = max(area / hh, min_width_ft * 1.5)
        return ww, hh
    aspect = 1.6
    ww = math.sqrt(area * aspect)
    hh = area / ww
    return ww, hh


def _support_zone_heuristic(room_type, entry_point, exit_points_ft, usable_poly, fallback_poly,
                             placed_polys, placed_types, foyer_rect):
    """The per-room-type score_fn/prefer_fn selection place_single_zone
    always used inline — pulled out so place_single_zone and the new
    auto-orchestration (_place_support_zones_and_foyer) share one
    implementation instead of two that could drift. foyer_rect may be None
    (no Foyer placed/known yet) — place_single_zone can be called before a
    Foyer exists (an architect adding Washroom via Add Zone before Foyer),
    and the new auto-orchestration always computes Foyer last by design, so
    both callers already had to cope with a None foyer_rect; this isn't new
    branching.

    Real entry point marked by the architect (spec M6 / SOP §4.4-§9): "Foyer
    (at main entry level)", "F&B: visible from entry", "Washrooms: ... not
    directly visible from foyer". Nothing in CAD extraction detects doors,
    so this is only applied when the architect actually marked one."""
    score_fn = prefer_fn = None
    if room_type == "PASSAGE":
        # A passage connects the foyer to the auditoriums — evidence-based
        # from the reference floor plans, not a compass-direction guess:
        # prefer a position close to both the foyer and the nearest
        # already-placed screen. Independent of whether an entry point is
        # marked (unlike every other support zone's heuristic below), since
        # foyer/auditorium positions are already known once either exists.
        aud_polys_only = [p for p, t in zip(placed_polys, placed_types) if t == "AUDITORIUM"]
        nearest_aud = (min(aud_polys_only, key=lambda p: p.distance(foyer_rect))
                       if aud_polys_only and foyer_rect is not None
                       else (aud_polys_only[0] if aud_polys_only else None))
        if foyer_rect is not None and nearest_aud is not None:
            score_fn = lambda c: _rect(*c).distance(foyer_rect) + _rect(*c).distance(nearest_aud)
        elif foyer_rect is not None:
            score_fn = lambda c: _rect(*c).distance(foyer_rect)
        elif nearest_aud is not None:
            score_fn = lambda c: _rect(*c).distance(nearest_aud)
        # else: no Foyer or Screen placed yet — falls through to a plain
        # scan below, same as any other support zone with no heuristic
        # available yet at this point in the layout.
    elif entry_point is not None:
        if room_type in ("FOYER", "BOX_OFFICE"):
            score_fn = lambda c: (_rect(*c).centroid.x - entry_point[0]) ** 2 + (_rect(*c).centroid.y - entry_point[1]) ** 2
        elif room_type == "FNB":
            # The foyer itself is deliberately excluded from what counts as
            # "blocking" this — see place_single_zone's own module docstring
            # discussion in the original _place_support_zones this was
            # extracted from: a sightline starting inside/behind the foyer
            # trivially fails otherwise.
            blockers = [p for p in placed_polys if p is not foyer_rect]
            prefer_fn = lambda c: _has_sightline(usable_poly, blockers, entry_point, _rect(*c))
        elif room_type == "WASHROOM":
            if foyer_rect is not None:
                foyer_centroid = (foyer_rect.centroid.x, foyer_rect.centroid.y)
                blockers = [p for p in placed_polys if p is not foyer_rect]
                prefer_fn = lambda c: not _has_sightline(usable_poly, blockers, foyer_centroid, _rect(*c))
            else:
                # No Foyer placed/known yet — "no sightline from the entry"
                # is a real, close proxy for "no sightline from the foyer,"
                # since Foyer ends up being exactly the leftover area around
                # the entry once everything else is placed (see
                # _build_foyer_room). Purely additive: before this rule
                # existed, Washroom had no preference at all without a real
                # foyer_rect.
                prefer_fn = lambda c: not _has_sightline(usable_poly, placed_polys, entry_point, _rect(*c))
        elif room_type == "BOH":
            # Back-of-house (electrical/server/store) is staff-only — sits as
            # far as possible from both the entrance and every marked exit.
            ref_points = [entry_point] + list(exit_points_ft or [])
            score_fn = lambda c: -min(
                (_rect(*c).centroid.x - rx) ** 2 + (_rect(*c).centroid.y - ry) ** 2
                for rx, ry in ref_points
            )
    elif room_type in ("FOYER", "BOX_OFFICE"):
        # No entrance marked: prefer a placement touching the boundary's own
        # perimeter — a foyer/box-office is essentially always at the
        # building's frontage in real cinema design.
        perimeter = _exterior_lines(fallback_poly)
        prefer_fn = lambda c: _rect(*c).distance(perimeter) < PERIMETER_TOUCH_TOLERANCE_FT
    return score_fn, prefer_fn


def place_single_zone(usable_poly, fallback_poly, column_polys, placed_polys, placed_types, bbox,
                       room_type, requirements, franchise_tier_id=None):
    """Places exactly one new room of `room_type` into the current layout
    state — placed_polys/placed_types describe every room already in the
    layout (every auditorium tagged "AUDITORIUM" regardless of its exact
    AUDITORIUM_N room_type, so _neighbor_gap_ft's screen-to-screen rule
    applies). This is what the "Add Zone" endpoint calls (main.py), so a
    manually added zone gets the same logical, entry-aware, collision-safe
    placement the auto-layout itself uses for screens — never the blind
    fixed-corner guess the frontend used to do.

    room_type is one of the AUDITORIUM_PRESET-driven "AUDITORIUM" (adds one
    more screen, using the same largest-preset-that-fits search as
    _place_auditoriums) or one of SUPPORT_ZONE_DEFAULTS's five ids.

    Returns (room_dict, note_or_None) on success, or (None, message) if
    nothing fits anywhere — never invents a placement that doesn't actually
    fit (Product Principle #4)."""
    entry_point = requirements.get("entry_point_ft") if requirements else None
    exit_points_ft = requirements.get("exit_points_ft") if requirements else None
    screen_width_ft = requirements.get("screen_width_ft") if requirements else None

    # No mirroring here (unlike _place_auditoriums) — place_single_zone
    # always scans in real space, so grid lines need no _mirror_axis_values
    # step, and _column_enclosure_ok is called with flip_x=flip_y=False.
    grid_lines_x, grid_lines_y = _column_grid_lines(column_polys)
    aud_column_cap = rules_registry.planning_norm("AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO")
    if aud_column_cap is None:
        aud_column_cap = 0.02
    aud_edge_tolerance_ft = rules_registry.planning_norm("AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT")
    if aud_edge_tolerance_ft is None:
        aud_edge_tolerance_ft = 2.0
    support_column_cap = rules_registry.planning_norm("SUPPORT_ZONE_MAX_ENCLOSED_COLUMN_RATIO")
    if support_column_cap is None:
        support_column_cap = 0.15
    door_width_ft = rules_registry.planning_norm("AUDITORIUM_DOOR_WIDTH_FT") or 3.5

    if room_type == "AUDITORIUM":
        presets = rules_registry.auditorium_presets()  # largest-first
        matched_preset = None
        for preset in presets:
            w_max = preset.get("width_max_ft", preset["width_min_ft"])
            h_max = preset.get("length_max_ft", preset["length_min_ft"])
            result, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, "AUDITORIUM", w_max, h_max, bbox,
                                                                grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y)
            if result and used_fallback and not _column_enclosure_ok(result, bbox, False, False, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                result = None
            if not result and (w_max, h_max) != (preset["width_min_ft"], preset["length_min_ft"]):
                result, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, "AUDITORIUM", preset["width_min_ft"], preset["length_min_ft"], bbox,
                                                                    grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y)
                if result and used_fallback and not _column_enclosure_ok(result, bbox, False, False, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                    result = None
            if result:
                matched_preset = preset
                break

        used_custom_fit = False
        if not matched_preset or not result:
            result = None
            min_preset_area_sqft = min((p["min_area_sqft"] for p in presets), default=0)
            min_short_side_ft = min((p["width_min_ft"] for p in presets), default=0)
            custom_result, custom_used_fallback = _find_largest_fitting_custom_screen(
                usable_poly, fallback_poly, placed_polys, placed_types, bbox,
                min_preset_area_sqft, min_short_side_ft=min_short_side_ft
            )
            if custom_result and custom_used_fallback and not _column_enclosure_ok(custom_result, bbox, False, False, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                custom_result = None
            if custom_result:
                result = custom_result
                used_fallback = custom_used_fallback
                used_custom_fit = True

        if not result:
            return None, "No space available for a new Screen — even a custom-fit footprint doesn't fit in the remaining area."

        x, y, w, h = result
        rect = _rect(x, y, w, h)
        enclosed_area = _enclosed_obstacle_area(rect, column_polys) if used_fallback else 0.0
        seat_config, seat_est = _best_seat_estimate(
            None if used_custom_fit else matched_preset, w, h, enclosed_area, screen_width_ft
        )
        existing_screens = sum(1 for t in placed_types if t == "AUDITORIUM")
        screen_wall = _screen_wall_for_rect(x, y, w, h, entry_point)
        room = {
            "room_id": f"auditorium-{uuid.uuid4().hex[:8]}",
            "room_type": f"AUDITORIUM_{existing_screens + 1}",
            "display_name": f"Screen {existing_screens + 1} (Auditorium)",
            "preset_id": matched_preset["id"] if matched_preset else None,
            "preset_name": matched_preset["name"] if matched_preset else "Custom-fit screen",
            "area_sqft": round(w * h, 2), "width_ft": round(w, 2), "depth_ft": round(h, 2),
            "origin_ft": [round(x, 2), round(y, 2)],
            "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            "label_point_ft": [round(x + w / 2, 2), round(y + h / 2, 2)],
            "seat_estimate": seat_est,
            "seat_config": seat_config,
            "screen_wall": screen_wall,
            "doors": _doors_for_screen_wall(w, h, screen_wall, door_width_ft)
        }
        if used_custom_fit:
            room["area_basis_note"] = (
                "No standard SOP auditorium preset fit the remaining usable area — sized to the largest "
                "rectangle that does fit, rather than leaving real usable floor area unplaced. Not a "
                "standard preset tier; review before finalizing."
            )
        if seat_est.get("note"):
            room["obstacle_note"] = seat_est["note"]
        return room, None

    default_entry = next((t for t in SUPPORT_ZONE_DEFAULTS if t[0] == room_type), None)
    if default_entry is None:
        return None, f"Unknown zone type '{room_type}'."
    _, display_name, default_target, min_area, note = default_entry

    total_aud_area = sum(p.area for p, t in zip(placed_polys, placed_types) if t == "AUDITORIUM")
    tier = rules_registry.franchise_tier(franchise_tier_id) if franchise_tier_id else None
    foyer_target = None
    if tier and tier.get("foyer_to_screen_ratio"):
        try:
            foyer_pct, screen_pct = [float(v) for v in tier["foyer_to_screen_ratio"].split(":")]
            foyer_target = total_aud_area * (foyer_pct / screen_pct)
        except Exception:
            foyer_target = None
    if foyer_target is None:
        foyer_target = total_aud_area * 0.30

    overrides = requirements.get("support_zone_area_overrides_sqft", {}) if requirements else {}
    target_area = overrides.get(room_type)
    if target_area is None:
        target_area = foyer_target if room_type == "FOYER" else (
            default_target if default_target is not None else total_aud_area * 0.08
        )
    if target_area <= 0:
        # No auditorium placed yet to size this zone against (0 screens, or an
        # override of 0) — fall back to the preset's own real minimum rather
        # than a bare division-by-zero a moment later.
        target_area = min_area

    w, h = _support_zone_dims(room_type, target_area)

    foyer_rect = next((p for p, t in zip(placed_polys, placed_types) if t == "FOYER"), None)

    score_fn, prefer_fn = _support_zone_heuristic(room_type, entry_point, exit_points_ft, usable_poly, fallback_poly,
                                                    placed_polys, placed_types, foyer_rect)

    note_out = None
    used_fallback = False
    if score_fn or prefer_fn:
        best, satisfied, used_fallback = _scan_place_best_with_fallback(
            usable_poly, fallback_poly, placed_polys, placed_types, room_type, w, h, bbox, score_fn=score_fn, prefer_fn=prefer_fn,
            grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y
        )
        placement = best
        if placement and used_fallback and not _column_enclosure_ok(placement, bbox, False, False, column_polys, support_column_cap):
            placement = None
            used_fallback = False
        if placement and prefer_fn and not satisfied:
            if room_type == "FNB":
                rule_desc = "a sightline from the entry"
            elif room_type == "WASHROOM":
                rule_desc = "no direct sightline from the foyer"
            else:
                rule_desc = "a position touching the building's perimeter/frontage"
            note_out = f"{display_name} placed, but no available position gave it {rule_desc} — used the best fit available instead."
    else:
        placement, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, room_type, w, h, bbox,
                                                               grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y)
        if placement and used_fallback and not _column_enclosure_ok(placement, bbox, False, False, column_polys, support_column_cap):
            placement = None
            used_fallback = False

    shrink_note = None
    if not placement:
        # Try shrinking toward the minimum before giving up — never invent
        # space that isn't there. The true floor (min_area) itself is always
        # tried last even if it falls between two factors above (a shallow
        # leftover strip can genuinely only fit the smallest legal size,
        # not any of the three round-number factors on the way down).
        shrink_sizes = [target_area * f for f in (0.75, 0.5, 0.35)]
        shrink_sizes = [a for a in shrink_sizes if a >= min_area] + [min_area]
        for area in shrink_sizes:
            w2, h2 = _support_zone_dims(room_type, area)
            placement, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, placed_types, room_type, w2, h2, bbox,
                                                                   grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y)
            if placement and used_fallback and not _column_enclosure_ok(placement, bbox, False, False, column_polys, support_column_cap):
                placement = None
                used_fallback = False
                continue
            if placement:
                shrink_note = f"Shrunk from target {round(target_area,1)} sqft to fit available space ({round(w2*h2,1)} sqft, {round(100*area/target_area) if target_area else 0}% of target)."
                break

    if not placement:
        return None, f"No space available for a new {display_name} — try deleting or resizing an existing room first. (target {round(target_area,1)} sqft; {note})"

    x, y, w, h = placement
    rect = _rect(x, y, w, h)
    zone = {
        "room_id": f"{room_type.lower()}-{uuid.uuid4().hex[:8]}",
        "room_type": room_type,
        "display_name": display_name,
        "area_sqft": round(w * h, 2),
        "width_ft": round(w, 2),
        "depth_ft": round(h, 2),
        "origin_ft": [round(x, 2), round(y, 2)],
        "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "label_point_ft": [round(x + w / 2, 2), round(y + h / 2, 2)],
        "area_basis_note": note
    }
    if shrink_note:
        zone["shrink_note"] = shrink_note
    # A support zone tolerates an enclosed column far more naturally than
    # an auditorium (real foyers/F&B areas commonly wrap a column) — still
    # flagged honestly rather than silently absorbed, so the architect
    # knows to route furniture/counters around it.
    if used_fallback:
        enclosed_area = _enclosed_obstacle_area(rect, column_polys)
        if enclosed_area > 0:
            zone["obstacle_note"] = (
                f"{round(enclosed_area, 1)} sqft of confirmed obstacle(s) (e.g. a structural column) fall "
                f"inside this room's footprint — plan furniture/layout around the obstacle position(s)."
            )
    return zone, note_out


# ---------- Post-auditorium auto-placement: real support zones + Foyer-as-remainder ----------
#
# Screens first (above), then Box Office/F&B/Washroom/BOH with real,
# connectivity-gated geometry, then Foyer computed as whatever's genuinely
# left — not independently placed. PASSAGE is deliberately excluded from
# auto-placement: its old purpose (connecting Foyer to the nearest screen)
# is now structurally satisfied by Foyer *being* the leftover common path;
# a separate auto-placed PASSAGE rectangle would just carve a piece out of
# what should become Foyer for no circulation benefit. PASSAGE remains
# available for a manual "Add Zone" edit against an existing layout.
SUPPORT_ZONE_AUTO_ORDER = ["BOX_OFFICE", "FNB", "WASHROOM", "BOH"]
SUPPORT_ZONE_CONNECTIVITY_TOP_K = 12
MIN_REAL_FOYER_SQFT = 20.0
DOOR_TOUCH_TOLERANCE_FT = 1.5


def _door_for_support_zone(w, h, wall, door_width_ft):
    """Single ENTRY door centered on `wall` — same {kind, wall, offset_ft,
    width_ft} shape _doors_for_screen_wall already produces (an auditorium
    needs a separate ENTRY+EXIT per SOP; a Box Office/F&B/Washroom/BOH room
    needs only one real opening), so export_dxf.py/export_pdf.py's door
    glyphs and EditableCanvas.tsx's doorGlyphPoints render it with zero
    changes — both already key only off room.doors[i].{wall,offset_ft,
    width_ft}."""
    wall_len = w if wall in ("min_y", "max_y") else h
    if wall_len <= 0:
        return []
    dw = min(door_width_ft, wall_len / 2.5)
    offset = max((wall_len - dw) / 2, 0.0)
    return [{"kind": "ENTRY", "wall": wall, "offset_ft": round(offset, 2), "width_ft": round(dw, 2)}]


def _place_single_support_zone_connectivity_aware(usable_poly, fallback_poly, column_polys, bbox,
                                                    placed_polys, placed_types, placed_rooms_for_doors,
                                                    room_type, requirements, entry_point, exit_points_ft,
                                                    support_column_cap, target_area, min_area):
    """One support zone, connectivity-gated: tries ranked candidates
    (strict tier, then column-tolerant fallback tier — see
    _scan_place_ranked_with_fallback) at the target size, then shrinks
    toward the minimum (same 75/50/35% ladder place_single_zone always
    used) — at every size, walks candidates in preference order and skips
    any that would SEVER reachability between the entry point and any
    already-placed room's door, relative to the current baseline (see
    placement.connectivity.would_sever) — not any that merely fails an
    absolute "everything reachable" test. That distinction matters on a
    real floor plate: a genuine confirmed WALL can leave two already-placed
    auditoriums on opposite sides with no path between them before any
    support zone is even considered — an absolute test would then reject
    every candidate forever (a pre-existing condition no candidate could
    fix), whereas the relative test only vetoes a candidate that makes
    things WORSE than they already were. Returns ((x, y, w, h,
    used_fallback), shrink_note_or_None) or (None, None) if nothing fits
    anywhere without blocking the common path."""
    grid_lines_x, grid_lines_y = _column_grid_lines(column_polys)
    score_fn, prefer_fn = _support_zone_heuristic(room_type, entry_point, exit_points_ft, usable_poly, fallback_poly,
                                                    placed_polys, placed_types, None)

    ref_points = ([entry_point] if entry_point else []) + [
        connectivity.door_outside_point(r, d) for r in placed_rooms_for_doors for d in r.get("doors", [])
    ]
    free_space_before = fallback_poly.difference(unary_union(placed_polys)) if placed_polys else fallback_poly

    def try_at(w, h):
        ranked = _scan_place_ranked_with_fallback(
            usable_poly, fallback_poly, placed_polys, placed_types, room_type, w, h, bbox,
            score_fn=score_fn, prefer_fn=prefer_fn, top_k=SUPPORT_ZONE_CONNECTIVITY_TOP_K,
            grid_lines_x=grid_lines_x, grid_lines_y=grid_lines_y
        )
        for (x, y, ow, oh), satisfied, used_fallback in ranked:
            if used_fallback and not _column_enclosure_ok((x, y, ow, oh), bbox, False, False, column_polys, support_column_cap):
                continue
            candidate_rect = _rect(x, y, ow, oh)
            free_space_after = free_space_before.difference(candidate_rect)
            if connectivity.would_sever(free_space_before, free_space_after, bbox, ref_points):
                continue
            return x, y, ow, oh, used_fallback
        return None

    result = try_at(*_support_zone_dims(room_type, target_area))
    if result:
        return result, None
    # The true floor (min_area) is always tried last even if it falls
    # between two round-number factors — a shallow leftover strip can
    # genuinely only fit the smallest legal size (see place_single_zone's
    # identical shrink-ladder change and its own comment).
    shrink_sizes = [target_area * f for f in (0.75, 0.5, 0.35)]
    shrink_sizes = [a for a in shrink_sizes if a >= min_area] + [min_area]
    for area in shrink_sizes:
        w2, h2 = _support_zone_dims(room_type, area)
        result = try_at(w2, h2)
        if result:
            shrink_note = f"Shrunk from target {round(target_area, 1)} sqft to fit available space ({round(w2 * h2, 1)} sqft, {round(100 * area / target_area) if target_area else 0}% of target)."
            return result, shrink_note
    return None, None


def _single_ring_with_keyholes(poly):
    """Converts a Shapely Polygon that may have interior holes (a real,
    confirmed case: a support zone can end up fully enclosed by leftover
    Foyer space, leaving a hole in Foyer's own remainder polygon) into one
    equivalent single ring, using the standard "keyhole"/slit technique:
    each hole is spliced into the outer ring via a degenerate (zero-width,
    there-and-back) cut connecting the hole's nearest point to the ring's
    nearest point. This preserves the TRUE area and shape exactly — no
    silent overlap with the room that created the hole — while staying
    representable in this codebase's existing single-ring geometry_points_ft
    convention (used everywhere: EditableCanvas.tsx's SVG polygon,
    export_dxf.py/export_pdf.py, validate_rooms). Before this existed, the
    exterior ring alone was stored, which silently discarded every hole and
    overstated the room's true footprint by their combined area — a real,
    measured defect found via this round's own reconciliation test (589
    sqft of false overlap on a real irregular boundary)."""
    ring = list(poly.exterior.coords)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    for hole in poly.interiors:
        hole_ring = list(hole.coords)
        if len(hole_ring) > 1 and hole_ring[0] == hole_ring[-1]:
            hole_ring = hole_ring[:-1]
        if not hole_ring:
            continue
        i, j = min(
            ((a, b) for a in range(len(ring)) for b in range(len(hole_ring))),
            key=lambda ab: (ring[ab[0]][0] - hole_ring[ab[1]][0]) ** 2 + (ring[ab[0]][1] - hole_ring[ab[1]][1]) ** 2,
        )
        detour = hole_ring[j:] + hole_ring[:j] + [hole_ring[j]]
        ring = ring[:i + 1] + detour + ring[i:]
    return ring


def _build_foyer_room(fallback_poly, placed_polys, placed_rooms_for_doors, entry_point):
    """Foyer is not independently placed — it's the real, contiguous
    leftover usable area once screens and every other support zone are
    placed. If the leftover is a MultiPolygon (disconnected pockets), the
    piece touching/containing the entry point wins when one is marked
    (falling back to the piece touching the most already-placed doors when
    not) — every other piece's area is reported as leftover slack, never
    promoted to a second Foyer room. Returns (foyer_room_or_None,
    leftover_slack_sqft)."""
    from shapely.geometry import Point
    remainder = fallback_poly.difference(unary_union(placed_polys)) if placed_polys else fallback_poly
    if remainder.is_empty:
        return None, 0.0
    pieces = [p for p in (remainder.geoms if remainder.geom_type == "MultiPolygon" else [remainder]) if p.area > 1e-6]
    if not pieces:
        return None, 0.0

    def door_touches(piece):
        pts = [connectivity.door_outside_point(r, d) for r in placed_rooms_for_doors for d in r.get("doors", [])]
        return sum(1 for px, py in pts if piece.distance(Point(px, py)) < DOOR_TOUCH_TOLERANCE_FT)

    if entry_point is not None:
        ep = Point(*entry_point)
        near_entry = [p for p in pieces if p.distance(ep) < PERIMETER_TOUCH_TOLERANCE_FT or p.contains(ep)]
        chosen = max(near_entry, key=lambda p: p.area) if near_entry else max(pieces, key=lambda p: (door_touches(p), p.area))
    else:
        chosen = max(pieces, key=lambda p: (door_touches(p), p.area))

    leftover_slack = round(sum(p.area for p in pieces if p is not chosen), 2)
    if chosen.area < MIN_REAL_FOYER_SQFT:
        return None, round(remainder.area, 2)

    coords = _single_ring_with_keyholes(chosen)
    b = chosen.bounds
    label_pt = chosen.representative_point()  # guaranteed inside the TRUE shape (holes excluded), not just its bbox center
    room = {
        "room_id": f"foyer-{uuid.uuid4().hex[:8]}",
        "room_type": "FOYER",
        "display_name": "Foyer",
        "area_sqft": round(chosen.area, 2),
        "width_ft": round(b[2] - b[0], 2),  # bounding box only — true shape is geometry_points_ft, which may be non-rectangular
        "depth_ft": round(b[3] - b[1], 2),
        "origin_ft": [round(b[0], 2), round(b[1], 2)],
        "geometry_points_ft": [[round(px, 2), round(py, 2)] for px, py in coords],
        "label_point_ft": [round(label_pt.x, 2), round(label_pt.y, 2)],
        "doors": [],
        "area_basis_note": "Computed as the real contiguous leftover usable area after screens and all other "
                            "support zones were placed, not independently sized or positioned.",
    }
    return room, leftover_slack


def _place_support_zones_and_foyer(usable_poly, fallback_poly, column_polys, bbox,
                                    auditorium_rooms, auditorium_polys, requirements,
                                    franchise_tier_id=None):
    """Post-auditorium auto-layout phase: places Box Office/F&B/Washroom/BOH
    with real, connectivity-gated geometry and a single entry door each
    (see SUPPORT_ZONE_AUTO_ORDER for placement order and rationale), then
    computes Foyer as the true leftover polygon. Returns (support_rooms,
    foyer_room_or_None, leftover_slack_sqft, warnings)."""
    entry_point = requirements.get("entry_point_ft") if requirements else None
    exit_points_ft = requirements.get("exit_points_ft") if requirements else None
    overrides = requirements.get("support_zone_area_overrides_sqft", {}) if requirements else {}
    door_width_ft = rules_registry.planning_norm("SUPPORT_ZONE_DOOR_WIDTH_FT") or 3.0
    support_column_cap = rules_registry.planning_norm("SUPPORT_ZONE_MAX_ENCLOSED_COLUMN_RATIO")
    if support_column_cap is None:
        support_column_cap = 0.15

    total_aud_area = sum(p.area for p in auditorium_polys)

    placed_polys = list(auditorium_polys)
    placed_types = ["AUDITORIUM"] * len(auditorium_polys)
    placed_rooms_for_doors = list(auditorium_rooms)
    support_rooms = []
    warnings = []

    for room_type in SUPPORT_ZONE_AUTO_ORDER:
        default_entry = next((t for t in SUPPORT_ZONE_DEFAULTS if t[0] == room_type), None)
        if default_entry is None:
            continue
        _, display_name, default_target, min_area, note = default_entry
        target_area = overrides.get(room_type)
        if target_area is None:
            target_area = default_target if default_target is not None else total_aud_area * 0.08
        if target_area <= 0:
            target_area = min_area

        result, shrink_note = _place_single_support_zone_connectivity_aware(
            usable_poly, fallback_poly, column_polys, bbox, placed_polys, placed_types, placed_rooms_for_doors,
            room_type, requirements, entry_point, exit_points_ft, support_column_cap, target_area, min_area
        )
        if result is None:
            warnings.append(f"Could not fit {display_name} anywhere without blocking the common path or remaining usable space — skipped.")
            continue

        x, y, w, h, used_fallback = result
        rect = _rect(x, y, w, h)
        wall = _screen_wall_for_rect(x, y, w, h, entry_point)
        zone = {
            "room_id": f"{room_type.lower()}-{uuid.uuid4().hex[:8]}",
            "room_type": room_type,
            "display_name": display_name,
            "area_sqft": round(w * h, 2),
            "width_ft": round(w, 2),
            "depth_ft": round(h, 2),
            "origin_ft": [round(x, 2), round(y, 2)],
            "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            "label_point_ft": [round(x + w / 2, 2), round(y + h / 2, 2)],
            "area_basis_note": note,
            "doors": _door_for_support_zone(w, h, wall, door_width_ft),
        }
        if shrink_note:
            zone["shrink_note"] = shrink_note
        if used_fallback:
            enclosed_area = _enclosed_obstacle_area(rect, column_polys)
            if enclosed_area > 0:
                zone["obstacle_note"] = (
                    f"{round(enclosed_area, 1)} sqft of confirmed obstacle(s) (e.g. a structural column) fall "
                    f"inside this room's footprint — plan furniture/layout around the obstacle position(s)."
                )
        support_rooms.append(zone)
        placed_polys.append(rect)
        placed_types.append(room_type)
        placed_rooms_for_doors.append(zone)

    foyer_room, leftover_slack = _build_foyer_room(fallback_poly, placed_polys, placed_rooms_for_doors, entry_point)
    return support_rooms, foyer_room, leftover_slack, warnings


def _entry_exit_flow_segments(rooms, entry_point, exit_points_ft):
    """A real, honest "common path" indication without full pathfinding:
    Foyer's connectivity to every door is already geometrically guaranteed
    by construction (this session's connectivity-gated support-zone
    placement), so a simple two-point flow line — the marked entry point
    straight to each auditorium's own ENTRY door, and each auditorium's
    EXIT door straight to the nearest marked exit point — is a real,
    honest simplification of circulation flow, the same convention real
    CAD zoning sheets use (a dashed desire-line arrow through open floor,
    not a fully routed corridor). Reuses connectivity.door_outside_point
    for the door-side endpoint — the exact same "just outside this door,
    in real open floor space" point this session's connectivity gate
    already computes and trusts.

    Returns a list of {"from": [x, y], "to": [x, y], "kind": "ENTRY"|"EXIT"}
    dicts — empty wherever the data to draw it isn't marked (no entry
    point, no exit points, or a room with no matching door), a real,
    confirmed case on at least one live project, never a crash."""
    segments = []
    for room in rooms:
        if not room["room_type"].startswith("AUDITORIUM"):
            continue
        for door in room.get("doors", []):
            outside_pt = connectivity.door_outside_point(room, door)
            if door.get("kind") == "ENTRY" and entry_point is not None:
                segments.append({"from": [round(entry_point[0], 2), round(entry_point[1], 2)],
                                  "to": [round(outside_pt[0], 2), round(outside_pt[1], 2)], "kind": "ENTRY"})
            elif door.get("kind") == "EXIT" and exit_points_ft:
                nearest = min(exit_points_ft, key=lambda ep: (ep[0] - outside_pt[0]) ** 2 + (ep[1] - outside_pt[1]) ** 2)
                segments.append({"from": [round(outside_pt[0], 2), round(outside_pt[1], 2)],
                                  "to": [round(nearest[0], 2), round(nearest[1], 2)], "kind": "EXIT"})
    return segments


def generate_candidate(usable_poly, boundary_points_ft, strategy: str, requirements: dict, confirmed_obstacles: list = None) -> dict:
    # True boundary bbox, not usable_poly's — obstacle subtraction almost
    # never shrinks the bounding box (obstacles are interior), but computing
    # it from the actual boundary is the strictly correct, zero-risk choice
    # now that scanning may run against either of two different polygons.
    bbox = poly_from_points(boundary_points_ft).bounds
    presets = rules_registry.auditorium_presets()  # already sorted largest-first
    confirmed_obstacles = confirmed_obstacles or []

    # Column-tolerant fallback polygon + the raw column geometries — a room
    # can be placed over a confirmed COLUMN (never any other obstacle type)
    # when no column-free placement exists for it; see _scan_place_with_fallback
    # and compute_usable_area's exclude_classifications for the real-world
    # reasoning (the SOP's own hard-minimum column grid is smaller than its
    # own smallest auditorium preset, so any compliant existing building
    # already requires this in practice). This is also the polygon "usable
    # area"/circulation get accounted against below — a column is now a
    # legitimately buildable-over structural element, not floor area that's
    # unavailable the way a wall or stairwell is, so it shouldn't read as
    # permanently lost area once a room can legitimately enclose it.
    fallback_poly = compute_usable_area(boundary_points_ft, confirmed_obstacles, exclude_classifications=("COLUMN",)) if confirmed_obstacles else usable_poly
    column_polys = [poly_from_points(o["points_ft"]) for o in confirmed_obstacles
                     if isinstance(o, dict) and o.get("classification") == "COLUMN"]

    if strategy == "MAX_SEATS_PER_SCREEN":
        order = lambda p: p  # largest-first (default order)
    else:  # MAX_SCREEN_COUNT
        order = lambda p: list(reversed(p))  # smallest-first

    max_auditoriums = requirements.get("max_auditoriums", 4) if requirements else 4
    entry_point = requirements.get("entry_point_ft") if requirements else None
    exit_points_ft = requirements.get("exit_points_ft") if requirements else None
    screen_width_ft = requirements.get("screen_width_ft") if requirements else None

    auditoriums, aud_polys, aud_warnings, undersized_count = _place_auditoriums(
        usable_poly, fallback_poly, column_polys, bbox, presets, max_auditoriums, order,
        entry_point=entry_point, exit_points_ft=exit_points_ft, screen_width_ft=screen_width_ft
    )
    total_aud_area = sum(a["area_sqft"] for a in auditoriums)

    # Screens first, then Box Office/F&B/Washroom/BOH with real,
    # connectivity-gated geometry, then Foyer computed as whatever's
    # genuinely left — see _place_support_zones_and_foyer's own docstring.
    # Manual "Add Zone" (place_single_zone, above) remains available
    # afterward for the architect to add PASSAGE or adjust anything.
    franchise_tier_id = requirements.get("franchise_tier_id") if requirements else None
    support_rooms, foyer_room, leftover_slack, support_warnings = _place_support_zones_and_foyer(
        usable_poly, fallback_poly, column_polys, bbox, auditoriums, aud_polys, requirements,
        franchise_tier_id=franchise_tier_id
    )
    auditoriums = auditoriums + support_rooms + ([foyer_room] if foyer_room else [])

    # fallback_poly.area, not usable_poly.area — a room can legitimately
    # enclose a confirmed column (see fallback_poly's own comment above), so
    # the true buildable floor area for "how much is left over" purposes
    # includes it; using the strict, columns-subtracted figure here would
    # under-count real usable area and over-report circulation. Now that
    # screens and every other component are real placed rooms and Foyer is
    # the real remainder, this is genuinely small leftover slack (disjoint
    # pockets Foyer didn't claim), not "everything not yet added."
    circulation_area = leftover_slack

    total_seats = sum(a["seat_estimate"]["seat_count"] for a in auditoriums if a["room_type"].startswith("AUDITORIUM"))
    screen_count = sum(1 for a in auditoriums if a["room_type"].startswith("AUDITORIUM"))
    seats_per_screen = round(total_seats / screen_count, 2) if screen_count else 0

    notes = list(support_warnings)
    if screen_count > 0:
        notes.append(
            f"{screen_count} screen(s) placed on {round(total_aud_area):,} sqft, plus "
            f"{len(support_rooms)} support zone(s)"
            + (" and a Foyer" if foyer_room else "")
            + f". {round(circulation_area):,} sqft of leftover slack remains."
        )
    if undersized_count > 0:
        # Real, evidence-based diagnostic (not a guess) — a screen only takes
        # a smaller preset than this strategy prefers when the larger
        # footprint genuinely didn't fit (an obstacle or the floor plate's
        # own shape blocked it).
        notes.append(
            f"{undersized_count} of {screen_count} screen(s) couldn't get this strategy's preferred size — a "
            f"confirmed obstacle or the floor plate's shape blocked the larger footprint, so a smaller preset "
            f"was used instead."
        )

    # Real entry/exit-configuration advisories (spec M6 / SOP §4.4-§9) — about
    # what was marked in Requirements, independent of which zones the
    # architect later adds via Add Zone.
    if entry_point is None:
        notes.append(
            "No main entrance was marked, so screen placement used a generic scan order instead of starting "
            "from the entry side, and Add Zone's entry-facing/sightline rules (§4.4/§9) won't apply either. "
            "Mark the entrance in Requirements to enable them."
        )
    if entry_point is not None and exit_points_ft:
        min_sep = rules_registry.planning_norm("MIN_ENTRY_EXIT_SEPARATION_FT") or 15.0
        too_close = [
            i for i, ep in enumerate(exit_points_ft, start=1)
            if math.hypot(ep[0] - entry_point[0], ep[1] - entry_point[1]) < min_sep
        ]
        if too_close:
            notes.append(
                f"Exit point(s) {', '.join(str(i) for i in too_close)} are within {min_sep:.0f} ft of the marked "
                f"main entrance — the SOP requires separate entry/exit flow with no cross-movement (§4.4/§9); "
                f"consider marking a more clearly separated exit."
            )

    return {
        "candidate_id": f"generic-{strategy.lower()}-{uuid.uuid4().hex[:8]}",
        "strategy": strategy,
        "strategy_label": "Maximize Seats per Screen" if strategy == "MAX_SEATS_PER_SCREEN" else "Maximize Screen Count",
        "rooms": auditoriums,
        "circulation_area_sqft": round(circulation_area, 2),
        "usable_area_sqft": round(fallback_poly.area, 2),
        "boundary_area_sqft": round(poly_from_points(boundary_points_ft).area, 2),
        "total_seats": total_seats,
        "screen_count": screen_count,
        "seats_per_screen": seats_per_screen,
        "flow_segments": _entry_exit_flow_segments(auditoriums, entry_point, exit_points_ft),
        "warnings": aud_warnings + notes
    }


def generate_optimized_candidate(usable_poly, boundary_points_ft, requirements: dict, confirmed_obstacles: list = None,
                                  time_limit_seconds=None) -> dict:
    """The "Optimize Layout" strategy: poses auditorium placement as a real
    combinatorial optimization (placement.solver's Maximum Weight
    Independent Set formulation over a real candidate pool) instead of any
    greedy heuristic — genuinely finds the best (or best-found-within-a-
    time-limit) arrangement, not just a good one. Real, measured result on
    the benchmark file this whole placement-engine upgrade is grounded in
    (see LOG.md): the greedy auto-layout (even with backtracking) placed 3
    screens / 145 seats; this found a *provably optimal* 4 screens / 262
    seats for the same candidate pool, in well under a second.

    Deliberately NOT part of the fast, always-on generate_candidates() pair
    (MAX_SEATS_PER_SCREEN / MAX_SCREEN_COUNT) — CP-SAT can take real time
    on a hard instance (see placement.solver.TIME_LIMIT_SECONDS), so this
    is a separate, explicit, opt-in action (main.py's
    POST .../zoning-runs/optimize). Returns the exact same candidate-dict
    shape generate_candidate() does, so every downstream consumer
    (feasibility, chart, export, the frontend's candidate cards) works
    with it unchanged."""
    bbox = poly_from_points(boundary_points_ft).bounds
    presets = rules_registry.auditorium_presets()
    confirmed_obstacles = confirmed_obstacles or []

    fallback_poly = compute_usable_area(boundary_points_ft, confirmed_obstacles, exclude_classifications=("COLUMN",)) if confirmed_obstacles else usable_poly
    column_polys = [poly_from_points(o["points_ft"]) for o in confirmed_obstacles
                     if isinstance(o, dict) and o.get("classification") == "COLUMN"]

    max_auditoriums = requirements.get("max_auditoriums", 4) if requirements else 4
    entry_point = requirements.get("entry_point_ft") if requirements else None
    exit_points_ft = requirements.get("exit_points_ft") if requirements else None
    screen_width_ft = requirements.get("screen_width_ft") if requirements else None

    aud_column_cap = rules_registry.planning_norm("AUDITORIUM_MAX_ENCLOSED_COLUMN_RATIO")
    if aud_column_cap is None:
        aud_column_cap = 0.02
    aud_edge_tolerance_ft = rules_registry.planning_norm("AUDITORIUM_COLUMN_EDGE_TOLERANCE_FT")
    if aud_edge_tolerance_ft is None:
        aud_edge_tolerance_ft = 2.0
    door_width_ft = rules_registry.planning_norm("AUDITORIUM_DOOR_WIDTH_FT") or 3.5

    solve_kwargs = {}
    if time_limit_seconds is not None:
        solve_kwargs["time_limit_seconds"] = time_limit_seconds
    selected, status = solver.solve(usable_poly, fallback_poly, column_polys, bbox, presets, max_auditoriums,
                                     aud_column_cap, screen_width_ft, aud_edge_tolerance_ft=aud_edge_tolerance_ft,
                                     **solve_kwargs)

    auditoriums = []
    aud_polys = []
    for i, cand in enumerate(selected):
        room = _build_auditorium_room(cand["x"], cand["y"], cand["w"], cand["h"], i + 1, cand["preset"],
                                       cand["used_fallback"], column_polys, screen_width_ft, entry_point, door_width_ft)
        auditoriums.append(room)
        aud_polys.append(_rect(cand["x"], cand["y"], cand["w"], cand["h"]))

    total_aud_area = sum(a["area_sqft"] for a in auditoriums)

    # Same post-auditorium support-zone + Foyer-as-remainder pass
    # generate_candidate uses — see _place_support_zones_and_foyer's own
    # docstring — so the optimizer's screen layout also gets a real,
    # buildable floor plan around it, not just a circulation number.
    franchise_tier_id = requirements.get("franchise_tier_id") if requirements else None
    support_rooms, foyer_room, leftover_slack, support_warnings = _place_support_zones_and_foyer(
        usable_poly, fallback_poly, column_polys, bbox, auditoriums, aud_polys, requirements,
        franchise_tier_id=franchise_tier_id
    )
    auditoriums = auditoriums + support_rooms + ([foyer_room] if foyer_room else [])

    circulation_area = leftover_slack
    total_seats = sum(a["seat_estimate"]["seat_count"] for a in auditoriums if a["room_type"].startswith("AUDITORIUM"))
    screen_count = sum(1 for a in auditoriums if a["room_type"].startswith("AUDITORIUM"))
    seats_per_screen = round(total_seats / screen_count, 2) if screen_count else 0

    if status in ("OPTIMAL", "FEASIBLE"):
        proof = "proven optimal" if status == "OPTIMAL" else "the best found within the solver's time limit (not proven optimal — a harder instance than usual)"
        notes = list(support_warnings) + [
            f"Solved via CP-SAT combinatorial optimization over {len(selected)} selected real placement(s) — "
            f"{proof}, not a greedy heuristic. {screen_count} screen(s) placed on {round(total_aud_area):,} sqft, "
            f"plus {len(support_rooms)} support zone(s)" + (" and a Foyer" if foyer_room else "") +
            f". {round(circulation_area):,} sqft of leftover slack remains."
        ]
    elif status == "NO_CANDIDATES":
        notes = ["The optimizer found no real candidate auditorium placement anywhere in the usable area."]
    else:
        notes = [f"The optimizer could not find a solution (solver status: {status})."]

    return {
        "candidate_id": f"optimized-{uuid.uuid4().hex[:8]}",
        "strategy": "OPTIMIZED",
        "strategy_label": "Optimized (CP-SAT)",
        "rooms": auditoriums,
        "circulation_area_sqft": round(circulation_area, 2),
        "usable_area_sqft": round(fallback_poly.area, 2),
        "boundary_area_sqft": round(poly_from_points(boundary_points_ft).area, 2),
        "total_seats": total_seats,
        "screen_count": screen_count,
        "seats_per_screen": seats_per_screen,
        "flow_segments": _entry_exit_flow_segments(auditoriums, entry_point, exit_points_ft),
        "warnings": notes
    }


def estimate_column_grid_spacing(confirmed_column_point_lists, cluster_tolerance_ft=1.0):
    """Estimates the structural column grid spacing (the VR_COLUMN_GRID_WIDTH/
    LENGTH_EXISTING viability rules' metric) from confirmed COLUMN obstacle
    positions — real, computed from the CAD data, not a guess.

    Method: cluster column centroids into distinct grid lines along X and along
    Y (columns whose coordinate is within `cluster_tolerance_ft` are treated as
    the same line — real column grids are regular but rarely pixel-exact), then
    take the SMALLEST gap between adjacent lines in each axis. That's the
    conservative choice: the viability rule cares whether the *tightest* bay in
    the building would fit an auditorium, not the average.

    The smaller of the two axis spacings is reported as "width" and the larger
    as "length" — matching the SOP's own numbers (width 20-22ft < length
    30-35ft), since true building orientation isn't otherwise known. This is an
    explicit, documented convention, not a claim of certainty about which way
    the building actually faces.

    Returns (width_ft, length_ft) or (None, None) if there aren't at least 2
    distinct grid lines in both axes to measure a gap from (e.g. 0 or 1 column,
    or all columns collinear) — never fabricates a spacing from insufficient data.
    """
    if not confirmed_column_point_lists or len(confirmed_column_point_lists) < 2:
        return None, None

    centroids = []
    for pts in confirmed_column_point_lists:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        centroids.append((cx, cy))

    def cluster_axis(values):
        values = sorted(values)
        lines = [values[0]]
        for v in values[1:]:
            if v - lines[-1] > cluster_tolerance_ft:
                lines.append(v)
        return lines

    x_lines = cluster_axis([c[0] for c in centroids])
    y_lines = cluster_axis([c[1] for c in centroids])

    x_gaps = [x_lines[i + 1] - x_lines[i] for i in range(len(x_lines) - 1)]
    y_gaps = [y_lines[i + 1] - y_lines[i] for i in range(len(y_lines) - 1)]

    if not x_gaps or not y_gaps:
        return None, None

    spacings = sorted([min(x_gaps), min(y_gaps)])
    return round(spacings[0], 2), round(spacings[1], 2)


def validate_rooms(boundary_points_ft, confirmed_obstacles, rooms: list) -> dict:
    """Real geometric validation for architect-edited layouts (spec Sec 38/61
    'geometry tests': overlap, containment, obstacle avoidance). Returns per-room
    errors — never silently accepts an invalid edit.

    confirmed_obstacles: list of {"points_ft":..., "classification":...} dicts
    (or bare point-lists, treated as classification-less), matching
    compute_usable_area's interface. A room overlapping a confirmed COLUMN is
    only a warning — an architect manually placing a room over a column is
    allowed, same as the auto-layout's own two-tier placement (see
    generate_candidate) — everything else (wall/stair/washroom/door/window/
    furniture/unclassified) stays a hard OBSTACLE_COLLISION error."""
    boundary = poly_from_points(boundary_points_ft)
    hard_obstacles, column_obstacles = [], []
    for o in (confirmed_obstacles or []):
        pts, classification = (o.get("points_ft"), o.get("classification")) if isinstance(o, dict) else (o, None)
        (column_obstacles if classification == "COLUMN" else hard_obstacles).append(poly_from_points(pts))

    errors = []
    warnings = []
    room_polys = {}
    for room in rooms:
        try:
            poly = poly_from_points(room["geometry_points_ft"])
        except Exception:
            errors.append({"room_id": room.get("room_id"), "issue": "INVALID_GEOMETRY", "message": "Room geometry could not be parsed as a polygon."})
            continue
        room_polys[room["room_id"]] = poly

        outside_area = poly.difference(boundary).area
        if outside_area > 0.5:
            errors.append({"room_id": room["room_id"], "issue": "OUTSIDE_BOUNDARY",
                            "message": f"{room['display_name']} extends {round(outside_area,1)} sqft outside the floor boundary."})

        for obs in hard_obstacles:
            inter = poly.intersection(obs).area
            if inter > 0.5:
                errors.append({"room_id": room["room_id"], "issue": "OBSTACLE_COLLISION",
                                "message": f"{room['display_name']} overlaps a confirmed structural obstacle by {round(inter,1)} sqft."})

        for obs in column_obstacles:
            inter = poly.intersection(obs).area
            if inter > 0.5:
                warnings.append({"room_id": room["room_id"], "issue": "ENCLOSES_COLUMN",
                                  "message": f"{room['display_name']} encloses a confirmed structural column ({round(inter,1)} sqft) — allowed, but verify furniture/seat layout around it."})

    ids = list(room_polys.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            inter = room_polys[ids[i]].intersection(room_polys[ids[j]]).area
            if inter > 0.5:
                r1 = next(r for r in rooms if r["room_id"] == ids[i])
                r2 = next(r for r in rooms if r["room_id"] == ids[j])
                errors.append({"room_id": ids[i], "issue": "ROOM_OVERLAP",
                                "message": f"{r1['display_name']} overlaps {r2['display_name']} by {round(inter,1)} sqft."})

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def generate_candidates(boundary_points_ft, confirmed_obstacles, requirements: dict) -> list:
    """confirmed_obstacles: list of {"points_ft":..., "classification":...}
    dicts (cad_extraction.py already attaches classification to every
    obstacle) — or bare point-lists for backward compatibility."""
    usable_poly = compute_usable_area(boundary_points_ft, confirmed_obstacles)
    if usable_poly.is_empty or usable_poly.area <= 0:
        return []
    return [
        generate_candidate(usable_poly, boundary_points_ft, "MAX_SEATS_PER_SCREEN", requirements, confirmed_obstacles),
        generate_candidate(usable_poly, boundary_points_ft, "MAX_SCREEN_COUNT", requirements, confirmed_obstacles)
    ]
