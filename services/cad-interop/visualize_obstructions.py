#!/usr/bin/env python3
"""
visualize_obstructions.py
Milestone M1, Step 4 — Visualizes fixed planning obstructions across PlanRegions.
Renders SVG previews distinguishing columns, walls, stairs, lifts, shafts,
fixed rooms, voids, and unknown candidates with distinct styling, patterns, and labels.
"""

import sys
import os
import json
import math
import html
import ezdxf

class ObstructionSVGCanvas:
    def __init__(self, width=1600, height=1200, margin_top=150, margin_bottom=60, margin_lr=80):
        self.width = width
        self.height = height
        self.margin_top = margin_top
        self.margin_bottom = margin_bottom
        self.margin_lr = margin_lr
        self.draw_w = width - 2 * margin_lr
        self.draw_h = height - margin_top - margin_bottom

        self.min_x = 0.0
        self.max_x = 1.0
        self.min_y = 0.0
        self.max_y = 1.0
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        self.elements = []

    def set_bounds(self, min_x, min_y, max_x, max_y, padding_pct=0.06):
        span_x = max(max_x - min_x, 1e-4)
        span_y = max(max_y - min_y, 1e-4)
        pad_x = span_x * padding_pct
        pad_y = span_y * padding_pct

        self.min_x = min_x - pad_x
        self.max_x = max_x + pad_x
        self.min_y = min_y - pad_y
        self.max_y = max_y + pad_y

        world_w = self.max_x - self.min_x
        world_h = self.max_y - self.min_y

        scale_x = self.draw_w / world_w
        scale_y = self.draw_h / world_h
        self.scale = min(scale_x, scale_y)

        rendered_w = world_w * self.scale
        rendered_h = world_h * self.scale
        self.offset_x = self.margin_lr + (self.draw_w - rendered_w) / 2.0
        self.offset_y = self.margin_top + (self.draw_h - rendered_h) / 2.0

    def world_to_svg(self, x, y):
        sx = self.offset_x + (x - self.min_x) * self.scale
        sy = self.offset_y + (self.max_y - y) * self.scale
        return sx, sy

    def add_line(self, x1, y1, x2, y2, stroke="#94a3b8", stroke_width=0.75, stroke_dash=None, title=None):
        sx1, sy1 = self.world_to_svg(x1, y1)
        sx2, sy2 = self.world_to_svg(x2, y2)
        dash_attr = f' stroke-dasharray="{stroke_dash}"' if stroke_dash else ""
        elem = f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" stroke="{stroke}" stroke-width="{stroke_width}"{dash_attr}>'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</line>'
        self.elements.append(elem)

    def add_polyline(self, pts, closed=False, stroke="#94a3b8", stroke_width=0.75, fill="none", stroke_dash=None, title=None):
        if not pts:
            return
        svg_pts = [self.world_to_svg(p[0], p[1]) for p in pts]
        d_parts = [f"M {svg_pts[0][0]:.1f} {svg_pts[0][1]:.1f}"]
        for p in svg_pts[1:]:
            d_parts.append(f"L {p[0]:.1f} {p[1]:.1f}")
        if closed:
            d_parts.append("Z")
        d_str = " ".join(d_parts)

        dash_attr = f' stroke-dasharray="{stroke_dash}"' if stroke_dash else ""
        elem = f'<path d="{d_str}" stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"{dash_attr}>'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</path>'
        self.elements.append(elem)

    def add_rect(self, min_x, min_y, max_x, max_y, stroke="#64748b", stroke_width=1.5, fill="none", stroke_dash=None, title=None):
        pts = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        self.add_polyline(pts, closed=True, stroke=stroke, stroke_width=stroke_width, fill=fill, stroke_dash=stroke_dash, title=title)

    def add_box_with_x(self, min_x, min_y, max_x, max_y, stroke="#0891b2", stroke_width=2.0, fill="rgba(8,145,178,0.15)", title=None):
        self.add_rect(min_x, min_y, max_x, max_y, stroke=stroke, stroke_width=stroke_width, fill=fill, title=title)
        self.add_line(min_x, min_y, max_x, max_y, stroke=stroke, stroke_width=stroke_width * 0.75, title=title)
        self.add_line(min_x, max_y, max_x, min_y, stroke=stroke, stroke_width=stroke_width * 0.75, title=title)

    def add_badge(self, x, y, text, fg_color, bg_color, border_color):
        sx, sy = self.world_to_svg(x, y)
        w = max(len(text) * 7.5 + 20, 90)
        h = 22
        badge = (
            f'<g transform="translate({sx - w/2:.1f}, {sy - h/2:.1f})">'
            f'  <rect width="{w:.1f}" height="{h}" rx="3" fill="{bg_color}" stroke="{border_color}" stroke-width="1.2" />'
            f'  <text x="{w/2:.1f}" y="15" font-family="Inter, sans-serif" font-size="10" font-weight="700" fill="{fg_color}" text-anchor="middle">{html.escape(text)}</text>'
            f'</g>'
        )
        self.elements.append(badge)

    def render_header(self, title_text, subtitle_text, counts_text, legend_items):
        header_elements = [
            f'<rect x="0" y="0" width="{self.width}" height="{self.margin_top - 20}" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />',
            # Title
            f'<text x="{self.margin_lr}" y="38" font-family="Inter, sans-serif" font-size="20" font-weight="700" fill="#0f172a">{html.escape(str(title_text))}</text>',
            # Subtitle
            f'<text x="{self.margin_lr}" y="62" font-family="Inter, sans-serif" font-size="12" fill="#475569">{html.escape(str(subtitle_text))}</text>',
            # Counts badge
            f'<g transform="translate({self.width - 480}, 20)">',
            f'  <rect x="0" y="0" width="400" height="34" rx="6" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1" />',
            f'  <text x="200" y="22" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#334155" text-anchor="middle">{html.escape(str(counts_text))}</text>',
            f'</g>',
            # Legend Bar
            f'<g transform="translate({self.margin_lr}, 95)">'
        ]

        lx = 0
        for label, style in legend_items:
            if style["type"] == "line":
                dash = f' stroke-dasharray="{style["dash"]}"' if "dash" in style else ""
                header_elements.append(f'<line x1="{lx}" y1="12" x2="{lx+24}" y2="12" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            elif style["type"] == "rect":
                fill = style.get("fill", "none")
                dash = f' stroke-dasharray="{style.get("dash", "")}"' if style.get("dash") else ""
                header_elements.append(f'<rect x="{lx}" y="4" width="20" height="15" rx="2" fill="{fill}" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            header_elements.append(f'<text x="{lx+28}" y="16" font-family="Inter, sans-serif" font-size="10" font-weight="600" fill="#334155">{html.escape(str(label))}</text>')
            lx += style.get("box_width", 140)

        header_elements.append('</g>')
        return "\n".join(header_elements)

    def to_svg(self, header_svg=""):
        svg = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}">',
            f'  <rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#f8fafc" />',
            header_svg,
            f'  <g id="obstructions_layer">',
            "\n".join(f"    {e}" for e in self.elements),
            f'  </g>',
            f'</svg>'
        ]
        return "\n".join(svg)

