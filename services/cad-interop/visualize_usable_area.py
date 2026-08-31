#!/usr/bin/env python3
"""
visualize_usable_area.py
Milestone M1, Step 5 — Visualizes usable planning areas derived from verified CAD geometry.
Renders SVG previews distinguishing Verified Boundary, Usable Planning Area, Hard Exclusions,
and Uncertain Obstructions with distinct visual treatment and exact area metrics.
"""

import sys
import os
import json
import math
import html
import ezdxf

class UsableAreaSVGCanvas:
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

    def add_polygon_with_holes(self, exterior, holes, stroke="#059669", stroke_width=2.5, fill="rgba(16,185,129,0.22)", title=None):
        svg_ext = [self.world_to_svg(p[0], p[1]) for p in exterior]
        d_parts = [f"M {svg_ext[0][0]:.1f} {svg_ext[0][1]:.1f}"]
        for p in svg_ext[1:]:
            d_parts.append(f"L {p[0]:.1f} {p[1]:.1f}")
        d_parts.append("Z")

        for hole in holes:
            svg_hole = [self.world_to_svg(p[0], p[1]) for p in hole]
            d_parts.append(f"M {svg_hole[0][0]:.1f} {svg_hole[0][1]:.1f}")
            for p in svg_hole[1:]:
                d_parts.append(f"L {p[0]:.1f} {p[1]:.1f}")
            d_parts.append("Z")

        d_str = " ".join(d_parts)
        elem = f'<path d="{d_str}" stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}" fill-rule="evenodd">'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</path>'
        self.elements.append(elem)

    def add_rect(self, min_x, min_y, max_x, max_y, stroke="#64748b", stroke_width=1.5, fill="none", stroke_dash=None, title=None):
        pts = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        self.add_polyline(pts, closed=True, stroke=stroke, stroke_width=stroke_width, fill=fill, stroke_dash=stroke_dash, title=title)

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

    def render_header(self, title_text, subtitle_text, metrics_text, status, legend_items):
        status_colors = {
            "VERIFIED_USABLE_AREA": ("#15803d", "#dcfce7", "#166534"), # Green
            "UNUSABLE_NO_BOUNDARY": ("#b45309", "#fef3c7", "#d97706"), # Amber
        }
        badge_fg, badge_bg, badge_border = status_colors.get(status, ("#475569", "#f1f5f9", "#94a3b8"))

        header_elements = [
            f'<rect x="0" y="0" width="{self.width}" height="{self.margin_top - 20}" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />',
            # Title
            f'<text x="{self.margin_lr}" y="38" font-family="Inter, sans-serif" font-size="20" font-weight="700" fill="#0f172a">{html.escape(str(title_text))}</text>',
            # Subtitle
            f'<text x="{self.margin_lr}" y="62" font-family="Inter, sans-serif" font-size="12" fill="#475569">{html.escape(str(subtitle_text))}</text>',
            # Metrics Badge
            f'<g transform="translate({self.width - 520}, 20)">',
            f'  <rect x="0" y="0" width="440" height="34" rx="6" fill="{badge_bg}" stroke="{badge_border}" stroke-width="1.2" />',
            f'  <text x="220" y="22" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="{badge_fg}" text-anchor="middle">{html.escape(str(metrics_text))}</text>',
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
            lx += style.get("box_width", 150)

        header_elements.append('</g>')
        return "\n".join(header_elements)

    def to_svg(self, header_svg=""):
        svg = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}">',
            f'  <rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#f8fafc" />',
            header_svg,
            f'  <g id="usable_area_layer">',
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
                    canvas.add_line(s[0]*scale_to_feet, s[1]*scale_to_feet, end[0]*scale_to_feet, end[1]*scale_to_feet, stroke="#e2e8f0", stroke_width=0.6)

