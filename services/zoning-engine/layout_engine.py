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

import rules_registry
import seat_engine

GRID_STEP_FT = 2.0
AISLE_CLEARANCE_FT = 3.5   # matches CENTRAL_AISLE_MIN_FT — used generically as the minimum gap between placed zones
OBSTACLE_BUFFER_FT = 0.5
MAX_SCAN_CELLS = 40000     # see _grid_step_for_bbox — real crash found via real testing, not a hypothetical


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


def compute_usable_area(boundary_points_ft, confirmed_obstacle_point_lists):
    boundary = poly_from_points(boundary_points_ft)
    if not confirmed_obstacle_point_lists:
        return boundary
    obstacles = [poly_from_points(p).buffer(OBSTACLE_BUFFER_FT) for p in confirmed_obstacle_point_lists]
    obstacle_union = unary_union(obstacles)
    usable = boundary.difference(obstacle_union)
    return usable if not usable.is_empty else boundary


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


def _place_auditoriums(usable_poly, bbox, presets, max_count, preset_order):
    placed = []
    placed_polys = []
    warnings = []

    for _ in range(max_count):
        placement = None
        used_preset = None
        for preset in preset_order(presets):
            w, h = preset["width_min_ft"], preset["length_min_ft"]
            result = _scan_place(usable_poly, placed_polys, w, h, bbox)
            if result:
                placement = result
                used_preset = preset
                break
        if not placement:
            warnings.append(f"Could not fit another auditorium after placing {len(placed)} — no remaining preset fits available usable space.")
            break

        x, y, w, h = placement
        rect = _rect(x, y, w, h)
        placed_polys.append(rect)
        seat_est = seat_engine.estimate_seats(w, h)
        placed.append({
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
        })

    return placed, placed_polys, warnings


def _place_support_zones(usable_poly, placed_polys, bbox, total_auditorium_area, franchise_tier_id, requirements):
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

    # Real entry point marked by the architect (spec M6 / SOP §4.4-§9): "Foyer
    # (at main entry level)", "F&B: visible from entry", "Washrooms: ... not
    # directly visible from foyer". Nothing in CAD extraction detects doors,
    # so this is only applied when the architect actually marked one —
    # skipped, with an honest note, rather than guessed at, otherwise.
    entry_point = requirements.get("entry_point_ft") if requirements else None
    foyer_rect = None
    if entry_point is None:
        warnings.append(
            "No main entrance was marked, so Foyer/F&B/Washroom placement used generic "
            "first-fit packing only — the SOP's entry-facing/sightline rules (§4.4/§9) "
            "were not applied. Mark the entrance in Requirements to enable them."
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
            if room_type == "FOYER":
                # "Foyer (at main entry level)" — closest available position to the entrance.
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

        if score_fn or prefer_fn:
            best, satisfied = _scan_place_best(usable_poly, placed_polys, w, h, bbox, score_fn=score_fn, prefer_fn=prefer_fn)
            placement = best
            if placement and prefer_fn and not satisfied:
                rule_desc = "a sightline from the entry" if room_type == "FNB" else "no direct sightline from the foyer"
                warnings.append(f"{display_name} placed, but no available position gave it {rule_desc} — used the best fit available instead.")
        else:
            placement = _scan_place(usable_poly, placed_polys, w, h, bbox)

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
                placement = _scan_place(usable_poly, placed_polys, w2, h2, bbox)
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
        zones.append(zone)

    return zones, warnings


def generate_candidate(usable_poly, boundary_points_ft, strategy: str, requirements: dict) -> dict:
    bbox = usable_poly.bounds
    presets = rules_registry.auditorium_presets()  # already sorted largest-first

    if strategy == "MAX_SEATS_PER_SCREEN":
        order = lambda p: p  # largest-first (default order)
    else:  # MAX_SCREEN_COUNT
        order = lambda p: list(reversed(p))  # smallest-first

    max_auditoriums = requirements.get("max_auditoriums", 4) if requirements else 4

    auditoriums, aud_polys, aud_warnings = _place_auditoriums(usable_poly, bbox, presets, max_auditoriums, order)
    total_aud_area = sum(a["area_sqft"] for a in auditoriums)

    support_zones, support_warnings = _place_support_zones(
        usable_poly, aud_polys, bbox, total_aud_area,
        requirements.get("franchise_tier_id") if requirements else None,
        requirements or {}
    )

    all_placed_polys = aud_polys + [box(*_rect(z["origin_ft"][0], z["origin_ft"][1], z["width_ft"], z["depth_ft"]).bounds) for z in support_zones]
    allocated_area = sum(p.area for p in all_placed_polys)
    circulation_area = max(usable_poly.area - allocated_area, 0.0)

    total_seats = sum(a["seat_estimate"]["seat_count"] for a in auditoriums)
    screen_count = len(auditoriums)
    seats_per_screen = round(total_seats / screen_count, 2) if screen_count else 0

    return {
        "candidate_id": f"generic-{strategy.lower()}-{uuid.uuid4().hex[:8]}",
        "strategy": strategy,
        "strategy_label": "Maximize Seats per Screen" if strategy == "MAX_SEATS_PER_SCREEN" else "Maximize Screen Count",
        "rooms": auditoriums + support_zones,
        "circulation_area_sqft": round(circulation_area, 2),
        "usable_area_sqft": round(usable_poly.area, 2),
        "boundary_area_sqft": round(poly_from_points(boundary_points_ft).area, 2),
        "total_seats": total_seats,
        "screen_count": screen_count,
        "seats_per_screen": seats_per_screen,
        "warnings": aud_warnings + support_warnings
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


def validate_rooms(boundary_points_ft, confirmed_obstacle_point_lists, rooms: list) -> dict:
    """Real geometric validation for architect-edited layouts (spec Sec 38/61
    'geometry tests': overlap, containment, obstacle avoidance). Returns per-room
    errors — never silently accepts an invalid edit."""
    boundary = poly_from_points(boundary_points_ft)
    obstacles = [poly_from_points(p) for p in (confirmed_obstacle_point_lists or [])]

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

        for obs in obstacles:
            inter = poly.intersection(obs).area
            if inter > 0.5:
                errors.append({"room_id": room["room_id"], "issue": "OBSTACLE_COLLISION",
                                "message": f"{room['display_name']} overlaps a confirmed structural obstacle by {round(inter,1)} sqft."})

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


def generate_candidates(boundary_points_ft, confirmed_obstacle_point_lists, requirements: dict) -> list:
    usable_poly = compute_usable_area(boundary_points_ft, confirmed_obstacle_point_lists)
    if usable_poly.is_empty or usable_poly.area <= 0:
        return []
    return [
        generate_candidate(usable_poly, boundary_points_ft, "MAX_SEATS_PER_SCREEN", requirements),
        generate_candidate(usable_poly, boundary_points_ft, "MAX_SCREEN_COUNT", requirements)
    ]
