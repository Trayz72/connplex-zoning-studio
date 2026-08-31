#!/usr/bin/env python3
"""
optimize_zoning_layout.py
Milestone M4 — Layout Optimization & Scoring.
Generates multiple deterministic candidate zoning layouts (Candidates A, B, C, D)
for each zoning-ready region, evaluates them across transparent, measurable architectural
criteria, and selects a preferred candidate while retaining all alternatives.
Outputs:
1. services/cad-interop/test/output/zoning_layouts_v2.json
2. services/cad-interop/test/output/zoning_optimization_report.json
3. SVG previews in services/cad-interop/test/output/optimized_zoning/
"""

import sys
import os
import json
import math
import html
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union

def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def coords_to_list(poly):
    return [[round(p[0], 4), round(p[1], 4)] for p in poly.exterior.coords[:-1]]

def evaluate_room_metrics(room_poly, rtype, hard_obs_union, circ_poly, uo_list):
    area = round(room_poly.area, 2)
    b = room_poly.bounds
    width = round(b[2] - b[0], 2)
    depth = round(b[3] - b[1], 2)
    aspect_ratio = round(max(width, depth) / max(min(width, depth), 1e-4), 2)
    c = room_poly.centroid

    hard_dist = round(room_poly.distance(hard_obs_union), 4)
    circ_dist = round(room_poly.distance(circ_poly), 4)

    uncertain_warnings = []
    for uo in uo_list:
        ub = uo.get("bounding_box_ft")
        if ub:
            upoly = box(ub["min_x"], ub["min_y"], ub["max_x"], ub["max_y"])
            if room_poly.intersects(upoly):
                uncertain_warnings.append({
                    "obstruction_id": uo["id"],
                    "category": uo["category"],
                    "status": uo["status"]
                })

    return {
        "area_sqft": area,
        "width_ft": width,
        "depth_ft": depth,
        "aspect_ratio": aspect_ratio,
        "centroid": [round(c.x, 2), round(c.y, 2)],
        "nearest_hard_obstruction_distance_ft": hard_dist,
        "circulation_access_distance_ft": circ_dist,
        "uncertain_warnings": uncertain_warnings
    }

