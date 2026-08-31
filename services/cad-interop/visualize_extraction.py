#!/usr/bin/env python3
"""
visualize_extraction.py
Milestone M1, Step 2d — CAD Extraction Visual Verification.
Generates human-verifiable SVG visualizations of extracted plan regions,
framing geometry, boundary geometry, structural columns, and source CAD geometry.
Also runs automated sanity checks across all regions.
"""

import sys
import os
import argparse
import json
import math
import html
from collections import Counter
import ezdxf

def get_entity_bbox(e):
    """Compute 2D bounding box (min_x, min_y, max_x, max_y) for an entity."""
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

class SVGCanvas:
    """Helper class to build styled SVGs with CAD-to-SVG coordinate mapping."""
    def __init__(self, width=1600, height=1200, margin_top=140, margin_bottom=60, margin_lr=80):
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
        self.defs = []

    def set_bounds(self, min_x, min_y, max_x, max_y, padding_pct=0.08):
        """Set CAD world coordinates bounding box with padding."""
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

        # Center geometry inside drawing area
        rendered_w = world_w * self.scale
        rendered_h = world_h * self.scale
        self.offset_x = self.margin_lr + (self.draw_w - rendered_w) / 2.0
        self.offset_y = self.margin_top + (self.draw_h - rendered_h) / 2.0

    def world_to_svg(self, x, y):
        """Convert CAD world coordinates to SVG pixel coordinates (Y flipped)."""
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

    def add_polyline(self, pts, closed=False, stroke="#94a3b8", stroke_width=0.75, fill="none", stroke_dash=None, title=None, extra_class=""):
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
        cls_attr = f' class="{extra_class}"' if extra_class else ""
        elem = f'<path d="{d_str}" stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}"{dash_attr}{cls_attr}>'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</path>'
        self.elements.append(elem)

    def add_circle(self, cx, cy, r, stroke="#94a3b8", stroke_width=0.75, fill="none", title=None):
        scx, scy = self.world_to_svg(cx, cy)
        sr = r * self.scale
        elem = f'<circle cx="{scx:.1f}" cy="{scy:.1f}" r="{sr:.1f}" stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}">'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</circle>'
        self.elements.append(elem)

    def add_arc(self, cx, cy, r, start_deg, end_deg, stroke="#94a3b8", stroke_width=0.75, title=None):
        rad1 = math.radians(start_deg)
        rad2 = math.radians(end_deg)
        x1 = cx + r * math.cos(rad1)
        y1 = cy + r * math.sin(rad1)
        x2 = cx + r * math.cos(rad2)
        y2 = cy + r * math.sin(rad2)

        sx1, sy1 = self.world_to_svg(x1, y1)
        sx2, sy2 = self.world_to_svg(x2, y2)
        sr = r * self.scale

        sweep_deg = (end_deg - start_deg) % 360.0
        large_arc = 1 if sweep_deg > 180 else 0
        # In SVG (inverted Y), standard CCW arc has sweep-flag = 0
        sweep_flag = 0

        d = f"M {sx1:.1f} {sy1:.1f} A {sr:.1f} {sr:.1f} 0 {large_arc} {sweep_flag} {sx2:.1f} {sy2:.1f}"
        elem = f'<path d="{d}" stroke="{stroke}" stroke-width="{stroke_width}" fill="none">'
        if title:
            elem += f'<title>{html.escape(str(title))}</title>'
        elem += '</path>'
        self.elements.append(elem)

    def add_rect(self, min_x, min_y, max_x, max_y, stroke="#2563eb", stroke_width=2.0, fill="none", stroke_dash=None, title=None):
        pts = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        self.add_polyline(pts, closed=True, stroke=stroke, stroke_width=stroke_width, fill=fill, stroke_dash=stroke_dash, title=title)

    def render_header(self, title_text, subtitle_text, validation_status, units, legend_items):
        """Render top banner, legend, and validation pill."""
        status_colors = {
            "PASS": ("#15803d", "#dcfce7", "#166534"),
            "WARNING": ("#b45309", "#fef3c7", "#92400e"),
            "FAIL": ("#b91c1c", "#fee2e2", "#991b1b"),
        }
        val_fg, val_bg, val_border = status_colors.get(validation_status, ("#475569", "#f1f5f9", "#334155"))

        header_elements = [
            f'<rect x="0" y="0" width="{self.width}" height="{self.margin_top - 20}" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />',
            # Title
            f'<text x="{self.margin_lr}" y="42" font-family="Inter, sans-serif" font-size="22" font-weight="700" fill="#0f172a">{html.escape(str(title_text))}</text>',
            # Subtitle
            f'<text x="{self.margin_lr}" y="70" font-family="Inter, sans-serif" font-size="13" fill="#475569">{html.escape(str(subtitle_text))}</text>',
            # Status Badge
            f'<g transform="translate({self.width - 240}, 26)">',
            f'  <rect x="0" y="0" width="160" height="32" rx="16" fill="{val_bg}" stroke="{val_border}" stroke-width="1" />',
            f'  <circle cx="20" cy="16" r="5" fill="{val_fg}" />',
            f'  <text x="35" y="21" font-family="Inter, sans-serif" font-size="13" font-weight="600" fill="{val_fg}">VALIDATION: {validation_status}</text>',
            f'</g>',
            # Legend Bar
            f'<g transform="translate({self.margin_lr}, 95)">'
        ]

        # Draw legend items
        lx = 0
        for label, style in legend_items:
            # swatch
            if style["type"] == "line":
                dash = f' stroke-dasharray="{style["dash"]}"' if "dash" in style else ""
                header_elements.append(f'<line x1="{lx}" y1="10" x2="{lx+30}" y2="10" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            elif style["type"] == "rect":
                fill = style.get("fill", "none")
                dash = f' stroke-dasharray="{style.get("dash", "")}"' if style.get("dash") else ""
                header_elements.append(f'<rect x="{lx}" y="3" width="24" height="14" rx="2" fill="{fill}" stroke="{style["stroke"]}" stroke-width="{style["width"]}"{dash} />')
            header_elements.append(f'<text x="{lx+38}" y="14" font-family="Inter, sans-serif" font-size="12" font-weight="500" fill="#334155">{html.escape(str(label))}</text>')
            lx += style.get("box_width", 170)

        header_elements.append('</g>')
        return "\n".join(header_elements)

    def to_svg(self, header_svg=""):
        """Assemble complete SVG document."""
        svg = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}">',
            f'  <rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#f8fafc" />',
            header_svg,
            f'  <g id="geometry_layer">',
            "\n".join(f"    {e}" for e in self.elements),
            f'  </g>',
            f'</svg>'
        ]
        return "\n".join(svg)

