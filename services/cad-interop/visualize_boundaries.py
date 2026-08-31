#!/usr/bin/env python3
"""
visualize_boundaries.py
Milestone M1, Step 3 — Visualizes reconstructed and verified floor boundaries.
Renders SVG previews distinguishing Source CAD, Plan Region, Framing,
Existing Verified Boundary, Reconstructed Candidates with IDs/Confidence, and Structural Columns.
"""

import sys
import os
import json
import math
import html
import ezdxf

def get_entity_bbox(e):
    dxftype = e.dxftype()
    try:
        if dxftype in ['LWPOLYLINE', 'POLYLINE']:
            pts = list(e.get_points())
            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                return min(xs), min(ys), max(xs), max(ys)
        elif dxftype == 'LINE':
            s = e.dxf.start
            end = e.dxf.end
            return min(s[0], end[0]), min(s[1], end[1]), max(s[0], end[0]), max(s[1], end[1])
        elif dxftype in ['CIRCLE', 'ARC']:
            c = e.dxf.center
            r = e.dxf.radius
            return c[0] - r, c[1] - r, c[0] + r, c[1] + r
        elif hasattr(e, 'dxf') and hasattr(e.dxf, 'insert'):
            p = e.dxf.insert
            return p[0], p[1], p[0], p[1]
    except Exception:
        pass
    return None

class BoundarySVGCanvas:
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

    def render_header(self, title_text, subtitle_text, status, confidence, legend_items):
        status_colors = {
            "PENDING_EXCLUSIONS": ("#0369a1", "#e0f2fe", "#0284c7"), # Blue
            "VERIFIED": ("#15803d", "#dcfce7", "#166534"),           # Green
            "INSUFFICIENT_EVIDENCE": ("#b45309", "#fef3c7", "#d97706"), # Amber
        }
        badge_fg, badge_bg, badge_border = status_colors.get(status, ("#475569", "#f1f5f9", "#94a3b8"))

        header_elements = [
            f'<rect x="0" y="0" width="{self.width}" height="{self.margin_top - 20}" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />',
            # Title
            f'<text x="{self.margin_lr}" y="40" font-family="Inter, sans-serif" font-size="22" font-weight="700" fill="#0f172a">{html.escape(str(title_text))}</text>',
            # Subtitle
            f'<text x="{self.margin_lr}" y="66" font-family="Inter, sans-serif" font-size="13" fill="#475569">{html.escape(str(subtitle_text))}</text>',
            # Status Badge
            f'<g transform="translate({self.width - 320}, 24)">',
            f'  <rect x="0" y="0" width="240" height="34" rx="17" fill="{badge_bg}" stroke="{badge_border}" stroke-width="1.5" />',
            f'  <circle cx="20" cy="17" r="5" fill="{badge_fg}" />',
            f'  <text x="35" y="22" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="{badge_fg}">STATUS: {status}</text>',
            f'</g>',
            # Legend Bar
            f'<g transform="translate({self.margin_lr}, 95)">'
        ]

        lx = 0
        for label, style in legend_items:
            if style["type"] == "line":
                dash = f' stroke-dasharray="{style["dash"]}"' if "dash" in style else ""
                header_elements.append(f'<line x1="{lx}" y1="12" x2="{lx+28}" y2="12" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            elif style["type"] == "rect":
                fill = style.get("fill", "none")
                dash = f' stroke-dasharray="{style.get("dash", "")}"' if style.get("dash") else ""
                header_elements.append(f'<rect x="{lx}" y="4" width="22" height="15" rx="2" fill="{fill}" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            header_elements.append(f'<text x="{lx+34}" y="16" font-family="Inter, sans-serif" font-size="11" font-weight="600" fill="#334155">{html.escape(str(label))}</text>')
            lx += style.get("box_width", 160)

        header_elements.append('</g>')
        return "\n".join(header_elements)

    def to_svg(self, header_svg=""):
        svg = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}">',
            f'  <rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#f8fafc" />',
            header_svg,
            f'  <g id="boundaries_layer">',
            "\n".join(f"    {e}" for e in self.elements),
            f'  </g>',
            f'</svg>'
        ]
        return "\n".join(svg)

