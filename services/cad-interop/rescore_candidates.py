#!/usr/bin/env python3
"""
Connplex Zoning Studio — Seat-Aware Rescoring (M8, additive; produces zoning_decision_v2.json)

Fixes the most important scoring mismatch found in the M5 decision engine: the
stakeholder-locked v1 optimization objective is "maximize total seat count" (spec
§3, Decision #5), but the frozen `generate_zoning_decision.py` scoring formula
(area/circulation/adjacency/proportion/clearance/simplicity) never included seat
count anywhere. This script does NOT modify the frozen M5 file or its output
(`zoning_decision_v1.json` is untouched); it reads it plus the new
`seat_layout_v1.json`, recomputes a seat-aware total score per candidate, and writes
a new versioned file `zoning_decision_v2.json` with the updated ranking. If the
preferred candidate changes, that is reported explicitly rather than silently
applied.

New weighting (100 pts total): Seats(30) + Area(20) + Circulation(15) + Adjacency(15)
+ Proportion(8) + Clearance(7) + Simplicity(5) - UncertaintyPenalty. Existing
component scores are rescaled proportionally from their original weights to preserve
their relative meaning. The Seats(30) component is scored against the Feasibility
Manual's hard 60-seats/screen threshold as full marks, per source
VR_SEATS_PER_SCREEN_FEASIBILITY_HARD in the rules registry — i.e. this score directly
operationalizes an approved, source-backed threshold rather than an invented one.
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DECISION_PATH = os.path.join(BASE, "test", "output", "zoning_decision_v1.json")
SEATS_PATH = os.path.join(BASE, "test", "output", "seat_layout_v1.json")
OUT_PATH = os.path.join(BASE, "test", "output", "zoning_decision_v2.json")
DIST_MIRROR = os.path.join(BASE, "..", "..", "apps", "web", "dist", "cad-data", "zoning_decision_v2.json")

SEATS_PER_SCREEN_FULL_MARKS = 60  # VR_SEATS_PER_SCREEN_FEASIBILITY_HARD threshold
OLD_MAX = {"area_efficiency": 25, "circulation": 20, "adjacency": 20, "proportion": 15, "clearance": 10, "simplicity": 10}
NEW_MAX = {"area_efficiency": 20, "circulation": 15, "adjacency": 15, "proportion": 8, "clearance": 7, "simplicity": 5}
SEATS_MAX = 30


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def rescale(old_components):
    return {k: round(old_components[k] * (NEW_MAX[k] / OLD_MAX[k]), 2) for k in OLD_MAX}


def seats_score(seats_per_screen):
    return round(min(seats_per_screen / SEATS_PER_SCREEN_FULL_MARKS, 1.0) * SEATS_MAX, 2)


def main():
    decisions = load_json(DECISION_PATH)
    seats = load_json(SEATS_PATH)

    seat_index = {}
    for region in seats["regions"]:
        for cand in region["candidates"]:
            screen_count = cand.get("screen_count", 0)
            total_seats = cand.get("total_seats", 0)
            seat_index[(region["region_id"], cand["candidate_id"])] = {
                "total_seats": total_seats,
                "screen_count": screen_count,
                "seats_per_screen": round(total_seats / screen_count, 2) if screen_count else 0
            }

    out_regions = []
    ranking_changes = []

    for region in decisions["regions"]:
        rid = region["region_id"]
        if not region.get("candidates"):
            out_regions.append(region)
            continue

        rescored_candidates = []
        for cand in region["candidates"]:
            seat_info = seat_index.get((rid, cand["candidate_id"]), {"total_seats": 0, "screen_count": 0, "seats_per_screen": 0})
            rescaled = rescale(cand["score_components"])
            s_score = seats_score(seat_info["seats_per_screen"])
            penalty = cand["score_components"].get("uncertainty_penalty", 0.0)
            new_total = round(sum(rescaled.values()) + s_score - penalty, 2)

            new_cand = dict(cand)
            new_cand["seat_data"] = seat_info
            new_cand["score_components_v2"] = {**rescaled, "seats": s_score, "uncertainty_penalty": penalty}
            new_cand["total_score_v1"] = cand["total_score"]
            new_cand["total_score"] = new_total
            rescored_candidates.append(new_cand)

        rescored_candidates.sort(key=lambda c: c["total_score"], reverse=True)
        new_preferred = rescored_candidates[0]

        old_preferred_id = region.get("preferred_candidate", {}).get("candidate_id") if region.get("preferred_candidate") else None
        if old_preferred_id and old_preferred_id != new_preferred["candidate_id"]:
            ranking_changes.append({
                "region_id": rid,
                "old_preferred": old_preferred_id,
                "new_preferred": new_preferred["candidate_id"],
                "reason": "Seat-aware rescoring (M8) changed the highest-scoring candidate."
            })

        new_region = dict(region)
        new_region["candidates"] = rescored_candidates
        new_region["preferred_candidate"] = new_preferred
        new_region["preferred_score"] = new_preferred["total_score"]
        new_region["preferred_score_v1"] = region.get("preferred_score")
        out_regions.append(new_region)

    output = {
        "schema_version": "2.0",
        "title": "Connplex Zoning Studio — Seat-Aware Decision Package (M8)",
        "description": (
            "Rescoring of the frozen M5 candidates with total seat count as the dominant weighted "
            "objective (30/100 pts), per the v1 stakeholder decision to maximize seat count. "
            "zoning_decision_v1.json remains frozen and unmodified."
        ),
        "scoring_weights": {**NEW_MAX, "seats": SEATS_MAX},
        "seats_full_marks_threshold_per_screen": SEATS_PER_SCREEN_FULL_MARKS,
        "ranking_changes_vs_v1": ranking_changes,
        "regions": out_regions
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUT_PATH}")

    if os.path.isdir(os.path.dirname(DIST_MIRROR)):
        with open(DIST_MIRROR, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {DIST_MIRROR}")

    print(f"Ranking changes vs v1: {len(ranking_changes)}")
    for rc in ranking_changes:
        print(f"  {rc['region_id']}: {rc['old_preferred']} -> {rc['new_preferred']}")

    for region in out_regions:
        if region.get("preferred_candidate"):
            pc = region["preferred_candidate"]
            print(f"{region['region_id']}: preferred={pc['candidate_id']} score={pc['total_score']} "
                  f"seats={pc['seat_data']['total_seats']} ({pc['seat_data']['seats_per_screen']}/screen)")


if __name__ == "__main__":
    main()