def render_cad_source_elements(canvas, entities, region_bbox, padding=10.0):
    """Render relevant background CAD entities that fall within the region bbox."""
    bx0, by0, bx1, by1 = region_bbox
    crop_x0 = bx0 - padding
    crop_y0 = by0 - padding
    crop_x1 = bx1 + padding
    crop_y1 = by1 + padding

    for e in entities:
        dxftype = e.dxftype()
        layer = str(e.dxf.layer)

        # Skip column entities on COLUMN (DCPL) because they are rendered distinctly in the structural layer
        if layer == 'COLUMN (DCPL)':
            continue

        eb = get_entity_bbox(e)
        if not eb:
            continue
        # Check intersection with crop bbox
        if eb[2] < crop_x0 or eb[0] > crop_x1 or eb[3] < crop_y0 or eb[1] > crop_y1:
            continue

        # Choose subtle styling based on layer
        is_wall = 'wall' in layer.lower() or 'wall_tmos' in layer.lower()
        color = "#64748b" if is_wall else "#cbd5e1"
        width = 1.0 if is_wall else 0.5
        h_str = f"Handle: {e.dxf.handle} | Layer: {layer}"

        if dxftype == 'LINE':
            s = e.dxf.start
            end = e.dxf.end
            canvas.add_line(s[0], s[1], end[0], end[1], stroke=color, stroke_width=width, title=h_str)
        elif dxftype in ['LWPOLYLINE', 'POLYLINE']:
            try:
                pts = list(e.get_points())
                if len(pts) >= 2:
                    is_closed = getattr(e, 'closed', False)
                    canvas.add_polyline([(p[0], p[1]) for p in pts], closed=is_closed, stroke=color, stroke_width=width, title=h_str)
            except Exception:
                pass
        elif dxftype == 'CIRCLE':
            c = e.dxf.center
            r = e.dxf.radius
            canvas.add_circle(c[0], c[1], r, stroke=color, stroke_width=width, title=h_str)
        elif dxftype == 'ARC':
            c = e.dxf.center
            r = e.dxf.radius
            canvas.add_arc(c[0], c[1], r, e.dxf.start_angle, e.dxf.end_angle, stroke=color, stroke_width=width, title=h_str)

