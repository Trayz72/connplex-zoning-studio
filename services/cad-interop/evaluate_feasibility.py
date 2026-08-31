#!/usr/bin/env python3
"""
Connplex Zoning Studio — Feasibility / Compliance Engine (M8, additive)

Evaluates each zoning-ready region's preferred candidate against the ViabilityRule
set in the Rules/Config registry, using real measured values where the current
pipeline can produce them (carpet/boundary area, seats-per-screen from
seat_layout_v1.json, screen count) and marking every other rule INSUFFICIENT_DATA
rather than fabricating a pass.

This replaces the previous state of the project, where `ValidationPanel.tsx` in the
frontend showed ten checks that were all hardcoded to `passed: true` with canned
text — i.e. no compliance evaluation existed at all. Per Master Context Product
Principle #4 ("Compliance is advisory, not a silent blocker") every result below
carries the specific rule, the specific measured value, and the specific threshold.
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(BASE, "..", "rules-config", "registry", "rules_registry_v1.json")
DECISION_PATH = os.path.join(BASE, "test", "output", "zoning_decision_v1.json")
SEATS_PATH = os.path.join(BASE, "test", "output", "seat_layout_v1.json")
OUT_PATH = os.path.join(BASE, "test", "output", "feasibility_v1.json")
DIST_MIRROR = os.path.join(BASE, "..", "..", "apps", "web", "dist", "cad-data", "feasibility_v1.json")

# All reference properties in this repo (Dhule) are floors inside an existing mall/business-hub
# building, not standalone open-land developments -- see project name "MARUTI NANDAN BUSINESS HUB".
DEFAULT_PROPERTY_TYPE = "EXISTING_BUILDING"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_rule(rule, measurements):
    metric = rule["metric"]
    if rule.get("evaluable") is False or metric not in measurements:
        return {
            "rule_id": rule["rule_id"],
            "result": "INSUFFICIENT_DATA",
            "severity": rule["severity"],
            "metric": metric,
            "measured_value": None,
            "threshold": rule.get("threshold"),
            "source": rule["source"],
            "message": f"Cannot evaluate — {metric} is not available from the current CAD extraction/intake."
        }

    measured = measurements[metric]
    op = rule["operator"]
    if op == ">=":
        passed = measured >= rule["threshold"]
    elif op == "<=":
        passed = measured <= rule["threshold"]
    elif op == "==":
        passed = measured == rule["threshold"]
    elif op == "between":
        passed = rule["threshold_min"] <= measured <= rule["threshold_max"]
    else:
        passed = None

    threshold_display = rule.get("threshold", f"{rule.get('threshold_min')}-{rule.get('threshold_max')}")
    return {
        "rule_id": rule["rule_id"],
        "result": "PASS" if passed else "FAIL",
        "severity": rule["severity"],
        "metric": metric,
        "measured_value": measured,
        "threshold": threshold_display,
        "unit": rule.get("unit"),
        "source": rule["source"],
        "source_section": rule.get("source_section"),
        "message": (rule.get("message_template") or f"{metric} = {measured} vs threshold {threshold_display}")
    }


def main():
    registry = load_json(REGISTRY_PATH)
    decisions = load_json(DECISION_PATH)
    seats = load_json(SEATS_PATH)

    seat_index = {}
    for region in seats["regions"]:
        for cand in region["candidates"]:
            seat_index[(region["region_id"], cand["candidate_id"])] = cand

    rules = [r for r in registry["viability_rules"]
             if r["property_type_scope"] in (DEFAULT_PROPERTY_TYPE, "ANY")]

    out_regions = []
    for region in decisions["regions"]:
        rid = region["region_id"]
        pref = region.get("preferred_candidate")
        if region["decision_status"] == "BLOCKED_NO_VERIFIED_BOUNDARY" or not pref:
            out_regions.append({
                "region_id": rid,
                "plan_region": region.get("plan_region"),
                "feasibility_result": "INSUFFICIENT_DATA",
                "reason": "No verified boundary / no preferred candidate — geometry stage blocked before feasibility can run.",
                "rule_results": []
            })
            continue

        cand_id = pref["candidate_id"]
        seat_data = seat_index.get((rid, cand_id), {})
        screen_count = seat_data.get("screen_count", 0)
        total_seats = seat_data.get("total_seats", 0)
        seats_per_screen = round(total_seats / screen_count, 1) if screen_count else 0

        measurements = {
            "carpet_area_sqft": region.get("boundary_area_sqft"),
            "seats_per_screen": seats_per_screen,
            "total_project_seats": total_seats,
            "screen_count": screen_count
        }
        measurements = {k: v for k, v in measurements.items() if v is not None}

        rule_results = [evaluate_rule(r, measurements) for r in rules]

        hard_fails = [rr for rr in rule_results if rr["result"] == "FAIL" and rr["severity"] == "HARD"]
        warnings = [rr for rr in rule_results if rr["result"] == "FAIL" and rr["severity"] in ("SOFT", "WARNING")]
        insufficient = [rr for rr in rule_results if rr["result"] == "INSUFFICIENT_DATA"]

        if hard_fails:
            overall = "NOT_FEASIBLE"
        elif insufficient:
            overall = "INSUFFICIENT_DATA"
        elif warnings:
            overall = "CONDITIONALLY_FEASIBLE"
        else:
            overall = "FEASIBLE"

        out_regions.append({
            "region_id": rid,
            "plan_region": region.get("plan_region"),
            "preferred_candidate_id": cand_id,
            "property_type_assumed": DEFAULT_PROPERTY_TYPE,
            "measurements": measurements,
            "feasibility_result": overall,
            "hard_fail_count": len(hard_fails),
            "warning_count": len(warnings),
            "insufficient_data_count": len(insufficient),
            "rule_results": rule_results
        })

    output = {
        "schema_version": "1.0",
        "title": "Connplex Zoning Studio — Feasibility / Compliance Engine Results (M8)",
        "note": (
            "Replaces the previous hardcoded-pass ValidationPanel. Every result below is computed "
            "from real measured geometry/seat data against the versioned ViabilityRule registry; "
            "rules that cannot be evaluated from current CAD extraction are marked INSUFFICIENT_DATA, "
            "never silently passed."
        ),
        "regions": out_regions
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUT_PATH}")

    if os.path.isdir(os.path.dirname(DIST_MIRROR)):
        with open(DIST_MIRROR, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {DIST_MIRROR}")

    for r in out_regions:
        print(f"{r['region_id']}: {r['feasibility_result']}"
              + (f" ({r['hard_fail_count']} hard fails, {r['warning_count']} warnings)" if 'hard_fail_count' in r else ""))


if __name__ == "__main__":
    main()
