#!/usr/bin/env python3
"""
Connplex Zoning Studio — Area & Seat Chart Generator (M8, additive)

Produces the AreaSeatChartSnapshot structure required by spec §2.11 item 2 and
Master Context §42 ("Required Client PDF"): the actual ground-truth deliverable
observed in both real Connplex reference drawings (Dhule, Vadodara) is a table with
columns LOCATION | AREA | LOUNGER | SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER |
TOTAL SEATS, one row per screen, plus a TOTAL SCREEN subtotal, a FOYER (Box Office +
Washrooms + F&B + Electrical + Service) subtotal, an EXIT PASSAGE row, and a grand
TOTAL row. No such table existed anywhere in the codebase before this script.

Reads: zoning_decision_v2.json (seat-aware preferred candidate per region) +
seat_layout_v1.json (per-auditorium seat breakdown). Writes: area_seat_chart_v1.json
(machine-readable) and area_seat_chart_v1_report.md (human-readable, in the same
style as the M5/M6/M7 reports already in this repo).
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DECISION_V2_PATH = os.path.join(BASE, "test", "output", "zoning_decision_v2.json")
LAYOUTS_PATH = os.path.join(BASE, "test", "output", "zoning_layouts_v2.json")
SEATS_PATH = os.path.join(BASE, "test", "output", "seat_layout_v1.json")
OUT_JSON = os.path.join(BASE, "test", "output", "area_seat_chart_v1.json")
OUT_MD = os.path.join(BASE, "test", "output", "area_seat_chart_v1_report.md")
DIST_MIRROR = os.path.join(BASE, "..", "..", "apps", "web", "dist", "cad-data", "area_seat_chart_v1.json")

NON_AUDITORIUM_LABELS = {
    "FOYER_CONCESSION": "FOYER",
    "PROJECTION_ROOM": "PROJECTION ROOM",
    "RESTROOMS": "WASHROOMS",
    "MANAGER_OFFICE": "MANAGER OFFICE"
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_region_chart(region, seat_region, layout_region):
    pref = region.get("preferred_candidate")
    if not pref:
        return None

    seat_cand = next((c for c in seat_region["candidates"] if c["candidate_id"] == pref["candidate_id"]), None)
    aud_by_room_id = {a["room_id"]: a for a in (seat_cand["auditoriums"] if seat_cand else [])}

    layout_cand = next((c for c in layout_region.get("candidates", []) if c["candidate_id"] == pref["candidate_id"]), None)
    rooms = layout_cand.get("rooms", []) if layout_cand else []

    screen_rows = []
    total_screen_area = 0.0
    total_lounger = total_sofa_slider = total_duo_lounger = total_premium_recliner = total_seats = 0

    non_auditorium_rooms = []
    for i, room in enumerate(rooms, start=1):
        if room["room_type"].startswith("AUDITORIUM"):
            aud = aud_by_room_id.get(room["room_id"], {})
            breakdown = aud.get("seat_breakdown", {"LOUNGER": 0, "SOFA_SLIDER": 0, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0})
            row_total_seats = sum(breakdown.values())
            screen_rows.append({
                "location": room["display_name"].upper(),
                "area_sqft": room["area_sqft"],
                "lounger": breakdown.get("LOUNGER", 0),
                "sofa_slider": breakdown.get("SOFA_SLIDER", 0),
                "duo_lounger": breakdown.get("DUO_LOUNGER", 0),
                "premium_recliner": breakdown.get("PREMIUM_RECLINER", 0),
                "total_seats": row_total_seats,
                "seat_estimate_status": aud.get("seat_packing", {}).get("status", "UNKNOWN")
            })
            total_screen_area += room["area_sqft"]
            total_lounger += breakdown.get("LOUNGER", 0)
            total_sofa_slider += breakdown.get("SOFA_SLIDER", 0)
            total_duo_lounger += breakdown.get("DUO_LOUNGER", 0)
            total_premium_recliner += breakdown.get("PREMIUM_RECLINER", 0)
            total_seats += row_total_seats
        else:
            non_auditorium_rooms.append(room)

    foyer_area = sum(r["area_sqft"] for r in non_auditorium_rooms)
    foyer_components = [
        {"location": NON_AUDITORIUM_LABELS.get(r["room_type"], r["room_type"]), "area_sqft": r["area_sqft"]}
        for r in non_auditorium_rooms
    ]

    exit_passage_area = pref.get("circulation_area_sqft", 0)

    grand_total_area = round(total_screen_area + foyer_area + exit_passage_area, 2)

    return {
        "region_id": region["region_id"],
        "plan_region": region.get("plan_region"),
        "preferred_candidate_id": pref["candidate_id"],
        "screen_rows": screen_rows,
        "total_screen_row": {
            "location": "TOTAL SCREEN",
            "area_sqft": round(total_screen_area, 2),
            "lounger": total_lounger,
            "sofa_slider": total_sofa_slider,
            "duo_lounger": total_duo_lounger,
            "premium_recliner": total_premium_recliner,
            "total_seats": total_seats
        },
        "foyer_row": {
            "location": "FOYER (Box Office + Washrooms + F&B + Electrical + Service)",
            "area_sqft": round(foyer_area, 2),
            "components": foyer_components,
            "note": "Current room program has no separate Box Office / F&B / Electrical-Server-Store zones (see CLAUDE.md audit notes) — this subtotal currently reflects only the room types the frozen geometry pipeline generates."
        },
        "exit_passage_row": {
            "location": "EXIT PASSAGE",
            "area_sqft": round(exit_passage_area, 2)
        },
        "grand_total_row": {
            "location": "TOTAL",
            "area_sqft": grand_total_area,
            "lounger": total_lounger,
            "sofa_slider": total_sofa_slider,
            "duo_lounger": total_duo_lounger,
            "premium_recliner": total_premium_recliner,
            "total_seats": total_seats
        }
    }


def render_markdown(charts):
    lines = [
        "# Connplex Zoning Studio — Area & Seat Chart (M8)",
        "",
        "> Matches the column structure of the real Connplex reference drawings (spec §2.11 item 2): "
        "LOCATION | AREA | LOUNGER | SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER | TOTAL SEATS.",
        ""
    ]
    for chart in charts:
        lines.append(f"## {chart['plan_region']} (`{chart['region_id']}`)")
        lines.append("")
        lines.append("| LOCATION | AREA (sqft) | LOUNGER | SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER | TOTAL SEATS |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for row in chart["screen_rows"]:
            lines.append(f"| {row['location']} | {row['area_sqft']} | {row['lounger']} | {row['sofa_slider']} | "
                          f"{row['duo_lounger']} | {row['premium_recliner']} | {row['total_seats']} |")
        t = chart["total_screen_row"]
        lines.append(f"| **{t['location']}** | **{t['area_sqft']}** | **{t['lounger']}** | **{t['sofa_slider']}** | "
                      f"**{t['duo_lounger']}** | **{t['premium_recliner']}** | **{t['total_seats']}** |")
        f_ = chart["foyer_row"]
        lines.append(f"| {f_['location']} | {f_['area_sqft']} | — | — | — | — | — |")
        e = chart["exit_passage_row"]
        lines.append(f"| {e['location']} | {e['area_sqft']} | — | — | — | — | — |")
        g = chart["grand_total_row"]
        lines.append(f"| **{g['location']}** | **{g['area_sqft']}** | **{g['lounger']}** | **{g['sofa_slider']}** | "
                      f"**{g['duo_lounger']}** | **{g['premium_recliner']}** | **{g['total_seats']}** |")
        lines.append("")
        lines.append(f"_Foyer note: {f_['note']}_")
        lines.append("")
    return "\n".join(lines)


def main():
    decisions_v2 = load_json(DECISION_V2_PATH)
    layouts = load_json(LAYOUTS_PATH)
    seats = load_json(SEATS_PATH)
    seat_region_index = {r["region_id"]: r for r in seats["regions"]}
    layout_region_index = {r["region_id"]: r for r in layouts["regions"]}

    charts = []
    for region in decisions_v2["regions"]:
        seat_region = seat_region_index.get(region["region_id"])
        layout_region = layout_region_index.get(region["region_id"])
        if not seat_region or not layout_region:
            continue
        chart = build_region_chart(region, seat_region, layout_region)
        if chart:
            charts.append(chart)

    output = {
        "schema_version": "1.0",
        "title": "Connplex Zoning Studio — Area & Seat Chart Snapshot (M8)",
        "note": "Structure mirrors the real Dhule/Vadodara reference drawings' Area/Seat Chart table exactly (spec §2.11 item 2).",
        "regions": charts
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUT_JSON}")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(render_markdown(charts))
    print(f"Wrote {OUT_MD}")

    if os.path.isdir(os.path.dirname(DIST_MIRROR)):
        with open(DIST_MIRROR, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {DIST_MIRROR}")


if __name__ == "__main__":
    main()