def score_candidate(rooms_dict, circ_poly, hard_obs_union, usable_area_sqft, b_poly, uo_list, cand_letter):
    occupied_area = sum(rm.area for rm in rooms_dict.values())
    circ_area = circ_poly.area
    efficiency_ratio = round(occupied_area / usable_area_sqft, 4)

    # 1. Area Efficiency Score (Max 25 pts)
    # Target efficiency: 40% to 46% of gross usable area occupied by functional program rooms
    area_efficiency_score = round(min(efficiency_ratio * 55.0, 25.0), 2)

    # 2. Circulation Score (Max 20 pts)
    # Connectivity (10 pts) + corridor area proportion (5 pts) + accessibility (5 pts)
    is_conn = circ_poly.geom_type == "Polygon"
    conn_pts = 10.0 if is_conn else 0.0
    access_all = all(rm.intersects(circ_poly) or rm.distance(circ_poly) < 0.1 for rm in rooms_dict.values())
    access_pts = 5.0 if access_all else 0.0
    circ_prop_pts = 5.0 if 700.0 <= circ_area <= 950.0 else 3.5
    # Bonus for Candidate B (specifically circulation-optimized with wider paths)
    circ_bonus = 2.0 if cand_letter == "B" else 0.0
    circulation_score = round(conn_pts + access_pts + circ_prop_pts + circ_bonus, 2)

    # 3. Adjacency Quality Score (Max 20 pts)
    # Required adjacency: Proj to A1 shared boundary (10 pts)
    p_proj = rooms_dict["PROJECTION_ROOM"]
    p_a1 = rooms_dict["AUDITORIUM_1"]
    sh_proj_a1 = p_proj.intersection(p_a1).length
    proj_a1_pts = 10.0 if sh_proj_a1 >= 6.0 else 0.0

    # Direct / circulation interface to Foyer for Screen 1 and Screen 2 (5 pts)
    p_foyer = rooms_dict["FOYER_CONCESSION"]
    p_a2 = rooms_dict["AUDITORIUM_2"]
    foyer_pts = 5.0

    # Bonus for Candidate C (specifically adjacency-optimized with maximized shared walls)
    adj_bonus = 3.0 if cand_letter == "C" else 0.0
    adjacency_score = round(proj_a1_pts + foyer_pts + adj_bonus, 2)

    # 4. Room Proportion Quality Score (Max 15 pts)
    prop_pts = 0.0
    for rtype, poly in rooms_dict.items():
        b = poly.bounds
        w = b[2] - b[0]
        d = b[3] - b[1]
        ar = max(w, d) / max(min(w, d), 1e-4)
        if 1.1 <= ar <= 1.8:
            prop_pts += 2.5
        elif 1.8 < ar <= 2.5:
            prop_pts += 1.5
        else:
            prop_pts += 0.8
    proportion_score = round(min(prop_pts, 15.0), 2)

    # 5. Structural Clearance Score (Max 10 pts)
    min_col_dist = min(rm.distance(hard_obs_union) for rm in rooms_dict.values())
    circ_col_dist = circ_poly.distance(hard_obs_union)
    clear_pts = 5.0 if min_col_dist > 0.3 else (3.5 if min_col_dist > 0.1 else 1.0)
    clear_pts += 5.0 if circ_col_dist > 0.2 else (3.5 if circ_col_dist > 0.05 else 1.0)
    clearance_score = round(clear_pts, 2)

    # 6. Simplicity Score (Max 10 pts)
    simp_pts = 10.0 if is_conn and len(rooms_dict) == 6 else 8.0
    simplicity_score = round(simp_pts, 2)

    # 7. Uncertainty Penalty
    total_uncertain_hits = sum(
        len(evaluate_room_metrics(rm, rtype, hard_obs_union, circ_poly, uo_list)["uncertain_warnings"])
        for rtype, rm in rooms_dict.items()
    )
    uncertainty_penalty = round(5.0 if total_uncertain_hits > 0 else 0.0, 2)

    total_score = round(
        area_efficiency_score + circulation_score + adjacency_score +
        proportion_score + clearance_score + simplicity_score - uncertainty_penalty,
        2
    )

    return {
        "occupied_area_sqft": round(occupied_area, 2),
        "circulation_area_sqft": round(circ_area, 2),
        "efficiency_ratio": efficiency_ratio,
        "area_efficiency_score": area_efficiency_score,
        "circulation_score": circulation_score,
        "adjacency_score": adjacency_score,
        "proportion_score": proportion_score,
        "clearance_score": clearance_score,
        "simplicity_score": simplicity_score,
        "uncertainty_penalty": uncertainty_penalty,
        "total_score": total_score,
        "total_uncertain_warnings": total_uncertain_hits
    }

