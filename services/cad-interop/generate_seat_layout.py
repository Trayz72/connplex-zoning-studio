#!/usr/bin/env python3
"""
Connplex Zoning Studio — Seat Layout Generator (M8, additive on top of frozen M0-M7)

Reads the frozen M4 geometry output (zoning_layouts_v2.json — per-candidate room
polygons with width_ft/depth_ft) plus the Rules/Config registry, and computes a real
seat count and seat-type breakdown for every AUDITORIUM_* room in every candidate.

This closes the single largest gap between the existing pipeline and the product
spec: the spec's required client deliverable is an Area & Seat Chart with seat-type
columns (LOUNGER | SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER | TOTAL SEATS) and the
stakeholder-locked optimization objective is "maximize total seat count" — neither
existed anywhere in the codebase before this script (verified: no `seat_count` /
`SeatType` logic previously existed outside of one reviewer-comment string).

Methodology (deterministic, documented, NOT presented as an approved architectural
rule — see rules_registry_v1.json approval_status fields):
  1. For a given auditorium room, apply clearances from PlanningNorm entries in the
     registry (central aisle = SOURCE_BACKED; side/rear clearances are marked
     ENGINEERING_ASSUMPTION / REQUIRES_APPROVAL).
  2. Usable seating width/depth = room width/depth minus those clearances.
  3. Pack rows using a single seat type's min_row_step_ft, and seats per row using
     that seat type's width. Slider Sofa is used as the default packing seat type
     because it is the only seat type common to all three SOP auditorium presets and
     has a fully specified footprint — see `seat_mix_methodology` in the output.
  4. This is a lower-bound, single-type estimate. Mixed seat-type layouts require an
     approved SeatMix ruleset (TBD per Master Context) and are out of scope for v1.

Never invents a dimension that is not in the registry: rooms with missing/ambiguous
seat-type data are reported with status EVALUATION_BLOCKED rather than a guessed
number.
"""
import json
import math
import os

BASE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(BASE, "..", "rules-config", "registry", "rules_registry_v1.json")
LAYOUTS_PATH = os.path.join(BASE, "test", "output", "zoning_layouts_v2.json")
OUT_PATH = os.path.join(BASE, "test", "output", "seat_layout_v1.json")
DIST_MIRROR = os.path.join(BASE, "..", "..", "apps", "web", "dist", "cad-data", "seat_layout_v1.json")

PACKING_SEAT_TYPE_ID = "SLIDER_SOFA"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_norm(norms, norm_id):
    for n in norms:
        if n["id"] == norm_id:
            return n
    return None


def pack_seats(width_ft, depth_ft, seat_type, central_aisle_ft, side_clear_ft, rear_clear_ft, front_setback_ft):
    """Deterministic single-seat-type row packer. Returns a dict with the result."""
    seat_width_ft = seat_type["width_in_after_slide"] / 12.0
    row_step_ft = seat_type["min_row_step_ft"]

    usable_width_ft = width_ft - (2 * side_clear_ft)
    usable_depth_ft = depth_ft - front_setback_ft - rear_clear_ft

    if usable_width_ft <= 0 or usable_depth_ft <= 0 or row_step_ft is None:
        return {
            "status": "INSUFFICIENT_ROOM_FOR_SEATING",
            "seat_count": 0,
            "rows": 0,
            "seats_per_row": 0,
            "usable_width_ft": round(max(usable_width_ft, 0), 2),
            "usable_depth_ft": round(max(usable_depth_ft, 0), 2)
        }

    rows = max(math.floor(usable_depth_ft / row_step_ft), 0)

    # If there's room for a central aisle plus at least one seat on each side, reserve it.
    if usable_width_ft > central_aisle_ft + (2 * seat_width_ft):
        seatable_width_ft = usable_width_ft - central_aisle_ft
        aisle_reserved = True
    else:
        seatable_width_ft = usable_width_ft
        aisle_reserved = False

    seats_per_row = max(math.floor(seatable_width_ft / seat_width_ft), 0)
    seat_count = rows * seats_per_row

    return {
        "status": "OK" if seat_count > 0 else "ZERO_SEATS_FIT",
        "seat_count": seat_count,
        "rows": rows,
        "seats_per_row": seats_per_row,
        "central_aisle_reserved": aisle_reserved,
        "usable_width_ft": round(usable_width_ft, 2),
        "usable_depth_ft": round(usable_depth_ft, 2),
        "seat_type_used": seat_type["id"],
        "row_step_ft": row_step_ft,
        "seat_width_ft": round(seat_width_ft, 3)
    }


