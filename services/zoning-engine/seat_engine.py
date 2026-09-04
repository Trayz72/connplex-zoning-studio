"""
Real seat-count estimation for an auditorium of a given width/depth, with a
selectable seat type and an optional two-type mix ratio — configurable by the
architect per-room at edit time (spec's seat-mix requirement, §20: "Seat mix
percentage is user-configurable").

Methodology, same deterministic row-packing approach as before, generalized:
  1. Central-aisle and screen-to-back-wall clearances are SOP-sourced; side/rear
     clearances are engineering assumptions (see rules_registry planning_norms).
  2. Each seat type's real footprint (width + row-to-row step) is read from the
     registry — never hardcoded here. Only registry entries that have BOTH a
     real width and a real row-step are offered as selectable (see
     `selectable_seat_types()`); types the SOP extract doesn't fully specify
     (e.g. Front Lounger has no stated row step) are excluded rather than
     guessing a number for them.
  3. A two-type mix splits the room's usable depth into two row-bands by the
     given ratio (e.g. 30% front rows one type, 70% back rows another) — each
     band is packed independently with its own type's real dimensions, then
     combined. This is an explicit, documented heuristic (proportional-depth
     split), not a claim that it matches any specific approved company layout
     standard — no such standard exists yet as a decided rule (Master Context
     §20: "Actual rules are catalogue/rule driven" and currently TBD).
"""
import math
import rules_registry

DEFAULT_SEAT_TYPE_ID = "SLIDER_SOFA"

# Registry seat_type id -> Area/Seat Chart column key (spec §2.11 item 2's four
# columns: LOUNGER | SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER). The chart
# format doesn't have a distinct "duo premium recliner" column, so that type
# reports under PREMIUM_RECLINER — an explicit, documented bucketing choice.
CHART_COLUMN_BY_SEAT_TYPE = {
    "SLIDER_SOFA": "SOFA_SLIDER",
    "FRONT_LOUNGER": "LOUNGER",
    "DUO_LOUNGER": "DUO_LOUNGER",
    "PREMIUM_RECLINER": "PREMIUM_RECLINER",
    "DUO_PREMIUM_RECLINER": "PREMIUM_RECLINER",
    "DUO_RECLINER_LOUNGER_LUNAR": "LOUNGER",
    "RECLINER_LOUNGER_GENERIC": "LOUNGER",
}


def _seat_geometry(seat_type: dict):
    """Returns (width_ft_per_seat, row_step_ft) from whichever real fields this
    registry entry actually has, or (None, None) if it doesn't have enough real
    data to pack (never fabricates a missing dimension)."""
    row_step = seat_type.get("min_row_step_ft")
    if row_step is None:
        return None, None

    seats_per_unit = seat_type.get("seats_per_unit", 1)
    if "width_in_after_slide" in seat_type:
        width_in = seat_type["width_in_after_slide"]
    elif "seat_width_in" in seat_type:
        width_in = seat_type["seat_width_in"]
    elif "width_in" in seat_type:
        width_in = seat_type["width_in"] / seats_per_unit
    else:
        return None, None

    return width_in / 12.0, row_step


def selectable_seat_types() -> list:
    """Seat types with enough real registry data to drive packing math —
    what the frontend should offer in a seat-type picker."""
    out = []
    for st in rules_registry.load()["seat_types"]:
        w, step = _seat_geometry(st)
        if w is not None:
            out.append({
                "id": st["id"], "name": st["name"], "category": st.get("category"),
                "chart_column": CHART_COLUMN_BY_SEAT_TYPE.get(st["id"], "LOUNGER"),
                "seat_width_ft": round(w, 3), "row_step_ft": step,
            })
    return out


def _pack_band(usable_width_ft, band_depth_ft, seat_type_id, central_aisle_ft):
    seat = rules_registry.seat_type(seat_type_id)
    seat_width_ft, row_step_ft = _seat_geometry(seat)
    if seat_width_ft is None or band_depth_ft <= 0 or usable_width_ft <= 0:
        return 0, 0, 0

    rows = max(math.floor(band_depth_ft / row_step_ft), 0)
    if usable_width_ft > central_aisle_ft + (2 * seat_width_ft):
        seatable_width_ft = usable_width_ft - central_aisle_ft
    else:
        seatable_width_ft = usable_width_ft
    seats_per_row = max(math.floor(seatable_width_ft / seat_width_ft), 0)
    return rows, seats_per_row, rows * seats_per_row


