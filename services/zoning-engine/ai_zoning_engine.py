"""
AI-assisted zoning: an alternative to layout_engine.py's deterministic
rectangle packer that asks Claude to reason about the actual floor geometry
(boundary + classified obstacles) and propose a zoning layout directly, rather
than mechanically trying preset sizes in a fixed order.

Why this exists (user-requested, 2026-09-01): the deterministic packer only
ever places whichever of the three SOP auditorium presets (60/90/125-seat)
first fits, in a fixed largest-first-or-smallest-first order — it can't decide
"6 screens with mixed sizes fits this odd-shaped floor better than 4 uniform
ones," and it treats every obstacle-fragmented leftover the same mechanical
way. Claude can reason about the actual shape of the floor and the actual
obstacle layout the way an architect would. Per spec §2.6, presets are anchor
points to interpolate around, not the only allowed sizes — this path is where
that flexibility actually gets used; the deterministic packer still only ever
tries a preset's own min/max footprint.

Non-negotiables carried over from the deterministic engine (Product Principle
#1/#4 — config over code, compliance is advisory but never silently wrong):
  - Every dimension Claude is allowed to reason with (preset ranges, seat
    footprints, planning norms) is read from rules_registry, not invented here
    or by the model — the prompt states real numbers, never asks Claude to
    recall them.
  - Claude's output is geometry, nothing else. Seat counts are computed from
    it by the same seat_engine.estimate_seats() the deterministic engine uses
    — an LLM is not trusted to do exact row/aisle packing arithmetic.
  - The output is re-validated with layout_engine.validate_rooms() before it's
    ever accepted — an obstacle collision, boundary violation, or room overlap
    is rejected and retried once with the specific errors fed back, never
    silently accepted or silently patched.
  - The resulting candidate is the exact same dict shape layout_engine.py's
    generate_candidate() produces, so every downstream consumer (feasibility,
    chart, manual editing, PDF/DXF/DWG export) needs zero AI-specific code.
"""
import json
import os
import uuid

from dotenv import load_dotenv

import layout_engine
import rules_registry
import seat_engine

load_dotenv()

MODEL_ID = "claude-opus-5"
NON_AUDITORIUM_DISPLAY_NAMES = {
    "FOYER": "Foyer",
    "FNB": "Food & Beverage / Concession",
    "WASHROOM": "Washrooms",
    "BOX_OFFICE": "Box Office / Ticketing",
    "BOH": "Back-of-House (Electrical / Server / Store)",
}
ROOM_TYPES = ["AUDITORIUM", "FOYER", "FNB", "WASHROOM", "BOX_OFFICE", "BOH"]


class AiZoningError(Exception):
    """Raised for anything that should surface as a clear, specific error to
    the architect — never silently degrade to an empty or partial layout."""


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AiZoningError(
            "AI-assisted zoning is not configured on this server — ANTHROPIC_API_KEY is not set. "
            "Set it in services/zoning-engine/.env (local) or the service's environment variables (deployed)."
        )
    import anthropic  # imported lazily so a missing key fails with the message above, not an import error
    return anthropic.Anthropic(api_key=api_key)


LAYOUT_TOOL = {
    "name": "propose_zoning_layout",
    "description": (
        "Propose a complete cinema zoning layout: a list of non-overlapping axis-aligned "
        "rectangular rooms placed inside the floor boundary, avoiding every hard obstacle."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "2-4 sentences: the placement strategy actually used for this floor "
                                "(e.g. why this many screens, why these sizes, how obstacles were routed around)."
            },
            "rooms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "room_type": {"type": "string", "enum": ROOM_TYPES},
                        "display_name": {"type": "string", "description": "e.g. 'Screen 1 (Auditorium)', 'Foyer'"},
                        "x_ft": {"type": "number", "description": "Bottom-left corner X, in the boundary's own ft coordinate system."},
                        "y_ft": {"type": "number", "description": "Bottom-left corner Y."},
                        "width_ft": {"type": "number", "description": "Extent along X."},
                        "depth_ft": {"type": "number", "description": "Extent along Y."},
                        "primary_seat_type_id": {
                            "type": ["string", "null"],
                            "description": "For AUDITORIUM rooms only: one real seat_type id from the provided list. Null for every other room_type."
                        },
                    },
                    "required": ["room_type", "display_name", "x_ft", "y_ft", "width_ft", "depth_ft", "primary_seat_type_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reasoning", "rooms"],
        "additionalProperties": False,
    },
}