def render_cad_background(canvas, entities, region_bbox, scale_to_feet=1.0, padding=10.0):
    bx0, by0, bx1, by1 = region_bbox
    cx0 = (bx0 - padding) / scale_to_feet
    cy0 = (by0 - padding) / scale_to_feet
    cx1 = (bx1 + padding) / scale_to_feet
    cy1 = (by1 + padding) / scale_to_feet

    for e in entities:
        if e.dxf.layer == 'COLUMN (DCPL)':
            continue
        eb = get_entity_bbox(e)
        if not eb:
            continue
        if eb[2] < cx0 or eb[0] > cx1 or eb[3] < cy0 or eb[1] > cy1:
            continue

        l_name = str(e.dxf.layer)
        is_wall = 'wall' in l_name.lower()
        color = "#94a3b8" if is_wall else "#e2e8f0"
        width = 0.8 if is_wall else 0.5
        title_str = f"Handle: {e.dxf.handle} | Layer: {l_name}"

        dxftype = e.dxftype()
        if dxftype == 'LINE':
            s = e.dxf.start
            end = e.dxf.end
            canvas.add_line(s[0] * scale_to_feet, s[1] * scale_to_feet, end[0] * scale_to_feet, end[1] * scale_to_feet, stroke=color, stroke_width=width, title=title_str)
        elif dxftype in ['LWPOLYLINE', 'POLYLINE']:
            try:
                pts = list(e.get_points())
                if len(pts) >= 2:
                    scaled = [(p[0] * scale_to_feet, p[1] * scale_to_feet) for p in pts]
                    canvas.add_polyline(scaled, closed=getattr(e, 'closed', False), stroke=color, stroke_width=width, title=title_str)
            except Exception:
                pass

