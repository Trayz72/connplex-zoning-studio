#!/usr/bin/env python3
"""
extract_geometry_v2.py
Milestone M1, Step 2c — Evidence-based CAD geometry extraction v2.
Extracts structured architectural plan regions and structural elements
from CAD drawings, preserving multi-plan layouts, explicit framing vs boundary
geometry, and CAD traceability.
"""

import sys
import os
import json
import math
from collections import Counter, defaultdict
import ezdxf

def get_dxf_units(doc):
    """Inspect DXF header for units."""
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
    unit_str = units_map.get(insunits, "Unspecified")
    measurement = doc.header.get("$MEASUREMENT", None)
    return {
        "INSUNITS_raw": insunits,
        "INSUNITS_interpreted": unit_str,
        "MEASUREMENT_raw": measurement,
        "MEASUREMENT_interpreted": "Metric (mm/m)" if measurement == 1 else ("English (inches/ft)" if measurement == 0 else "Unspecified")
    }

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

def clean_text_str(e):
    """Extract clean string from text entity."""
    if hasattr(e, 'plain_text'):
        txt = e.plain_text().strip()
        if txt:
            return txt
    if hasattr(e, 'text'):
        return str(e.text).strip()
    if hasattr(e, 'dxf') and hasattr(e.dxf, 'text'):
        return str(e.dxf.text).strip()
    return ""

def get_clean_polyline_points(e):
    """Extract clean 2D vertices from polyline."""
    try:
        raw_pts = list(e.get_points())
        pts = [(float(p[0]), float(p[1])) for p in raw_pts]
        if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4:
            pts = pts[:-1]
        return pts
    except Exception:
        return []

def validate_plan_region(region, known_frame_handles):
    """Perform automated safety checks on an extracted plan region."""
    warnings = []
    errors = []

    # Check 1: Known overall drawing frame check
    if region["boundary_geometry"] and region["boundary_geometry"]["handle"] in known_frame_handles:
        errors.append(f"Boundary geometry uses known overall drawing frame [{region['boundary_geometry']['handle']}].")

    # Check 2: Boundary aspect ratio
    if region["boundary_geometry"]:
        w = region["boundary_geometry"]["width"]
        h = region["boundary_geometry"]["height"]
        ar = max(w, h) / max(min(w, h), 1e-6)
        if ar > 8.0:
            warnings.append(f"Boundary aspect ratio is high ({ar:.1f}).")

    # Check 3: Implausibly large column count
    col_count = len(region["structural_elements"])
    if col_count > 150:
        warnings.append(f"Column count is high ({col_count}) for a single plan region.")

    # Check 4: Boundary dramatically larger than framing or geometry
    if region["boundary_geometry"] and region["framing_geometry"]:
        if region["boundary_geometry"]["area"] > 1.2 * region["framing_geometry"]["area"]:
            warnings.append("Boundary geometry is larger than framing geometry.")

    # Check 5: Duplicate structural elements check
    struct_handles = [s["source_entity_handle"] for s in region["structural_elements"]]
    if len(struct_handles) != len(set(struct_handles)):
        dup_count = len(struct_handles) - len(set(struct_handles))
        warnings.append(f"Found {dup_count} duplicate structural element handles.")

    status = "FAIL" if errors else ("WARNING" if warnings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings
    }

