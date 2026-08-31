#!/usr/bin/env python3
"""
inspect_layers.py
Inspects layer structure in DXF files, breaking down entity counts by layer
for Model Space and Paper Space layouts separately.
Identifies the layer and space of the oversized rectangle picked as floor_boundary.
"""

import sys
import os
import math
from collections import Counter
import ezdxf

def polygon_area(pts: list[tuple[float, float]]) -> float:
    """Calculate enclosed area using Shoelace formula."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
    return abs(area) / 2.0

def inspect_layers(dxf_path: str):
    if not os.path.isfile(dxf_path):
        print(f"Error: File not found: {dxf_path}", file=sys.stderr)
        sys.exit(1)

    filename = os.path.basename(dxf_path)
    doc = ezdxf.readfile(dxf_path)

    print("=" * 80)
    print(f"DXF LAYER INSPECTION: {filename}")
    print("=" * 80)

    # 1. Inspect Model Space
    msp = doc.modelspace()
    msp_layers = Counter(e.dxf.layer for e in msp)
    print(f"\n1. MODEL SPACE (paperspace = 0)")
    print(f"   Total entities: {len(msp)}")
    print(f"   Distinct layers: {len(msp_layers)}")
    print(f"   {'-'*55}")
    print(f"   {'Layer Name':<35} | {'Entity Count':>15}")
    print(f"   {'-'*55}")
    for layer, count in msp_layers.most_common():
        print(f"   {layer:<35} | {count:>15}")

    # 2. Inspect Paper Space layouts
    psp_layouts = [l for l in doc.layouts if l.is_any_paperspace]
    print(f"\n2. PAPER SPACE LAYOUTS (paperspace != 0)")
    print(f"   Number of paper space layouts: {len(psp_layouts)}")
    for layout in psp_layouts:
        psp_layers = Counter(e.dxf.layer for e in layout)
        print(f"\n   Layout Name: \"{layout.name}\" (paperspace = 1)")
        print(f"   Total entities: {len(layout)}")
        print(f"   Distinct layers: {len(psp_layers)}")
        print(f"   {'-'*55}")
        print(f"   {'Layer Name':<35} | {'Entity Count':>15}")
        print(f"   {'-'*55}")
        for layer, count in psp_layers.most_common():
            print(f"   {layer:<35} | {count:>15}")

    # 3. Identify closed polylines in Model Space vs Paper Space
    msp_polys = []
    psp_polys = []

    for e in doc.entities:
        if e.dxftype() in ["LWPOLYLINE", "POLYLINE"]:
            try:
                raw_pts = [(float(p[0]), float(p[1])) for p in e.get_points()]
                is_closed = getattr(e, "closed", False)
                pts = raw_pts
                if not is_closed and len(raw_pts) > 2:
                    if math.hypot(raw_pts[0][0] - raw_pts[-1][0], raw_pts[0][1] - raw_pts[-1][1]) < 1e-4:
                        is_closed = True
                        pts = raw_pts[:-1]
                elif is_closed and len(raw_pts) > 2 and math.hypot(raw_pts[0][0] - raw_pts[-1][0], raw_pts[0][1] - raw_pts[-1][1]) < 1e-4:
                    pts = raw_pts[:-1]

                if is_closed and len(pts) >= 3:
                    area = polygon_area(pts)
                    ps_flag = e.dxf.get("paperspace", 0)
                    space_name = "Paper Space" if ps_flag != 0 else "Model Space"
                    item = (area, e.dxf.layer, space_name, ps_flag, pts)
                    if ps_flag == 0:
                        msp_polys.append(item)
                    else:
                        psp_polys.append(item)
            except Exception:
                pass

    msp_polys.sort(key=lambda x: x[0], reverse=True)
    psp_polys.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "=" * 80)
    print("OVERSIZED RECTANGLE IDENTIFICATION (From Step 2 Heuristic)")
    print("=" * 80)
    
    print("\nA. MODEL SPACE: Largest Closed Polylines (Step 2 searched Model Space)")
    if msp_polys:
        top_msp = msp_polys[0]
        pts = top_msp[4]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        print(f"   [PICKED IN STEP 2 AS FLOOR_BOUNDARY]")
        print(f"   - Layer Name:         '{top_msp[1]}'")
        print(f"   - Space:              {top_msp[2]} (paperspace = {top_msp[3]})")
        print(f"   - Enclosed Area:      {top_msp[0]:,.2f}")
        print(f"   - Bounding Box:       {w:.2f} x {h:.2f}")
        print(f"   - Point Count:        {len(pts)}")
        print(f"   - Vertices:           {pts}")

        print(f"\n   Top 5 largest in Model Space:")
        for idx, cp in enumerate(msp_polys[:5], 1):
            c_xs = [p[0] for p in cp[4]]
            c_ys = [p[1] for p in cp[4]]
            cw = max(c_xs) - min(c_xs)
            ch = max(c_ys) - min(c_ys)
            print(f"     {idx}. Area: {cp[0]:>14,.2f} | Layer: '{cp[1]:<18}' | Dim: {cw:.2f} x {ch:.2f}")
    else:
        print("   No closed polylines found in Model Space.")

    print("\nB. PAPER SPACE: Largest Closed Polylines")
    if psp_polys:
        for idx, cp in enumerate(psp_polys[:5], 1):
            c_xs = [p[0] for p in cp[4]]
            c_ys = [p[1] for p in cp[4]]
            cw = max(c_xs) - min(c_xs)
            ch = max(c_ys) - min(c_ys)
            print(f"     {idx}. Area: {cp[0]:>14,.2f} | Layer: '{cp[1]:<18}' | Dim: {cw:.2f} x {ch:.2f}")
    else:
        print("   No closed polylines found in Paper Space.")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_layers.py <dxf_file>")
        sys.exit(1)
    inspect_layers(sys.argv[1])