def _build_prompt(boundary_points_ft, confirmed_obstacles, requirements):
    presets = rules_registry.auditorium_presets()
    seat_types = seat_engine.selectable_seat_types()
    planning_norms = rules_registry.load()["planning_norms"]
    franchise_tier = None
    if requirements.get("franchise_tier_id"):
        franchise_tier = rules_registry.franchise_tier(requirements["franchise_tier_id"])
    property_type = requirements.get("property_type", "EXISTING_BUILDING")
    viability_rules = rules_registry.viability_rules(property_type)

    obstacles_desc = [
        {"classification": o.get("classification"), "points_ft": o.get("points_ft")}
        for o in confirmed_obstacles
    ]

    context = {
        "floor_boundary_points_ft": boundary_points_ft,
        "confirmed_obstacles": obstacles_desc,
        "requirements": {
            "property_type": property_type,
            "max_auditoriums": requirements.get("max_auditoriums", 4),
            "franchise_tier": franchise_tier,
            "clear_height_ft": requirements.get("clear_height_ft"),
            "entry_point_ft": requirements.get("entry_point_ft"),
        },
        "auditorium_presets_reference_only": presets,
        "selectable_seat_types": seat_types,
        "planning_norms": planning_norms,
        "hard_viability_rules": [
            {"metric": r.get("metric"), "operator": r.get("operator"), "threshold": r.get("threshold"),
             "unit": r.get("unit"), "severity": r.get("severity")}
            for r in viability_rules
        ],
    }

    return f"""You are laying out a cinema zoning plan for a real property, the same task a Connplex \
design architect does by hand in AutoCAD. You are given the real, measured floor boundary and every \
confirmed structural/architectural obstacle on it (walls, columns, staircases, washroom fixtures, doors, \
windows, furniture) — not a hypothetical.

Every business number you may use (auditorium size ranges, real seat footprints, planning-norm distances, \
franchise tier targets, hard viability thresholds) is given to you below, read live from Connplex's own \
versioned rules registry. Do not invent or recall a number that isn't in this data — if you need a \
threshold that isn't provided, make the most conservative reasonable choice and say so in `reasoning`.

CONTEXT (JSON):
{json.dumps(context, indent=2)}

YOUR TASK — propose rooms via the propose_zoning_layout tool:
1. Place up to {requirements.get("max_auditoriums", 4)} AUDITORIUM rooms. You are NOT limited to the three \
preset sizes listed above — those are anchor points, not the only allowed sizes. Choose whatever \
width/depth combination (and however many screens, from 1 up to the max) actually makes the best use of \
THIS floor's real shape — different screens may have different sizes if that fits better than forcing \
uniform screens. Every auditorium must still fall within a sane real-world range (roughly 28-55 ft wide, \
40-75 ft deep — smaller or bigger than that isn't a real cinema screen).
2. Maximize total seat count across all auditoriums — this is the locked v1 optimization objective — while \
never overlapping a hard obstacle (WALL, STAIRCASE, WASHROOM_FIXTURE, DOOR, WINDOW, FURNITURE, \
UNCLASSIFIED_OBSTACLE) and never extending outside the floor boundary. A CONFIRMED_OBSTACLE classified \
COLUMN is the one exception — a room may enclose a column if there is genuinely no better option, since a \
real architect designs around a structural column rather than refusing to use that floor area, but prefer \
a column-free placement whenever one exists. Leave at least 1 ft of real clearance between a room edge and \
any hard obstacle or the boundary edge — placements that just barely touch an obstacle's coordinates are \
routinely rejected by exact geometric validation afterward, so don't cut it precisely to the edge.
3. Include real support zones: at least one FOYER, one FNB, one WASHROOM, one BOX_OFFICE, and one BOH — \
these are mandatory per SOP (§9), sized reasonably against what's left after auditoriums, not to any fixed \
number.
4. No two rooms may overlap each other.
5. Space utilization is the main thing you're being judged on. Before finalizing, add up every room's area \
and compare it to the usable floor area — if less than ~75-80% of the usable area is covered by real rooms, \
you have NOT finished: go back and add another screen, enlarge existing screens toward the top of the sane \
size range, or grow the support zones, until the floor is genuinely well-used. A regular, obstacle-free \
rectangular region big enough for another auditorium or a bigger one is a mistake to leave empty. Only leave \
space uncovered when it's genuinely too small, too irregularly shaped, or too obstacle-fragmented for any \
room to use — never merely because you stopped at a round number of screens.
6. For every AUDITORIUM room, set primary_seat_type_id to one real id from selectable_seat_types above \
(pick the one that best matches the franchise tier's allowed_seat_types if a tier was given). Set it to \
null for every non-auditorium room.

Call propose_zoning_layout exactly once with your complete layout."""


