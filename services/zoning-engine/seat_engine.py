"""
Real seat-count estimation for an auditorium of a given width/depth.

Same deterministic single-seat-type row-packing methodology as
services/cad-interop/generate_seat_layout.py (ported here as a plain function so
the live zoning-runs endpoint can call it directly instead of shelling out to a
script over a fixed file). See that script's docstring for the full methodology
notes and honest limitations (single-seat-type lower-bound estimate; mixed
seat-type layouts need an approved SeatMix ruleset that doesn't exist yet).
"""
import math
import rules_registry

PACKING_SEAT_TYPE_ID = "SLIDER_SOFA"


def estimate_seats(width_ft: float, depth_ft: float) -> dict:
    seat = rules_registry.seat_type(PACKING_SEAT_TYPE_ID)
    central_aisle_ft = rules_registry.planning_norm("CENTRAL_AISLE_MIN_FT")
    side_clear_ft = rules_registry.planning_norm("SIDE_CLEARANCE_ASSUMPTION_FT")
    rear_clear_ft = rules_registry.planning_norm("REAR_CLEARANCE_ASSUMPTION_FT")
    front_setback_ft = rules_registry.planning_norm("SCREEN_TO_BACK_WALL_MIN_FT")

    seat_width_ft = seat["width_in_after_slide"] / 12.0
    row_step_ft = seat["min_row_step_ft"]

    usable_width_ft = width_ft - (2 * side_clear_ft)
    usable_depth_ft = depth_ft - front_setback_ft - rear_clear_ft

    if usable_width_ft <= 0 or usable_depth_ft <= 0:
        return {"status": "INSUFFICIENT_ROOM_FOR_SEATING", "seat_count": 0, "rows": 0, "seats_per_row": 0}

    rows = max(math.floor(usable_depth_ft / row_step_ft), 0)

    if usable_width_ft > central_aisle_ft + (2 * seat_width_ft):
        seatable_width_ft = usable_width_ft - central_aisle_ft
    else:
        seatable_width_ft = usable_width_ft

    seats_per_row = max(math.floor(seatable_width_ft / seat_width_ft), 0)
    seat_count = rows * seats_per_row

    return {
        "status": "OK" if seat_count > 0 else "ZERO_SEATS_FIT",
        "seat_count": seat_count,
        "rows": rows,
        "seats_per_row": seats_per_row,
        "seat_type_used": seat["id"],
        "seat_breakdown": {"LOUNGER": 0, "SOFA_SLIDER": seat_count, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0}
    }


def best_fit_preset(area_sqft: float) -> dict:
    presets = rules_registry.load()["auditorium_presets"]
    satisfied = [p for p in presets if area_sqft >= p["min_area_sqft"]]
    if not satisfied:
        smallest = min(presets, key=lambda p: p["min_area_sqft"])
        return {"matches_preset": None, "status": "BELOW_ALL_SOP_PRESETS",
                "shortfall_vs_smallest_preset_sqft": round(smallest["min_area_sqft"] - area_sqft, 1)}
    best = max(satisfied, key=lambda p: p["min_area_sqft"])
    return {"matches_preset": best["id"], "status": "MEETS_PRESET_AREA_FLOOR"}
