"""
Generic auto-layout generator (spec Sec 7.2 / Sec 8.5): places auditoriums and
support zones inside an arbitrary usable-area polygon, avoiding confirmed
obstacles, without any per-project hardcoding.

Algorithm (the staged greedy packer spec Sec 7.2 explicitly recommends for v1,
rather than a full constraint solver):
  1. Subtract confirmed obstacles (+ a clearance buffer) from the boundary to get
     the usable area.
  2. Scan-and-fit: try candidate rectangle placements on a grid across the usable
     area's bounding box, in a fixed deterministic order, and take the first
     position where the rectangle is fully contained in the remaining usable area
     and does not overlap anything already placed (+ an aisle clearance). This is
     a standard first-fit rectangle-packing heuristic — not optimal, but real,
     deterministic (same input -> same output, per the project's reproducibility
     requirement), and honest about not fitting something that doesn't fit.
  3. Auditoriums are placed first, trying the largest AuditoriumPreset that still
     fits at each step (this is what operationalizes "maximize total seat count").
  4. Whatever remains is carved into support zones (foyer/F&B/washroom/box
     office/back-of-house) against target areas, shrinking to whatever actually
     fits rather than inventing space. True leftover becomes circulation.

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

GRID_STEP_FT = 2.0
AISLE_CLEARANCE_FT = 3.5   # matches CENTRAL_AISLE_MIN_FT — used generically as the minimum gap between placed zones
OBSTACLE_BUFFER_FT = 0.5
MAX_SCAN_CELLS = 40000     # see _grid_step_for_bbox — real crash found via real testing, not a hypothetical

# TARGET_CIRCULATION_RATIO/SUPPORT_ZONE_MAX_SCALE moved into
# rules_registry_v1.json (SUPPORT_ZONE_CIRCULATION_RESERVE_RATIO /
# SUPPORT_ZONE_MAX_GROWTH_FACTOR planning_norms) so they're versioned and
# carry an honest ENGINEERING_ASSUMPTION/REQUIRES_APPROVAL status like every
# other business number here, per Product Principle #2 ("config over code")
# — read via rules_registry.planning_norm() at the two call sites below
# instead of being bare module constants.
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
    ("BOH", "Back-of-House (Electrical / Server / Store)", 90.0, 60.0, "ENGINEERING_ASSUMPTION — SOP lists these as required foyer sub-functions but gives no area figures")
]


def poly_from_points(points_ft):
    p = Polygon(points_ft)
    return p if p.is_valid else p.buffer(0)


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
    _place_support_zones below, since a room is allowed to be placed over a
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


def _scan_place(usable_poly, placed_polys, w, h, bbox, allow_rotate=True):
    """First-fit deterministic scan: returns (x, y, w_used, h_used) of the first
    valid placement, or None. Tries both orientations if allow_rotate."""
    minx, miny, maxx, maxy = bbox
    step = _grid_step_for_bbox(bbox)
    orientations = [(w, h)]
    if allow_rotate and abs(w - h) > 1e-6:
        orientations.append((h, w))

    y = miny
    while y + min(h, w) <= maxy:
        x = minx
        while x + min(h, w) <= maxx:
            for ow, oh in orientations:
                if x + ow > maxx or y + oh > maxy:
                    continue
                cand = _rect(x, y, ow, oh)
                if not usable_poly.contains(cand.buffer(-0.01)):
                    continue
                clearance = cand.buffer(AISLE_CLEARANCE_FT / 2)
                if any(clearance.intersects(p) for p in placed_polys):
                    continue
                return x, y, ow, oh
            x += step
        y += step
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


def _scan_place_best(usable_poly, placed_polys, w, h, bbox, allow_rotate=True, score_fn=None, prefer_fn=None, max_candidates=80):
    """Same first-fit grid scan as _scan_place, but collects up to
    max_candidates valid positions instead of stopping at the first one, so a
    placement can be chosen for *where* it sits, not just *that* it fits.
    prefer_fn is a soft constraint (e.g. "has a sightline from the entry") —
    placement still succeeds using the unfiltered candidates if none satisfy
    it, per Product Principle #7 (never silently invent a placement that
    contradicts real geometry, but never silently drop a room either)."""
    minx, miny, maxx, maxy = bbox
    step = _grid_step_for_bbox(bbox)
    orientations = [(w, h)]
    if allow_rotate and abs(w - h) > 1e-6:
        orientations.append((h, w))

    candidates = []
    y = miny
    while y + min(h, w) <= maxy and len(candidates) < max_candidates:
        x = minx
        while x + min(h, w) <= maxx and len(candidates) < max_candidates:
            for ow, oh in orientations:
                if x + ow > maxx or y + oh > maxy:
                    continue
                cand = _rect(x, y, ow, oh)
                if not usable_poly.contains(cand.buffer(-0.01)):
                    continue
                clearance = cand.buffer(AISLE_CLEARANCE_FT / 2)
                if any(clearance.intersects(p) for p in placed_polys):
                    continue
                candidates.append((x, y, ow, oh))
                if len(candidates) >= max_candidates:
                    break
            x += step
        y += step

    if not candidates:
        return None, False
    if score_fn is None and prefer_fn is None:
        return candidates[0], False

    pool = candidates
    satisfied_preference = False
    if prefer_fn:
        preferred = [c for c in candidates if prefer_fn(c)]
        if preferred:
            pool = preferred
            satisfied_preference = True

    best = min(pool, key=score_fn) if score_fn else pool[0]
    return best, satisfied_preference


def _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, w, h, bbox, allow_rotate=True):
    """Try the strict (all-obstacles-subtracted) polygon first — a column-free
    placement is always preferred when one exists, this changes nothing about
    today's behavior in that case. Only if that fails does it retry against
    fallback_poly (obstacles minus COLUMN — see compute_usable_area), which
    allows the rectangle to cover a confirmed structural column but nothing
    else. Returns (placement_or_None, used_fallback: bool)."""
    result = _scan_place(usable_poly, placed_polys, w, h, bbox, allow_rotate)
    if result:
        return result, False
    if fallback_poly is not None and fallback_poly is not usable_poly:
        result = _scan_place(fallback_poly, placed_polys, w, h, bbox, allow_rotate)
        if result:
            return result, True
    return None, False


def _scan_place_best_with_fallback(usable_poly, fallback_poly, placed_polys, w, h, bbox, allow_rotate=True,
                                    score_fn=None, prefer_fn=None, max_candidates=80):
    """Same strict-then-column-tolerant retry as _scan_place_with_fallback,
    for the score_fn/prefer_fn-driven placements (foyer-near-entry etc)."""
    best, satisfied = _scan_place_best(usable_poly, placed_polys, w, h, bbox, allow_rotate, score_fn, prefer_fn, max_candidates)
    if best:
        return best, satisfied, False
    if fallback_poly is not None and fallback_poly is not usable_poly:
        best, satisfied = _scan_place_best(fallback_poly, placed_polys, w, h, bbox, allow_rotate, score_fn, prefer_fn, max_candidates)
        if best:
            return best, satisfied, True
    return None, False, False


def _enclosed_obstacle_area(rect, column_polys):
    """How much of rect's own area is covered by confirmed COLUMN obstacles —
    used to honestly discount a seat estimate and to flag which rooms need
    the enclosed-obstacle note, only meaningful when a placement actually
    used the column-tolerant fallback tier above."""
    if not column_polys:
        return 0.0
    return sum(rect.intersection(cp).area for cp in column_polys)


def _place_auditoriums(usable_poly, fallback_poly, column_polys, bbox, presets, max_count, preset_order,
                        entry_point=None, exit_points_ft=None):
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
    # against support zones placed afterward in _place_support_zones).
    flip_x, flip_y = _entry_exit_scan_flip(bbox, entry_point, exit_points_ft)
    scan_usable = _mirror_for_scan(usable_poly, bbox, flip_x, flip_y)
    scan_fallback = _mirror_for_scan(fallback_poly, bbox, flip_x, flip_y)
    scan_placed_polys = []      # mirrored-space, used only for the scan's own collision checks

    for _ in range(max_count):
        placement = None
        used_preset = None
        ordered_presets = preset_order(presets)
        for preset in ordered_presets:
            # Try the preset's largest allowed footprint first (falls back to
            # its own min axis when a max isn't declared for that axis — e.g.
            # 60_SEAT/90_SEAT only declare a max on one axis) — this is what
            # actually uses the space a preset is allowed to occupy instead of
            # always taking its smallest legal footprint, directly increasing
            # both seats (the locked v1 objective) and area utilization.
            w_max = preset.get("width_max_ft", preset["width_min_ft"])
            h_max = preset.get("length_max_ft", preset["length_min_ft"])
            result, used_fallback = _scan_place_with_fallback(scan_usable, scan_fallback, scan_placed_polys, w_max, h_max, bbox)
            if not result and (w_max, h_max) != (preset["width_min_ft"], preset["length_min_ft"]):
                result, used_fallback = _scan_place_with_fallback(scan_usable, scan_fallback, scan_placed_polys, preset["width_min_ft"], preset["length_min_ft"], bbox)
            if result:
                placement = result
                used_preset = preset
                break
        if not placement:
            warnings.append(f"Could not fit another auditorium after placing {len(placed)} — no remaining preset fits available usable space.")
            break

        if used_preset is not ordered_presets[0]:
            undersized_count += 1

        sx, sy, w, h = placement
        scan_placed_polys.append(_rect(sx, sy, w, h))
        x, y = _unmirror_rect(sx, sy, w, h, bbox, flip_x, flip_y)
        rect = _rect(x, y, w, h)
        placed_polys.append(rect)
        # used_fallback means no column-free placement existed for this
        # preset tier at this step — the winning rect is allowed to cover a
        # confirmed structural column (never any other obstacle type; see
        # compute_usable_area's exclude_classifications), same as a real
        # architect designing an auditorium around an existing column in a
        # retrofit building. Seat count is discounted honestly, not
        # optimistically ignored — see seat_engine.estimate_seats.
        enclosed_area = _enclosed_obstacle_area(rect, column_polys) if used_fallback else 0.0
        seat_est = seat_engine.estimate_seats(w, h, enclosed_obstacle_area_sqft=enclosed_area)
        room = {
            "room_id": f"auditorium-{uuid.uuid4().hex[:8]}",
            "room_type": f"AUDITORIUM_{len(placed) + 1}",
            "display_name": f"Screen {len(placed) + 1} (Auditorium)",
            "preset_id": used_preset["id"],
            "preset_name": used_preset["name"],
            "area_sqft": round(w * h, 2),
            "width_ft": round(w, 2),
            "depth_ft": round(h, 2),
            "origin_ft": [round(x, 2), round(y, 2)],
            "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            "seat_estimate": seat_est
        }
        if seat_est.get("note"):
            room["obstacle_note"] = seat_est["note"]
        placed.append(room)

    return placed, placed_polys, warnings, undersized_count


def _place_support_zones(usable_poly, fallback_poly, column_polys, placed_polys, bbox, total_auditorium_area, franchise_tier_id, requirements):
    zones = []
    warnings = []

    tier = rules_registry.franchise_tier(franchise_tier_id) if franchise_tier_id else None
    foyer_target = None
    if tier and tier.get("foyer_to_screen_ratio"):
        try:
            foyer_pct, screen_pct = [float(x) for x in tier["foyer_to_screen_ratio"].split(":")]
            foyer_target = total_auditorium_area * (foyer_pct / screen_pct)
        except Exception:
            foyer_target = None
    if foyer_target is None:
        foyer_target = total_auditorium_area * 0.30

    overrides = requirements.get("support_zone_area_overrides_sqft", {}) if requirements else {}

    targets = []
    for room_type, display_name, default_target, min_area, note in SUPPORT_ZONE_DEFAULTS:
        target = overrides.get(room_type)
        if target is None:
            target = foyer_target if room_type == "FOYER" else (
                default_target if default_target is not None else total_auditorium_area * 0.08
            )
        targets.append((room_type, display_name, target, min_area, note))

    # Scale zone targets up to use real leftover space instead of letting it
    # silently vanish into "circulation" — never shrinks a target below its
    # formulaic value, and capped at SUPPORT_ZONE_MAX_GROWTH_FACTOR (versioned
    # in rules_registry_v1.json) so no single zone balloons past what's
    # plausible.
    # fallback_poly (columns not subtracted), not usable_poly (strict) — a
    # column is now legitimately buildable-over, so the "how much floor is
    # really left for support zones" accounting should include it too,
    # consistent with generate_candidate's own usable_area_sqft below.
    remaining_area = max(fallback_poly.area - total_auditorium_area, 0.0)
    base_targets_sum = sum(t for _, _, t, _, _ in targets)
    if base_targets_sum > 0:
        circulation_reserve_ratio = rules_registry.planning_norm("SUPPORT_ZONE_CIRCULATION_RESERVE_RATIO")
        max_growth_factor = rules_registry.planning_norm("SUPPORT_ZONE_MAX_GROWTH_FACTOR")
        reserved_circulation = fallback_poly.area * circulation_reserve_ratio
        scalable_budget = max(remaining_area - reserved_circulation, 0.0)
        scale = min(max(scalable_budget / base_targets_sum, 1.0), max_growth_factor)
        if scale > 1.01:
            targets = [(rt, dn, t * scale, ma, note) for rt, dn, t, ma, note in targets]

    # Real entry point marked by the architect (spec M6 / SOP §4.4-§9): "Foyer
    # (at main entry level)", "F&B: visible from entry", "Washrooms: ... not
    # directly visible from foyer". Nothing in CAD extraction detects doors,
    # so this is only applied when the architect actually marked one —
    # skipped, with an honest note, rather than guessed at, otherwise.
    entry_point = requirements.get("entry_point_ft") if requirements else None
    exit_points_ft = requirements.get("exit_points_ft") if requirements else None
    foyer_rect = None
    if entry_point is None:
        warnings.append(
            "No main entrance was marked, so Foyer/Box Office were placed using a generic "
            "perimeter preference and F&B/Washroom used plain first-fit packing — the SOP's "
            "entry-facing/sightline rules (§4.4/§9) were not applied. Mark the entrance in "
            "Requirements to enable them."
        )

    # SOP planning norm SEPARATE_ENTRY_EXIT_FLOW ("no cross-movement between
    # entry/exit flows") is qualitative and this engine does no real
    # circulation-path routing, so it can't be checked exactly — but a
    # marked exit sitting right on top of the entrance is a real, honest
    # proxy signal that the two flows clearly aren't separated, worth
    # surfacing rather than silently ignoring just because it can't be
    # checked precisely. MIN_ENTRY_EXIT_SEPARATION_FT is this engine's own
    # straight-line substitute threshold (ENGINEERING_ASSUMPTION, not an
    # SOP-stated distance) — a warning, never a hard block, same as every
    # other soft constraint in this function.
    if entry_point is not None and exit_points_ft:
        min_sep = rules_registry.planning_norm("MIN_ENTRY_EXIT_SEPARATION_FT") or 15.0
        too_close = [
            i for i, ep in enumerate(exit_points_ft, start=1)
            if math.hypot(ep[0] - entry_point[0], ep[1] - entry_point[1]) < min_sep
        ]
        if too_close:
            warnings.append(
                f"Exit point(s) {', '.join(str(i) for i in too_close)} are within {min_sep:.0f} ft of the marked "
                f"main entrance — the SOP requires separate entry/exit flow with no cross-movement (§4.4/§9); "
                f"consider marking a more clearly separated exit."
            )

    for room_type, display_name, target_area, min_area, note in targets:
        if target_area <= 0:
            # Real, reproducible crash found via brutal testing: a region too
            # small/oddly-shaped to fit even the smallest auditorium preset
            # leaves total_auditorium_area at 0, every support-zone target
            # derived from it also becomes 0, and w = sqrt(0) = 0 made the
            # next line's target_area / w a bare division by zero — an
            # unhandled 500 on every zoning run against that region instead
            # of an honest "couldn't fit anything here."
            warnings.append(
                f"Skipped {display_name} — its target area is 0 sqft because no auditorium "
                f"could be placed in this region to size support zones against."
            )
            continue
        aspect = 1.6
        w = math.sqrt(target_area * aspect)
        h = target_area / w

        score_fn = prefer_fn = None
        if entry_point is not None:
            if room_type in ("FOYER", "BOX_OFFICE"):
                # "Foyer (at main entry level)" — closest available position to the
                # entrance. Box office/ticketing next to the entrance is the same
                # standard cinema-layout convention, not previously entry-aware here.
                score_fn = lambda c: (_rect(*c).centroid.x - entry_point[0]) ** 2 + (_rect(*c).centroid.y - entry_point[1]) ** 2
            elif room_type == "FNB":
                # "F&B: visible from entry" — the foyer itself is deliberately excluded from
                # what counts as "blocking" this: the foyer is the entry transition space by
                # design, sits between the literal entry point and everything else, and a
                # first version of this check (that didn't exclude it) found the foyer
                # blocking its own "visible from entry" requirement on every real test —
                # the SOP's intent is "visible once you're in from the entry/foyer area",
                # not an unobstructed line through where the foyer itself stands.
                blockers = [p for p in placed_polys if p is not foyer_rect]
                prefer_fn = lambda c: _has_sightline(usable_poly, blockers, entry_point, _rect(*c))
            elif room_type == "WASHROOM":
                # "Washrooms: ... not directly visible from foyer" — sightline from the
                # foyer's centroid if one was placed, otherwise falls back to generic
                # placement (this specific rule is meaningless with no foyer to be hidden
                # from). The foyer itself is excluded from the blocking set here too — a
                # sightline starting at the foyer's own centroid trivially "intersects" the
                # foyer polygon it starts inside of, which would make every placement look
                # hidden regardless of real geometry.
                if foyer_rect is not None:
                    foyer_centroid = (foyer_rect.centroid.x, foyer_rect.centroid.y)
                    blockers = [p for p in placed_polys if p is not foyer_rect]
                    prefer_fn = lambda c: not _has_sightline(usable_poly, blockers, foyer_centroid, _rect(*c))
            elif room_type == "BOH":
                # Back-of-house (electrical/server/store) is staff-only —
                # never part of the patron entry/exit flow at all, so unlike
                # Foyer/F&B/Box Office it should sit as FAR as possible from
                # both the entrance and every marked exit, the same "keep
                # it out of the public circulation path" call a real
                # architect makes, not just wherever first-fit lands it.
                ref_points = [entry_point] + list(exit_points_ft or [])
                score_fn = lambda c: -min(
                    (_rect(*c).centroid.x - rx) ** 2 + (_rect(*c).centroid.y - ry) ** 2
                    for rx, ry in ref_points
                )
        elif room_type in ("FOYER", "BOX_OFFICE"):
            # No entrance marked: fall back to a generic-but-real geometric
            # heuristic instead of arbitrary first-fit — prefer a placement
            # touching the boundary's own perimeter, since a foyer/box-office
            # is essentially always at the building's frontage in real cinema
            # design (see _exterior_lines for why this isn't a bare
            # usable_poly.exterior). Falls back to the best available fit if
            # nothing touches the perimeter, same soft-constraint semantics
            # as the entry-aware rules above.
            perimeter = _exterior_lines(fallback_poly)
            prefer_fn = lambda c: _rect(*c).distance(perimeter) < PERIMETER_TOUCH_TOLERANCE_FT

        used_fallback = False
        if score_fn or prefer_fn:
            best, satisfied, used_fallback = _scan_place_best_with_fallback(usable_poly, fallback_poly, placed_polys, w, h, bbox, score_fn=score_fn, prefer_fn=prefer_fn)
            placement = best
            if placement and prefer_fn and not satisfied:
                if room_type == "FNB":
                    rule_desc = "a sightline from the entry"
                elif room_type == "WASHROOM":
                    rule_desc = "no direct sightline from the foyer"
                else:
                    rule_desc = "a position touching the building's perimeter/frontage"
                warnings.append(f"{display_name} placed, but no available position gave it {rule_desc} — used the best fit available instead.")
        else:
            placement, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, w, h, bbox)

        shrink_note = None
        if not placement:
            # Try shrinking toward the minimum before giving up — never invent space that isn't there.
            # Sightline/entry preferences are dropped once shrinking — a smaller-than-target
            # room that actually fits beats a correctly-placed room that doesn't exist.
            for factor in (0.75, 0.5, 0.35):
                w2 = math.sqrt(target_area * factor * aspect)
                h2 = (target_area * factor) / w2
                if w2 * h2 < min_area:
                    break
                placement, used_fallback = _scan_place_with_fallback(usable_poly, fallback_poly, placed_polys, w2, h2, bbox)
                if placement:
                    shrink_note = f"Shrunk from target {round(target_area,1)} sqft to fit available space ({round(w2*h2,1)} sqft, {int(factor*100)}% of target)."
                    break

        if not placement:
            warnings.append(f"Could not place {display_name} (target {round(target_area,1)} sqft) — insufficient remaining usable area. {note}")
            continue

        x, y, w, h = placement
        rect = _rect(x, y, w, h)
        if room_type == "FOYER":
            foyer_rect = rect
        placed_polys.append(rect)
        zone = {
            "room_id": f"{room_type.lower()}-{uuid.uuid4().hex[:8]}",
            "room_type": room_type,
            "display_name": display_name,
            "area_sqft": round(w * h, 2),
            "width_ft": round(w, 2),
            "depth_ft": round(h, 2),
            "origin_ft": [round(x, 2), round(y, 2)],
            "geometry_points_ft": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
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
        zones.append(zone)

    return zones, warnings


def generate_candidate(usable_poly, boundary_points_ft, strategy: str, requirements: dict, confirmed_obstacles: list = None) -> dict:
    # True boundary bbox, not usable_poly's — obstacle subtraction almost
    # never shrinks the bounding box (obstacles are interior), but computing
    # it from the actual boundary is the strictly correct, zero-risk choice
    # now that scanning may run against either of two different polygons.
    bbox = poly_from_points(boundary_points_ft).bounds
    presets = rules_registry.auditorium_presets()  # already sorted largest-first
    confirmed_obstacles = confirmed_obstacles or []
    obstacle_count = len(confirmed_obstacles)

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

    auditoriums, aud_polys, aud_warnings, undersized_count = _place_auditoriums(
        usable_poly, fallback_poly, column_polys, bbox, presets, max_auditoriums, order,
        entry_point=entry_point, exit_points_ft=exit_points_ft
    )
    total_aud_area = sum(a["area_sqft"] for a in auditoriums)

    support_zones, support_warnings = _place_support_zones(
        usable_poly, fallback_poly, column_polys, aud_polys, bbox, total_aud_area,
        requirements.get("franchise_tier_id") if requirements else None,
        requirements or {}
    )

    # aud_polys is the same list object passed into _place_support_zones as its
    # placed_polys param, which appends each support zone's rect to it in place
    # (needed internally so later zones see earlier ones for clearance checks) —
    # by this point it already holds every auditorium AND every support zone.
    # A previous version of this line re-added the support zones a second time
    # via a fresh list comprehension, silently double-counting their area and
    # under-reporting circulation_area_sqft (the number shown to the architect
    # and used in the exported Area & Seat Chart's "EXIT PASSAGE" row) — found
    # via real testing while verifying the utilization fixes above.
    # fallback_poly.area, not usable_poly.area — a room can now legitimately
    # enclose a confirmed column (see fallback_poly's own comment above), so
    # the true buildable floor area for "how much is left over" purposes
    # includes it; using the strict, columns-subtracted figure here would
    # under-count real usable area and over-report circulation.
    allocated_area = sum(p.area for p in aud_polys)
    circulation_area = max(fallback_poly.area - allocated_area, 0.0)

    total_seats = sum(a["seat_estimate"]["seat_count"] for a in auditoriums)
    screen_count = len(auditoriums)
    seats_per_screen = round(total_seats / screen_count, 2) if screen_count else 0

    utilization_warnings = []
    if fallback_poly.area > 0:
        circulation_ratio = circulation_area / fallback_poly.area
        # Real leftover space is expected (real aisles/back-of-house gaps/odd
        # corners a rectangle-packer can't reach) — this is a health check,
        # not a hard limit: never blocks a run, just makes an unusually large
        # unused chunk visible instead of silently calling it "circulation"
        # with no explanation. 30% has no SOP source; it's set from what a
        # well-packed real floor plate looks like after the fixes above.
        if circulation_ratio > 0.30:
            # Evidence-based cause, not a guess — found via real testing that the
            # generic "leftover pockets / raise Max Auditoriums" explanation was
            # actively misleading on a floor with a real structural column grid
            # (confirmed via isolation test: excluding columns took utilization
            # from 30% to 72% on the same floor) — telling someone to raise Max
            # Auditoriums there would have sent them chasing the wrong fix.
            cause_hints = []
            if undersized_count > 0:
                cause_hints.append(
                    f"{undersized_count} of {screen_count} auditorium(s) couldn't get this strategy's preferred "
                    f"preset size because a confirmed obstacle (e.g. a structural column) blocked the larger "
                    f"footprint, so they used a smaller preset instead"
                )
            if obstacle_count > 15:
                cause_hints.append(
                    f"{obstacle_count} confirmed obstacles on this floor (columns/walls/etc.) fragment the open "
                    f"area — a rectangle-based packer can't route a large room around interior columns the way "
                    f"an architect designing around the real structural grid would"
                )
            if not cause_hints:
                cause_hints.append(
                    f"likely leftover pockets too small or oddly shaped for any remaining room to fit, or the "
                    f"{max_auditoriums}-auditorium limit in Requirements leaving more floor than that many screens "
                    f"plus support zones need — consider raising Max Auditoriums, or check the floor plan for "
                    f"irregular leftover regions"
                )
            utilization_warnings.append(
                f"{round(circulation_ratio * 100)}% of the usable area ({round(circulation_area):,} sqft) ended up "
                f"unallocated — " + "; and ".join(cause_hints) + "."
            )

    return {
        "candidate_id": f"generic-{strategy.lower()}-{uuid.uuid4().hex[:8]}",
        "strategy": strategy,
        "strategy_label": "Maximize Seats per Screen" if strategy == "MAX_SEATS_PER_SCREEN" else "Maximize Screen Count",
        "rooms": auditoriums + support_zones,
        "circulation_area_sqft": round(circulation_area, 2),
        "usable_area_sqft": round(fallback_poly.area, 2),
        "boundary_area_sqft": round(poly_from_points(boundary_points_ft).area, 2),
        "total_seats": total_seats,
        "screen_count": screen_count,
        "seats_per_screen": seats_per_screen,
        "warnings": aud_warnings + support_warnings + utilization_warnings
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