def _room_type_and_label(raw_type, index, counters):
    """Auditoriums get the AUDITORIUM_N convention the rest of the codebase
    (chart_engine, export_pdf's ROOM_SHORT_LABEL, EditableCanvas) already
    keys off of via .startswith("AUDITORIUM") — everything else keeps its
    literal room_type."""
    if raw_type == "AUDITORIUM":
        counters["AUDITORIUM"] = counters.get("AUDITORIUM", 0) + 1
        n = counters["AUDITORIUM"]
        return f"AUDITORIUM_{n}", f"Screen {n} (Auditorium)"
    return raw_type, NON_AUDITORIUM_DISPLAY_NAMES.get(raw_type, raw_type.replace("_", " ").title())


def _rooms_from_tool_input(tool_input, column_polys):
    valid_seat_ids = {s["id"] for s in seat_engine.selectable_seat_types()}
    counters = {}
    rooms = []
    for r in tool_input.get("rooms", []):
        w, d = float(r["width_ft"]), float(r["depth_ft"])
        x, y = float(r["x_ft"]), float(r["y_ft"])
        if w <= 0 or d <= 0:
            raise AiZoningError(f"AI proposed a non-positive room size for '{r.get('display_name')}' — rejected.")
        raw_type = r["room_type"]
        room_type, default_label = _room_type_and_label(raw_type, len(rooms), counters)
        display_name = r.get("display_name") or default_label
        geometry_points_ft = [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]
        room = {
            "room_id": f"{raw_type.lower()}-{uuid.uuid4().hex[:8]}",
            "room_type": room_type,
            "display_name": display_name,
            "area_sqft": round(w * d, 2),
            "width_ft": round(w, 2),
            "depth_ft": round(d, 2),
            "origin_ft": [round(x, 2), round(y, 2)],
            "geometry_points_ft": geometry_points_ft,
        }
        if room_type.startswith("AUDITORIUM"):
            seat_type_id = r.get("primary_seat_type_id")
            if seat_type_id not in valid_seat_ids:
                seat_type_id = seat_engine.DEFAULT_SEAT_TYPE_ID
            rect_poly = layout_engine.poly_from_points(geometry_points_ft)
            enclosed_area = layout_engine._enclosed_obstacle_area(rect_poly, column_polys) if column_polys else 0.0
            seat_est = seat_engine.estimate_seats(w, d, primary_seat_type_id=seat_type_id, enclosed_obstacle_area_sqft=enclosed_area)
            room["seat_estimate"] = seat_est
            room["seat_config"] = {"primary_seat_type_id": seat_type_id, "secondary_seat_type_id": None, "primary_ratio_pct": 100}
            if seat_est.get("note"):
                room["obstacle_note"] = seat_est["note"]
        rooms.append(room)
    return rooms