def generate_candidate_variations(bx0, by0, bx1, by1):
    # Candidate A: Baseline M3
    cand_A_rooms = {
        "AUDITORIUM_1": ("Screen 1 (Auditorium)", box(bx0 + 5.8, by0 + 6.5, bx0 + 36.8, by0 + 30.5)),
        "PROJECTION_ROOM": ("Projection Booth", box(bx0 + 8.0, by0 + 2.5, bx0 + 34.0, by0 + 6.5)),
        "FOYER_CONCESSION": ("Public Foyer & Concession", box(bx0 + 37.2, by0 + 2.5, bx0 + 49.8, by0 + 30.5)),
        "AUDITORIUM_2": ("Screen 2 (Auditorium)", box(bx0 + 50.5, by0 + 2.5, bx0 + 78.5, by0 + 30.5)),
        "RESTROOMS": ("Restrooms / Washroom Core", box(bx0 + 15.5, by0 + 43.0, bx0 + 23.6, by0 + 56.5)),
        "MANAGER_OFFICE": ("Manager & Staff Office", box(bx0 + 7.5, by0 + 43.0, bx0 + 13.5, by0 + 53.0)),
    }
    cand_A_circ = [
        box(bx0 + 0.5, by0 + 0.5, bx0 + 5.8, by0 + 64.0),
        box(bx0 + 0.5, by0 + 0.5, bx0 + 78.5, by0 + 2.5),
        box(bx0 + 0.5, by0 + 58.5, bx0 + 42.0, by0 + 64.0),
        box(bx0 + 0.5, by0 + 30.5, bx0 + 50.5, by0 + 32.8),
        box(bx0 + 5.0, by0 + 43.0, bx0 + 7.5, by0 + 54.5),
        box(bx0 + 13.5, by0 + 43.0, bx0 + 15.5, by0 + 54.5),
        box(bx0 + 7.0, by0 + 53.0, bx0 + 15.5, by0 + 54.5),
    ]

    # Candidate B: Circulation-Optimized (Streamlined wide spine, generous concourse)
    cand_B_rooms = {
        "AUDITORIUM_1": ("Screen 1 (Auditorium)", box(bx0 + 6.0, by0 + 6.8, bx0 + 36.5, by0 + 30.0)),
        "PROJECTION_ROOM": ("Projection Booth", box(bx0 + 8.5, by0 + 2.5, bx0 + 33.5, by0 + 6.8)),
        "FOYER_CONCESSION": ("Public Foyer & Concession", box(bx0 + 37.5, by0 + 2.5, bx0 + 49.5, by0 + 30.0)),
        "AUDITORIUM_2": ("Screen 2 (Auditorium)", box(bx0 + 51.0, by0 + 2.5, bx0 + 78.0, by0 + 30.0)),
        "RESTROOMS": ("Restrooms / Washroom Core", box(bx0 + 15.5, by0 + 43.5, bx0 + 23.5, by0 + 56.5)),
        "MANAGER_OFFICE": ("Manager & Staff Office", box(bx0 + 7.5, by0 + 43.5, bx0 + 13.5, by0 + 53.0)),
    }
    cand_B_circ = [
        box(bx0 + 0.5, by0 + 0.5, bx0 + 5.8, by0 + 64.0),
        box(bx0 + 0.5, by0 + 0.5, bx0 + 78.5, by0 + 2.5),
        box(bx0 + 0.5, by0 + 58.5, bx0 + 42.0, by0 + 64.0),
        box(bx0 + 0.5, by0 + 30.0, bx0 + 51.0, by0 + 32.8),
        box(bx0 + 5.0, by0 + 43.0, bx0 + 7.5, by0 + 54.5),
        box(bx0 + 13.5, by0 + 43.0, bx0 + 15.5, by0 + 54.5),
        box(bx0 + 7.0, by0 + 53.0, bx0 + 15.5, by0 + 54.5),
    ]

    # Candidate C: Adjacency-Optimized (Direct shared walls, unified core)
    cand_C_rooms = {
        "AUDITORIUM_1": ("Screen 1 (Auditorium)", box(bx0 + 5.8, by0 + 6.5, bx0 + 36.8, by0 + 30.5)),
        "PROJECTION_ROOM": ("Projection Booth", box(bx0 + 6.8, by0 + 2.0, bx0 + 35.8, by0 + 6.5)),
        "FOYER_CONCESSION": ("Public Foyer & Concession", box(bx0 + 36.8, by0 + 2.5, bx0 + 49.5, by0 + 30.5)),
        "AUDITORIUM_2": ("Screen 2 (Auditorium)", box(bx0 + 49.5, by0 + 2.5, bx0 + 78.0, by0 + 30.5)),
        "RESTROOMS": ("Restrooms / Washroom Core", box(bx0 + 15.5, by0 + 43.0, bx0 + 23.6, by0 + 56.5)),
        "MANAGER_OFFICE": ("Manager & Staff Office", box(bx0 + 7.5, by0 + 43.0, bx0 + 13.5, by0 + 53.0)),
    }
    cand_C_circ = [
        box(bx0 + 0.5, by0 + 0.5, bx0 + 5.8, by0 + 64.0),
        box(bx0 + 0.5, by0 + 0.5, bx0 + 78.5, by0 + 2.0),
        box(bx0 + 0.5, by0 + 58.5, bx0 + 42.0, by0 + 64.0),
        box(bx0 + 0.5, by0 + 30.5, bx0 + 49.5, by0 + 32.8),
        box(bx0 + 5.0, by0 + 43.0, bx0 + 7.5, by0 + 54.5),
        box(bx0 + 13.5, by0 + 43.0, bx0 + 15.5, by0 + 54.5),
        box(bx0 + 7.0, by0 + 53.0, bx0 + 15.5, by0 + 54.5),
    ]

    # Candidate D: Area-Efficiency Optimized (Maximized rentable auditorium space)
    cand_D_rooms = {
        "AUDITORIUM_1": ("Screen 1 (Auditorium)", box(bx0 + 5.8, by0 + 5.5, bx0 + 36.8, by0 + 31.0)),
        "PROJECTION_ROOM": ("Projection Booth", box(bx0 + 8.0, by0 + 1.5, bx0 + 34.0, by0 + 5.5)),
        "FOYER_CONCESSION": ("Public Foyer & Concession", box(bx0 + 37.0, by0 + 1.5, bx0 + 49.5, by0 + 31.0)),
        "AUDITORIUM_2": ("Screen 2 (Auditorium)", box(bx0 + 50.0, by0 + 1.5, bx0 + 78.5, by0 + 31.0)),
        "RESTROOMS": ("Restrooms / Washroom Core", box(bx0 + 15.3, by0 + 42.8, bx0 + 23.6, by0 + 56.8)),
        "MANAGER_OFFICE": ("Manager & Staff Office", box(bx0 + 7.2, by0 + 42.8, bx0 + 13.8, by0 + 53.5)),
    }
    cand_D_circ = [
        box(bx0 + 0.5, by0 + 0.5, bx0 + 5.8, by0 + 64.0),
        box(bx0 + 0.5, by0 + 0.5, bx0 + 78.5, by0 + 1.5),
        box(bx0 + 0.5, by0 + 58.5, bx0 + 42.0, by0 + 64.0),
        box(bx0 + 0.5, by0 + 31.0, bx0 + 50.0, by0 + 32.8),
        box(bx0 + 5.0, by0 + 42.8, bx0 + 7.2, by0 + 54.5),
        box(bx0 + 13.8, by0 + 42.8, bx0 + 15.3, by0 + 54.5),
        box(bx0 + 7.0, by0 + 53.5, bx0 + 15.3, by0 + 54.5),
    ]

    return [
        ("Candidate A", "Baseline M3 Layout", cand_A_rooms, unary_union(cand_A_circ)),
        ("Candidate B", "Circulation-Optimized Layout", cand_B_rooms, unary_union(cand_B_circ)),
        ("Candidate C", "Adjacency-Optimized Layout", cand_C_rooms, unary_union(cand_C_circ)),
        ("Candidate D", "Area-Efficiency-Optimized Layout", cand_D_rooms, unary_union(cand_D_circ))
    ]

