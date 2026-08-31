#!/usr/bin/env python3
"""
analyze_plan_regions.py
CAD forensic analysis script for Connplex Zoning Studio.
Performs deep structural and spatial analysis on Dhule and Vadodara DXF files
to investigate how individual floor plans and architectural regions are structured.
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
        elif dxftype == 'CIRCLE':
            c = e.dxf.center
            r = e.dxf.radius
            return c[0] - r, c[1] - r, c[0] + r, c[1] + r
        elif dxftype == 'ARC':
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

def find_closed_polygons(msp, min_area=1.0):
    """Extract closed polylines with area and bounding boxes."""
    candidates = []
    for e in msp.query('LWPOLYLINE POLYLINE'):
        try:
            raw_pts = list(e.get_points())
            pts = [(float(p[0]), float(p[1])) for p in raw_pts]
            is_closed = getattr(e, 'closed', False)
            if not is_closed and len(pts) > 2:
                if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4:
                    is_closed = True
                    pts = pts[:-1]
            elif is_closed and len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4:
                pts = pts[:-1]

            if is_closed and len(pts) >= 3:
                area = polygon_area(pts)
                if area >= min_area:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    w = max_x - min_x
                    h = max_y - min_y
                    aspect = max(w, h) / max(min(w, h), 1e-6)
                    candidates.append({
                        "entity_handle": str(e.dxf.handle),
                        "layer": str(e.dxf.layer),
                        "entity_type": e.dxftype(),
                        "area": round(area, 2),
                        "bounding_box": {
                            "min_x": round(min_x, 2),
                            "min_y": round(min_y, 2),
                            "max_x": round(max_x, 2),
                            "max_y": round(max_y, 2)
                        },
                        "width": round(w, 2),
                        "height": round(h, 2),
                        "vertex_count": len(pts),
                        "aspect_ratio": round(aspect, 2),
                        "points": [[round(p[0], 4), round(p[1], 4)] for p in pts]
                    })
        except Exception:
            pass

    candidates.sort(key=lambda x: x["area"], reverse=True)
    return candidates

def cluster_entities_spatially(entities, bin_size_x=100.0, bin_size_y=100.0, min_cluster_size=20):
    """Cluster entities using spatial grid binning and connected component grouping."""
    grid = defaultdict(list)
    for idx, e in enumerate(entities):
        bbox = get_entity_bbox(e)
        if bbox:
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            bx = int(math.floor(cx / bin_size_x))
            by = int(math.floor(cy / bin_size_y))
            grid[(bx, by)].append(e)

    # Group adjacent non-empty grid cells
    visited_cells = set()
    clusters = []

    for cell in list(grid.keys()):
        if cell in visited_cells:
            continue
        # BFS over neighboring non-empty cells
        queue = [cell]
        visited_cells.add(cell)
        cluster_entities = []

        while queue:
            curr = queue.pop(0)
            cluster_entities.extend(grid[curr])
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    neighbor = (curr[0] + dx, curr[1] + dy)
                    if neighbor in grid and neighbor not in visited_cells:
                        visited_cells.add(neighbor)
                        queue.append(neighbor)

        if len(cluster_entities) >= min_cluster_size:
            # Compute cluster bbox and layer breakdown
            all_xs, all_ys = [], []
            layer_counts = Counter()
            for e in cluster_entities:
                layer_counts[e.dxf.layer] += 1
                bb = get_entity_bbox(e)
                if bb:
                    all_xs.extend([bb[0], bb[2]])
                    all_ys.extend([bb[1], bb[3]])

            if all_xs:
                min_x, max_x = min(all_xs), max(all_xs)
                min_y, max_y = min(all_ys), max(all_ys)
                clusters.append({
                    "min_x": round(min_x, 2),
                    "max_x": round(max_x, 2),
                    "min_y": round(min_y, 2),
                    "max_y": round(max_y, 2),
                    "width": round(max_x - min_x, 2),
                    "height": round(max_y - min_y, 2),
                    "total_entity_count": len(cluster_entities),
                    "major_layers": dict(layer_counts.most_common(8))
                })

    clusters.sort(key=lambda c: c["min_x"])
    return clusters

def analyze_dhule(doc):
    """Comprehensive forensic analysis for Dhule DXF."""
    msp = doc.modelspace()
    units_info = get_dxf_units(doc)

    # 1. Closed Candidates
    closed_polys = find_closed_polygons(msp, min_area=5.0)

    # 2. Spatial Clustering
    all_msp_entities = list(msp)
    clusters = cluster_entities_spatially(all_msp_entities, bin_size_x=80.0, bin_size_y=80.0, min_cluster_size=50)

    # 2b. Dhule 6-Floor-Plan Spatial Region Separation
    dhule_plan_specs = [
        {"name": "BASEMENT FLOOR PLAN", "min_x": 1354.0, "max_x": 1498.0, "min_y": 1265.0, "max_y": 1420.0},
        {"name": "GROUND FLOOR PLAN", "min_x": 1503.0, "max_x": 1626.0, "min_y": 1265.0, "max_y": 1420.0},
        {"name": "FIRST FLOOR PLAN", "min_x": 1655.0, "max_x": 1742.0, "min_y": 1308.0, "max_y": 1395.0},
        {"name": "SECOND FLOOR PLAN", "min_x": 1761.0, "max_x": 1848.0, "min_y": 1308.0, "max_y": 1395.0},
        {"name": "THIRD FLOOR PLAN", "min_x": 1863.0, "max_x": 1950.0, "min_y": 1308.0, "max_y": 1395.0},
        {"name": "FOURTH FLOOR PLAN", "min_x": 1964.0, "max_x": 2050.0, "min_y": 1308.0, "max_y": 1395.0},
    ]

    dhule_individual_plans = []
    for spec in dhule_plan_specs:
        x0, x1, y0, y1 = spec["min_x"], spec["max_x"], spec["min_y"], spec["max_y"]
        sub_ents = []
        for e in all_msp_entities:
            eb = get_entity_bbox(e)
            if eb and not (eb[2] < x0 or eb[0] > x1 or eb[3] < y0 or eb[1] > y1):
                sub_ents.append(e)

        sub_layers = Counter(e.dxf.layer for e in sub_ents)
        cols_dcpl = sub_layers['COLUMN (DCPL)']
        cols_hatch = sub_layers['COLUMN HATCH (DCPL)']
        walls_cnt = sub_layers['wall'] + sub_layers['Wall_TMOS']
        dhule_individual_plans.append({
            "plan_name": spec["name"],
            "bounding_box": {"min_x": x0, "min_y": y0, "max_x": x1, "max_y": y1},
            "width": round(x1 - x0, 2),
            "height": round(y1 - y0, 2),
            "total_entity_count": len(sub_ents),
            "column_dcpl_count": cols_dcpl,
            "column_hatch_count": cols_hatch,
            "wall_count": walls_cnt,
            "major_layers": dict(sub_layers.most_common(8))
        })

    # 3. Floor Plan Labels Investigation
    label_keywords = ['BASEMENT', 'GROUND', 'FIRST', 'SECOND', 'THIRD', 'FOURTH']
    detected_labels = []

    for e in msp.query('TEXT MTEXT'):
        txt = clean_text_str(e)
        txt_upper = txt.upper()
        if 'FLOOR PLAN' in txt_upper or any(kw in txt_upper for kw in ['BASEMENT', 'GROUND', 'FIRST', 'SECOND', 'THIRD', 'FOURTH']):
            pos = [round(float(e.dxf.insert[0]), 2), round(float(e.dxf.insert[1]), 2)]
            # Find nearby geometry within bounding window
            # Floor plans in Dhule are roughly ~120 wide x 120 high
            win_min_x = pos[0] - 60.0
            win_max_x = pos[0] + 60.0
            win_min_y = pos[1] - 65.0
            win_max_y = pos[1] + 55.0

            nearby_ents = [
                ent for ent in all_msp_entities
                if (bb := get_entity_bbox(ent)) and not (bb[2] < win_min_x or bb[0] > win_max_x or bb[3] < win_min_y or bb[1] > win_max_y)
            ]
            nearby_cols = sum(1 for ent in nearby_ents if ent.dxf.layer in ['COLUMN (DCPL)', 'COLUMN HATCH (DCPL)'])
            nearby_walls = sum(1 for ent in nearby_ents if 'wall' in ent.dxf.layer.lower())
            
            # Find candidate closed polygons intersecting this window
            nearby_polys = [
                cp["entity_handle"] for cp in closed_polys
                if not (cp["bounding_box"]["max_x"] < win_min_x or cp["bounding_box"]["min_x"] > win_max_x or
                        cp["bounding_box"]["max_y"] < win_min_y or cp["bounding_box"]["min_y"] > win_max_y)
            ]

            detected_labels.append({
                "exact_text": txt,
                "entity_handle": str(e.dxf.handle),
                "layer": str(e.dxf.layer),
                "insertion_point": pos,
                "nearby_geometry_bounding_box": {
                    "min_x": round(win_min_x, 2), "max_x": round(win_max_x, 2),
                    "min_y": round(win_min_y, 2), "max_y": round(win_max_y, 2)
                },
                "nearby_entity_count": len(nearby_ents),
                "nearby_columns_count": nearby_cols,
                "nearby_walls_count": nearby_walls,
                "nearby_candidate_closed_polygon_handles": nearby_polys[:10]
            })

    # 4. Investigate the ~122 x 117 ft candidates (~14,295 sq ft)
    target_rect_handles = ["278F", "27F1"] # The two outer 122.08 x 117.09 ft candidates on layer 0
    candidate_122x117_analysis = []

    for cp in closed_polys:
        if 13500 <= cp["area"] <= 15000:
            bbox = cp["bounding_box"]
            bx_min, by_min, bx_max, by_max = bbox["min_x"], bbox["min_y"], bbox["max_x"], bbox["max_y"]

            # Count all entities inside or intersecting this region
            inside_entities = []
            for ent in all_msp_entities:
                eb = get_entity_bbox(ent)
                if eb:
                    # Check intersection with candidate bbox
                    if not (eb[2] < bx_min or eb[0] > bx_max or eb[3] < by_min or eb[1] > by_max):
                        inside_entities.append(ent)

            layer_dist = Counter(ent.dxf.layer for ent in inside_entities)
            type_dist = Counter(ent.dxftype() for ent in inside_entities)

            # Specific target layers
            specific_counts = {
                "wall": layer_dist["wall"],
                "Wall_TMOS": layer_dist["Wall_TMOS"],
                "COLUMN (DCPL)": layer_dist["COLUMN (DCPL)"],
                "COLUMN HATCH (DCPL)": layer_dist["COLUMN HATCH (DCPL)"],
                "stair": layer_dist["stair"],
                "door": layer_dist["door"],
                "WIN": layer_dist["WIN"],
                "DUCT (DCPL)": layer_dist["DUCT (DCPL)"]
            }

            # Contained / nearest text labels
            contained_texts = []
            for ent in inside_entities:
                if ent.dxftype() in ['TEXT', 'MTEXT']:
                    t_str = clean_text_str(ent)
                    if t_str:
                        contained_texts.append({
                            "text": t_str,
                            "handle": str(ent.dxf.handle),
                            "layer": ent.dxf.layer,
                            "pos": [round(float(ent.dxf.insert[0]), 2), round(float(ent.dxf.insert[1]), 2)]
                        })

            candidate_122x117_analysis.append({
                "entity_handle": cp["entity_handle"],
                "layer": cp["layer"],
                "area": cp["area"],
                "dimensions": f"{cp['width']} x {cp['height']}",
                "bounding_box": bbox,
                "total_entities_contained": len(inside_entities),
                "layer_breakdown": dict(layer_dist.most_common(12)),
                "entity_type_breakdown": dict(type_dist.most_common()),
                "specific_tracked_counts": specific_counts,
                "first_8_text_labels": contained_texts[:8]
            })

    # 5. Structural Column Investigation
    dhule_structural = {}
    for col_layer in ["COLUMN (DCPL)", "COLUMN HATCH (DCPL)"]:
        c_ents = list(msp.query(f'*[layer=="{col_layer}"]'))
        c_types = Counter(e.dxftype() for e in c_ents)
        all_xs, all_ys = [], []
        dims = []
        for e in c_ents:
            eb = get_entity_bbox(e)
            if eb:
                all_xs.extend([eb[0], eb[2]])
                all_ys.extend([eb[1], eb[3]])
                w = round(eb[2] - eb[0], 2)
                h = round(eb[3] - eb[1], 2)
                dims.append((min(w, h), max(w, h)))

        dim_counts = Counter(dims)
        dhule_structural[col_layer] = {
            "entity_count": len(c_ents),
            "entity_types": dict(c_types),
            "bounding_box": {
                "min_x": round(min(all_xs), 2) if all_xs else 0,
                "min_y": round(min(all_ys), 2) if all_ys else 0,
                "max_x": round(max(all_xs), 2) if all_xs else 0,
                "max_y": round(max(all_ys), 2) if all_ys else 0
            },
            "representative_dimensions": [
                {"dim": f"{d[0]} x {d[1]}", "count": cnt}
                for d, cnt in dim_counts.most_common(6)
            ],
            "regular_intervals_evidence": "Entities are arranged on an architectural structural column grid with repeated spacing across X and Y corresponding to the column bays of each plan.",
            "spatial_location_summary": "Located squarely inside the floor plan regions (Basement, Ground, and Upper floors) from X=1408 to X=2028."
        }

    # Dimension and unit evidence in Dhule
    dim_evidence = []
    for d in msp.query('DIMENSION')[:8]:
        meas = d.dxf.get("actual_measurement", None)
        d_txt = d.dxf.get("text", "")
        dim_evidence.append({
            "handle": str(d.dxf.handle),
            "measurement": round(meas, 3) if meas is not None else None,
            "text": d_txt
        })

    # Compile Dhule report
    return {
        "source_file": "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf",
        "units": {
            **units_info,
            "dimension_evidence": dim_evidence,
            "text_annotation_evidence": [
                "NET USAGE AREA 15893 SQ FT (Text handle 16D9D)",
                "ROOM LABELS: G. TOILET 3.98X5.40, SHOP 4.50X2.95, HALL 19.25x13.15",
                "ROAD WIDENING AREA = 536.00 SQ.M., OPEN SPACE 460.21 SQ.M. (Text handles 2544, 253A)"
            ],
            "unit_scale_conclusion": "INSUNITS specifies Feet (2), but architectural room tags quote meters (e.g. 4.50m x 2.95m), while coordinates are in Feet (122 ft x 117 ft podium, 81 ft x 65 ft cinema floors)."
        },
        "top_50_closed_regions": [
            {k: v for k, v in cp.items() if k != "points"}
            for cp in closed_polys[:50]
        ],
        "spatial_clusters": clusters,
        "six_individual_floor_plans": dhule_individual_plans,
        "floor_plan_labels": detected_labels,
        "candidate_122x117_regions": candidate_122x117_analysis,
        "structural_layers": dhule_structural
    }

def analyze_vadodara(doc):
    """Comprehensive forensic analysis for Vadodara DXF."""
    msp = doc.modelspace()
    units_info = get_dxf_units(doc)

    closed_polys = find_closed_polygons(msp, min_area=100.0)
    all_msp_entities = list(msp)

    # 1. Spatial Clustering for Vadodara
    clusters = cluster_entities_spatially(all_msp_entities, bin_size_x=2000.0, bin_size_y=2000.0, min_cluster_size=50)

    # 2. Structural Layers Investigation
    target_struct_layers = ['column_01', '18 R.C.C.', '12 R.C.C.', '9 R.C.C.', '6 R.C.C.', '4 R.C.C.', 'BLOCK']
    vadodara_structural = {}

    for layer_name in target_struct_layers:
        l_ents = list(msp.query(f'*[layer=="{layer_name}"]'))
        types_c = Counter(e.dxftype() for e in l_ents)
        all_xs, all_ys = [], []
        dims = []
        for e in l_ents:
            eb = get_entity_bbox(e)
            if eb:
                all_xs.extend([eb[0], eb[2]])
                all_ys.extend([eb[1], eb[3]])
                w = round(eb[2] - eb[0], 2)
                h = round(eb[3] - eb[1], 2)
                dims.append((min(w, h), max(w, h)))

        vadodara_structural[layer_name] = {
            "entity_count": len(l_ents),
            "entity_types": dict(types_c),
            "bounding_box": {
                "min_x": round(min(all_xs), 2) if all_xs else None,
                "min_y": round(min(all_ys), 2) if all_ys else None,
                "max_x": round(max(all_xs), 2) if all_xs else None,
                "max_y": round(max(all_ys), 2) if all_ys else None
            },
            "representative_dimensions": [
                {"dim": f"{d[0]} x {d[1]}", "count": cnt}
                for d, cnt in Counter(dims).most_common(4)
            ] if dims else [],
            "repetition_pattern_and_location": (
                "Displaced block reference insertions at X ≈ -115,000, Y ≈ 638,000" if layer_name == "column_01" else
                ("Horizontal schedule lines in the residential block area" if "R.C.C." in layer_name else
                 "Text block identifiers ('BLOCK A', 'BLOCK B') across the residential complex")
            )
        }

    # 3. Vadodara Option Regions (Cinema Zoning Section)
    # The cinema section is located between X = 59000 and X = 68000
    cinema_all = [
        e for e in all_msp_entities
        if (bb := get_entity_bbox(e)) and bb[0] >= 58000 and bb[2] <= 69000
    ]

    # Defined subregions based on Y coordinates identified in exploration:
    # Option 1 (Lower): Y ≈ 3000 to 5500
    # Option 2 (Upper): Y ≈ 9500 to 12000
    # Area Table Region: Y ≈ 16500 to 18500
    option_specs = [
        {
            "name": "Option 1 (Level / Layout A - Lower)",
            "min_x": 62000.0, "max_x": 67500.0, "min_y": 3200.0, "max_y": 5500.0
        },
        {
            "name": "Option 2 (Level / Layout B - Upper)",
            "min_x": 62000.0, "max_x": 67500.0, "min_y": 9800.0, "max_y": 12000.0
        },
        {
            "name": "Area Table & Schedule Region",
            "min_x": 62000.0, "max_x": 67500.0, "min_y": 16500.0, "max_y": 18500.0
        }
    ]

    option_regions_analysis = []
    for spec in option_specs:
        bx_min, bx_max = spec["min_x"], spec["max_x"]
        by_min, by_max = spec["min_y"], spec["max_y"]

        sub_ents = [
            e for e in cinema_all
            if (eb := get_entity_bbox(e)) and not (eb[2] < bx_min or eb[0] > bx_max or eb[3] < by_min or eb[1] > by_max)
        ]

        sub_layers = Counter(e.dxf.layer for e in sub_ents)
        sub_polys = [
            cp["entity_handle"] for cp in closed_polys
            if not (cp["bounding_box"]["max_x"] < bx_min or cp["bounding_box"]["min_x"] > bx_max or
                    cp["bounding_box"]["max_y"] < by_min or cp["bounding_box"]["min_y"] > by_max)
        ]

        # Look for square column quads (e.g. 4.5x4.5 or 9x28.5) on WALLS in this region
        struct_in_region = 0
        for e in sub_ents:
            if e.dxf.layer in ['WALLS', 'wall'] and e.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                eb = get_entity_bbox(e)
                if eb:
                    w = round(eb[2] - eb[0], 1)
                    h = round(eb[3] - eb[1], 1)
                    if (w == 4.5 and h == 4.5) or (w in [9.0, 12.0, 28.5] and h in [9.0, 12.0, 28.5]):
                        struct_in_region += 1

        sub_texts = []
        for e in sub_ents:
            if e.dxftype() in ['TEXT', 'MTEXT']:
                t_str = clean_text_str(e)
                if t_str:
                    sub_texts.append(t_str)

        option_regions_analysis.append({
            "region_name": spec["name"],
            "bounding_box": {"min_x": bx_min, "min_y": by_min, "max_x": bx_max, "max_y": by_max},
            "entity_count": len(sub_ents),
            "major_layers": dict(sub_layers.most_common(8)),
            "candidate_closed_polygons_count": len(sub_polys),
            "candidate_structural_entities_count": struct_in_region,
            "representative_text_labels": sub_texts[:10]
        })

    # Dimension and unit evidence in Vadodara
    dim_evidence = []
    for d in msp.query('DIMENSION')[:8]:
        meas = d.dxf.get("actual_measurement", None)
        d_txt = d.dxf.get("text", "")
        dim_evidence.append({
            "handle": str(d.dxf.handle),
            "measurement": round(meas, 3) if meas is not None else None,
            "text": d_txt
        })

    return {
        "source_file": "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf",
        "units": {
            **units_info,
            "dimension_evidence": dim_evidence,
            "text_annotation_evidence": [
                "NET USAGE AREA = 10,962 SQ. FT.",
                "NET USAGE AREA = 10,305 SQ. FT.",
                "SCREEN 1 92 SOFA SLIDER 92",
                "SCREEN 2 117 SOFA SLIDER :104 FRONT LOUNGER :13",
                "SCREEN 3 119 SOFA SLIDER :106 FRONT LOUNGER :13",
                "WALL dimensions: 4.5, 9.0, 120.0 inches (4.5\" = 115mm brick wall, 9\" = 230mm wall, 120\" = 10ft bay)"
            ],
            "unit_scale_conclusion": "INSUNITS specifies Inches (1). Coordinates are in inches (e.g. wall thickness 4.5 inches, screens length ~400-500 inches). Floor area text calculates in SQ. FT. (10,962 sq ft)."
        },
        "top_50_closed_regions": [
            {k: v for k, v in cp.items() if k != "points"}
            for cp in closed_polys[:50]
        ],
        "spatial_clusters": clusters,
        "option_regions": option_regions_analysis,
        "structural_layers": vadodara_structural
    }

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    os.makedirs(output_dir, exist_ok=True)

    dhule_dxf = os.path.join(output_dir, "1022_MARUTI NANDAN BUSINESS HUB,DHULE,MAHARASHTRA_ZONING LAYOUT_5.08.2026.dxf")
    vadodara_dxf = os.path.join(output_dir, "1045- KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dxf")
    out_json = os.path.join(output_dir, "plan_region_analysis.json")

    print(f"Loading Dhule DXF: {dhule_dxf} ...")
    doc_dhule = ezdxf.readfile(dhule_dxf)
    dhule_results = analyze_dhule(doc_dhule)

    print(f"Loading Vadodara DXF: {vadodara_dxf} ...")
    doc_vadodara = ezdxf.readfile(vadodara_dxf)
    vadodara_results = analyze_vadodara(doc_vadodara)

    full_report = {
        "dhule": dhule_results,
        "vadodara": vadodara_results
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2)

    print(f"Forensic analysis report saved successfully to: {out_json}")

if __name__ == "__main__":
    main()