def _call_claude(client, messages):
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": "max"},
        tools=[LAYOUT_TOOL],
        tool_choice={"type": "tool", "name": "propose_zoning_layout"},
        messages=messages,
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise AiZoningError("Claude did not return a zoning proposal (no tool call in the response).")
    return response, tool_use


def generate_ai_candidate(boundary_points_ft, confirmed_obstacles, requirements: dict) -> dict:
    """Returns a candidate dict in the exact same shape as
    layout_engine.generate_candidate() — see that function's return value for
    the contract every downstream consumer (feasibility/chart/export) relies on."""
    client = _client()
    boundary_poly = layout_engine.poly_from_points(boundary_points_ft)
    column_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in confirmed_obstacles
                     if o.get("classification") == "COLUMN"]

    prompt = _build_prompt(boundary_points_ft, confirmed_obstacles, requirements)
    messages = [{"role": "user", "content": prompt}]

    last_errors = None
    rooms = None
    reasoning = ""
    tool_use = None
    for attempt in range(3):  # one shot + two retries with validation errors fed back
        if last_errors:
            # Replay the full previous assistant turn (not just the tool_use
            # block) — the SDK's own documented pattern for continuing a tool
            # loop, so any thinking block that came with it stays intact.
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": (
                        "That layout failed geometry validation and cannot be used. Fix these specific "
                        "problems and call propose_zoning_layout again with a corrected full room list:\n"
                        + "\n".join(f"- {e['message']}" for e in last_errors)
                    ),
                }],
            })

        try:
            response, tool_use = _call_claude(client, messages)
        except Exception as e:
            raise AiZoningError(f"AI zoning request failed: {e}")

        reasoning = tool_use.input.get("reasoning", "")
        try:
            rooms = _rooms_from_tool_input(tool_use.input, column_polys)
        except AiZoningError as e:
            last_errors = [{"message": str(e)}]
            continue

        validation = layout_engine.validate_rooms(boundary_points_ft, confirmed_obstacles, rooms)
        if validation["valid"]:
            column_warnings = [w["message"] for w in validation["warnings"]]
            break
        last_errors = validation["errors"]
        rooms = None
    else:
        column_warnings = []

    if rooms is None:
        details = "; ".join(e["message"] for e in (last_errors or []))
        raise AiZoningError(
            f"Claude's proposed layout still failed geometry validation after a retry — rejected rather than "
            f"used as-is: {details}"
        )

    fallback_poly = layout_engine.compute_usable_area(boundary_points_ft, confirmed_obstacles, exclude_classifications=("COLUMN",))
    allocated_area = sum(layout_engine.poly_from_points(r["geometry_points_ft"]).area for r in rooms)
    circulation_area = max(fallback_poly.area - allocated_area, 0.0)

    auditoriums = [r for r in rooms if r["room_type"].startswith("AUDITORIUM")]
    total_seats = sum(r["seat_estimate"]["seat_count"] for r in auditoriums)
    screen_count = len(auditoriums)

    warnings = [f"AI reasoning: {reasoning}"] if reasoning else []
    warnings += column_warnings

    return {
        "candidate_id": f"ai-assisted-{uuid.uuid4().hex[:8]}",
        "strategy": "AI_ASSISTED",
        "strategy_label": "AI-Assisted Layout (Claude)",
        "rooms": rooms,
        "circulation_area_sqft": round(circulation_area, 2),
        "usable_area_sqft": round(fallback_poly.area, 2),
        "boundary_area_sqft": round(boundary_poly.area, 2),
        "total_seats": total_seats,
        "screen_count": screen_count,
        "seats_per_screen": round(total_seats / screen_count, 2) if screen_count else 0,
        "warnings": warnings,
    }
