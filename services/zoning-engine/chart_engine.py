"""Builds the Area & Seat Chart (spec Sec 2.11 item 2 — LOCATION | AREA | LOUNGER |
SOFA SLIDER | DUO LOUNGER | PREMIUM RECLINER | TOTAL SEATS) from a candidate's
room list. Same structure as services/cad-interop/generate_area_seat_chart.py,
generalized to operate on any candidate, not just the frozen Dhule ones."""

NON_AUDITORIUM_LABELS = {
    "FOYER": "FOYER",
    "FNB": "F&B / CONCESSION",
    "WASHROOM": "WASHROOMS",
    "BOX_OFFICE": "BOX OFFICE",
    "BOH": "BACK-OF-HOUSE (ELECTRICAL/SERVER/STORE)",
    "PASSAGE": "PASSAGE / CORRIDOR"
}


def build_chart(candidate: dict) -> dict:
    screen_rows = []
    total_area = total_lounger = total_sofa_slider = total_duo_lounger = total_premium_recliner = total_seats = 0

    non_auditorium_rooms = []
    for room in candidate["rooms"]:
        if room["room_type"].startswith("AUDITORIUM"):
            breakdown = room.get("seat_estimate", {}).get("seat_breakdown", {"LOUNGER": 0, "SOFA_SLIDER": 0, "DUO_LOUNGER": 0, "PREMIUM_RECLINER": 0})
            row_total = sum(breakdown.values())
            screen_rows.append({
                "location": room["display_name"].upper(),
                "area_sqft": room["area_sqft"],
                "lounger": breakdown.get("LOUNGER", 0),
                "sofa_slider": breakdown.get("SOFA_SLIDER", 0),
                "duo_lounger": breakdown.get("DUO_LOUNGER", 0),
                "premium_recliner": breakdown.get("PREMIUM_RECLINER", 0),
                "total_seats": row_total
            })
            total_area += room["area_sqft"]
            total_lounger += breakdown.get("LOUNGER", 0)
            total_sofa_slider += breakdown.get("SOFA_SLIDER", 0)
            total_duo_lounger += breakdown.get("DUO_LOUNGER", 0)
            total_premium_recliner += breakdown.get("PREMIUM_RECLINER", 0)
            total_seats += row_total
        else:
            non_auditorium_rooms.append(room)

    foyer_area = sum(r["area_sqft"] for r in non_auditorium_rooms)
    foyer_components = [{"location": NON_AUDITORIUM_LABELS.get(r["room_type"], r["room_type"]), "area_sqft": r["area_sqft"]} for r in non_auditorium_rooms]
    exit_passage_area = candidate.get("circulation_area_sqft", 0)
    grand_total_area = round(total_area + foyer_area + exit_passage_area, 2)

    return {
        "screen_rows": screen_rows,
        "total_screen_row": {"location": "TOTAL SCREEN", "area_sqft": round(total_area, 2), "lounger": total_lounger,
                              "sofa_slider": total_sofa_slider, "duo_lounger": total_duo_lounger,
                              "premium_recliner": total_premium_recliner, "total_seats": total_seats},
        "foyer_row": {"location": "FOYER (Box Office + Washrooms + F&B + Electrical + Service)",
                      "area_sqft": round(foyer_area, 2), "components": foyer_components},
        "exit_passage_row": {"location": "EXIT PASSAGE", "area_sqft": round(exit_passage_area, 2)},
        "grand_total_row": {"location": "TOTAL", "area_sqft": grand_total_area, "lounger": total_lounger,
                             "sofa_slider": total_sofa_slider, "duo_lounger": total_duo_lounger,
                             "premium_recliner": total_premium_recliner, "total_seats": total_seats}
    }