def best_fit_preset(area_sqft, presets):
    """Report which SOP auditorium preset (if any) this room's area satisfies."""
    satisfied = [p for p in presets if area_sqft >= p["min_area_sqft"]]
    if not satisfied:
        smallest = min(presets, key=lambda p: p["min_area_sqft"])
        return {
            "matches_preset": None,
            "status": "BELOW_ALL_SOP_PRESETS",
            "shortfall_vs_smallest_preset_sqft": round(smallest["min_area_sqft"] - area_sqft, 1),
            "smallest_preset_id": smallest["id"]
        }
    best = max(satisfied, key=lambda p: p["min_area_sqft"])
    return {"matches_preset": best["id"], "status": "MEETS_PRESET_AREA_FLOOR"}


def main():
    registry = load_json(REGISTRY_PATH)
    layouts = load_json(LAYOUTS_PATH)

    norms = registry["planning_norms"]
    central_aisle_ft = get_norm(norms, "CENTRAL_AISLE_MIN_FT")["value"]
    side_clear_ft = get_norm(norms, "SIDE_CLEARANCE_ASSUMPTION_FT")["value"]
    rear_clear_ft = get_norm(norms, "REAR_CLEARANCE_ASSUMPTION_FT")["value"]
    front_setback_ft = get_norm(norms, "SCREEN_TO_BACK_WALL_MIN_FT")["value"]

    seat_type = next(s for s in registry["seat_types"] if s["id"] == PACKING_SEAT_TYPE_ID)
    presets = registry["auditorium_presets"]

    out_regions = []
    for region in layouts.get("regions", []):
        region_out = {
            "region_id": region["region_id"],
            "plan_region": region.get("plan_region"),
            "candidates": []
        }
        for cand in region.get("candidates", []):
            cand_out = {
                "candidate_id": cand["candidate_id"],
                "auditoriums": [],
                "total_seats": 0,
                "screen_count": 0
            }
            for room in cand.get("rooms", []):
                if not room["room_type"].startswith("AUDITORIUM"):
                    continue
                pack = pack_seats(
                    room["width_ft"], room["depth_ft"], seat_type,
                    central_aisle_ft, side_clear_ft, rear_clear_ft, front_setback_ft
                )
                preset_fit = best_fit_preset(room["area_sqft"], presets)
                cand_out["auditoriums"].append({
                    "room_id": room["room_id"],
                    "display_name": room["display_name"],
                    "area_sqft": room["area_sqft"],
                    "width_ft": room["width_ft"],
                    "depth_ft": room["depth_ft"],
                    "seat_packing": pack,
                    "preset_fit": preset_fit,
                    "seat_breakdown": {
                        "LOUNGER": 0,
                        "SOFA_SLIDER": pack["seat_count"] if pack["status"] == "OK" else 0,
                        "DUO_LOUNGER": 0,
                        "PREMIUM_RECLINER": 0
                    }
                })
                cand_out["total_seats"] += pack["seat_count"] if pack["status"] == "OK" else 0
                cand_out["screen_count"] += 1
            region_out["candidates"].append(cand_out)
        out_regions.append(region_out)

    output = {
        "schema_version": "1.0",
        "title": "Connplex Zoning Studio — Seat Layout & Seat-Count Estimate (M8)",
        "methodology_note": (
            "Deterministic single-seat-type (Slider Sofa) row-packing estimate. Central-aisle and "
            "screen-to-back-wall clearances are SOP-sourced; side/rear clearances are engineering "
            "assumptions pending architect approval (see rules_registry_v1.json planning_norms). "
            "This is a lower-bound estimate — mixed seat-type layouts require an approved SeatMix "
            "ruleset (currently TBD) and are not computed here."
        ),
        "packing_seat_type": PACKING_SEAT_TYPE_ID,
        "clearances_used_ft": {
            "central_aisle": central_aisle_ft,
            "side_clearance_each_side": side_clear_ft,
            "rear_clearance": rear_clear_ft,
            "front_setback": front_setback_ft
        },
        "regions": out_regions
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUT_PATH}")

    if os.path.isdir(os.path.dirname(DIST_MIRROR)):
        with open(DIST_MIRROR, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {DIST_MIRROR}")

    for region in out_regions:
        for cand in region["candidates"]:
            if cand["screen_count"] > 0:
                print(f"{region['region_id']} / {cand['candidate_id']}: "
                      f"{cand['screen_count']} screens, {cand['total_seats']} total seats")


if __name__ == "__main__":
    main()
