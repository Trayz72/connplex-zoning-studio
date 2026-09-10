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
     `selectable_seat_types()`); a type the SOP extract doesn't fully specify
     (e.g. Front Lounger's row step) gets a real, evidence-derived estimate
     in the registry itself instead — tagged ENGINEERING_ASSUMPTION there,
     not invented here — rather than being permanently excluded.
  3. A two-type mix splits the room's usable depth into two row-bands by the
     given ratio (e.g. 30% front rows one type, 70% back rows another) — each
     band is packed independently with its own type's real dimensions, then
     combined. This is an explicit, documented heuristic (proportional-depth
     split), not a claim that it matches any specific approved company layout
     standard — no such standard exists yet as a decided rule (Master Context
     §20: "Actual rules are catalogue/rule driven" and currently TBD).
  4. Every seat this module places gets a real (row, col, along_ft, depth_ft)
     position (`seat_positions` in estimate_seats' result), not just an
     aggregate count — the single source `seat_count`/`seat_breakdown` are
     always derived FROM that list, never computed separately. This is what
     lets a door on an auditorium's side wall (`side_exclusions`) remove the
     specific seat(s) nearest it, instead of an aggregate area-based fudge
     like the confirmed-obstacle correction below still is.
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
    elif "width_in_front_view" in seat_type:
        # FRONT_LOUNGER's own real field name — "front view width" is the
        # same real quantity every other seat type calls seat/width_in,
        # just named for how it was measured (a lounger's width is read off
        # its front elevation, not a plan-view footprint).
        width_in = seat_type["width_in_front_view"]
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


def _pack_band_seats(usable_width_ft, band_depth_ft, seat_type_id, central_aisle_ft,
                      depth_offset_ft, side_exclusions=None):
    """Same row/seats-per-row packing this project has always used, but
    keeping each seat's own real (row, col, along_ft, depth_ft) position
    instead of only a total — so a side-wall door's keep-clear zone
    (side_exclusions) can drop the specific seat nearest it, not an
    aggregate count. Two symmetric blocks (left/right of the central aisle,
    when one fits) rather than one merged row, matching how a real theater
    bowl is actually built — same total seats_per_row as the old single-
    formula version, just spatially real now.

    depth_offset_ft anchors along the room's own screen-to-back-wall axis
    (0 = at the screen wall), not this band's own start, so a mixed front/
    back-band room's exclusion zones — themselves expressed in the same
    screen-relative depth (see layout_engine._side_door_exclusions) — line
    up correctly regardless of which band a row falls in.

    Returns (seats, rows, seats_per_row, packed_depth_ft). rows/
    seats_per_row/packed_depth_ft are the nominal pre-exclusion numbers
    (a door removes at most the outermost seat of a handful of rows, not a
    whole row or column of capacity — reporting the room's real typical
    capacity here matches this field's historical meaning); seat_count is
    computed by every caller from len(seats), which does reflect any
    exclusions applied."""
    seat = rules_registry.seat_type(seat_type_id)
    seat_width_ft, row_step_ft = _seat_geometry(seat)
    if seat_width_ft is None or band_depth_ft <= 0 or usable_width_ft <= 0:
        return [], 0, 0, 0.0

    rows = max(math.floor(band_depth_ft / row_step_ft), 0)
    has_aisle = usable_width_ft > central_aisle_ft + (2 * seat_width_ft)
    seatable_width_ft = usable_width_ft - central_aisle_ft if has_aisle else usable_width_ft
    seats_per_row = max(math.floor(seatable_width_ft / seat_width_ft), 0)

    if has_aisle:
        left_count = math.ceil(seats_per_row / 2)
        right_count = seats_per_row - left_count
        right_block_start_ft = left_count * seat_width_ft + central_aisle_ft
    else:
        left_count, right_count, right_block_start_ft = seats_per_row, 0, 0.0

    seats = []
    for r in range(rows):
        row_depth_ft = depth_offset_ft + r * row_step_ft
        excluded_left = excluded_right = False
        for ex in (side_exclusions or []):
            if ex["depth_start_ft"] <= row_depth_ft < ex["depth_end_ft"]:
                if ex["side"] == "left":
                    excluded_left = True
                else:
                    excluded_right = True
        for c in range(left_count):
            if excluded_left and c == 0:
                continue  # the seat nearest the door — the room's own min-side wall
            seats.append({"row": r, "col": c, "along_ft": round(c * seat_width_ft, 2),
                          "depth_ft": round(row_depth_ft, 2), "seat_type_id": seat_type_id})
        for c in range(right_count):
            if excluded_right and c == right_count - 1:
                continue  # the seat nearest the door — the room's own max-side wall
            seats.append({"row": r, "col": left_count + c, "along_ft": round(right_block_start_ft + c * seat_width_ft, 2),
                          "depth_ft": round(row_depth_ft, 2), "seat_type_id": seat_type_id})
    # The band's own real packed depth (rows actually placed x that type's
    # own row step) — not band_depth_ft itself, which is the depth OFFERED
    # to this band and can exceed what an integer number of rows actually
    # fills. Feeds last_row_distance_ft below (real theater-design
    # convention: "how far is the back row from the screen", not "how deep
    # is the room").
    return seats, rows, seats_per_row, rows * row_step_ft


def estimate_seats(width_ft: float, depth_ft: float, primary_seat_type_id: str = DEFAULT_SEAT_TYPE_ID,
                    secondary_seat_type_id: str = None, primary_ratio_pct: float = 100,
                    front_row_count: int = None,
                    enclosed_obstacle_area_sqft: float = 0.0, screen_width_ft: float = None,
                    side_exclusions: list = None) -> dict:
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
                "seat_positions": [],
                "first_row_distance_ft": round(front_setback_ft, 2),
                "last_row_distance_ft": round(front_setback_ft, 2)}

    primary_ratio_pct = max(0, min(100, primary_ratio_pct))
    use_mix = secondary_seat_type_id and (primary_ratio_pct < 100 or front_row_count is not None)

    breakdown = {"LOUNGER": 0, "SOFA_SLIDER": 0, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0}
    all_seats = []

    if not use_mix:
        seats, rows, seats_per_row, packed_depth_ft = _pack_band_seats(
            usable_width_ft, usable_depth_ft, primary_seat_type_id, central_aisle_ft,
            front_setback_ft, side_exclusions
        )
        all_seats.extend(seats)
        col = CHART_COLUMN_BY_SEAT_TYPE.get(primary_seat_type_id, "LOUNGER")
        breakdown[col] = len(seats)
        seat_type_used = primary_seat_type_id
        total_rows, total_seats_per_row = rows, seats_per_row
    else:
        if front_row_count is not None:
            # Exact row-count split (e.g. "1 front lounger row, rest sofa
            # slider") — the real convention observed across every real
            # Connplex reference file, crisper than a depth percentage
            # (which can silently yield 0 or 2 front rows depending on the
            # room's actual depth). primary_seat_type_id is the *front*
            # band here (see this function's own module docstring: primary
            # = front rows, secondary = back rows).
            _, primary_step = _seat_geometry(rules_registry.seat_type(primary_seat_type_id))
            primary_depth = min(front_row_count * primary_step, usable_depth_ft) if primary_step else 0.0
        else:
            primary_depth = usable_depth_ft * (primary_ratio_pct / 100.0)
        secondary_depth = usable_depth_ft - primary_depth
        p_seats, p_rows, p_spr, p_packed_depth_ft = _pack_band_seats(
            usable_width_ft, primary_depth, primary_seat_type_id, central_aisle_ft,
            front_setback_ft, side_exclusions
        )
        s_seats, s_rows, s_spr, s_packed_depth_ft = _pack_band_seats(
            usable_width_ft, secondary_depth, secondary_seat_type_id, central_aisle_ft,
            front_setback_ft + primary_depth, side_exclusions
        )
        all_seats.extend(p_seats)
        all_seats.extend(s_seats)
        breakdown[CHART_COLUMN_BY_SEAT_TYPE.get(primary_seat_type_id, "LOUNGER")] += len(p_seats)
        breakdown[CHART_COLUMN_BY_SEAT_TYPE.get(secondary_seat_type_id, "LOUNGER")] += len(s_seats)
        if front_row_count is not None:
            seat_type_used = f"{primary_seat_type_id} ({p_rows}x front row) + {secondary_seat_type_id}"
        else:
            seat_type_used = f"{primary_seat_type_id}+{secondary_seat_type_id} ({primary_ratio_pct:.0f}/{100-primary_ratio_pct:.0f})"
        total_rows = p_rows + s_rows
        total_seats_per_row = max(p_spr, s_spr)
        packed_depth_ft = p_packed_depth_ft + s_packed_depth_ft

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
        # This correction is a proportional area-share estimate, not real
        # per-seat geometry (unlike the door exclusion above) — it has no
        # specific seat(s) to point to, so it can only trim the *count* of
        # real positions still on offer, arbitrarily from the end of the
        # list. Keeps seat_positions and seat_count/seat_breakdown
        # consistent (len(seat_positions) == seat_count always holds) rather
        # than reporting a positions list that disagrees with its own count.
        all_seats = all_seats[:seat_count]
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
        "seat_positions": all_seats,
        "first_row_distance_ft": round(front_setback_ft, 2),
        # How far the BACK row sits from the screen — front_setback_ft (the
        # first row's own distance) plus the real packed seating depth
        # actually placed (rows x each band's own row step), not
        # usable_depth_ft itself, which is only the depth OFFERED to the
        # rows and can exceed what an integer row count fills. Feeds
        # VR_LAST_ROW_DISTANCE (see rules_registry_v1.json) — general
        # theater-design guidance (SMPTE / BS 5588) that a back-row seat too
        # far from the screen loses legible facial expression, distinct
        # from FIRST_ROW_DISTANCE_RULE's own too-close concern.
        "last_row_distance_ft": round(front_setback_ft + packed_depth_ft, 2)
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


def _nearest_preset_for_area(area_sqft: float):
    """Same "largest preset whose min_area_sqft <= area_sqft" selection as
    best_fit_preset, but returns the real preset dict (not just an id/
    status string) — used to give a custom-fit room (no preset object of
    its own) a realistic seat-type mix to borrow, via default_seat_config,
    instead of always falling back to one flat seat type. Falls back to the
    smallest configured preset when the room is smaller than every real
    preset's own floor (still a real, defined mix — not nothing)."""
    presets = rules_registry.load()["auditorium_presets"]
    satisfied = [p for p in presets if area_sqft >= p["min_area_sqft"]]
    if not satisfied:
        return min(presets, key=lambda p: p["min_area_sqft"])
    return max(satisfied, key=lambda p: p["min_area_sqft"])


def default_seat_config(preset):
    """Real seat type + a front-lounger row when the matched preset's own
    seating_mix calls for one — not a hardcoded default. Every preset
    already declares its own seating_mix (35_SEAT: PREMIUM_RECLINER + DUO_
    LOUNGER; 60/90/125_SEAT: SLIDER_SOFA + FRONT_LOUNGER); this reads that
    declaration instead of silently defaulting every screen to SLIDER_SOFA
    regardless of preset — wrong even for a premium-tier screen, and
    missing the front-lounger row every real Connplex reference file this
    project has (Swati Trinity, Keshav Landmark, Maruti Nandan) uses as
    standard practice. Returns (primary_seat_type_id,
    secondary_seat_type_id_or_None, front_row_count_or_None) — primary is
    the *front* band when a front row is used (see estimate_seats's own
    front-row convention), so a real front-lounger mix comes back as
    (FRONT_LOUNGER, bulk_type, 1)."""
    mix = preset.get("seating_mix") or []
    selectable = {s["id"] for s in selectable_seat_types()}
    bulk_candidates = [t for t in mix if t in selectable and t != "FRONT_LOUNGER"]
    bulk_type = bulk_candidates[0] if bulk_candidates else DEFAULT_SEAT_TYPE_ID
    if "FRONT_LOUNGER" in mix and "FRONT_LOUNGER" in selectable:
        return "FRONT_LOUNGER", bulk_type, 1
    return bulk_type, None, None


def best_seat_estimate(preset, w, h, enclosed_obstacle_area_sqft, screen_width_ft):
    """The real "maximize total seat count" objective (this pipeline's own
    locked v1 goal) applies to seat *type* choice too, not just room
    placement — a front-lounger row isn't always a win. Real, measured case
    that would otherwise regress: a room with a large screen_width_ft (a
    big first-row setback) can be so depth-starved that swapping one row
    from the narrower-stepped bulk type to the wider-stepped FRONT_LOUNGER
    (5.67ft vs SLIDER_SOFA's 4.25ft) costs an entire row and nets *fewer*
    total seats, even though the same mix is a real net gain in a normal,
    non-depth-starved room. Computes both options when a front-lounger row
    applies at all and keeps whichever genuinely seats more — ties go to
    the front-row mix (the real, human-observed default), never silently
    accepting fewer seats for its own sake.

    preset=None (a custom-fit room, no standard SOP tier matched) still
    gets a real mix, not a flat single seat type: it borrows
    default_seat_config from whichever standard preset its own actual area
    (w*h) most resembles (_nearest_preset_for_area) — the room's reported
    preset_id/preset_name stay None/"Custom-fit screen" elsewhere (its
    PLACEMENT is genuinely non-standard), only its seat proportions borrow
    a real tier's realistic mix instead of defaulting to one uniform type.
    Returns (seat_config_dict, seat_estimate_dict)."""
    mix_source = preset if preset else _nearest_preset_for_area(w * h)
    primary, secondary, front_rows = default_seat_config(mix_source)
    mixed_estimate = estimate_seats(
        w, h, primary_seat_type_id=primary, secondary_seat_type_id=secondary, front_row_count=front_rows,
        enclosed_obstacle_area_sqft=enclosed_obstacle_area_sqft, screen_width_ft=screen_width_ft
    )
    if front_rows is None:
        seat_config = {"primary_seat_type_id": primary, "secondary_seat_type_id": None, "primary_ratio_pct": 100, "front_row_count": None}
        return seat_config, mixed_estimate

    bulk_only_estimate = estimate_seats(
        w, h, primary_seat_type_id=secondary,
        enclosed_obstacle_area_sqft=enclosed_obstacle_area_sqft, screen_width_ft=screen_width_ft
    )
    if bulk_only_estimate["seat_count"] > mixed_estimate["seat_count"]:
        seat_config = {"primary_seat_type_id": secondary, "secondary_seat_type_id": None, "primary_ratio_pct": 100, "front_row_count": None}
        return seat_config, bulk_only_estimate

    seat_config = {"primary_seat_type_id": primary, "secondary_seat_type_id": secondary, "primary_ratio_pct": 100, "front_row_count": front_rows}
    return seat_config, mixed_estimate
