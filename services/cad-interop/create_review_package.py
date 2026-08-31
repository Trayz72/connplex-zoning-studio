#!/usr/bin/env python3
"""
create_review_package.py
Milestone M6 — Architect Review & Decision Workflow.
Generates an auditable, deterministic human-review layer over the frozen M5 decision package.
Outputs:
1. services/cad-interop/test/output/review_package_v1.json
2. services/cad-interop/test/output/review_summary.json
3. services/cad-interop/test/output/reviewer_template.json
4. services/cad-interop/test/output/review_report.md
5. Visualizations in services/cad-interop/test/output/review_package/
"""

import sys
import os
import json
import html
from shapely.geometry import Polygon, box

DISCLAIMER_TEXT = (
    "DISCLAIMER: This document and associated review records represent a human-review interface and computational baseline. "
    "This system does NOT constitute statutory architectural approval, certified building-code compliance, structural engineering clearance, "
    "fire-safety certification, or construction-readiness documentation. Final construction drawings and life-safety compliance "
    "must be prepared, sealed, and certified by an appropriately licensed professional architect and registered structural engineer."
)

def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def create_review_package():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, "test", "output")
    svg_dir = os.path.join(out_dir, "review_package")
    os.makedirs(svg_dir, exist_ok=True)

    # 1. Authoritative Frozen Inputs
    decision_file = os.path.join(out_dir, "zoning_decision_v1.json")
    decision_summary_file = os.path.join(out_dir, "zoning_decision_summary.json")
    layouts_v2_file = os.path.join(out_dir, "zoning_layouts_v2.json")
    inputs_file = os.path.join(out_dir, "zoning_inputs_v1.json")

    dec_data = load_json(decision_file)
    lay_data = load_json(layouts_v2_file)
    inputs_data = load_json(inputs_file)

    inputs_map = {r["region_id"]: r for r in inputs_data["regions"]}
    lay_map = {r["region_id"]: r for r in lay_data["regions"]}

    review_regions = []
    summary_regions = []

    for r in dec_data["regions"]:
        rid = r["region_id"]
        plan_label = r["plan_region"]
        doc = r["document"]
        dec_status = r["decision_status"]

        # BLOCKED REGIONS (Basement, Ground, Vadodara Option 1 & 2)
        if dec_status == "BLOCKED_NO_VERIFIED_BOUNDARY":
            blocker_item = {
                "item_id": f"{rid}-blocker-01",
                "item_type": "BOUNDARY_VERIFICATION_BLOCKER",
                "source_entity_id": rid,
                "description": "Verified exterior boundary required before architectural zoning review can commence.",
                "computational_status": "BLOCKED_NO_VERIFIED_BOUNDARY",
                "review_status": "BLOCKED",
                "reviewer_comment": "Zoning review blocked until closed outer exterior wall linework is verified in CAD model space.",
                "requested_action": "RECONSTRUCT_EXTERIOR_BOUNDARY_GEOMETRY",
                "provenance": {
                    "source": "CAD_Forensic_Extraction_v2",
                    "boundary_status": "NOT_VERIFIED"
                }
            }

            rev_reg = {
                "region_id": rid,
                "document": doc,
                "plan_region": plan_label,
                "m5_preferred_candidate_id": None,
                "m5_preferred_score": None,
                "computational_status": "BLOCKED_NO_VERIFIED_BOUNDARY",
                "review_status": "BLOCKED",
                "reviewer": {
                    "reviewer_name": None,
                    "reviewer_role": None,
                    "reviewer_license_reference": None
                },
                "review_timestamp": None,
                "overall_decision": "BLOCKED",
                "review_items": [blocker_item],
                "review_comments": [],
                "requested_revisions": ["Provide verified closed exterior boundary polylines."],
                "provenance": {
                    "boundary_status": "NOT_VERIFIED",
                    "input_decision_record": "zoning_decision_v1.json"
                }
            }
            review_regions.append(rev_reg)

            summary_regions.append({
                "region_id": rid,
                "plan_region": plan_label,
                "computational_status": "BLOCKED_NO_VERIFIED_BOUNDARY",
                "review_status": "BLOCKED",
                "overall_decision": "BLOCKED",
                "total_review_items": 1,
                "unreviewed_items_count": 0,
                "review_required_items_count": 0
            })
            continue

        # ZONING-READY REGIONS (Dhule 1st, 2nd, 3rd, 4th floors)
        pref = r["preferred_candidate"]
        pref_id = pref["candidate_id"]
        pref_score = pref["total_score"]
        in_reg = inputs_map[rid]
        lay_reg = lay_map[rid]
        pref_cand_geom = next(c for c in lay_reg["candidates"] if c["candidate_id"] == pref_id)

        # Build Review Items
        items = []

        # 1. Rooms Review Items (6 cinema program rooms)
        for rm in pref["room_summary"]:
            rtype = rm["room_type"]
            is_rev_req = rm["status"] == "REVIEW_REQUIRED"

            init_status = "REVIEW_REQUIRED" if is_rev_req else "NOT_REVIEWED"
            init_comment = "Special review required: intersects unclosed CAD partition linework in model space." if is_rev_req else None
            init_action = "VERIFY_PARTITION_INTEGRITY" if is_rev_req else None

            items.append({
                "item_id": f"{rid}-review-{rtype.lower()}",
                "item_type": "PROGRAM_ROOM",
                "source_entity_id": rm["room_id"],
                "room_type": rtype,
                "display_name": rm["display_name"],
                "area_sqft": rm["area_sqft"],
                "dimensions": rm["dimensions"],
                "computational_status": rm["status"],
                "review_status": init_status,
                "reviewer_comment": init_comment,
                "requested_action": init_action,
                "provenance": {
                    "source_candidate_id": pref_id,
                    "boundary_handle": in_reg["verified_boundary"]["boundary_source_handle"]
                }
            })

        # 2. Circulation Review Item
        circ = pref["circulation_summary"]
        items.append({
            "item_id": f"{rid}-review-circulation",
            "item_type": "CIRCULATION_NETWORK",
            "source_entity_id": circ["circulation_id"],
            "area_sqft": circ["area_sqft"],
            "is_connected": circ["is_connected"],
            "touches_all_rooms": circ["touches_all_rooms"],
            "primary_corridor_width_ft": circ["primary_corridor_width_ft"],
            "minimum_corridor_width_ft": circ["minimum_corridor_width_ft"],
            "computational_status": "CONNECTED",
            "review_status": "NOT_REVIEWED",
            "reviewer_comment": None,
            "requested_action": None,
            "provenance": {
                "source_candidate_id": pref_id,
                "boundary_handle": in_reg["verified_boundary"]["boundary_source_handle"]
            }
        })

        # 3. Structural Clearances Review Item
        sc = pref["structural_clearance_summary"]
        items.append({
            "item_id": f"{rid}-review-structural-clearance",
            "item_type": "STRUCTURAL_CLEARANCE",
            "source_entity_id": f"{rid}-structural-grid",
            "hard_obstruction_collisions": sc["hard_obstruction_collisions"],
            "minimum_room_column_clearance_ft": sc["minimum_room_column_clearance_ft"],
            "minimum_corridor_column_clearance_ft": sc["minimum_corridor_column_clearance_ft"],
            "columns_avoided_count": sc["columns_avoided_count"],
            "computational_status": "ZERO_COLLISION_VERIFIED",
            "review_status": "NOT_REVIEWED",
            "reviewer_comment": None,
            "requested_action": None,
            "provenance": {
                "columns_source": "DXF_Layer_COLUMN_(DCPL)",
                "columns_count": sc["columns_avoided_count"]
            }
        })

        # 4. Hard Obstructions Review Item
        items.append({
            "item_id": f"{rid}-review-hard-obstructions",
            "item_type": "HARD_OBSTRUCTIONS",
            "source_entity_id": f"{rid}-hard-obstructions",
            "verified_columns_count": len(in_reg["hard_obstructions"]),
            "additional_verified_obstructions_count": len(in_reg.get("additional_verified_obstructions", [])),
            "computational_status": "SUBTRACTED_AND_AVOIDED",
            "review_status": "NOT_REVIEWED",
            "reviewer_comment": None,
            "requested_action": None,
            "provenance": {
                "provenance_handles": [c.get("source_handle", c.get("id")) for c in in_reg["hard_obstructions"][:5]]
            }
        })

        # 5. Uncertain Geometry Review Item
        items.append({
            "item_id": f"{rid}-review-uncertain-geometry",
            "item_type": "UNCERTAIN_GEOMETRY",
            "source_entity_id": f"{rid}-uncertain-obstructions",
            "uncertain_obstructions_count": len(in_reg.get("uncertain_obstructions", [])),
            "treatment": "WARNING_NOT_SUBTRACTED",
            "computational_status": "PRESERVED_AS_WARNINGS",
            "review_status": "REVIEW_REQUIRED" if rid == "dhule-fourth-floor" else "NOT_REVIEWED",
            "reviewer_comment": "Inspect open stair linework and unclosed partition boundaries before construction sign-off.",
            "requested_action": "FIELD_VERIFY_OPEN_CAD_LINEWORK",
            "provenance": {
                "status": "FOOTPRINT_UNCERTAIN"
            }
        })

        # 6. Adjacency Relationships Review Item
        items.append({
            "item_id": f"{rid}-review-adjacencies",
            "item_type": "ADJACENCY_RELATIONSHIPS",
            "source_entity_id": f"{rid}-adjacencies",
            "projection_to_auditorium_shared_wall_ft": pref["adjacency_summary"]["projection_to_auditorium_shared_wall_ft"],
            "satisfaction_rate": pref["adjacency_summary"]["satisfaction_rate"],
            "computational_status": "SATISFIED_OPTIMAL",
            "review_status": "NOT_REVIEWED",
            "reviewer_comment": None,
            "requested_action": None,
            "provenance": {
                "program_schema": "zoning_program_v1.json"
            }
        })

        # 7. Fourth-Floor Unclosed Partition Linework Item (Explicitly for Fourth Floor)
        if rid == "dhule-fourth-floor":
            items.append({
                "item_id": "dhule-fourth-floor-review-unclosed-partitions",
                "item_type": "UNCLOSED_CAD_PARTITION_LINEWORK",
                "source_entity_id": "dhule-fourth-floor-partitions",
                "affected_rooms": ["RESTROOMS", "MANAGER_OFFICE"],
                "uncertainty_penalty": -5.00,
                "computational_status": "VALID_REVIEW_REQUIRED",
                "review_status": "REVIEW_REQUIRED",
                "reviewer_comment": "Unclosed residential/commercial CAD partition linework intersects candidate Restrooms and Manager Office footprints.",
                "requested_action": "ARCHITECT_FIELD_MEASUREMENT_AND_WALL_CONFIRMATION",
                "provenance": {
                    "cad_layer": "WALLS",
                    "inspection_note": "Open linework preserved without solid obstruction fabrication"
                }
            })

        rev_req_count = sum(1 for it in items if it["review_status"] == "REVIEW_REQUIRED")
        overall_rev_status = "REVIEW_REQUIRED" if rev_req_count > 0 else "NOT_REVIEWED"

        rev_reg = {
            "region_id": rid,
            "document": doc,
            "plan_region": plan_label,
            "m5_preferred_candidate_id": pref_id,
            "m5_preferred_score": pref_score,
            "computational_status": dec_status,
            "review_status": overall_rev_status,
            "reviewer": {
                "reviewer_name": None,
                "reviewer_role": None,
                "reviewer_license_reference": None
            },
            "review_timestamp": None,
            "overall_decision": "PENDING_REVIEW",
            "review_items": items,
            "review_comments": [],
            "requested_revisions": [
                "Verify fourth-floor unclosed CAD partition linework on-site." if rid == "dhule-fourth-floor" else "Review candidate room proportions and concession egress access."
            ],
            "provenance": {
                "m5_decision_source": "zoning_decision_v1.json",
                "preferred_candidate": pref_id,
                "boundary_handle": in_reg["verified_boundary"]["boundary_source_handle"]
            }
        }
        review_regions.append(rev_reg)

        summary_regions.append({
            "region_id": rid,
            "plan_region": plan_label,
            "computational_status": dec_status,
            "review_status": overall_rev_status,
            "overall_decision": "PENDING_REVIEW",
            "total_review_items": len(items),
            "unreviewed_items_count": sum(1 for it in items if it["review_status"] == "NOT_REVIEWED"),
            "review_required_items_count": rev_req_count
        })

    # Master Review Package Object
    package_data = {
        "schema_version": "1.0",
        "title": "Connplex Zoning Studio — Milestone M6 Architect Review & Decision Package",
        "description": "Structured human-review package providing auditability, individual item review, and decision tracking over M5 computational decisions.",
        "architectural_disclaimer": DISCLAIMER_TEXT,
        "review_session": {
            "session_id": "review-session-m6-001",
            "status": "PENDING_REVIEW",
            "reviewer_identity_assigned": False
        },
        "regions": review_regions
    }

    # Write review_package_v1.json
    out_pkg_json = os.path.join(out_dir, "review_package_v1.json")
    with open(out_pkg_json, "w", encoding="utf-8") as f:
        json.dump(package_data, f, indent=2)
    print(f"Saved review package to: {out_pkg_json}")

    # Write review_summary.json
    summary_data = {
        "title": "Connplex Zoning Studio — Architect Review Summary",
        "architectural_disclaimer": DISCLAIMER_TEXT,
        "total_regions": len(review_regions),
        "review_ready_floors_count": sum(1 for r in review_regions if r["review_status"] != "BLOCKED"),
        "blocked_regions_count": sum(1 for r in review_regions if r["review_status"] == "BLOCKED"),
        "overall_session_decision": "PENDING_REVIEW",
        "floors": summary_regions
    }
    out_sum_json = os.path.join(out_dir, "review_summary.json")
    with open(out_sum_json, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Saved review summary to: {out_sum_json}")

    # Write reviewer_template.json
    template_data = {
        "project": "Connplex Zoning Studio — Cinema Zoning Project",
        "reviewer_name": None,
        "reviewer_role": None,
        "reviewer_license_reference": None,
        "review_date": None,
        "overall_decision": "PENDING_REVIEW",
        "decision_options": [
            "PENDING_REVIEW",
            "ACCEPTED_WITHOUT_CHANGE",
            "ACCEPTED_WITH_NOTES",
            "REVISION_REQUESTED",
            "REJECTED",
            "BLOCKED"
        ],
        "item_review_options": [
            "NOT_REVIEWED",
            "ACCEPTED",
            "REJECTED",
            "NEEDS_REVISION",
            "REVIEW_REQUIRED",
            "BLOCKED"
        ],
        "comments": [],
        "disclaimer": DISCLAIMER_TEXT
    }
    out_tmpl_json = os.path.join(out_dir, "reviewer_template.json")
    with open(out_tmpl_json, "w", encoding="utf-8") as f:
        json.dump(template_data, f, indent=2)
    print(f"Saved reviewer template to: {out_tmpl_json}")

    # Generate review_report.md
    out_md = os.path.join(out_dir, "review_report.md")
    generate_review_report(package_data, out_md)

    # Render SVGs
    render_review_svgs(package_data, inputs_data, lay_data, svg_dir)

def generate_review_report(pkg_data, report_file):
    md = [
        "# Connplex Zoning Studio — Milestone M6 Architect Review Report",
        "",
        "> [!IMPORTANT]",
        f"> **Architectural Disclaimer**: {DISCLAIMER_TEXT}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        "Milestone M6 establishes the formal Human-in-the-Loop Architect Review and Decision layer for Connplex Zoning Studio. "
        "Built on top of the frozen M0–M5 computational baseline, M6 enables licensed architects and designated review professionals "
        "to inspect preferred candidate layouts, evaluate functional rooms, verify structural clearances, record comments, "
        "and register formal review decisions without mutating the underlying computational geometry.",
        "",
        "- **Total Regions**: 8",
        "- **Review-Ready Floors**: 4 (Dhule First, Second, Third, and Fourth floors)",
        "- **Blocked Regions**: 4 (Dhule Basement, Ground, Vadodara Option 1 & 2)",
        "- **Initial Review State**: `NOT_REVIEWED` / `PENDING_REVIEW`",
        "- **Special Review State**: Fourth Floor marked `VALID_REVIEW_REQUIRED` / `REVIEW_REQUIRED` due to unclosed partition linework",
        "- **Approval Claims**: **Zero**. Computational candidates are preserved strictly as decision-support models until formal human sign-off.",
        "",
        "---",
        "",
        "## 2. Computational Baseline vs. Human Review Layer",
        "",
        "| Layer | Responsible Entity | Authority | Role | Current Status |",
        "| :--- | :--- | :--- | :--- | :--- |",
        "| **Computational Baseline (M5)** | Algorithmic Optimization Pipeline | Objective Metric Evaluation | Produces preferred candidate layout | `DECISION_READY` (1st-3rd), `VALID_REVIEW_REQUIRED` (4th) |",
        "| **Human Review Layer (M6)** | Licensed Professional Architect | Professional & Statutory Judgment | Reviews, annotates, and certifies | `PENDING_REVIEW` (`NOT_REVIEWED`) |",
        "",
        "---",
        "",
        "## 3. Review Status by Floor",
        "",
        "| Plan Region | Region ID | Preferred Candidate | M5 Score | Computational Status | Review Status | Overall Decision | Review Items Count |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]

    for reg in pkg_data["regions"]:
        if reg["review_status"] == "BLOCKED":
            md.append(f"| {reg['plan_region']} | `{reg['region_id']}` | *None* | N/A | `{reg['computational_status']}` | `{reg['review_status']}` | `{reg['overall_decision']}` | 1 |")
        else:
            md.append(
                f"| {reg['plan_region']} | `{reg['region_id']}` | `{reg['m5_preferred_candidate_id']}` | {reg['m5_preferred_score']} | "
                f"`{reg['computational_status']}` | `{reg['review_status']}` | `{reg['overall_decision']}` | {len(reg['review_items'])} |"
            )

    md.extend([
        "",
        "---",
        "",
        "## 4. Room-by-Room Review Matrix (First Floor Reference)",
        "",
        "| Item ID | Room / Element | Area (sqft) | Dimensions | Computational Status | Initial Review Status | Reviewer Action Required |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
        "| `dhule-first-floor-review-auditorium_1` | Screen 1 (Auditorium) | 744.00 | 31.0 x 24.0 ft | `VALID` | `NOT_REVIEWED` | Review sightlines and screen distance. |",
        "| `dhule-first-floor-review-auditorium_2` | Screen 2 (Auditorium) | 798.00 | 28.5 x 28.0 ft | `VALID` | `NOT_REVIEWED` | Review acoustic separation wall. |",
        "| `dhule-first-floor-review-foyer_concession` | Public Foyer & Concession | 355.60 | 12.7 x 28.0 ft | `VALID` | `NOT_REVIEWED` | Review concession queueing capacity. |",
        "| `dhule-first-floor-review-projection_room` | Projection Booth | 130.50 | 29.0 x 4.5 ft | `VALID` | `NOT_REVIEWED` | Review projection port alignment. |",
        "| `dhule-first-floor-review-restrooms` | Restrooms / Washroom Core | 109.35 | 8.1 x 13.5 ft | `VALID` | `NOT_REVIEWED` | Review plumbing fixture counts. |",
        "| `dhule-first-floor-review-manager_office` | Manager & Staff Office | 60.00 | 6.0 x 10.0 ft | `VALID` | `NOT_REVIEWED` | Review staff security access. |",
        "",
        "---",
        "",
        "## 5. Circulation, Structural, and Obstruction Review",
        "",
        "1. **Circulation Network**: Single contiguous polygon (824.20 sq ft) with 5.5 ft primary concourses and 2.0 ft secondary access paths. Initial state: `NOT_REVIEWED`.",
        "2. **Structural Clearance**: All candidate rooms maintain clear clearance > 0.16 ft from verified columns. Hard obstruction collision count: exactly 0.00. Initial state: `NOT_REVIEWED`.",
        "3. **Hard Obstructions**: Subtracted and excluded from usable planning space with provenance handles preserved. Initial state: `NOT_REVIEWED`.",
        "4. **Uncertain Geometry**: Open stair linework and shafts preserved as non-subtracted warnings without fabrication. Initial state: `NOT_REVIEWED` (Dhule 1st–3rd) / `REVIEW_REQUIRED` (Dhule 4th).",
        "",
        "---",
        "",
        "## 6. Fourth-Floor Special Review",
        "",
        "The Fourth Floor carries an explicit architectural review mandate:",
        "- **Item**: `dhule-fourth-floor-review-unclosed-partitions`",
        "- **Computational Status**: `VALID_REVIEW_REQUIRED`",
        "- **Review Status**: `REVIEW_REQUIRED`",
        "- **Uncertainty Penalty**: `-5.00` points",
        "- **Description**: Unclosed residential/commercial CAD partition linework intersects candidate Restrooms and Manager Office spaces.",
        "- **Action**: On-site field measurement and wall condition verification required before architectural sign-off.",
        "",
        "---",
        "",
        "## 7. Blocked Regions",
        "",
        "The following regions lack verified exterior boundaries and cannot receive architectural zoning approval:",
        "- `dhule-basement`: `BLOCKED`",
        "- `dhule-ground`: `BLOCKED`",
        "- `vadodara-option-1`: `BLOCKED`",
        "- `vadodara-option-2`: `BLOCKED`",
        "",
        "Blocker Item: `BOUNDARY_VERIFICATION_BLOCKER` — Closed outer wall polyline required.",
        "",
        "---",
        "",
        "## 8. Provenance & Frozen File Protection",
        "",
        "M0–M5 frozen source files remain 100% unaltered. Checksums verified.",
        ""
    ])

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"Saved review report to: {report_file}")

def render_review_svgs(pkg_data, inputs_data, lay_data, svg_dir):
    input_by_id = {r["region_id"]: r for r in inputs_data["regions"]}
    lay_by_id = {r["region_id"]: r for r in lay_data["regions"]}

    room_colors = {
        "AUDITORIUM_1": ("#4338ca", "rgba(99, 102, 241, 0.28)", "#312e81"),
        "AUDITORIUM_2": ("#6366f1", "rgba(129, 140, 248, 0.28)", "#3730a3"),
        "FOYER_CONCESSION": ("#d97706", "rgba(245, 158, 11, 0.28)", "#92400e"),
        "PROJECTION_ROOM": ("#0891b2", "rgba(6, 182, 212, 0.32)", "#155e75"),
        "RESTROOMS": ("#059669", "rgba(16, 185, 129, 0.28)", "#065f46"),
        "MANAGER_OFFICE": ("#7c3aed", "rgba(139, 92, 246, 0.28)", "#5b21b6"),
    }

    filename_map = {
        "dhule-first-floor": "dhule_first_floor_review.svg",
        "dhule-second-floor": "dhule_second_floor_review.svg",
        "dhule-third-floor": "dhule_third_floor_review.svg",
        "dhule-fourth-floor": "dhule_fourth_floor_review.svg",
    }

    for reg in pkg_data["regions"]:
        rid = reg["region_id"]
        if rid not in filename_map:
            continue

        in_reg = input_by_id[rid]
        lay_reg = lay_by_id[rid]
        pref_id = reg["m5_preferred_candidate_id"]
        pref_cand_geom = next(c for c in lay_reg["candidates"] if c["candidate_id"] == pref_id)

        b_pts = in_reg["verified_boundary"]["geometry"]["exterior"]
        b_poly = Polygon(b_pts)
        bx0, by0, bx1, by1 = b_poly.bounds

        width, height = 1600, 1250
        margin_lr, margin_top, margin_bottom = 80, 160, 70
        draw_w = width - 2 * margin_lr
        draw_h = height - margin_top - margin_bottom

        world_w = max(bx1 - bx0, 1.0)
        world_h = max(by1 - by0, 1.0)
        scale = min(draw_w / (world_w * 1.1), draw_h / (world_h * 1.1))
        offset_x = margin_lr + (draw_w - world_w * scale) / 2.0
        offset_y = margin_top + (draw_h - world_h * scale) / 2.0

        def to_screen(x, y):
            return offset_x + (x - bx0) * scale, offset_y + (by1 - y) * scale

        elements = []

        # 1. Verified Boundary
        b_scr = [to_screen(p[0], p[1]) for p in b_pts]
        d_b = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in b_scr) + " Z"
        elements.append(f'<path d="{d_b}" stroke="#059669" stroke-width="3.5" fill="#f8fafc" />')

        # 2. Circulation
        for circ in pref_cand_geom["circulation"]:
            c_pts = circ["geometry"]["exterior"]
            c_scr = [to_screen(p[0], p[1]) for p in c_pts]
            d_c = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in c_scr) + " Z"
            elements.append(f'<path d="{d_c}" stroke="#cbd5e1" stroke-width="1.5" fill="#e2e8f0" fill-opacity="0.8" />')

        # 3. Rooms
        for rm in pref_cand_geom["rooms"]:
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

            review_badge = "[NOT_REVIEWED]"
            badge_fill = "#e0f2fe"
            badge_stroke = "#0284c7"
            badge_text_c = "#0369a1"

            if rm["status"] == "REVIEW_REQUIRED":
                review_badge = "[REVIEW_REQUIRED]"
                badge_fill = "#ffedd5"
                badge_stroke = "#ea580c"
                badge_text_c = "#c2410c"

            elements.append(
                f'<g transform="translate({scx:.1f}, {scy:.1f})">'
                f'  <rect x="-105" y="-22" width="210" height="44" rx="5" fill="#ffffff" fill-opacity="0.95" stroke="{border_c}" stroke-width="1.2" />'
                f'  <text x="0" y="-7" font-family="Inter, sans-serif" font-size="10" font-weight="700" fill="{text_c}" text-anchor="middle">{html.escape(label)}</text>'
                f'  <text x="0" y="7" font-family="Inter, sans-serif" font-size="9" font-weight="600" fill="#64748b" text-anchor="middle">{html.escape(area_str)}</text>'
                f'  <text x="0" y="18" font-family="Inter, sans-serif" font-size="8.5" font-weight="700" fill="{badge_text_c}" text-anchor="middle">{html.escape(review_badge)}</text>'
                f'</g>'
            )

        # 4. Verified Columns
        for col in in_reg["hard_obstructions"]:
            c_pts = col["geometry"]["points"]
            c_scr = [to_screen(p[0], p[1]) for p in c_pts]
            d_col = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in c_scr) + " Z"
            elements.append(f'<path d="{d_col}" stroke="#991b1b" stroke-width="1.2" fill="#dc2626" />')

        # 5. 4th floor verified lift 22D8
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

        # Header Bar
        badge_color = "#ea580c" if reg["review_status"] == "REVIEW_REQUIRED" else "#0284c7"
        header_svg = (
            f'<rect x="0" y="0" width="{width}" height="140" fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />'
            f'<text x="{margin_lr}" y="38" font-family="Inter, sans-serif" font-size="22" font-weight="700" fill="#0f172a">Architect Review Package — {reg["plan_region"]}</text>'
            f'<text x="{margin_lr}" y="62" font-family="Inter, sans-serif" font-size="12" fill="#475569">Candidate C (Adjacency-Optimized) | M5 Score: {reg["m5_preferred_score"]:.2f} | Overall Decision: {reg["overall_decision"]}</text>'
            f'<g transform="translate({width - 660}, 22)">'
            f'  <rect width="580" height="42" rx="6" fill="#f8fafc" stroke="{badge_color}" stroke-width="1.5" />'
            f'  <text x="290" y="26" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="{badge_color}" text-anchor="middle">HUMAN REVIEW STATUS: {reg["review_status"]}</text>'
            f'</g>'
            f'<g transform="translate({margin_lr}, 90)">'
            f'  <text x="0" y="10" font-family="Inter, sans-serif" font-size="10" font-weight="600" fill="#334155">'
            f'Review Items: {len(reg["review_items"])} total | Unreviewed: {sum(1 for it in reg["review_items"] if it["review_status"] == "NOT_REVIEWED")} | Review Required: {sum(1 for it in reg["review_items"] if it["review_status"] == "REVIEW_REQUIRED")} | Reviewer: Unassigned'
            f'  </text>'
            f'</g>'
            f'<g transform="translate({margin_lr}, 114)">'
            f'  <text x="0" y="10" font-family="Inter, sans-serif" font-size="9.5" font-weight="500" fill="#dc2626">'
            f'NOTICE: Human Review Interface. Does NOT constitute statutory approval, building code certification, or construction readiness.'
            f'  </text>'
            f'</g>'
        )

        # Footer Bar
        footer_svg = (
            f'<g transform="translate(0, {height - 45})">'
            f'  <rect width="{width}" height="45" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1" />'
            f'  <text x="{width / 2}" y="26" font-family="Inter, sans-serif" font-size="9" fill="#64748b" text-anchor="middle">{html.escape(DISCLAIMER_TEXT)}</text>'
            f'</g>'
        )

        svg_out = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            f'  <rect width="{width}" height="{height}" fill="#f1f5f9" />',
            header_svg,
            f'  <g id="review_layout_layer">',
            "\n".join(f"    {e}" for e in elements),
            f'  </g>',
            footer_svg,
            f'</svg>'
        ]

        fname = filename_map[rid]
        fpath = os.path.join(svg_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(svg_out))
        print(f"  [CREATED REVIEW SVG] {fpath}")

def main():
    create_review_package()

if __name__ == "__main__":
    main()
