"""
Real PDF zoning report (spec Sec 41/42/8.7): a templated renderer driven entirely
by structured project/candidate data (Product Principle #5 — the drawing is a
projection of data, not hand-edited). Produces the required content list from
Master Context Sec 42: project info, floor plan, auditorium dimensions/type, seat
types/counts, foyer/F&B/toilet/service/circulation areas, and an Area/Seat Chart.

Honest scope note: this reproduces the REQUIRED CONTENT of Connplex's zoning
sheet (title block, floor plan, Area & Seat Chart, legend, revision log) using a
clean generic template. It does not attempt to byte-for-byte replicate Connplex's
proprietary title-block artwork/logo — spec Sec 7.3 flags exact visual-format
matching as its own acceptance-tested milestone (M8) requiring the real reference
PDFs and Connplex's brand assets, which are not available to generate pixel-exact
replicas from inside this session.
"""
import os
from datetime import datetime

from reportlab.lib.pagesizes import landscape, A3
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas as pdfcanvas

PAGE_SIZE = landscape(A3)
MARGIN = 0.4 * inch

ROOM_FILL = {
    "AUDITORIUM": HexColor("#c7d9f5"), "FOYER": HexColor("#d9f5d0"), "FNB": HexColor("#f5e8c7"),
    "WASHROOM": HexColor("#e0d0f5"), "BOX_OFFICE": HexColor("#f5d0e0"), "BOH": HexColor("#e6e6e6")
}


def _room_color(room_type):
    key = room_type.split("_")[0] if room_type.startswith("AUDITORIUM") else room_type
    return ROOM_FILL.get(key, HexColor("#eeeeee"))


def _draw_title_block(c, project_meta, sheet_type, page_w, page_h):
    box_h = 1.4 * inch
    c.setStrokeColor(black)
    c.setLineWidth(1)
    c.rect(MARGIN, MARGIN, page_w - 2 * MARGIN, box_h)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(MARGIN + 10, MARGIN + box_h - 20, "CONNPLEX ZONING STUDIO")
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN + 10, MARGIN + box_h - 32, "Computational decision-support draft — not a final architectural/structural/fire-engineering document.")

    fields = [
        ("Project Code", project_meta.get("project_code", "-")),
        ("Property", project_meta.get("property_name", "-")),
        ("Client", project_meta.get("client_name", "-")),
        ("City / State", f"{project_meta.get('city','-')}, {project_meta.get('state','-')}"),
        ("Sheet", sheet_type),
        ("Revision", project_meta.get("revision", "R0")),
        ("Drawn By", project_meta.get("drawn_by", "Zoning Engine (auto)")),
        ("Date", project_meta.get("generated_at", datetime.utcnow().strftime("%Y-%m-%d"))),
    ]
    col_w = (page_w - 2 * MARGIN - 20) / len(fields)
    for i, (label, value) in enumerate(fields):
        x = MARGIN + 10 + i * col_w
        c.setFont("Helvetica", 7)
        c.drawString(x, MARGIN + 22, label.upper())
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, MARGIN + 10, str(value)[:24])


def _draw_floor_plan(c, boundary_points_ft, rooms, page_w, page_h, top_y, area_h):
    if not boundary_points_ft:
        return
    xs = [p[0] for p in boundary_points_ft]
    ys = [p[1] for p in boundary_points_ft]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    if bw <= 0 or bh <= 0:
        return

    avail_w = page_w - 2 * MARGIN - 20
    avail_h = area_h - 30
    scale = min(avail_w / bw, avail_h / bh) * 0.92
    ox = MARGIN + 10 + (avail_w - bw * scale) / 2 - min(xs) * scale
    oy = top_y - area_h + 15 + (avail_h - bh * scale) / 2 - min(ys) * scale

    def tx(pt):
        return (ox + pt[0] * scale, oy + pt[1] * scale)

    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    c.setFillColor(white)
    path = c.beginPath()
    px, py = tx(boundary_points_ft[0])
    path.moveTo(px, py)
    for p in boundary_points_ft[1:]:
        x, y = tx(p)
        path.lineTo(x, y)
    path.close()
    c.drawPath(path, stroke=1, fill=1)

    for room in rooms:
        pts = room["geometry_points_ft"]
        c.setFillColor(_room_color(room["room_type"]))
        c.setStrokeColor(black)
        c.setLineWidth(0.75)
        path = c.beginPath()
        x0, y0 = tx(pts[0])
        path.moveTo(x0, y0)
        for p in pts[1:]:
            x, y = tx(p)
            path.lineTo(x, y)
        path.close()
        c.drawPath(path, stroke=1, fill=1)

        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        lx, ly = tx((cx, cy))
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(lx, ly + 4, room["display_name"])
        c.setFont("Helvetica", 6)
        seat_txt = f" / {room['seat_estimate']['seat_count']} seats" if room.get("seat_estimate", {}).get("seat_count") else ""
        c.drawCentredString(lx, ly - 5, f"{room['area_sqft']} sqft{seat_txt}")


