#!/usr/bin/env python3
"""
extract_geometry.py
Extracts floor boundary, structural elements (columns/walls), and text labels from a DXF file.
Outputs a structured JSON file.
"""

import sys
import os
import json
import math
from collections import Counter
import ezdxf

def get_dxf_units(doc) -> str:
    """Extract units from DXF header."""
    insunits = doc.header.get("$INSUNITS", None)
    units_map = {
        0: "Unspecified",
        1: "Inches",
        2: "Feet",
        3: "Miles",
        4: "Millimeters",
        5: "Centimeters",
        6: "Meters",
        7: "Kilometers",
        8: "Microinches",
        9: "Mils",
        10: "Yards",
        11: "Angstroms",
        12: "Nanometers",
        13: "Microns",
        14: "Decimeters",
        15: "Decameters",
        16: "Hectometers",
        17: "Gigameters",
        18: "Astronomical units",
        19: "Light years",
        20: "Parsecs",
    }
    unit_str = units_map.get(insunits)
    if not unit_str or unit_str == "Unspecified":
        measurement = doc.header.get("$MEASUREMENT", None)
        if measurement == 1:
            return "Millimeters"
        elif measurement == 0:
            return "Inches"
        return "Unspecified"
    return unit_str

def polygon_area(pts: list[tuple[float, float]]) -> float:
    """Calculate the enclosed area of a 2D polygon using the Shoelace formula."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
    return abs(area) / 2.0

def get_polyline_points(entity) -> list[tuple[float, float]]:
    """Extract 2D coordinates from LWPOLYLINE or POLYLINE."""
    try:
        pts = list(entity.get_points())
        return [(float(p[0]), float(p[1])) for p in pts]
    except Exception:
        return []

def is_polyline_closed(entity, pts: list[tuple[float, float]]) -> bool:
    """Check whether a polyline is closed either via flag or coincident endpoints."""
    if not pts or len(pts) < 3:
        return False
    if getattr(entity, "closed", False):
        return True
    # Check if first and last vertices coincide
    return math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4

def extract_clean_text(entity) -> str:
    """Extract readable text from TEXT or MTEXT entity."""
    if hasattr(entity, "plain_text"):
        txt = entity.plain_text().strip()
        if txt:
            return txt
    if hasattr(entity, "text"):
        return str(entity.text).strip()
    if hasattr(entity, "dxf") and hasattr(entity.dxf, "text"):
        return str(entity.dxf.text).strip()
    return ""

def extract_geometry(dxf_path: str, output_path: str = None) -> dict:
    if not os.path.isfile(dxf_path):
        raise FileNotFoundError(f"DXF file not found: '{dxf_path}'")

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    source_file = os.path.basename(dxf_path)
    units_name = get_dxf_units(doc)

    # -------------------------------------------------------------
    # 1. Find Floor Boundary
    # -------------------------------------------------------------
    candidate_polys = []
    for entity in msp.query("LWPOLYLINE POLYLINE"):
        raw_pts = get_polyline_points(entity)
        if is_polyline_closed(entity, raw_pts):
            # Clean duplicate closing point if present
            pts = raw_pts[:-1] if (len(raw_pts) > 2 and math.hypot(raw_pts[0][0]-raw_pts[-1][0], raw_pts[0][1]-raw_pts[-1][1]) < 1e-4) else raw_pts
            if len(pts) >= 3:
                area = polygon_area(pts)
                candidate_polys.append((area, entity, pts))

    if not candidate_polys:
        raise ValueError(f"No closed polylines found in {source_file} to determine floor boundary.")

    # Largest closed polyline by enclosed area
    candidate_polys.sort(key=lambda x: x[0], reverse=True)
    boundary_area, boundary_entity, boundary_pts = candidate_polys[0]

    b_xs = [p[0] for p in boundary_pts]
    b_ys = [p[1] for p in boundary_pts]
    bw = max(b_xs) - min(b_xs)
    bh = max(b_ys) - min(b_ys)
    boundary_diag = math.hypot(bw, bh)
    min_b_dim = min(bw, bh) if min(bw, bh) > 0 else boundary_diag

    floor_boundary = {
        "type": "polygon",
        "points": [[round(p[0], 4), round(p[1], 4)] for p in boundary_pts]
    }

    # -------------------------------------------------------------
    # 2. Extract Text Labels (TEXT & MTEXT)
    # -------------------------------------------------------------
    text_labels = []
    for entity in msp.query("TEXT MTEXT"):
        txt = extract_clean_text(entity)
        if txt:
            pos = [round(float(entity.dxf.insert[0]), 4), round(float(entity.dxf.insert[1]), 4)]
            text_labels.append({
                "text": txt,
                "position": pos
            })

    # -------------------------------------------------------------
    # 3. Find Structural Elements (Columns & Walls)
    # -------------------------------------------------------------
    structural_elements = []
    unrecognized_count = 0

    # A. Circles (Small closed circles repeated across drawing)
    circles = list(msp.query("CIRCLE"))
    radii_counter = Counter(round(float(c.dxf.radius), 2) for c in circles)

    for c in circles:
        r = float(c.dxf.radius)
        r_rounded = round(r, 2)
        cx = float(c.dxf.center[0])
        cy = float(c.dxf.center[1])

        # Must be small relative to floor plate and repeated at multiple positions
        if radii_counter[r_rounded] >= 2 and r < (0.05 * boundary_diag):
            # Approximate circle with a 16-point regular polygon
            circle_pts = [
                [
                    round(cx + r * math.cos(2 * math.pi * i / 16), 4),
                    round(cy + r * math.sin(2 * math.pi * i / 16), 4)
                ]
                for i in range(16)
            ]
            structural_elements.append({
                "type": "column",
                "points": circle_pts
            })
        else:
            unrecognized_count += 1

    # B. Closed Polylines (excluding the chosen floor boundary)
    other_polys = [cp for cp in candidate_polys if cp[1] != boundary_entity]

    # Pre-filter candidate quads and measure dimensions to check repetition
    quad_candidates = []
    unclassified_polys = []

    for area, entity, pts in other_polys:
        if len(pts) == 4:
            s0 = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            s1 = math.hypot(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
            s2 = math.hypot(pts[3][0] - pts[2][0], pts[3][1] - pts[2][1])
            s3 = math.hypot(pts[0][0] - pts[3][0], pts[0][1] - pts[3][1])

            max_s_a = max(s0, s2, 1e-5)
            max_s_b = max(s1, s3, 1e-5)

            # Check if opposite sides match (parallelogram / rectangle)
            if abs(s0 - s2) / max_s_a < 0.15 and abs(s1 - s3) / max_s_b < 0.15:
                w = min(s0, s1)
                l = max(s0, s1)
                if w > 1e-4 and l < (0.25 * min_b_dim):
                    aspect = l / w
                    layer = getattr(entity.dxf, "layer", "").lower()
                    quad_candidates.append({
                        "entity": entity,
                        "w": round(w, 2),
                        "l": round(l, 2),
                        "aspect": aspect,
                        "layer": layer,
                        "points": [[round(p[0], 4), round(p[1], 4)] for p in pts]
                    })
                    continue

        unclassified_polys.append(entity)

    # Count repetition of rectangle sizes
    dim_counter = Counter((q["w"], q["l"]) for q in quad_candidates)

    for q in quad_candidates:
        w_dim = q["w"]
        l_dim = q["l"]
        aspect = q["aspect"]
        layer = q["layer"]
        is_repeated = dim_counter[(w_dim, l_dim)] >= 2

        if is_repeated:
            if aspect <= 1.5 or ("col" in layer):
                structural_elements.append({
                    "type": "column",
                    "points": q["points"]
                })
            elif aspect >= 3.0 or ("wall" in layer):
                structural_elements.append({
                    "type": "wall",
                    "points": q["points"]
                })
            else:
                unrecognized_count += 1
        else:
            unrecognized_count += 1

    # Add remaining unclassified polylines to unrecognized count
    unrecognized_count += len(unclassified_polys)

    # Also add open polylines that were not closed
    all_polys = list(msp.query("LWPOLYLINE POLYLINE"))
    closed_entity_set = {cp[1] for cp in candidate_polys}
    for poly in all_polys:
        if poly not in closed_entity_set:
            unrecognized_count += 1

    # -------------------------------------------------------------
    # 4. Count all other unclassified modelspace entities
    # -------------------------------------------------------------
    other_entity_types = [
        "LINE", "ARC", "HATCH", "INSERT", "ELLIPSE", "SPLINE",
        "DIMENSION", "LEADER", "IMAGE", "VIEWPORT", "SOLID", "3DFACE", "RAY", "XLINE"
    ]
    for ent_type in other_entity_types:
        unrecognized_count += len(list(msp.query(ent_type)))

    # Assemble JSON object matching exact specified shape
    result_data = {
        "source_file": source_file,
        "units": units_name,
        "floor_boundary": floor_boundary,
        "structural_elements": structural_elements,
        "text_labels": text_labels,
        "unrecognized_entity_count": unrecognized_count
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)
        print(f"Extraction complete. Saved to: {output_path}")

    return result_data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 extract_geometry.py <dxf_file_path> [output_json_path]")
        sys.exit(1)

    dxf_input = sys.argv[1]
    json_output = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        data = extract_geometry(dxf_input, json_output)
        if not json_output:
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error extracting geometry: {e}", file=sys.stderr)
        sys.exit(1)