def run_automated_sanity_checks(dhule_doc, vadodara_doc):
    """Run Part 9 Automated Sanity Checks across both drawings."""
    failures = []
    results = []

    # Check 1: Non-empty bounding box for every region
    all_regions = dhule_doc.get("plan_regions", []) + vadodara_doc.get("plan_regions", [])
    for r in all_regions:
        if r["width"] <= 0 or r["height"] <= 0:
            failures.append(f"Check 1 Failed: Region '{r['id']}' has empty bounding box ({r['width']} x {r['height']}).")
    results.append(("Check 1: Non-empty bounding box for every PlanRegion", len(failures) == 0))

    # Check 2: No PlanRegion overlaps another Dhule floor-plan region substantially
    dhule_regions = dhule_doc.get("plan_regions", [])
    overlap_fail = False
    for i in range(len(dhule_regions)):
        for j in range(i + 1, len(dhule_regions)):
            b1 = dhule_regions[i]["bounding_box"]
            b2 = dhule_regions[j]["bounding_box"]
            overlap_x = max(0.0, min(b1["max_x"], b2["max_x"]) - max(b1["min_x"], b2["min_x"]))
            overlap_y = max(0.0, min(b1["max_y"], b2["max_y"]) - max(b1["min_y"], b2["min_y"]))
            overlap_area = overlap_x * overlap_y
            if overlap_area > 0.0:
                overlap_fail = True
                failures.append(f"Check 2 Failed: Substantial overlap between '{dhule_regions[i]['id']}' and '{dhule_regions[j]['id']}': {overlap_area:.2f} sq units.")
    results.append(("Check 2: No substantial overlap between Dhule floor plans", not overlap_fail))

    # Check 3: No extracted Dhule column lies far outside its assigned PlanRegion
    col_bounds_fail = False
    for r in dhule_regions:
        bbox = r["bounding_box"]
        for c in r.get("structural_elements", []):
            cb = c["bounding_box"]
            cx = (cb["min_x"] + cb["max_x"]) / 2.0
            cy = (cb["min_y"] + cb["max_y"]) / 2.0
            if not (bbox["min_x"] <= cx <= bbox["max_x"] and bbox["min_y"] <= cy <= bbox["max_y"]):
                col_bounds_fail = True
                failures.append(f"Check 3 Failed: Column '{c['id']}' at ({cx:.1f}, {cy:.1f}) outside region '{r['id']}'.")
    results.append(("Check 3: Dhule columns spatially contained in assigned PlanRegion", not col_bounds_fail))

    # Check 4: No extracted column has zero/negative dimensions
    dim_fail = False
    for r in all_regions:
        for c in r.get("structural_elements", []):
            if c.get("width", 0) <= 0 or c.get("height", 0) <= 0:
                dim_fail = True
                failures.append(f"Check 4 Failed: Column '{c['id']}' in '{r['id']}' has invalid dimensions.")
    results.append(("Check 4: Non-zero positive dimensions for all structural columns", not dim_fail))

    # Check 5: No extracted column comes from known plumbing layers
    plumbing_layers = {'COLD WATER', '4. UPCV', '4 upvc pip', 'P_DOMESTIC'}
    plumb_fail = False
    for r in all_regions:
        for c in r.get("structural_elements", []):
            if c.get("layer") in plumbing_layers:
                plumb_fail = True
                failures.append(f"Check 5 Failed: Column '{c['id']}' comes from plumbing layer '{c.get('layer')}'.")
    results.append(("Check 5: No columns from known plumbing layers", not plumb_fail))

    # Check 6: No boundary_geometry equals the known overall drawing frame
    known_frames = {'2A1A', '8285A'}
    frame_bound_fail = False
    for r in all_regions:
        bg = r.get("boundary_geometry")
        if bg and bg.get("handle") in known_frames:
            frame_bound_fail = True
            failures.append(f"Check 6 Failed: Region '{r['id']}' uses known overall drawing frame [{bg.get('handle')}] as boundary.")
    results.append(("Check 6: No boundary_geometry equals overall drawing frame", not frame_bound_fail))

    # Check 7: Framing geometry and boundary geometry remain separate
    separate_fail = False
    for r in all_regions:
        fg = r.get("framing_geometry")
        bg = r.get("boundary_geometry")
        if fg and bg and fg.get("handle") == bg.get("handle"):
            separate_fail = True
            failures.append(f"Check 7 Failed: Region '{r['id']}' conflates framing and boundary geometry [{fg.get('handle')}].")
    results.append(("Check 7: Framing geometry and boundary geometry remain separate", not separate_fail))

    # Check 8: Number of extracted PlanRegions is Dhule=6, Vadodara=3 (2 zoning options)
    vadodara_regions = vadodara_doc.get("plan_regions", [])
    count_fail = False
    if len(dhule_regions) != 6:
        count_fail = True
        failures.append(f"Check 8 Failed: Dhule region count is {len(dhule_regions)} (expected 6).")
    if len(vadodara_regions) != 3:
        count_fail = True
        failures.append(f"Check 8 Failed: Vadodara region count is {len(vadodara_regions)} (expected 3).")
    vad_options = [r for r in vadodara_regions if "Option" in r.get("label", "")]
    if len(vad_options) != 2:
        count_fail = True
        failures.append(f"Check 8 Failed: Vadodara zoning option count is {len(vad_options)} (expected 2).")
    results.append(("Check 8: Region counts match expected (Dhule=6, Vadodara=3 [2 options])", not count_fail))

    return {
        "status": "FAIL" if failures else "PASS",
        "checks": results,
        "failures": failures
    }