def estimate_seats(width_ft: float, depth_ft: float, primary_seat_type_id: str = DEFAULT_SEAT_TYPE_ID,
                    secondary_seat_type_id: str = None, primary_ratio_pct: float = 100,
                    enclosed_obstacle_area_sqft: float = 0.0, screen_width_ft: float = None) -> dict:
    central_aisle_ft = rules_registry.planning_norm("CENTRAL_AISLE_MIN_FT")
    side_clear_ft = rules_registry.planning_norm("SIDE_CLEARANCE_ASSUMPTION_FT")
    rear_clear_ft = rules_registry.planning_norm("REAR_CLEARANCE_ASSUMPTION_FT")
    # SCREEN_TO_BACK_WALL_MIN_FT (3 ft) is the SOP's absolute minimum front
    # setback, not a claim that 3 ft is enough for a legible first row —
    # that's FIRST_ROW_DISTANCE_RULE's separate, much larger requirement
    # (first_row_distance_ft >= screen_width_ft). When the architect has
    # actually captured a screen width, use whichever is bigger, so the
    # seat-packing math itself satisfies the legibility rule by
    # construction instead of silently under-setting the front row and
    # letting a feasibility check fail after the fact.
    front_setback_ft = rules_registry.planning_norm("SCREEN_TO_BACK_WALL_MIN_FT")
    if screen_width_ft:
        front_setback_ft = max(front_setback_ft, screen_width_ft)

    usable_width_ft = width_ft - (2 * side_clear_ft)
    usable_depth_ft = depth_ft - front_setback_ft - rear_clear_ft

    if usable_width_ft <= 0 or usable_depth_ft <= 0:
        return {"status": "INSUFFICIENT_ROOM_FOR_SEATING", "seat_count": 0, "rows": 0, "seats_per_row": 0,
                "seat_breakdown": {"LOUNGER": 0, "SOFA_SLIDER": 0, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0},
                "first_row_distance_ft": round(front_setback_ft, 2)}

    primary_ratio_pct = max(0, min(100, primary_ratio_pct))
    use_mix = secondary_seat_type_id and primary_ratio_pct < 100

    breakdown = {"LOUNGER": 0, "SOFA_SLIDER": 0, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0}

    if not use_mix:
        rows, seats_per_row, count = _pack_band(usable_width_ft, usable_depth_ft, primary_seat_type_id, central_aisle_ft)
        col = CHART_COLUMN_BY_SEAT_TYPE.get(primary_seat_type_id, "LOUNGER")
        breakdown[col] = count
        seat_type_used = primary_seat_type_id
        total_rows, total_seats_per_row = rows, seats_per_row
    else:
        primary_depth = usable_depth_ft * (primary_ratio_pct / 100.0)
        secondary_depth = usable_depth_ft - primary_depth
        p_rows, p_spr, p_count = _pack_band(usable_width_ft, primary_depth, primary_seat_type_id, central_aisle_ft)
        s_rows, s_spr, s_count = _pack_band(usable_width_ft, secondary_depth, secondary_seat_type_id, central_aisle_ft)
        breakdown[CHART_COLUMN_BY_SEAT_TYPE.get(primary_seat_type_id, "LOUNGER")] += p_count
        breakdown[CHART_COLUMN_BY_SEAT_TYPE.get(secondary_seat_type_id, "LOUNGER")] += s_count
        seat_type_used = f"{primary_seat_type_id}+{secondary_seat_type_id} ({primary_ratio_pct:.0f}/{100-primary_ratio_pct:.0f})"
        total_rows = p_rows + s_rows
        total_seats_per_row = max(p_spr, s_spr)

    seat_count = sum(breakdown.values())

    # A confirmed obstacle (structural column) allowed to fall inside this
    # room (see layout_engine.py's two-tier placement — columns are the only
    # obstacle type a room can be placed over) does cost real seats even
    # though the row/column packing above has no per-obstacle geometry
    # awareness. Rather than either ignore this (an optimistic overcount) or
    # refuse the placement entirely (the old behavior this replaces),
    # conservatively scale the seat count down by the enclosed obstacle's
    # share of the room's own footprint — a real, reproducible correction,
    # not a fabricated number — and say so explicitly rather than silently
    # presenting a seat count as exact.
    note = None
    room_area = width_ft * depth_ft
    if enclosed_obstacle_area_sqft > 0 and room_area > 0 and seat_count > 0:
        retained_fraction = max(1.0 - (enclosed_obstacle_area_sqft / room_area), 0.0)
        breakdown = {k: math.floor(v * retained_fraction) for k, v in breakdown.items()}
        seat_count = sum(breakdown.values())
        note = (
            f"{round(enclosed_obstacle_area_sqft, 1)} sqft of confirmed obstacle(s) (e.g. a structural column) "
            f"fall inside this room's footprint — seat count reduced proportionally from the raw row/column "
            f"packing above; verify the actual seat plan around the obstacle position(s) before finalizing."
        )

    result = {
        "status": "OK" if seat_count > 0 else "ZERO_SEATS_FIT",
        "seat_count": seat_count,
        "rows": total_rows,
        "seats_per_row": total_seats_per_row,
        "seat_type_used": seat_type_used,
        "seat_breakdown": breakdown,
        "first_row_distance_ft": round(front_setback_ft, 2)
    }
    if note:
        result["note"] = note
    return result


def best_fit_preset(area_sqft: float) -> dict:
    presets = rules_registry.load()["auditorium_presets"]
    satisfied = [p for p in presets if area_sqft >= p["min_area_sqft"]]
    if not satisfied:
        smallest = min(presets, key=lambda p: p["min_area_sqft"])
        return {"matches_preset": None, "status": "BELOW_ALL_SOP_PRESETS",
                "shortfall_vs_smallest_preset_sqft": round(smallest["min_area_sqft"] - area_sqft, 1)}
    best = max(satisfied, key=lambda p: p["min_area_sqft"])
    return {"matches_preset": best["id"], "status": "MEETS_PRESET_AREA_FLOOR"}
