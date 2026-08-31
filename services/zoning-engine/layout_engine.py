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
            x += GRID_STEP_FT
        y += GRID_STEP_FT
    return None


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

    for room_type, display_name, target_area, min_area, note in targets:
        aspect = 1.6
        w = math.sqrt(target_area * aspect)
        h = target_area / w
        placement = _scan_place(usable_poly, placed_polys, w, h, bbox)

        shrink_note = None
        if not placement:
            # Try shrinking toward the minimum before giving up — never invent space that isn't there.
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