def generate_region_svg(region, units, entities, output_path):
    """Generate high-clarity SVG for a single PlanRegion."""
    canvas = SVGCanvas(width=1600, height=1200, margin_top=140, margin_bottom=60, margin_lr=80)
    bbox = region["bounding_box"]
    canvas.set_bounds(bbox["min_x"], bbox["min_y"], bbox["max_x"], bbox["max_y"], padding_pct=0.06)

    # 1. Source CAD entities in background
    render_cad_source_elements(canvas, entities, (bbox["min_x"], bbox["min_y"], bbox["max_x"], bbox["max_y"]), padding=8.0)

    # 2. Plan Region Bounding Box (slate dashed)
    canvas.add_rect(
        bbox["min_x"], bbox["min_y"], bbox["max_x"], bbox["max_y"],
        stroke="#64748b", stroke_width=1.5, stroke_dash="6,4",
        title=f"Plan Region BBox: {region['label']} ({region['width']} x {region['height']} {units})"
    )

    # 3. Framing Geometry (bold blue dashed)
    fg = region.get("framing_geometry")
    if fg and "points" in fg:
        f_pts = fg["points"]
        canvas.add_polyline(
            f_pts, closed=True,
            stroke="#2563eb", stroke_width=2.5, stroke_dash="10,5", fill="rgba(37, 99, 235, 0.03)",
            title=f"Framing Rectangle: [{fg['handle']}] Layer: {fg['layer']} | Area: {fg['area']} sq {units}"
        )

    # 4. Boundary Geometry (prominent green solid)
    bg = region.get("boundary_geometry")
    if bg and "points" in bg:
        b_pts = bg["points"]
        canvas.add_polyline(
            b_pts, closed=True,
            stroke="#16a34a", stroke_width=3.0, fill="rgba(22, 163, 74, 0.08)",
            title=f"Verified Exterior Boundary: [{bg['handle']}] Layer: {bg['layer']} | Area: {bg['area']} sq {units}"
        )
    else:
        # Overlay note for NO VERIFIED CLOSED BOUNDARY
        center_x = (bbox["min_x"] + bbox["max_x"]) / 2.0
        center_y = bbox["max_y"] - (bbox["max_y"] - bbox["min_y"]) * 0.12
        scx, scy = canvas.world_to_svg(center_x, center_y)
        banner_w = 460
        banner_h = 32
        canvas.elements.append(
            f'<g transform="translate({scx - banner_w/2:.1f}, {scy - banner_h/2:.1f})">'
            f'  <rect width="{banner_w}" height="{banner_h}" rx="6" fill="#fef2f2" stroke="#f87171" stroke-width="1.5" />'
            f'  <text x="{banner_w/2}" y="20" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#991b1b" text-anchor="middle">NO VERIFIED CLOSED BOUNDARY — COMPOSITE WALL SEGMENTS</text>'
            f'</g>'
        )

    # 5. Structural Columns (bold red quads with tooltips)
    for col in region.get("structural_elements", []):
        pts = col["geometry"]["points"]
        h = col.get("source_entity_handle", "")
        layer = col.get("layer", "")
        w = col.get("width", 0)
        height = col.get("height", 0)
        conf = col.get("confidence", "high")
        c_title = f"Column col-{h} | Handle: [{h}] | Layer: {layer} | Dim: {w} x {height} {units} | Conf: {conf}"
        canvas.add_polyline(
            pts, closed=True,
            stroke="#991b1b", stroke_width=1.5, fill="#dc2626",
            title=c_title
        )

    # Header Legend Setup
    legend_items = [
        ("SOURCE CAD", {"type": "line", "stroke": "#94a3b8", "width": 1.0, "box_width": 140}),
        ("FRAMING RECTANGLE", {"type": "line", "stroke": "#2563eb", "width": 2.5, "dash": "10,5", "box_width": 180}),
        ("EXTERIOR BOUNDARY", {"type": "rect", "stroke": "#16a34a", "width": 2.5, "fill": "rgba(22, 163, 74, 0.15)", "box_width": 190}),
        ("STRUCTURAL COLUMNS", {"type": "rect", "stroke": "#991b1b", "width": 1.5, "fill": "#dc2626", "box_width": 200}),
        ("PLAN BBOX", {"type": "line", "stroke": "#64748b", "width": 1.5, "dash": "6,4", "box_width": 140}),
    ]

    val_status = region.get("validation", {}).get("status", "PASS")
    subtitle = f"Region Dimensions: {region['width']} x {region['height']} {units} | Entities: {region.get('total_entities_count', 0)} | Columns: {len(region.get('structural_elements', []))}"
    header_svg = canvas.render_header(
        title_text=f"{region['label']}",
        subtitle_text=subtitle,
        validation_status=val_status,
        units=units,
        legend_items=legend_items
    )

    full_svg = canvas.to_svg(header_svg)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_svg)