def visualize_region_boundary(region_data, ext_region, entities, scale_to_feet, output_path):
    canvas = BoundarySVGCanvas(width=1600, height=1200, margin_top=150, margin_bottom=60, margin_lr=80)
    raw_bbox = ext_region["bounding_box"]
    bbox_ft = {
        "min_x": raw_bbox["min_x"] * scale_to_feet,
        "min_y": raw_bbox["min_y"] * scale_to_feet,
        "max_x": raw_bbox["max_x"] * scale_to_feet,
        "max_y": raw_bbox["max_y"] * scale_to_feet
    }
    canvas.set_bounds(bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"], padding_pct=0.06)

    # 1. Source CAD background
    render_cad_background(canvas, entities, (bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"]), scale_to_feet=scale_to_feet, padding=8.0)

    # 2. Plan Region Bounding Box
    canvas.add_rect(
        bbox_ft["min_x"], bbox_ft["min_y"], bbox_ft["max_x"], bbox_ft["max_y"],
        stroke="#64748b", stroke_width=1.5, stroke_dash="6,4",
        title=f"Plan Region BBox: {region_data['label']}"
    )

    # 3. Framing Geometry (if present)
    fg = ext_region.get("framing_geometry")
    if fg and "points" in fg:
        scaled_f = [[p[0] * scale_to_feet, p[1] * scale_to_feet] for p in fg["points"]]
        canvas.add_polyline(
            scaled_f, closed=True,
            stroke="#2563eb", stroke_width=2.5, stroke_dash="10,5", fill="none",
            title=f"Framing Rectangle: [{fg['handle']}] | {fg['width']} x {fg['height']} ft | Area: {fg['area']} sqft"
        )

    # 4. Existing Verified Boundary (Dhule First - Fourth)
    bg = region_data.get("source_boundary")
    if bg and "points" in bg:
        canvas.add_polyline(
            bg["points"], closed=True,
            stroke="#059669", stroke_width=3.5, fill="rgba(16, 185, 129, 0.08)",
            title=f"Verified Exterior Wall Boundary [{bg['source_entity_handles'][0]}] | Area: {region_data['area']['gross']} sqft"
        )
        # Add label on top edge of boundary
        bx = bg["bounding_box"]["min_x"] + bg["width"] / 2.0
        by = bg["bounding_box"]["max_y"]
        sbx, sby = canvas.world_to_svg(bx, by)
        canvas.elements.append(
            f'<rect x="{sbx-140}" y="{sby-26}" width="280" height="22" rx="4" fill="#ecfdf5" stroke="#059669" stroke-width="1"/>'
            f'<text x="{sbx}" y="{sby-11}" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#065f46" text-anchor="middle">VERIFIED WALL BOUNDARY: {bg["width"]:.1f} x {bg["height"]:.1f} ft ({region_data["area"]["gross"]:,.1f} sqft)</text>'
        )

    # 5. Reconstructed Candidate Loops (For ambiguous / unclosed regions)
    candidate_loops = region_data.get("candidate_loops", [])
    loop_palette = [
        ("#7c3aed", "rgba(124, 58, 237, 0.06)"), # Purple
        ("#0284c7", "rgba(2, 132, 199, 0.06)"),  # Cyan
        ("#d97706", "rgba(217, 119, 6, 0.06)"),  # Amber
        ("#e11d48", "rgba(225, 29, 72, 0.06)"),   # Rose
        ("#4f46e5", "rgba(79, 70, 229, 0.06)"),  # Indigo
        ("#059669", "rgba(5, 150, 105, 0.06)"),  # Emerald
    ]

    for idx, loop in enumerate(candidate_loops):
        cls = loop.get("classification", "")
        # Skip verified boundary already drawn above
        if "loop-6A8" in loop.get("candidate_id", "") or "loop-1393" in loop.get("candidate_id", "") or "loop-177B" in loop.get("candidate_id", "") or "loop-21D8" in loop.get("candidate_id", ""):
            continue
        if cls == "title_block_frame":
            continue

        l_pts = loop.get("points") or (loop.get("geometry", {}).get("points") if "geometry" in loop else None)
        if l_pts:
            stroke_c, fill_c = loop_palette[idx % len(loop_palette)]
            cid = loop.get("candidate_id", f"Loop {idx+1}")
            conf = loop.get("confidence", "MEDIUM")
            l_area = loop.get("area") or loop.get("area_sqft", 0)
            c_title = f"{cid} | Conf: {conf} | Class: {cls} | Area: {l_area} sqft | Dim: {loop.get('dimensions', '')}"
            canvas.add_polyline(l_pts, closed=True, stroke=stroke_c, stroke_width=2.0, fill=fill_c, stroke_dash="6,3", title=c_title)

            # Draw small loop badge near centroid
            if len(l_pts) >= 3 and l_area > 100:
                cx = sum(p[0] for p in l_pts) / len(l_pts)
                cy = sum(p[1] for p in l_pts) / len(l_pts)
                scx, scy = canvas.world_to_svg(cx, cy)
                canvas.elements.append(
                    f'<g transform="translate({scx-60:.1f}, {scy-12:.1f})">'
                    f'  <rect width="120" height="22" rx="3" fill="#ffffff" stroke="{stroke_c}" stroke-width="1.2" />'
                    f'  <text x="60" y="15" font-family="Inter, sans-serif" font-size="10" font-weight="700" fill="{stroke_c}" text-anchor="middle">{cid}: {l_area:.0f} sqft</text>'
                    f'</g>'
                )

    # 6. If no verified boundary, render prominent banner
    if region_data["status"] == "INSUFFICIENT_EVIDENCE":
        cx = bbox_ft["min_x"] + (bbox_ft["max_x"] - bbox_ft["min_x"]) / 2.0
        cy = bbox_ft["max_y"] - (bbox_ft["max_y"] - bbox_ft["min_y"]) * 0.12
        scx, scy = canvas.world_to_svg(cx, cy)
        banner_w = 560
        banner_h = 36
        canvas.elements.append(
            f'<g transform="translate({scx - banner_w/2:.1f}, {scy - banner_h/2:.1f})">'
            f'  <rect width="{banner_w}" height="{banner_h}" rx="6" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.5" />'
            f'  <text x="{banner_w/2}" y="22" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#92400e" text-anchor="middle">BOUNDARY_RECONSTRUCTION_INSUFFICIENT_EVIDENCE — UNCLOSED PERIMETER</text>'
            f'</g>'
        )

    # 7. Structural Columns (red quads)
    for col in ext_region.get("structural_elements", []):
        pts = col["geometry"]["points"]
        scaled_c = [[p[0] * scale_to_feet, p[1] * scale_to_feet] for p in pts]
        h = col.get("source_entity_handle", "")
        c_title = f"Column [{h}] | Dim: {col.get('width',0)} x {col.get('height',0)} ft"
        canvas.add_polyline(scaled_c, closed=True, stroke="#991b1b", stroke_width=1.2, fill="#dc2626", title=c_title)

    # Legend Setup
    legend_items = [
        ("SOURCE CAD", {"type": "line", "stroke": "#94a3b8", "width": 1.0, "box_width": 130}),
        ("PLAN BBOX", {"type": "line", "stroke": "#64748b", "width": 1.5, "dash": "6,4", "box_width": 130}),
        ("FRAMING", {"type": "line", "stroke": "#2563eb", "width": 2.5, "dash": "10,5", "box_width": 130}),
        ("VERIFIED BOUNDARY", {"type": "rect", "stroke": "#059669", "width": 2.5, "fill": "rgba(16, 185, 129, 0.15)", "box_width": 170}),
        ("CANDIDATE LOOPS", {"type": "line", "stroke": "#7c3aed", "width": 2.0, "dash": "6,3", "box_width": 160}),
        ("COLUMNS", {"type": "rect", "stroke": "#991b1b", "width": 1.2, "fill": "#dc2626", "box_width": 120}),
    ]

    area_val = region_data.get("area", {}).get("gross")
    area_str = f"{area_val:,.1f} sqft" if area_val else "None (Unclosed)"
    subtitle = f"Plan: {region_data['label']} | Canonical Units: Feet | Area: {area_str} | Status: {region_data['status']}"
    header_svg = canvas.render_header(
        title_text=f"Boundary Verification — {region_data['label']}",
        subtitle_text=subtitle,
        status=region_data["status"],
        confidence=region_data["confidence"],
        legend_items=legend_items
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(canvas.to_svg(header_svg))

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    bound_dir = os.path.join(output_dir, "boundaries")
    os.makedirs(bound_dir, exist_ok=True)

    v1_json = os.path.join(output_dir, "floor_boundaries_v1.json")
    v2_ext_json = os.path.join(output_dir, "extracted_geometry_v2.json")

    with open(v1_json, "r", encoding="utf-8") as f:
        boundaries_data = json.load(f)
    with open(v2_ext_json, "r", encoding="utf-8") as f:
        ext_data = json.load(f)

    dhule_dxf = os.path.join(output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")

    # 1. Visualize Dhule Regions
    dh_doc = ezdxf.readfile(dhule_dxf)
    dh_entities = list(dh_doc.modelspace())
    dh_boundaries = boundaries_data["documents"][0]["regions"]
    dh_ext_regions = {r["id"]: r for r in ext_data["dhule"]["plan_regions"]}

    dh_filenames = {
        "dhule-basement": "dhule_basement_boundary.svg",
        "dhule-ground": "dhule_ground_boundary.svg",
        "dhule-first-floor": "dhule_first_boundary.svg",
        "dhule-second-floor": "dhule_second_boundary.svg",
        "dhule-third-floor": "dhule_third_boundary.svg",
        "dhule-fourth-floor": "dhule_fourth_boundary.svg",
    }

    print("=" * 80)
    print("GENERATING DHULE BOUNDARY VISUALIZATIONS")
    print("=" * 80)
    for r in dh_boundaries:
        rid = r["region_id"]
        fname = dh_filenames.get(rid, f"{rid}_boundary.svg")
        fpath = os.path.join(bound_dir, fname)
        visualize_region_boundary(r, dh_ext_regions[rid], dh_entities, scale_to_feet=1.0, output_path=fpath)
        print(f"  [CREATED] {fname} ({r['label']}) | Status: {r['status']}")

    # 2. Visualize Vadodara Regions
    vad_doc = ezdxf.readfile(vadodara_dxf)
    vad_entities = list(vad_doc.modelspace())
    vad_boundaries = boundaries_data["documents"][1]["regions"]
    vad_ext_regions = {r["id"]: r for r in ext_data["vadodara"]["plan_regions"]}

    vad_filenames = {
        "vadodara-option-1": "vadodara_option1_boundary.svg",
        "vadodara-option-2": "vadodara_option2_boundary.svg"
    }

    print("\n" + "=" * 80)
    print("GENERATING VADODARA BOUNDARY VISUALIZATIONS")
    print("=" * 80)
    for r in vad_boundaries:
        rid = r["region_id"]
        fname = vad_filenames.get(rid, f"{rid}_boundary.svg")
        fpath = os.path.join(bound_dir, fname)
        visualize_region_boundary(r, vad_ext_regions[rid], vad_entities, scale_to_feet=1.0/12.0, output_path=fpath)
        print(f"  [CREATED] {fname} ({r['label']}) | Status: {r['status']}")

    print("\n[ALL BOUNDARY VISUALIZATIONS GENERATED SUCCESSFULLY]")
    print(f"SVGs located in: {bound_dir}")

if __name__ == "__main__":
    main()