def _draw_legend(c, page_w, y):
    x = MARGIN + 10
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x, y, "LEGEND:")
    x += 55
    for room_type, label in [("AUDITORIUM", "Auditorium"), ("FOYER", "Foyer"), ("FNB", "F&B"),
                              ("WASHROOM", "Washroom"), ("BOX_OFFICE", "Box Office"), ("BOH", "Back-of-House")]:
        c.setFillColor(_room_color(room_type))
        c.rect(x, y - 2, 10, 8, stroke=1, fill=1)
        c.setFillColor(black)
        c.setFont("Helvetica", 7)
        c.drawString(x + 14, y, label)
        x += 90


def _draw_chart_table(c, chart, page_w, top_y):
    x0 = MARGIN + 10
    col_widths = [340, 70, 60, 80, 80, 100, 80]
    headers = ["LOCATION", "AREA (sqft)", "LOUNGER", "SOFA SLIDER", "DUO LOUNGER", "PREMIUM RECLINER", "TOTAL SEATS"]
    row_h = 16
    y = top_y

    def draw_row(cells, bold=False, fill=None):
        nonlocal y
        x = x0
        if fill:
            c.setFillColor(fill)
            c.rect(x0, y - row_h + 4, sum(col_widths), row_h, stroke=0, fill=1)
        c.setFillColor(black)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8)
        for cell, w in zip(cells, col_widths):
            c.drawString(x + 3, y - 10, str(cell))
            x += w
        y -= row_h

    c.setStrokeColor(black)
    c.line(x0, y + 4, x0 + sum(col_widths), y + 4)
    draw_row(headers, bold=True, fill=HexColor("#e0e0e0"))
    c.line(x0, y + 4, x0 + sum(col_widths), y + 4)

    for row in chart["screen_rows"]:
        draw_row([row["location"], row["area_sqft"], row["lounger"], row["sofa_slider"], row["duo_lounger"], row["premium_recliner"], row["total_seats"]])

    t = chart["total_screen_row"]
    draw_row([t["location"], t["area_sqft"], t["lounger"], t["sofa_slider"], t["duo_lounger"], t["premium_recliner"], t["total_seats"]], bold=True, fill=HexColor("#f0f0f0"))

    f_ = chart["foyer_row"]
    draw_row([f_["location"], f_["area_sqft"], "-", "-", "-", "-", "-"])
    e = chart["exit_passage_row"]
    draw_row([e["location"], e["area_sqft"], "-", "-", "-", "-", "-"])

    g = chart["grand_total_row"]
    c.line(x0, y + 4, x0 + sum(col_widths), y + 4)
    draw_row([g["location"], g["area_sqft"], g["lounger"], g["sofa_slider"], g["duo_lounger"], g["premium_recliner"], g["total_seats"]], bold=True, fill=HexColor("#d0e6ff"))
    c.line(x0, y + 4, x0 + sum(col_widths), y + 4)
    return y


def _draw_feasibility_summary(c, feasibility, x0, top_y, max_w):
    y = top_y
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, f"FEASIBILITY: {feasibility['feasibility_result'].replace('_', ' ')}")
    y -= 16
    c.setFont("Helvetica", 7)
    for rr in feasibility["rule_results"]:
        icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "INSUFFICIENT_DATA": "[N/A] "}[rr["result"]]
        line = f"{icon} {rr['message']}"
        if rr["measured_value"] is not None:
            line += f"  ({rr['measured_value']} vs {rr['threshold']})"
        c.drawString(x0, y, line[:150])
        y -= 10
        if y < MARGIN + 20:
            break
    return y


def render_pdf(project_meta: dict, boundary_points_ft, rooms, chart: dict, feasibility: dict, out_path: str, sheet_type="Zoning Layout"):
    page_w, page_h = PAGE_SIZE
    c = pdfcanvas.Canvas(out_path, pagesize=PAGE_SIZE)

    # --- Page 1: floor plan sheet ---
    plan_area_top = page_h - MARGIN - 10
    plan_area_h = page_h - 2 * MARGIN - 1.4 * inch - 40
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN + 10, page_h - MARGIN - 12, f"{project_meta.get('property_name', 'Untitled Project')} — {sheet_type.upper()}")
    _draw_floor_plan(c, boundary_points_ft, rooms, page_w, page_h, plan_area_top - 20, plan_area_h)
    _draw_legend(c, page_w, MARGIN + 1.4 * inch + 20)
    _draw_title_block(c, project_meta, sheet_type, page_w, page_h)
    c.showPage()

    # --- Page 2: Area & Seat Chart + feasibility + revision log ---
    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN + 10, page_h - MARGIN - 20, "AREA & SEAT CHART")
    chart_bottom = _draw_chart_table(c, chart, page_w, page_h - MARGIN - 45)

    if feasibility:
        _draw_feasibility_summary(c, feasibility, MARGIN + 10, chart_bottom - 30, page_w - 2 * MARGIN)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN + 10, MARGIN + 1.4 * inch + 30, "REVISIONS")
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN + 10, MARGIN + 1.4 * inch + 18,
                 f"{project_meta.get('revision', 'R0')}  |  {project_meta.get('generated_at', datetime.utcnow().strftime('%Y-%m-%d'))}  |  Generated by Connplex Zoning Studio")

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(MARGIN + 10, MARGIN + 1.4 * inch + 4,
                 "General Notes: All dimensions to be checked and co-related with architectural/interior drawings. All drawings to be read, not measured. Units: feet.")

    _draw_title_block(c, project_meta, "Area & Seat Chart", page_w, page_h)
    c.showPage()
    c.save()
    return out_path