def generate_overview_svg(doc_data, entities, output_path, title_prefix="Overview"):
    """Generate wide full-drawing overview preview showing all regions side by side."""
    canvas = SVGCanvas(width=2000, height=900, margin_top=130, margin_bottom=50, margin_lr=60)
    regions = doc_data.get("plan_regions", [])
    if not regions:
        return

    units = doc_data.get("units", "Units")
    all_min_x = min(r["bounding_box"]["min_x"] for r in regions)
    all_min_y = min(r["bounding_box"]["min_y"] for r in regions)
    all_max_x = max(r["bounding_box"]["max_x"] for r in regions)
    all_max_y = max(r["bounding_box"]["max_y"] for r in regions)

    canvas.set_bounds(all_min_x, all_min_y, all_max_x, all_max_y, padding_pct=0.04)

    # Render source entities in background
    render_cad_source_elements(canvas, entities, (all_min_x, all_min_y, all_max_x, all_max_y), padding=10.0)

    # Render each region
    for r in regions:
        bbox = r["bounding_box"]
        canvas.add_rect(bbox["min_x"], bbox["min_y"], bbox["max_x"], bbox["max_y"], stroke="#64748b", stroke_width=1.5, stroke_dash="6,4")

        # Framing
        fg = r.get("framing_geometry")
        if fg and "points" in fg:
            canvas.add_polyline(fg["points"], closed=True, stroke="#2563eb", stroke_width=2.0, stroke_dash="8,4")

        # Boundary
        bg = r.get("boundary_geometry")
        if bg and "points" in bg:
            canvas.add_polyline(bg["points"], closed=True, stroke="#16a34a", stroke_width=2.5, fill="rgba(22, 163, 74, 0.08)")

        # Columns
        for col in r.get("structural_elements", []):
            canvas.add_polyline(col["geometry"]["points"], closed=True, stroke="#991b1b", stroke_width=1.0, fill="#dc2626")

        # Label above region
        cx = (bbox["min_x"] + bbox["max_x"]) / 2.0
        cy = bbox["max_y"]
        scx, scy = canvas.world_to_svg(cx, cy)
        canvas.elements.append(
            f'<text x="{scx:.1f}" y="{scy - 10:.1f}" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#0f172a" text-anchor="middle">{html.escape(str(r["label"]))}</text>'
        )

    legend_items = [
        ("SOURCE CAD", {"type": "line", "stroke": "#94a3b8", "width": 1.0, "box_width": 140}),
        ("FRAMING", {"type": "line", "stroke": "#2563eb", "width": 2.0, "dash": "8,4", "box_width": 140}),
        ("BOUNDARY", {"type": "rect", "stroke": "#16a34a", "width": 2.0, "fill": "rgba(22, 163, 74, 0.15)", "box_width": 150}),
        ("COLUMNS", {"type": "rect", "stroke": "#991b1b", "width": 1.0, "fill": "#dc2626", "box_width": 150}),
    ]

    header_svg = canvas.render_header(
        title_text=f"{title_prefix} — Full Model Space Regions Overview",
        subtitle_text=f"Total Regions: {len(regions)} | Units: {units}",
        validation_status="PASS",
        units=units,
        legend_items=legend_items
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(canvas.to_svg(header_svg))

def main():
    parser = argparse.ArgumentParser(description="Generate CAD extraction SVG visual verifications.")
    parser.add_argument("--dxf", type=str, help="Path to input DXF file.")
    parser.add_argument("--json", type=str, help="Path to extracted_geometry_v2.json.")
    parser.add_argument("--output", type=str, help="Path to output SVG preview or visualization directory.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_output_dir = os.path.join(base_dir, "test", "output")
    vis_dir = os.path.join(test_output_dir, "visualizations")
    os.makedirs(vis_dir, exist_ok=True)

    json_path = args.json or os.path.join(test_output_dir, "extracted_geometry_v2.json")
    if not os.path.exists(json_path):
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        extracted_data = json.load(f)

    dhule_data = extracted_data["dhule"]
    vadodara_data = extracted_data["vadodara"]

    # 1. Automated Sanity Checks
    print("\n" + "=" * 80)
    print("RUNNING AUTOMATED SANITY CHECKS (PART 9)")
    print("=" * 80)
    sanity_results = run_automated_sanity_checks(dhule_data, vadodara_data)
    for check_desc, passed in sanity_results["checks"]:
        mark = "[PASS]" if passed else "[FAIL]"
        print(f"  {mark} {check_desc}")

    if sanity_results["status"] == "FAIL":
        print("\nSANITY CHECKS FAILED:")
        for fail_msg in sanity_results["failures"]:
            print(f"  * {fail_msg}")
        sys.exit(1)
    else:
        print("\nALL 8 AUTOMATED SANITY CHECKS PASSED 100%!")

    # 2. Generate Visualizations
    dhule_dxf = os.path.join(test_output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(test_output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")

    process_dhule = True
    process_vadodara = True

    if args.dxf:
        dxf_lower = args.dxf.lower()
        if "dhule" in dxf_lower or "1022" in dxf_lower:
            dhule_dxf = args.dxf
            process_vadodara = False
        elif "vadodara" in dxf_lower or "1045" in dxf_lower:
            vadodara_dxf = args.dxf
            process_dhule = False

    visualization_report = {
        "report_title": "Connplex Zoning Studio — CAD Extraction Visual Verification Report",
        "sanity_checks_status": sanity_results["status"],
        "documents": []
    }

    # Generate Dhule visualizations
    if process_dhule and os.path.exists(dhule_dxf):
        print("\n" + "-" * 80)
        print(f"Generating Dhule Visualizations from: {os.path.basename(dhule_dxf)}")
        print("-" * 80)
        doc_dh = ezdxf.readfile(dhule_dxf)
        dh_entities = list(doc_dh.modelspace())
        dh_units = dhule_data.get("units", "Feet")

        dh_filenames = {
            "dhule-basement": "dhule_basement.svg",
            "dhule-ground": "dhule_ground.svg",
            "dhule-first-floor": "dhule_first.svg",
            "dhule-second-floor": "dhule_second.svg",
            "dhule-third-floor": "dhule_third.svg",
            "dhule-fourth-floor": "dhule_fourth.svg"
        }

        dh_doc_report = {
            "source_file": dhule_data["source_file"],
            "units": dh_units,
            "regions": []
        }

        for r in dhule_data["plan_regions"]:
            rid = r["id"]
            fname = dh_filenames.get(rid, f"{rid}.svg")
            fpath = os.path.join(vis_dir, fname)
            generate_region_svg(r, dh_units, dh_entities, fpath)
            print(f"  [CREATED] {fname} ({r['label']}) | Cols: {len(r['structural_elements'])}")

            dh_doc_report["regions"].append({
                "id": rid,
                "label": r["label"],
                "preview_file": os.path.relpath(fpath, test_output_dir),
                "bounding_box": r["bounding_box"],
                "framing": f"{r['framing_geometry']['width']} x {r['framing_geometry']['height']} ft (Area: {r['framing_geometry']['area']} sq ft)" if r.get("framing_geometry") else "none",
                "boundary_verified": r.get("boundary_geometry") is not None,
                "boundary_status": "EXPLICIT_WALL_BOUNDARY_FOUND" if r.get("boundary_geometry") else "NO_VERIFIED_CLOSED_BOUNDARY",
                "column_count": len(r.get("structural_elements", [])),
                "validation": r.get("validation", {}).get("status", "PASS")
            })

        # Generate overview
        dh_overview = os.path.join(vis_dir, "dhule_overview.svg")
        generate_overview_svg(dhule_data, dh_entities, dh_overview, title_prefix="DHULE")
        print(f"  [CREATED] dhule_overview.svg (All 6 Floor Plans Overview)")

        # If --output argument specified, write there too
        if args.output and not process_vadodara:
            import shutil
            shutil.copyfile(dh_overview, args.output)
            print(f"  [COPIED] {args.output}")

        visualization_report["documents"].append(dh_doc_report)

    # Generate Vadodara visualizations
    if process_vadodara and os.path.exists(vadodara_dxf):
        print("\n" + "-" * 80)
        print(f"Generating Vadodara Visualizations from: {os.path.basename(vadodara_dxf)}")
        print("-" * 80)
        doc_vad = ezdxf.readfile(vadodara_dxf)
        vad_entities = list(doc_vad.modelspace())
        vad_units = vadodara_data.get("units", "Inches")

        vad_filenames = {
            "vadodara-option-1": "vadodara_option1.svg",
            "vadodara-option-2": "vadodara_option2.svg",
            "vadodara-area-schedule": "vadodara_schedule.svg"
        }

        vad_doc_report = {
            "source_file": vadodara_data["source_file"],
            "units": vad_units,
            "regions": []
        }

        for r in vadodara_data["plan_regions"]:
            rid = r["id"]
            fname = vad_filenames.get(rid, f"{rid}.svg")
            fpath = os.path.join(vis_dir, fname)
            generate_region_svg(r, vad_units, vad_entities, fpath)
            print(f"  [CREATED] {fname} ({r['label']}) | Cols: {len(r['structural_elements'])}")

            vad_doc_report["regions"].append({
                "id": rid,
                "label": r["label"],
                "preview_file": os.path.relpath(fpath, test_output_dir),
                "bounding_box": r["bounding_box"],
                "framing": "none",
                "boundary_verified": r.get("boundary_geometry") is not None,
                "boundary_status": "EXPLICIT_WALL_BOUNDARY_FOUND" if r.get("boundary_geometry") else "NO_VERIFIED_CLOSED_BOUNDARY",
                "column_count": len(r.get("structural_elements", [])),
                "validation": r.get("validation", {}).get("status", "PASS")
            })

        # Generate overview
        vad_overview = os.path.join(vis_dir, "vadodara_overview.svg")
        generate_overview_svg(vadodara_data, vad_entities, vad_overview, title_prefix="VADODARA")
        print(f"  [CREATED] vadodara_overview.svg (Cinema Zoning Overview)")

        if args.output and not process_dhule:
            import shutil
            shutil.copyfile(vad_overview, args.output)
            print(f"  [COPIED] {args.output}")

        visualization_report["documents"].append(vad_doc_report)

    # Save visualization report JSON
    report_json_path = os.path.join(test_output_dir, "visualization_report.json")
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(visualization_report, f, indent=2)
    print(f"\n[REPORT SAVED] {report_json_path}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