def extract_dhule(doc):
    """Evidence-based extraction for Dhule multi-plan DXF."""
    msp = doc.modelspace()
    all_msp_entities = list(msp)
    units_info = get_dxf_units(doc)

    known_overall_frames = ["2A1A"]

    # The 6 verified architectural plan regions in Dhule:
    plan_definitions = [
        {
            "id": "dhule-basement",
            "label": "BASEMENT FLOOR PLAN",
            "label_handle": "29AD",
            "frame_handle": "278F",
            "wall_boundary_handle": None, # Discrete wall segments; no single closed polyline
            "search_bbox": (1354.0, 1265.0, 1498.0, 1420.0),
            "evidence": [
                "Detected text label 'BASEMENT FLOOR PLAN' (handle 29AD) at (1431.42, 1346.50).",
                "Framing geometry handle 278F (122.08 x 117.09 ft, area 14,294.79 sq ft) on layer '0' bounds the basement sheet.",
                "No single closed polyline exists on layer 'wall'; exterior boundary is formed by composite wall segments. boundary_geometry set to null to avoid false boundary.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        },
        {
            "id": "dhule-ground",
            "label": "GROUND FLOOR PLAN",
            "label_handle": "29C0",
            "frame_handle": "27F1",
            "wall_boundary_handle": None, # Discrete wall segments; no single closed polyline
            "search_bbox": (1503.0, 1265.0, 1626.0, 1420.0),
            "evidence": [
                "Detected text label 'GROUND FLOOR PLAN' (handle 29C0) at (1551.17, 1345.10).",
                "Framing geometry handle 27F1 (122.08 x 117.09 ft, area 14,294.79 sq ft) on layer '0' bounds the ground floor sheet.",
                "Exterior walls are composed of discrete wall lines. boundary_geometry set to null to avoid false boundary.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        },
        {
            "id": "dhule-first-floor",
            "label": "FIRST FLOOR PLAN",
            "label_handle": "29D2",
            "frame_handle": "284A",
            "wall_boundary_handle": "6A8", # Explicit closed wall polyline 80.90 x 64.80 ft
            "search_bbox": (1655.0, 1308.0, 1742.0, 1395.0),
            "evidence": [
                "Detected text label 'FIRST FLOOR PLAN' (handle 29D2) at (1687.99, 1350.66).",
                "Framing geometry handle 284A (85.77 x 80.14 ft, area 6,873.64 sq ft) on layer '0'.",
                "Explicit exterior wall polyline handle 6A8 (80.90 x 64.80 ft, area 5,242.04 sq ft) on layer 'wall' cleanly outlines the floor plate.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        },
        {
            "id": "dhule-second-floor",
            "label": "SECOND FLOOR PLAN",
            "label_handle": "29E4",
            "frame_handle": "28A3",
            "wall_boundary_handle": "1393", # Explicit closed wall polyline 80.90 x 64.80 ft
            "search_bbox": (1761.0, 1308.0, 1848.0, 1395.0),
            "evidence": [
                "Detected text label 'SECOND FLOOR PLAN' (handle 29E4) at (1793.29, 1350.56).",
                "Framing geometry handle 28A3 (85.77 x 80.14 ft, area 6,873.64 sq ft) on layer '0'.",
                "Explicit exterior wall polyline handle 1393 (80.90 x 64.80 ft, area 5,242.04 sq ft) on layer 'wall' cleanly outlines the floor plate.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        },
        {
            "id": "dhule-third-floor",
            "label": "THIRD FLOOR PLAN",
            "label_handle": "29F6",
            "frame_handle": "28FC",
            "wall_boundary_handle": "177B", # Explicit closed wall polyline 80.90 x 64.80 ft
            "search_bbox": (1863.0, 1308.0, 1950.0, 1395.0),
            "evidence": [
                "Detected text label 'THIRD FLOOR PLAN' (handle 29F6) at (1895.41, 1350.68).",
                "Framing geometry handle 28FC (85.77 x 80.14 ft, area 6,873.64 sq ft) on layer '0'.",
                "Explicit exterior wall polyline handle 177B (80.90 x 64.80 ft, area 5,242.04 sq ft) on layer 'wall' cleanly outlines the floor plate.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        },
        {
            "id": "dhule-fourth-floor",
            "label": "FOURTH FLOOR PLAN",
            "label_handle": "2A08",
            "frame_handle": "2955",
            "wall_boundary_handle": "21D8", # Explicit closed wall polyline 80.90 x 64.80 ft
            "search_bbox": (1964.0, 1308.0, 2050.0, 1395.0),
            "evidence": [
                "Detected text label 'FOURTH FLOOR PLAN' (handle 2A08) at (1990.56, 1350.15).",
                "Framing geometry handle 2955 (85.77 x 80.14 ft, area 6,873.64 sq ft) on layer '0'.",
                "Explicit exterior wall polyline handle 21D8 (80.90 x 64.80 ft, area 5,242.04 sq ft) on layer 'wall' cleanly outlines the floor plate.",
                "Structural columns extracted strictly from layer 'COLUMN (DCPL)'."
            ]
        }
    ]

    entity_by_handle = {str(e.dxf.handle): e for e in all_msp_entities}
    plan_regions = []

    for pdef in plan_definitions:
        x0, y0, x1, y1 = pdef["search_bbox"]

        # Collect entities inside the region's bounding box
        region_entities = []
        for e in all_msp_entities:
            eb = get_entity_bbox(e)
            if eb and not (eb[2] < x0 or eb[0] > x1 or eb[3] < y0 or eb[1] > y1):
                region_entities.append(e)

        layer_counts = Counter(e.dxf.layer for e in region_entities)

        # Build framing geometry
        frame_geom = None
        if pdef["frame_handle"] in entity_by_handle:
            fe = entity_by_handle[pdef["frame_handle"]]
            f_pts = get_clean_polyline_points(fe)
            f_area = polygon_area(f_pts)
            fxs = [p[0] for p in f_pts]
            fys = [p[1] for p in f_pts]
            frame_geom = {
                "handle": str(fe.dxf.handle),
                "layer": str(fe.dxf.layer),
                "type": "polygon",
                "area": round(f_area, 2),
                "width": round(max(fxs) - min(fxs), 2),
                "height": round(max(fys) - min(fys), 2),
                "bounding_box": {
                    "min_x": round(min(fxs), 2), "min_y": round(min(fys), 2),
                    "max_x": round(max(fxs), 2), "max_y": round(max(fys), 2)
                },
                "points": [[round(p[0], 4), round(p[1], 4)] for p in f_pts]
            }

        # Build boundary geometry
        bound_geom = None
        if pdef["wall_boundary_handle"] and pdef["wall_boundary_handle"] in entity_by_handle:
            be = entity_by_handle[pdef["wall_boundary_handle"]]
            b_pts = get_clean_polyline_points(be)
            b_area = polygon_area(b_pts)
            bxs = [p[0] for p in b_pts]
            bys = [p[1] for p in b_pts]
            bound_geom = {
                "handle": str(be.dxf.handle),
                "layer": str(be.dxf.layer),
                "type": "polygon",
                "area": round(b_area, 2),
                "width": round(max(bxs) - min(bxs), 2),
                "height": round(max(bys) - min(bys), 2),
                "bounding_box": {
                    "min_x": round(min(bxs), 2), "min_y": round(min(bys), 2),
                    "max_x": round(max(bxs), 2), "max_y": round(max(bys), 2)
                },
                "points": [[round(p[0], 4), round(p[1], 4)] for p in b_pts]
            }

        # Extract structural columns strictly from COLUMN (DCPL) inside framing/search bbox
        bx_min = frame_geom["bounding_box"]["min_x"] if frame_geom else x0
        bx_max = frame_geom["bounding_box"]["max_x"] if frame_geom else x1
        by_min = frame_geom["bounding_box"]["min_y"] if frame_geom else y0
        by_max = frame_geom["bounding_box"]["max_y"] if frame_geom else y1

        structural_elements = []
        seen_col_handles = set()

        for e in region_entities:
            if e.dxf.layer == 'COLUMN (DCPL)' and e.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                h = str(e.dxf.handle)
                if h in seen_col_handles:
                    continue
                c_pts = get_clean_polyline_points(e)
                if len(c_pts) >= 3:
                    cxs = [p[0] for p in c_pts]
                    cys = [p[1] for p in c_pts]
                    cx = sum(cxs) / len(cxs)
                    cy = sum(cys) / len(cys)
                    # Check spatial containment within frame
                    if bx_min <= cx <= bx_max and by_min <= cy <= by_max:
                        seen_col_handles.add(h)
                        w = round(max(cxs) - min(cxs), 2)
                        height = round(max(cys) - min(cys), 2)
                        structural_elements.append({
                            "id": f"col-{h}",
                            "type": "column",
                            "geometry": {
                                "type": "polygon",
                                "points": [[round(p[0], 4), round(p[1], 4)] for p in c_pts]
                            },
                            "width": w,
                            "height": height,
                            "area": round(polygon_area(c_pts), 3),
                            "bounding_box": {
                                "min_x": round(min(cxs), 2), "min_y": round(min(cys), 2),
                                "max_x": round(max(cxs), 2), "max_y": round(max(cys), 2)
                            },
                            "layer": str(e.dxf.layer),
                            "source_entity_handle": h,
                            "confidence": "high"
                        })

        region_record = {
            "id": pdef["id"],
            "label": pdef["label"],
            "source_entity_handles": [pdef["label_handle"]] + ([pdef["frame_handle"]] if pdef["frame_handle"] else []) + ([pdef["wall_boundary_handle"]] if pdef["wall_boundary_handle"] else []),
            "bounding_box": {
                "min_x": round(x0, 2), "min_y": round(y0, 2),
                "max_x": round(x1, 2), "max_y": round(y1, 2)
            },
            "width": round(x1 - x0, 2),
            "height": round(y1 - y0, 2),
            "framing_geometry": frame_geom,
            "boundary_geometry": bound_geom,
            "structural_elements": structural_elements,
            "total_entities_count": len(region_entities),
            "major_layers": dict(layer_counts.most_common(6)),
            "evidence": pdef["evidence"],
            "confidence": "high" if bound_geom else "medium"
        }

        # Run safety validation
        val = validate_plan_region(region_record, known_overall_frames)
        region_record["validation"] = val
        plan_regions.append(region_record)

    return {
        "source_file": "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf",
        "units": units_info["INSUNITS_interpreted"],
        "plan_regions": plan_regions
    }

def extract_vadodara(doc):
    """Evidence-based extraction for Vadodara multi-option DXF."""
    msp = doc.modelspace()
    all_msp_entities = list(msp)
    units_info = get_dxf_units(doc)

    known_overall_frames = ["8285A"]

    # Vadodara architectural regions in the cinema zoning section (X in [59000, 68000]):
    vadodara_definitions = [
        {
            "id": "vadodara-option-1",
            "label": "Cinema Zoning Studio — Option 1 (Lower Layout / Screens 1–5)",
            "search_bbox": (62000.0, 3200.0, 67500.0, 5500.0),
            "evidence": [
                "Zoning layout contains Screens 1-5, Foyer, Cafe, and Box Office at Y in [3200, 5500].",
                "Surrounded by overall sheet border handle 8285A (layer WALLS), which is rejected as a floor boundary.",
                "Exterior boundary is defined by composite wall segments on layer WALLS; boundary_geometry is set to null.",
                "Structural columns extracted conservatively as small closed quads (4.5x4.5 in, 9x28.5 in) on layer WALLS."
            ]
        },
        {
            "id": "vadodara-option-2",
            "label": "Cinema Zoning Studio — Option 2 (Upper Layout / Screens 1–5)",
            "search_bbox": (62000.0, 9800.0, 67500.0, 12000.0),
            "evidence": [
                "Alternative zoning layout contains Screens 1-5, Foyer, and Projector Rooms at Y in [9800, 12000].",
                "Framing polyline 8285A spans both options and is rejected as a floor boundary.",
                "Exterior boundary is defined by composite wall segments; boundary_geometry is set to null.",
                "Structural columns extracted conservatively from closed quads on layer WALLS."
            ]
        },
        {
            "id": "vadodara-area-schedule",
            "label": "Cinema Zoning Studio — Area Calculations & Schedule Table",
            "search_bbox": (62000.0, 16500.0, 67500.0, 18500.0),
            "evidence": [
                "Contains architectural area schedule text: 'NET USAGE AREA = 10,962 SQ. FT.' and 'NET USAGE AREA = 10,305 SQ. FT.'.",
                "Non-occupiable calculation schedule region."
            ]
        }
    ]

    plan_regions = []

    for vdef in vadodara_definitions:
        x0, y0, x1, y1 = vdef["search_bbox"]

        # Collect entities inside the region's bounding box
        region_entities = []
        for e in all_msp_entities:
            eb = get_entity_bbox(e)
            if eb and not (eb[2] < x0 or eb[0] > x1 or eb[3] < y0 or eb[1] > y1):
                region_entities.append(e)

        layer_counts = Counter(e.dxf.layer for e in region_entities)

        # Extract conservative structural elements
        structural_elements = []
        seen_handles = set()

        for e in region_entities:
            if e.dxf.layer == 'WALLS' and e.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                h = str(e.dxf.handle)
                if h in seen_handles or h in known_overall_frames:
                    continue
                c_pts = get_clean_polyline_points(e)
                if len(c_pts) == 4 and getattr(e, 'closed', False):
                    xs = [p[0] for p in c_pts]
                    ys = [p[1] for p in c_pts]
                    w = round(max(xs) - min(xs), 1)
                    height = round(max(ys) - min(ys), 1)
                    area = polygon_area(c_pts)

                    # Conservative column criteria:
                    # 4.5" x 4.5" square column or 9.0" x 28.5" rectangular column
                    is_small_square = (w == 4.5 and height == 4.5)
                    is_rec_column = (min(w, height) in [9.0, 12.0] and max(w, height) in [28.5, 30.0])

                    if is_small_square or is_rec_column:
                        seen_handles.add(h)
                        structural_elements.append({
                            "id": f"col-{h}",
                            "type": "column",
                            "geometry": {
                                "type": "polygon",
                                "points": [[round(p[0], 4), round(p[1], 4)] for p in c_pts]
                            },
                            "width": w,
                            "height": height,
                            "area": round(area, 2),
                            "bounding_box": {
                                "min_x": round(min(xs), 2), "min_y": round(min(ys), 2),
                                "max_x": round(max(xs), 2), "max_y": round(max(ys), 2)
                            },
                            "layer": str(e.dxf.layer),
                            "source_entity_handle": h,
                            "confidence": "medium"
                        })

        region_record = {
            "id": vdef["id"],
            "label": vdef["label"],
            "source_entity_handles": list(seen_handles)[:10],
            "bounding_box": {
                "min_x": round(x0, 2), "min_y": round(y0, 2),
                "max_x": round(x1, 2), "max_y": round(y1, 2)
            },
            "width": round(x1 - x0, 2),
            "height": round(y1 - y0, 2),
            "framing_geometry": None,
            "boundary_geometry": None, # Composite wall lines, no single closed polyline
            "structural_elements": structural_elements,
            "total_entities_count": len(region_entities),
            "major_layers": dict(layer_counts.most_common(6)),
            "evidence": vdef["evidence"],
            "confidence": "medium" if "Option" in vdef["label"] else "low"
        }

        # Run safety validation
        val = validate_plan_region(region_record, known_overall_frames)
        region_record["validation"] = val
        plan_regions.append(region_record)

    return {
        "source_file": "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf",
        "units": units_info["INSUNITS_interpreted"],
        "plan_regions": plan_regions
    }

def print_human_reviewable_output(doc_result):
    """Print clean diagnostic output matching Part 11 specification."""
    print("=" * 80)
    print(f"CAD DOCUMENT EXTRACTION REPORT v2: {doc_result['source_file']}")
    print(f"Units: {doc_result['units']} | Total Plan Regions: {len(doc_result['plan_regions'])}")
    print("=" * 80)

    for r in doc_result["plan_regions"]:
        print("-" * 50)
        print("PLAN REGION")
        print("-" * 50)
        print(f"Label:        {r['label']}")
        print(f"Bounding box: ({r['bounding_box']['min_x']}, {r['bounding_box']['min_y']}) -> ({r['bounding_box']['max_x']}, {r['bounding_box']['max_y']})")
        print(f"Width:        {r['width']} {doc_result['units']}")
        print(f"Height:       {r['height']} {doc_result['units']}")
        print()

        print("Framing:")
        fg = r.get("framing_geometry")
        if fg:
            print(f"  handle:     [{fg['handle']}]")
            print(f"  layer:      {fg['layer']}")
            print(f"  area:       {fg['area']:,.2f} sq {doc_result['units']}")
            print(f"  dim:        {fg['width']} x {fg['height']}")
        else:
            print("  status:     none")

        print("Boundary:")
        bg = r.get("boundary_geometry")
        if bg:
            print(f"  handle:     [{bg['handle']}]")
            print(f"  layer:      {bg['layer']}")
            print(f"  area:       {bg['area']:,.2f} sq {doc_result['units']}")
            print(f"  status:     EXPLICIT_WALL_BOUNDARY_FOUND")
        else:
            print("  status:     null (composite wall lines; no single closed polyline)")

        print()
        print("Entities:")
        print(f"  total:      {r['total_entities_count']}")
        print(f"  top layers: {r['major_layers']}")

        print()
        print("Structural:")
        cols = r["structural_elements"]
        high_c = sum(1 for s in cols if s["confidence"] == "high")
        low_c = sum(1 for s in cols if s["confidence"] in ["low", "medium"])
        print(f"  column count:          {len(cols)}")
        print(f"  high-confidence count: {high_c}")
        print(f"  medium/low-confidence: {low_c}")

        print()
        val = r.get("validation", {"status": "PASS", "warnings": [], "errors": []})
        print(f"Validation:   {val['status']}")
        if val["warnings"]:
            for w in val["warnings"]:
                print(f"  [WARN] {w}")
        if val["errors"]:
            for err in val["errors"]:
                print(f"  [ERROR] {err}")

        print()
        print("Evidence:")
        for ev in r["evidence"]:
            print(f"  * {ev}")
        print()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    os.makedirs(output_dir, exist_ok=True)

    dhule_dxf = os.path.join(output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")
    out_json = os.path.join(output_dir, "extracted_geometry_v2.json")

    dhule_doc = ezdxf.readfile(dhule_dxf)
    dhule_data = extract_dhule(dhule_doc)

    vadodara_doc = ezdxf.readfile(vadodara_dxf)
    vadodara_data = extract_vadodara(vadodara_doc)

    combined_output = {
        "dhule": dhule_data,
        "vadodara": vadodara_data
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(combined_output, f, indent=2)

    # Print human-reviewable report
    print_human_reviewable_output(dhule_data)
    print_human_reviewable_output(vadodara_data)

    print(f"\nSaved v2 extracted geometry JSON to: {out_json}")

if __name__ == "__main__":
    main()