def visualize_usable_area_for_region(u_reg, b_reg, o_reg, ext_reg, msp, scale_to_feet, output_path):
    canvas = UsableAreaSVGCanvas(width=1600, height=1200, margin_top=150, margin_bottom=60, margin_lr=80)
    raw_bbox = ext_reg["bounding_box"]
    bbox_ft = {
        "min_x": raw_bbox["min_x"] * scale_to_feet,
        "min_y": raw_bbox["min_y"] * scale_to_feet,
        "max_x": raw_bbox["max_x"] * scale_to_feet,
        "max_y": raw_bbox["max_y"] * scale_to_feet
    }
    canvas.set_bounds(bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"], padding_pct=0.06)

    # 1. Background interior wall lines (very light)
    render_background_walls(canvas, msp, (raw_bbox["min_x"], raw_bbox["min_y"], raw_bbox["max_x"], raw_bbox["max_y"]), scale_to_feet)

    # 2. Plan Region Bounding Box
    canvas.add_rect(
        bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"],
        stroke="#94a3b8", stroke_width=1.2, stroke_dash="6,4",
        title=f"Plan Region BBox: {u_reg['label']}"
    )

    # 3. Framing geometry if unclosed
    if u_reg["status"] == "UNUSABLE_NO_BOUNDARY":
        fg = ext_reg.get("framing_geometry")
        if fg and "points" in fg:
            scaled_f = [[p[0]*scale_to_feet, p[1]*scale_to_feet] for p in fg["points"]]
            canvas.add_polyline(
                scaled_f, closed=True,
                stroke="#2563eb", stroke_width=2.0, stroke_dash="8,4", fill="none",
                title=f"Framing Rectangle: [{fg['handle']}]"
            )
        # Prominent Unusable Banner
        cx = bbox_ft["min_x"] + (bbox_ft["max_x"] - bbox_ft["min_x"]) / 2.0
        cy = bbox_ft["min_y"] + (bbox_ft["max_y"] - bbox_ft["min_y"]) / 2.0
        scx, scy = canvas.world_to_svg(cx, cy)
        banner_w = 640
        banner_h = 44
        canvas.elements.append(
            f'<g transform="translate({scx - banner_w/2:.1f}, {scy - banner_h/2:.1f})">'
            f'  <rect width="{banner_w}" height="{banner_h}" rx="6" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.5" />'
            f'  <text x="{banner_w/2}" y="27" font-family="Inter, sans-serif" font-size="13" font-weight="700" fill="#92400e" text-anchor="middle">USABLE PLANNING AREA = NULL (NO VERIFIED CLOSED BOUNDARY)</text>'
            f'</g>'
        )

    # 4. Verified Usable Planning Area Polygon with Column Holes Cut Out
    if u_reg["usable_geometry"]:
        geom = u_reg["usable_geometry"]
        ext_pts = geom["exterior"]
        holes = geom.get("holes", [])
        canvas.add_polygon_with_holes(
            ext_pts, holes,
            stroke="#059669", stroke_width=3.0, fill="rgba(16, 185, 129, 0.20)",
            title=f"Usable Planning Area: {u_reg['usable_planning_area_sqft']:,.2f} sqft (Exterior minus {u_reg['hard_obstruction_count']} columns)"
        )

    # 5. Hard Exclusions: Structural Columns (Filled solid red inside the cut holes)
    for sub in u_reg.get("subtracted_geometry", []):
        c_cen = sub["center"]
        w = sub["width"]
        h = sub["height"]
        pts = [
            [c_cen[0] - w/2.0, c_cen[1] - h/2.0],
            [c_cen[0] + w/2.0, c_cen[1] - h/2.0],
            [c_cen[0] + w/2.0, c_cen[1] + h/2.0],
            [c_cen[0] - w/2.0, c_cen[1] + h/2.0]
        ]
        c_title = f"Hard Exclusion: Column [{sub['source_handle']}] | Area: {sub['area_sqft']} sqft"
        canvas.add_polyline(pts, closed=True, stroke="#991b1b", stroke_width=1.2, fill="#dc2626", title=c_title)

    # 6. Uncertain Obstructions (Rendered with fill='none' so they do NOT appear subtracted)
    # A. Stairs (Orange dashed outline)
    for st in o_reg["circulation"]["stairs"]:
        b = st["bounding_box_ft"]
        canvas.add_rect(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#ea580c", stroke_width=1.8, stroke_dash="6,4", fill="none",
            title=f"Uncertain: Staircase Footprint (Not Subtracted)"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "STAIR (UNCERTAIN)", "#c2410c", "#ffffff", "#ea580c")

    # B. Lifts (Indigo dashed outline)
    for lf in o_reg["circulation"]["lifts"]:
        b = lf["bounding_box_ft"]
        canvas.add_rect(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#4338ca", stroke_width=1.8, stroke_dash="6,4", fill="none",
            title=f"Uncertain: Lift Core [{lf['source_handle']}] (Line-based, Not Subtracted)"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "LIFT (UNCERTAIN)", "#3730a3", "#ffffff", "#4338ca")

    # C. Shafts / Ducts (Cyan dashed outline)
    for sh in o_reg["services"].get("shafts", []):
        b = sh["bounding_box_ft"]
        canvas.add_rect(
            b["min_x"], b["min_y"], b["max_x"], b["max_y"],
            stroke="#0891b2", stroke_width=1.8, stroke_dash="4,4", fill="none",
            title=f"Uncertain: Duct Opening (Line-based, Not Subtracted)"
        )
        canvas.add_badge((b["min_x"]+b["max_x"])/2.0, (b["min_y"]+b["max_y"])/2.0, "DUCT (UNCERTAIN)", "#0e7490", "#ffffff", "#0891b2")

    # D. Fixed Rooms (Toilets / Technical / Storage) (Amber dashed outline)
    for rm in o_reg["architectural"]["fixed_rooms"]:
        p = rm.get("position_ft")
        if p:
            canvas.add_rect(p[0]-3, p[1]-3, p[0]+3, p[1]+3, stroke="#d97706", stroke_width=1.5, stroke_dash="4,4", fill="none", title=f"Uncertain Room: {rm['label']}")
            lbl = "TOILET (UNCERTAIN)" if "TOILET" in rm.get("label", "") else "ROOM (UNCERTAIN)"
            canvas.add_badge(p[0], p[1], lbl, "#b45309", "#ffffff", "#d97706")

    # Legend and Header
    if u_reg["usable_planning_area_sqft"]:
        metrics_str = f"Gross: {u_reg['boundary_area_sqft']:,.2f} sqft  -  Hard Obs: {u_reg['hard_obstruction_area_sqft']:,.2f} sqft  =  USABLE: {u_reg['usable_planning_area_sqft']:,.2f} SQFT"
    else:
        metrics_str = "USABLE PLANNING AREA: NULL (INSUFFICIENT BOUNDARY EVIDENCE)"

    legend_items = [
        ("VERIFIED BOUNDARY", {"type": "line", "stroke": "#059669", "width": 3.0, "box_width": 170}),
        ("USABLE PLANNING AREA", {"type": "rect", "stroke": "#059669", "width": 1.5, "fill": "rgba(16, 185, 129, 0.25)", "box_width": 190}),
        ("HARD EXCLUSION (COLUMN)", {"type": "rect", "stroke": "#991b1b", "width": 1.2, "fill": "#dc2626", "box_width": 210}),
        ("UNCERTAIN (NOT SUBTRACTED)", {"type": "rect", "stroke": "#ea580c", "width": 1.8, "dash": "6,4", "fill": "none", "box_width": 230}),
        ("PLAN BBOX", {"type": "line", "stroke": "#94a3b8", "width": 1.2, "dash": "6,4", "box_width": 120}),
    ]

    header_svg = canvas.render_header(
        title_text=f"Usable Planning Area — {u_reg['label']}",
        subtitle_text=f"Deterministic Architectural Planning Area Model | Units: Feet",
        metrics_text=metrics_str,
        status=u_reg["status"],
        legend_items=legend_items
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(canvas.to_svg(header_svg))

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    area_dir = os.path.join(output_dir, "usable_area")
    os.makedirs(area_dir, exist_ok=True)

    areas_json = os.path.join(output_dir, "usable_planning_areas_v1.json")
    bound_json = os.path.join(output_dir, "floor_boundaries_v1.json")
    obs_json = os.path.join(output_dir, "planning_obstructions_v1.json")
    ext_json = os.path.join(output_dir, "extracted_geometry_v2.json")

    with open(areas_json, "r", encoding="utf-8") as f:
        areas_data = json.load(f)
    with open(bound_json, "r", encoding="utf-8") as f:
        bound_data = json.load(f)
    with open(obs_json, "r", encoding="utf-8") as f:
        obs_data = json.load(f)
    with open(ext_json, "r", encoding="utf-8") as f:
        ext_data = json.load(f)

    dhule_dxf = os.path.join(output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")

    # Dhule
    dh_doc = ezdxf.readfile(dhule_dxf)
    dh_msp = dh_doc.modelspace()
    dh_areas = areas_data["documents"][0]["regions"]
    dh_bounds = bound_data["documents"][0]["regions"]
    dh_obs = obs_data["documents"][0]["regions"]
    dh_ext = {r["id"]: r for r in ext_data["dhule"]["plan_regions"]}

    dh_filenames = {
        "dhule-basement": "dhule_basement_usable_area.svg",
        "dhule-ground": "dhule_ground_usable_area.svg",
        "dhule-first-floor": "dhule_first_usable_area.svg",
        "dhule-second-floor": "dhule_second_usable_area.svg",
        "dhule-third-floor": "dhule_third_usable_area.svg",
        "dhule-fourth-floor": "dhule_fourth_usable_area.svg",
    }

    print("=" * 80)
    print("GENERATING DHULE USABLE AREA VISUALIZATIONS")
    print("=" * 80)
    for idx, r in enumerate(dh_areas):
        rid = r["region_id"]
        fname = dh_filenames.get(rid, f"{rid}_usable_area.svg")
        fpath = os.path.join(area_dir, fname)
        visualize_usable_area_for_region(
            r, dh_bounds[idx], dh_obs[idx], dh_ext[rid], dh_msp, scale_to_feet=1.0, output_path=fpath
        )
        print(f"  [CREATED] {fname} ({r['label']}) | Usable: {r['usable_planning_area_sqft']} sqft")

    # Vadodara
    vad_doc = ezdxf.readfile(vadodara_dxf)
    vad_msp = vad_doc.modelspace()
    vad_areas = areas_data["documents"][1]["regions"]
    vad_bounds = bound_data["documents"][1]["regions"]
    vad_obs = obs_data["documents"][1]["regions"]
    vad_ext = {r["id"]: r for r in ext_data["vadodara"]["plan_regions"]}

    vad_filenames = {
        "vadodara-option-1": "vadodara_option1_usable_area.svg",
        "vadodara-option-2": "vadodara_option2_usable_area.svg"
    }

    print("\n" + "=" * 80)
    print("GENERATING VADODARA USABLE AREA VISUALIZATIONS")
    print("=" * 80)
    for idx, r in enumerate(vad_areas):
        rid = r["region_id"]
        fname = vad_filenames.get(rid, f"{rid}_usable_area.svg")
        fpath = os.path.join(area_dir, fname)
        visualize_usable_area_for_region(
            r, vad_bounds[idx], vad_obs[idx], vad_ext[rid], vad_msp, scale_to_feet=1.0/12.0, output_path=fpath
        )
        print(f"  [CREATED] {fname} ({r['label']}) | Usable: {r['usable_planning_area_sqft']} sqft")

    print("\n[ALL USABLE AREA VISUALIZATIONS GENERATED SUCCESSFULLY]")
    print(f"SVGs located in: {area_dir}")

if __name__ == "__main__":
    main()