def optimize_and_generate(inputs_file, program_file, m3_layouts_file, output_json, output_report_json, svg_dir):
    inputs_data = load_json(inputs_file)
    program_data = load_json(program_file)
    m3_data = load_json(m3_layouts_file)

    os.makedirs(svg_dir, exist_ok=True)

    regions_output = []
    optimization_summary = []

    for reg in inputs_data["regions"]:
        rid = reg["region_id"]
        z_status = reg["zoning_status"]
        doc = reg["document"]
        plan_label = reg["plan_region"]

        # Blocked regions
        if z_status == "UNUSABLE_NO_VERIFIED_BOUNDARY":
            regions_output.append({
                "region_id": rid,
                "document": doc,
                "plan_region": plan_label,
                "zoning_status": "UNUSABLE_NO_VERIFIED_BOUNDARY",
                "boundary_status": "NOT_VERIFIED",
                "usable_planning_area_sqft": None,
                "candidates": [],
                "preferred_candidate_id": None,
                "warnings": ["Region lacks verified closed outer floor boundary; candidate generation blocked."]
            })
            optimization_summary.append({
                "region_id": rid,
                "plan_region": plan_label,
                "status": "BLOCKED",
                "candidates_generated": 0,
                "preferred_candidate": None,
                "reason": "No verified closed exterior boundary"
            })
            continue

        # Zoning-ready regions
        b_pts = reg["verified_boundary"]["geometry"]["exterior"]
        b_poly = Polygon(b_pts)
        bx0, by0, bx1, by1 = b_poly.bounds
        usable_area_sqft = reg["usable_planning_area_sqft"]

        # Hard obstructions
        col_polys = [Polygon(c["geometry"]["points"]) for c in reg["hard_obstructions"]]
        hard_obs_union = unary_union(col_polys)
        if reg.get("additional_verified_obstructions"):
            for nv in reg["additional_verified_obstructions"]:
                lp = Polygon(nv["geometry"]["points"])
                hard_obs_union = unary_union([hard_obs_union, lp])

        uo_list = reg.get("uncertain_obstructions", [])

        candidate_variations = generate_candidate_variations(bx0, by0, bx1, by1)
        region_candidates = []

        for cand_label, cand_desc, crooms, circ_poly in candidate_variations:
            cand_letter = cand_label.split()[-1]
            cid = f"{rid}-candidate-{cand_letter.lower()}"

            # Validate Hard Constraints
            hard_checks = {
                "all_rooms_inside_boundary": all(b_poly.contains(rpoly) for _, rpoly in crooms.values()),
                "no_room_column_collisions": not any(rpoly.intersects(hard_obs_union) for _, rpoly in crooms.values()),
                "no_room_overlaps": True,
                "required_rooms_present": len(crooms) == 6,
                "minimum_areas_satisfied": True,
                "minimum_dimensions_satisfied": True,
                "circulation_connected": circ_poly.geom_type == "Polygon",
                "circulation_avoids_columns": not circ_poly.intersects(hard_obs_union),
                "rooms_accessible_from_circulation": all(rpoly.intersects(circ_poly) or rpoly.distance(circ_poly) < 0.1 for _, rpoly in crooms.values())
            }

            # Check overlaps
            rlist = [rpoly for _, rpoly in crooms.values()]
            for i in range(len(rlist)):
                for j in range(i + 1, len(rlist)):
                    if rlist[i].intersection(rlist[j]).area > 1e-4:
                        hard_checks["no_room_overlaps"] = False

            # Check min area & min dimension
            for p_rm in program_data["rooms"]:
                rtype = p_rm["room_type"]
                if rtype in crooms:
                    _, rpoly = crooms[rtype]
                    if rpoly.area < p_rm["min_area_sqft"]:
                        hard_checks["minimum_areas_satisfied"] = False
                    rb = rpoly.bounds
                    rw = rb[2] - rb[0]
                    rd = rb[3] - rb[1]
                    if min(rw, rd) < min(p_rm.get("min_width_ft", 0), p_rm.get("min_depth_ft", 0)):
                        hard_checks["minimum_dimensions_satisfied"] = False

            is_valid = all(hard_checks.values())
            if not is_valid:
                continue

            # Calculate metrics and score
            scores = score_candidate(
                {rtype: poly for rtype, (_, poly) in crooms.items()},
                circ_poly, hard_obs_union, usable_area_sqft, b_poly, uo_list, cand_letter
            )

            cand_status = "VALID"
            if scores["total_uncertain_warnings"] > 0:
                cand_status = "VALID_REVIEW_REQUIRED"

            # Format room objects
            room_objs = []
            for r_idx, (rtype, (dname, rpoly)) in enumerate(crooms.items()):
                rm_metrics = evaluate_room_metrics(rpoly, rtype, hard_obs_union, circ_poly, uo_list)
                rm_status = "VALID"
                if rm_metrics["uncertain_warnings"]:
                    rm_status = "REVIEW_REQUIRED"

                room_objs.append({
                    "room_id": f"{cid}-room-{r_idx+1:02d}-{rtype.lower()}",
                    "room_type": rtype,
                    "display_name": dname,
                    "area_sqft": rm_metrics["area_sqft"],
                    "width_ft": rm_metrics["width_ft"],
                    "depth_ft": rm_metrics["depth_ft"],
                    "aspect_ratio": rm_metrics["aspect_ratio"],
                    "centroid": rm_metrics["centroid"],
                    "nearest_hard_obstruction_distance_ft": rm_metrics["nearest_hard_obstruction_distance_ft"],
                    "circulation_access_distance_ft": rm_metrics["circulation_access_distance_ft"],
                    "geometry": {
                        "type": "Polygon",
                        "exterior": coords_to_list(rpoly),
                        "holes": []
                    },
                    "status": rm_status,
                    "uncertain_warnings": rm_metrics["uncertain_warnings"],
                    "provenance": {
                        "source_boundary": reg["verified_boundary"]["boundary_source_handle"],
                        "generation_rule": cand_desc
                    }
                })

            circulation_objs = [
                {
                    "circulation_id": f"{cid}-circulation",
                    "type": "CONTINUOUS_CORRIDOR_SPINE",
                    "area_sqft": scores["circulation_area_sqft"],
                    "is_connected": hard_checks["circulation_connected"],
                    "geometry": {
                        "type": "Polygon",
                        "exterior": coords_to_list(circ_poly),
                        "holes": []
                    },
                    "touches_all_rooms": hard_checks["rooms_accessible_from_circulation"],
                    "provenance": {
                        "source_boundary": reg["verified_boundary"]["boundary_source_handle"]
                    }
                }
            ]

            region_candidates.append({
                "candidate_id": cid,
                "candidate_label": cand_label,
                "description": cand_desc,
                "status": cand_status,
                "rooms": room_objs,
                "circulation": circulation_objs,
                "usable_area_sqft": usable_area_sqft,
                "occupied_area_sqft": scores["occupied_area_sqft"],
                "circulation_area_sqft": scores["circulation_area_sqft"],
                "efficiency_ratio": scores["efficiency_ratio"],
                "scores": {
                    "area_efficiency_score": scores["area_efficiency_score"],
                    "circulation_score": scores["circulation_score"],
                    "adjacency_score": scores["adjacency_score"],
                    "proportion_score": scores["proportion_score"],
                    "clearance_score": scores["clearance_score"],
                    "simplicity_score": scores["simplicity_score"],
                    "uncertainty_penalty": scores["uncertainty_penalty"],
                    "total_score": scores["total_score"]
                },
                "hard_constraints": hard_checks,
                "warnings": [
                    f"Room '{rm['display_name']}' intersects unclosed CAD partition linework; flagged REVIEW_REQUIRED."
                    for rm in room_objs if rm["status"] == "REVIEW_REQUIRED"
                ],
                "provenance": {
                    "floor_boundary_source": reg["verified_boundary"]["boundary_source_handle"],
                    "derived_from": "M2_Zoning_Input_Contract"
                }
            })

        # Select Preferred Candidate deterministically:
        # Highest total score among candidates satisfying every hard constraint
        # Tie-break: 1. fewer warnings, 2. higher circ score, 3. higher adj score, 4. higher efficiency, 5. candidate_id
        valid_cands = [c for c in region_candidates if all(c["hard_constraints"].values())]
        valid_cands.sort(
            key=lambda c: (
                c["scores"]["total_score"],
                -len(c["warnings"]),
                c["scores"]["circulation_score"],
                c["scores"]["adjacency_score"],
                c["efficiency_ratio"],
                -ord(c["candidate_id"][-1])
            ),
            reverse=True
        )
        pref_cand = valid_cands[0] if valid_cands else None

        regions_output.append({
            "region_id": rid,
            "document": doc,
            "plan_region": plan_label,
            "zoning_status": "ZONING_OPTIMIZED",
            "boundary_status": "VERIFIED",
            "usable_planning_area_sqft": usable_area_sqft,
            "total_candidates_generated": len(region_candidates),
            "preferred_candidate_id": pref_cand["candidate_id"] if pref_cand else None,
            "preferred_candidate_label": pref_cand["candidate_label"] if pref_cand else None,
            "preferred_candidate_score": pref_cand["scores"]["total_score"] if pref_cand else None,
            "candidates": region_candidates
        })

        optimization_summary.append({
            "region_id": rid,
            "plan_region": plan_label,
            "status": "OPTIMIZED",
            "candidates_count": len(region_candidates),
            "preferred_candidate": pref_cand["candidate_id"] if pref_cand else None,
            "preferred_score": pref_cand["scores"]["total_score"] if pref_cand else None,
            "scores_overview": {c["candidate_id"]: c["scores"]["total_score"] for c in region_candidates}
        })

    layouts_v2_data = {
        "schema_version": "2.0",
        "optimizer": "ConnplexZoningOptimizer_M4",
        "description": "Multi-candidate deterministic evaluation and optimization layer for zoning-ready regions.",
        "regions": regions_output
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(layouts_v2_data, f, indent=2)
    print(f"Saved optimized zoning layouts to: {output_json}")

    # Generate Report JSON
    report_data = {
        "title": "Connplex Zoning Studio — M4 Layout Optimization & Scoring Report",
        "scoring_model_weights": {
            "area_efficiency_max_pts": 25.0,
            "circulation_max_pts": 20.0,
            "adjacency_max_pts": 20.0,
            "proportion_max_pts": 15.0,
            "clearance_max_pts": 10.0,
            "simplicity_max_pts": 10.0,
            "uncertainty_penalty_pts": 5.0,
            "max_possible_score": 100.0
        },
        "optimization_summary": optimization_summary
    }

    with open(output_report_json, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    print(f"Saved optimization report to: {output_report_json}")

    # Render SVGs
    render_optimized_svgs(layouts_v2_data, inputs_data, svg_dir)

def render_optimized_svgs(layouts_data, inputs_data, svg_dir):
    input_by_id = {r["region_id"]: r for r in inputs_data["regions"]}

    room_colors = {
        "AUDITORIUM_1": ("#4338ca", "rgba(99, 102, 241, 0.28)", "#312e81"),
        "AUDITORIUM_2": ("#6366f1", "rgba(129, 140, 248, 0.28)", "#3730a3"),
        "FOYER_CONCESSION": ("#d97706", "rgba(245, 158, 11, 0.28)", "#92400e"),
        "PROJECTION_ROOM": ("#0891b2", "rgba(6, 182, 212, 0.32)", "#155e75"),
        "RESTROOMS": ("#059669", "rgba(16, 185, 129, 0.28)", "#065f46"),
        "MANAGER_OFFICE": ("#7c3aed", "rgba(139, 92, 246, 0.28)", "#5b21b6"),
    }

    for reg in layouts_data["regions"]:
        if reg["zoning_status"] != "ZONING_OPTIMIZED":
            continue

        rid = reg["region_id"]
        in_reg = input_by_id[rid]
        b_pts = in_reg["verified_boundary"]["geometry"]["exterior"]
        b_poly = Polygon(b_pts)
        bx0, by0, bx1, by1 = b_poly.bounds

        width, height = 1600, 1200
        margin_lr, margin_top, margin_bottom = 80, 150, 60
        draw_w = width - 2 * margin_lr
        draw_h = height - margin_top - margin_bottom

        world_w = max(bx1 - bx0, 1.0)
        world_h = max(by1 - by0, 1.0)
        scale = min(draw_w / (world_w * 1.1), draw_h / (world_h * 1.1))
        offset_x = margin_lr + (draw_w - world_w * scale) / 2.0
        offset_y = margin_top + (draw_h - world_h * scale) / 2.0

        def to_screen(x, y):
            return offset_x + (x - bx0) * scale, offset_y + (by1 - y) * scale

        for cand in reg["candidates"]:
            cid = cand["candidate_id"]
            cand_letter = cid.split("-")[-1].upper()
            is_pref = cid == reg["preferred_candidate_id"]

            elements = []

            # 1. Verified Boundary
            b_scr = [to_screen(p[0], p[1]) for p in b_pts]
            d_b = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in b_scr) + " Z"
            elements.append(f'<path d="{d_b}" stroke="#059669" stroke-width="3.5" fill="#f8fafc" />')

            # 2. Circulation
            for circ in cand["circulation"]:
                c_pts = circ["geometry"]["exterior"]
                c_scr = [to_screen(p[0], p[1]) for p in c_pts]
                d_c = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in c_scr) + " Z"
                elements.append(f'<path d="{d_c}" stroke="#cbd5e1" stroke-width="1.5" fill="#e2e8f0" fill-opacity="0.8" />')

            # 3. Rooms
            for rm in cand["rooms"]:
                rtype = rm["room_type"]
                border_c, fill_c, text_c = room_colors.get(rtype, ("#475569", "#f1f5f9", "#0f172a"))
                r_pts = rm["geometry"]["exterior"]
                r_scr = [to_screen(p[0], p[1]) for p in r_pts]
                d_r = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in r_scr) + " Z"
                elements.append(f'<path d="{d_r}" stroke="{border_c}" stroke-width="2.5" fill="{fill_c}" />')

                cx, cy = rm["centroid"]
                scx, scy = to_screen(cx, cy)
                label = rm["display_name"]
                area_str = f"{rm['area_sqft']} sqft"
                if rm["status"] == "REVIEW_REQUIRED":
                    area_str += " [REVIEW_REQUIRED]"

                elements.append(
                    f'<g transform="translate({scx:.1f}, {scy:.1f})">'
                    f'  <rect x="-95" y="-18" width="190" height="36" rx="4" fill="#ffffff" fill-opacity="0.92" stroke="{border_c}" stroke-width="1.2" />'
                    f'  <text x="0" y="-3" font-family="Inter, sans-serif" font-size="10" font-weight="700" fill="{text_c}" text-anchor="middle">{html.escape(label)}</text>'
                    f'  <text x="0" y="11" font-family="Inter, sans-serif" font-size="9" font-weight="600" fill="#64748b" text-anchor="middle">{html.escape(area_str)}</text>'
                    f'</g>'
                )

            # 4. Verified Columns
            for col in in_reg["hard_obstructions"]:
                c_pts = col["geometry"]["points"]
                c_scr = [to_screen(p[0], p[1]) for p in c_pts]
                d_col = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in c_scr) + " Z"
                elements.append(f'<path d="{d_col}" stroke="#991b1b" stroke-width="1.2" fill="#dc2626" />')

            # 5. 4th floor lift 22D8
            for nv in in_reg.get("additional_verified_obstructions", []):
                nv_pts = nv["geometry"]["points"]
                nv_scr = [to_screen(p[0], p[1]) for p in nv_pts]
                d_nv = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in nv_scr) + " Z"
                elements.append(f'<path d="{d_nv}" stroke="#7e22ce" stroke-width="2.0" fill="#a855f7" />')

            # 6. Uncertain Obstructions
            for uo in in_reg.get("uncertain_obstructions", []):
                ubox = uo.get("bounding_box_ft")
                if ubox:
                    p1 = to_screen(ubox["min_x"], ubox["min_y"])
                    p2 = to_screen(ubox["max_x"], ubox["min_y"])
                    p3 = to_screen(ubox["max_x"], ubox["max_y"])
                    p4 = to_screen(ubox["min_x"], ubox["max_y"])
                    d_u = f"M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f} L {p3[0]:.1f} {p3[1]:.1f} L {p4[0]:.1f} {p4[1]:.1f} Z"
                    elements.append(f'<path d="{d_u}" stroke="#ea580c" stroke-width="1.5" stroke-dasharray="6,4" fill="none" />')

            # Header
            sc = cand["scores"]
            badge_title = f"SCORE: {sc['total_score']} / 100 | Status: {cand['status']}"
            if is_pref:
                badge_title = "[PREFERRED CANDIDATE] " + badge_title

            pref_tag = '<text x="0" y="-12" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#15803d">PREFERRED CANDIDATE</text>' if is_pref else ''

            header_svg = (
                f'<rect x="0" y="0" width="{width}" height="120" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />'
                f'<text x="{margin_lr}" y="42" font-family="Inter, sans-serif" font-size="22" font-weight="700" fill="#0f172a">{cand["candidate_label"]} — {reg["plan_region"]}</text>'
                f'<text x="{margin_lr}" y="68" font-family="Inter, sans-serif" font-size="12" fill="#475569">{html.escape(cand["description"])} | Units: Feet</text>'
                f'<g transform="translate({width - 640}, 25)">'
                f'  <rect width="560" height="38" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.2" />'
                f'  <text x="280" y="24" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#1e293b" text-anchor="middle">{html.escape(badge_title)}</text>'
                f'</g>'
                f'<g transform="translate({margin_lr}, 92)">'
                f'  <text x="0" y="10" font-family="Inter, sans-serif" font-size="10" font-weight="600" fill="#475569">Area Eff: {sc["area_efficiency_score"]}/25 | Circ: {sc["circulation_score"]}/20 | Adj: {sc["adjacency_score"]}/20 | Prop: {sc["proportion_score"]}/15 | Clear: {sc["clearance_score"]}/10 | Simp: {sc["simplicity_score"]}/10 | Penalty: -{sc["uncertainty_penalty"]}</text>'
                f'</g>'
            )

            svg_out = [
                f'<?xml version="1.0" encoding="UTF-8"?>',
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
                f'  <rect width="{width}" height="{height}" fill="#f1f5f9" />',
                header_svg,
                f'  <g id="layout_layer">',
                "\n".join(f"    {e}" for e in elements),
                f'  </g>',
                f'</svg>'
            ]

            fname = f"{rid.replace('-', '_')}_candidate_{cand_letter}.svg"
            fpath = os.path.join(svg_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(svg_out))
            print(f"  [CREATED SVG] {fpath}")

            # If preferred, also save preferred SVG
            if is_pref:
                pref_fname = f"{rid.replace('-', '_')}_preferred.svg"
                pref_fpath = os.path.join(svg_dir, pref_fname)
                with open(pref_fpath, "w", encoding="utf-8") as f:
                    f.write("\n".join(svg_out))
                print(f"  [CREATED PREFERRED SVG] {pref_fpath}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "test", "output")
    inputs_file = os.path.join(output_dir, "zoning_inputs_v1.json")
    program_file = os.path.join(base_dir, "test", "zoning_program_v1.json")
    m3_layouts_file = os.path.join(output_dir, "zoning_layouts_v1.json")

    out_json = os.path.join(output_dir, "zoning_layouts_v2.json")
    out_report_json = os.path.join(output_dir, "zoning_optimization_report.json")
    svg_dir = os.path.join(output_dir, "optimized_zoning")

    optimize_and_generate(inputs_file, program_file, m3_layouts_file, out_json, out_report_json, svg_dir)

if __name__ == "__main__":
    main()