def render_background_walls(canvas, msp, region_bbox, scale_to_feet):
    bx0, by0, bx1, by1 = region_bbox
    for e in msp:
        if e.dxf.layer in ['wall', 'Wall_TMOS', 'WALLS']:
            if e.dxftype() == 'LINE':
                s, end = e.dxf.start, e.dxf.end
                if (bx0 <= s[0] <= bx1 and by0 <= s[1] <= by1) or (bx0 <= end[0] <= bx1 and by0 <= end[1] <= by1):
                    canvas.add_line(s[0]*scale_to_feet, s[1]*scale_to_feet, end[0]*scale_to_feet, end[1]*scale_to_feet, stroke="#cbd5e1", stroke_width=0.7)

def visualize_obstructions_for_region(region_data, ext_region, b_data, msp, scale_to_feet, output_path):
    canvas = ObstructionSVGCanvas(width=1600, height=1200, margin_top=150, margin_bottom=60, margin_lr=80)
    raw_bbox = ext_region["bounding_box"]
    bbox_ft = {
        "min_x": raw_bbox["min_x"] * scale_to_feet,
        "min_y": raw_bbox["min_y"] * scale_to_feet,
        "max_x": raw_bbox["max_x"] * scale_to_feet,
        "max_y": raw_bbox["max_y"] * scale_to_feet
    }
    canvas.set_bounds(bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"], padding_pct=0.06)

    # 1. Background interior wall geometry
    render_background_walls(canvas, msp, (raw_bbox["min_x"], raw_bbox["min_y"], raw_bbox["max_x"], raw_bbox["max_y"]), scale_to_feet)

    # 2. Plan Region Bounding Box
    canvas.add_rect(
        bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"],
        stroke="#64748b", stroke_width=1.5, stroke_dash="6,4",
        title=f"Plan Region BBox: {region_data['label']}"
    )

    # 3. Floor Boundary (if present) or Framing
    bg = b_data.get("source_boundary")
    if bg and "points" in bg:
        canvas.add_polyline(
            bg["points"], closed=True,
            stroke="#059669", stroke_width=3.5, fill="rgba(16, 185, 129, 0.05)",
            title=f"Floor Boundary [{bg['source_entity_handles'][0]}]"
        )
    elif ext_region.get("framing_geometry"):
        fg = ext_region["framing_geometry"]
        if "points" in fg:
            scaled_f = [[p[0]*scale_to_feet, p[1]*scale_to_feet] for p in fg["points"]]
            canvas.add_polyline(
                scaled_f, closed=True,
                stroke="#2563eb", stroke_width=2.0, stroke_dash="8,4", fill="none",
                title=f"Framing Rectangle: [{fg['handle']}]"
            )

    # 4. Vertical Circulation: Stairs
    for st in region_data["circulation"]["stairs"]:
        b = st["bounding_box_ft"]
        canvas.add_rect(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#ea580c", stroke_width=2.5, stroke_dash="6,3", fill="rgba(234, 88, 12, 0.12)",
            title=f"Staircase: {st['subtype']} (Entities: {st['total_entities']}) - FOOTPRINT_UNCERTAIN"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "STAIR CORE", "#c2410c", "#fff7ed", "#ea580c")

    # 5. Vertical Circulation: Lifts
    for lf in region_data["circulation"]["lifts"]:
        b = lf["bounding_box_ft"]
        canvas.add_box_with_x(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#4338ca", stroke_width=2.0, fill="rgba(67, 56, 202, 0.15)",
            title=f"Lift: {lf['source_text']} | Handle: [{lf['source_handle']}]"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "LIFT", "#3730a3", "#e0e7ff", "#4338ca")

    # 6. MEP Shafts / Ducts
    for sh in region_data["services"]["shafts"]:
        b = sh["bounding_box_ft"]
        canvas.add_box_with_x(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#0891b2", stroke_width=2.0, fill="rgba(8, 145, 178, 0.15)",
            title=f"Shaft/Duct (Lines: {sh['entity_count']})"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "DUCT", "#0e7490", "#ecfeff", "#0891b2")

    # 7. Fixed Rooms (Toilets / Technical Rooms / Storage)
    for rm in region_data["architectural"]["fixed_rooms"]:
        p = rm.get("position_ft")
        if p:
            canvas.add_rect(p[0]-3, p[1]-3, p[0]+3, p[1]+3, stroke="#d97706", stroke_width=1.5, fill="rgba(217, 119, 6, 0.15)", title=f"Fixed Room: {rm['label']}")
            lbl = "TOILET" if "TOILET" in rm.get("label", "") else ("STORAGE" if "STORAGE" in rm.get("label", "") else "FIXED ROOM")
            canvas.add_badge(p[0], p[1], lbl, "#b45309", "#fef3c7", "#d97706")

    # Service Rooms in Vadodara (Projector Booths)
    for sr in region_data["services"].get("service_rooms", []):
        p = sr.get("position_ft")
        if p:
            canvas.add_rect(p[0]-6, p[1]-4, p[0]+6, p[1]+4, stroke="#7c3aed", stroke_width=1.8, fill="rgba(124, 58, 237, 0.15)", title=f"Service Room: {sr['label']}")
            canvas.add_badge(p[0], p[1], "PROJ BOOTH", "#6d28d9", "#ede9fe", "#7c3aed")

    # 8. Voids / Cutouts
    for vd in region_data["voids"]:
        p = vd.get("position_ft")
        if p:
            canvas.add_rect(p[0]-4, p[1]-4, p[0]+4, p[1]+4, stroke="#e11d48", stroke_width=1.8, stroke_dash="4,4", fill="rgba(225, 29, 72, 0.10)", title=f"Void: {vd.get('label', 'Cutout')}")
            lbl = "RAMP" if "RAMP" in vd.get("label", "") else "VOID"
            canvas.add_badge(p[0], p[1], lbl, "#be123c", "#ffe4e6", "#e11d48")

    # 9. Unknown Candidates
    for unk in region_data["unknown_candidates"]:
        pass

    # 10. Structural Columns (Prominently rendered in red)
    for col in region_data["structural"]["columns"]:
        pts = col["geometry"]["points"]
        h = col.get("source_handle", "")
        c_title = f"Column [{h}] | Dim: {col.get('width', 0)} x {col.get('height', 0)} ft | Area: {col.get('area_sqft', 0)} sqft"
        canvas.add_polyline(pts, closed=True, stroke="#991b1b", stroke_width=1.2, fill="#dc2626", title=c_title)

    # Header and Legend setup
    cols_cnt = len(region_data["structural"]["columns"])
    stairs_cnt = len(region_data["circulation"]["stairs"])
    lifts_cnt = len(region_data["circulation"]["lifts"])
    shafts_cnt = len(region_data["services"]["shafts"])
    rooms_cnt = len(region_data["architectural"]["fixed_rooms"]) + len(region_data["services"].get("service_rooms", []))
    counts_str = f"Cols: {cols_cnt} | Stairs: {stairs_cnt} | Lifts: {lifts_cnt} | Shafts: {shafts_cnt} | Fixed Rooms: {rooms_cnt}"

    legend_items = [
        ("COLUMN", {"type": "rect", "stroke": "#991b1b", "width": 1.2, "fill": "#dc2626", "box_width": 115}),
        ("STAIR CORE", {"type": "rect", "stroke": "#ea580c", "width": 2.0, "dash": "6,3", "fill": "rgba(234, 88, 12, 0.2)", "box_width": 135}),
        ("LIFT SHAFT", {"type": "rect", "stroke": "#4338ca", "width": 2.0, "fill": "rgba(67, 56, 202, 0.2)", "box_width": 135}),
        ("MEP SHAFT", {"type": "rect", "stroke": "#0891b2", "width": 2.0, "fill": "rgba(8, 145, 178, 0.2)", "box_width": 135}),
        ("FIXED ROOM", {"type": "rect", "stroke": "#d97706", "width": 1.8, "fill": "rgba(217, 119, 6, 0.2)", "box_width": 135}),
        ("VOID / RAMP", {"type": "rect", "stroke": "#e11d48", "width": 1.8, "dash": "4,4", "fill": "rgba(225, 29, 72, 0.15)", "box_width": 140}),
        ("WALLS", {"type": "line", "stroke": "#cbd5e1", "width": 1.0, "box_width": 100}),
    ]

    header_svg = canvas.render_header(
        title_text=f"Fixed Planning Obstructions — {region_data['label']}",
        subtitle_text=f"Fixed Structural, Vertical Circulation & Service Elements | Canonical Units: Feet",
        counts_text=counts_str,
        legend_items=legend_items
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(canvas.to_svg(header_svg))

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    obs_dir = os.path.join(output_dir, "obstructions")
    os.makedirs(obs_dir, exist_ok=True)

    obs_json = os.path.join(output_dir, "planning_obstructions_v1.json")
    ext_json = os.path.join(output_dir, "extracted_geometry_v2.json")
    bound_json = os.path.join(output_dir, "floor_boundaries_v1.json")

    with open(obs_json, "r", encoding="utf-8") as f:
        obstructions_data = json.load(f)
    with open(ext_json, "r", encoding="utf-8") as f:
        ext_data = json.load(f)
    with open(bound_json, "r", encoding="utf-8") as f:
        boundaries_data = json.load(f)

    dhule_dxf = os.path.join(output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")

    # Dhule
    dh_doc = ezdxf.readfile(dhule_dxf)
    dh_msp = dh_doc.modelspace()
    dh_obstructions = obstructions_data["documents"][0]["regions"]
    dh_ext_regions = {r["id"]: r for r in ext_data["dhule"]["plan_regions"]}
    dh_boundaries = {r["region_id"]: r for r in boundaries_data["documents"][0]["regions"]}

    dh_filenames = {
        "dhule-basement": "dhule_basement_obstructions.svg",
        "dhule-ground": "dhule_ground_obstructions.svg",
        "dhule-first-floor": "dhule_first_obstructions.svg",
        "dhule-second-floor": "dhule_second_obstructions.svg",
        "dhule-third-floor": "dhule_third_obstructions.svg",
        "dhule-fourth-floor": "dhule_fourth_obstructions.svg",
    }

    print("=" * 80)
    print("GENERATING DHULE OBSTRUCTION VISUALIZATIONS")
    print("=" * 80)
    for r in dh_obstructions:
        rid = r["region_id"]
        fname = dh_filenames.get(rid, f"{rid}_obstructions.svg")
        fpath = os.path.join(obs_dir, fname)
        visualize_obstructions_for_region(
            r, dh_ext_regions[rid], dh_boundaries[rid], dh_msp, scale_to_feet=1.0, output_path=fpath
        )
        print(f"  [CREATED] {fname} ({r['label']})")

    # Vadodara
    vad_doc = ezdxf.readfile(vadodara_dxf)
    vad_msp = vad_doc.modelspace()
    vad_obstructions = obstructions_data["documents"][1]["regions"]
    vad_ext_regions = {r["id"]: r for r in ext_data["vadodara"]["plan_regions"]}
    vad_boundaries = {r["region_id"]: r for r in boundaries_data["documents"][1]["regions"]}

    vad_filenames = {
        "vadodara-option-1": "vadodara_option1_obstructions.svg",
        "vadodara-option-2": "vadodara_option2_obstructions.svg"
    }

    print("\n" + "=" * 80)
    print("GENERATING VADODARA OBSTRUCTION VISUALIZATIONS")
    print("=" * 80)
    for r in vad_obstructions:
        rid = r["region_id"]
        fname = vad_filenames.get(rid, f"{rid}_obstructions.svg")
        fpath = os.path.join(obs_dir, fname)
        visualize_obstructions_for_region(
            r, vad_ext_regions[rid], vad_boundaries[rid], vad_msp, scale_to_feet=1.0/12.0, output_path=fpath
        )
        print(f"  [CREATED] {fname} ({r['label']})")

    print("\n[ALL OBSTRUCTION VISUALIZATIONS GENERATED SUCCESSFULLY]")
    print(f"SVGs located in: {obs_dir}")

if __name__ == "__main__":
    main()
