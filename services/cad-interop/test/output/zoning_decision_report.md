# Connplex Zoning Studio — Milestone M5 Decision-Ready Zoning Report

> [!IMPORTANT]
> **Architectural Disclaimer**: DISCLAIMER: This computational decision package is generated for design decision-support only. It does NOT constitute architectural approval, statutory code compliance certification, structural engineering clearance, or construction documentation. All room dimensions, structural clearances, egress paths, and layout configurations must be independently reviewed and certified by a licensed professional architect and registered structural engineer.

---

## 1. Executive Summary

Milestone M5 establishes the computational decision-support package for the Connplex Zoning Studio pipeline. Operating on top of the frozen M0–M4 geometry and evaluation layers, M5 compares all valid candidates, identifies the highest-scoring candidate for each zoning-ready floor, articulates the exact mathematical and spatial rationale for selection, and rigorously documents all uncertainty and review items.

- **Total Plan Regions Analyzed**: 8
- **Decision-Ready / Optimized Floors**: 4 (Dhule First, Second, Third, and Fourth floors)
- **Blocked Regions (Unverified Boundary)**: 4 (Dhule Basement, Ground, Vadodara Options 1 & 2)
- **Selected Strategy**: **Candidate C (Adjacency-Optimized Layout)** across all 4 zoning-ready floors
- **Review Items**: Fourth-floor RESTROOMS and MANAGER_OFFICE retain `VALID_REVIEW_REQUIRED` due to unclosed partition linework

---

## 2. Floor-by-Floor Decision Table

| Plan Region | Region ID | Boundary Area | Step 5 Usable | Preferred Candidate | Score | Status | Review Required |
| :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: |
| BASEMENT FLOOR PLAN | `dhule-basement` | N/A | N/A | *None (Blocked)* | N/A | `BLOCKED_NO_VERIFIED_BOUNDARY` | 0 |
| GROUND FLOOR PLAN | `dhule-ground` | N/A | N/A | *None (Blocked)* | N/A | `BLOCKED_NO_VERIFIED_BOUNDARY` | 0 |
| FIRST FLOOR PLAN | `dhule-first-floor` | 5242.03 sqft | 5215.06 sqft | **Candidate C** (Adjacency-Optimized Layout) | **90.28** | `DECISION_READY` | 0 |
| SECOND FLOOR PLAN | `dhule-second-floor` | 5242.03 sqft | 5216.19 sqft | **Candidate C** (Adjacency-Optimized Layout) | **90.27** | `DECISION_READY` | 0 |
| THIRD FLOOR PLAN | `dhule-third-floor` | 5242.03 sqft | 5216.2 sqft | **Candidate C** (Adjacency-Optimized Layout) | **90.27** | `DECISION_READY` | 0 |
| FOURTH FLOOR PLAN | `dhule-fourth-floor` | 5242.04 sqft | 5222.04 sqft | **Candidate C** (Adjacency-Optimized Layout) | **85.24** | `VALID_REVIEW_REQUIRED` | 2 |
| Cinema Zoning Studio — Option 1 (Lower Layout / Screens 1–5) | `vadodara-option-1` | N/A | N/A | *None (Blocked)* | N/A | `BLOCKED_NO_VERIFIED_BOUNDARY` | 0 |
| Cinema Zoning Studio — Option 2 (Upper Layout / Screens 1–5) | `vadodara-option-2` | N/A | N/A | *None (Blocked)* | N/A | `BLOCKED_NO_VERIFIED_BOUNDARY` | 0 |

---

## 3. Candidate Comparison & Scoring Breakdown

For each zoning-ready floor, 4 deterministic candidates were evaluated across 6 objective weighted categories (Max 100 pts):

$$\text{Total Score} = S_{\text{area}} (25) + S_{\text{circ}} (20) + S_{\text{adj}} (20) + S_{\text{prop}} (15) + S_{\text{clear}} (10) + S_{\text{simp}} (10) - P_{\text{uncert}} (5)$$

| Candidate | Strategy | Area Eff (25) | Circ (20) | Adj (20) | Prop (15) | Clear (10) | Simp (10) | Penalty | Total Score | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Candidate A** | Baseline M3 | 22.72 | 20.00 | 15.00 | 10.60 | 8.50 | 10.00 | 0.00 | **86.82** | `VALID` |
| **Candidate B** | Circulation-Optimized | 21.60 | 22.00 | 15.00 | 10.60 | 8.50 | 10.00 | 0.00 | **87.70** | `VALID` |
| **Candidate C** | **Adjacency-Optimized (Preferred)** | **23.18** | **20.00** | **18.00** | **10.60** | **8.50** | **10.00** | **0.00** | **90.28** | **`VALID`** |
| **Candidate D** | Area-Efficiency-Optimized | 24.16 | 20.00 | 15.00 | 10.60 | 8.50 | 10.00 | 0.00 | **88.26** | `VALID` |

*Note: On Fourth Floor, an uncertainty penalty of -5.00 applies across all candidates due to CAD partition linework, yielding Candidate C score of 85.24 pts (`VALID_REVIEW_REQUIRED`).*

---

## 4. Preferred Candidate Rationale

**Candidate C** is selected deterministically across all zoning-ready floors because:
1. **Highest Total Objective Score**: Outperforms Candidate B by +2.58 points and Candidate D by +2.02 points.
2. **Acoustic Adjacency**: Expands the direct shared physical boundary between `PROJECTION_ROOM` and `AUDITORIUM_1` from 26.0 ft to 29.0 ft, maximizing optical throw alignment.
3. **Direct Concourse Interfacing**: `AUDITORIUM_1` and `AUDITORIUM_2` directly interface with the central `FOYER_CONCESSION` gathering lounge.
4. **Zero Collisions**: 100% hard-obstruction avoidance with clear distances > 0.16 ft from all structural columns.
5. **Connected Circulation**: Fully connected single-polygon corridor network (824.20 sq ft) guaranteeing direct egress from all 6 functional rooms.

---

## 5. Room Program Summary (Preferred Candidate C)

| Room Type | Display Name | Width (ft) | Depth (ft) | Area (sq ft) | Min Req (sq ft) | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `AUDITORIUM_1` | Screen 1 (Auditorium) | 31.00 | 24.00 | **744.00** | 700.00 | `VALID` |
| `AUDITORIUM_2` | Screen 2 (Auditorium) | 28.50 | 28.00 | **798.00** | 700.00 | `VALID` |
| `FOYER_CONCESSION` | Public Foyer & Concession | 12.70 | 28.00 | **355.60** | 300.00 | `VALID` |
| `PROJECTION_ROOM` | Projection Booth | 29.00 | 4.50 | **130.50** | 80.00 | `VALID` |
| `RESTROOMS` | Restrooms / Washroom Core | 8.10 | 13.50 | **109.35** | 90.00 | `VALID`* |
| `MANAGER_OFFICE` | Manager & Staff Office | 6.00 | 10.00 | **60.00** | 50.00 | `VALID`* |
| **Total Room Area** | | | | **2,197.45** | | |
| **Circulation Network** | Connected Corridor Spine | Min 2.0 | Prim 5.5 | **824.20** | Min 2.0 ft | `CONNECTED` |

*\*On Fourth Floor, flagged `REVIEW_REQUIRED`.*

---

## 6. Fourth-Floor REVIEW_REQUIRED Treatment

On the Fourth Floor, `RESTROOMS` and `MANAGER_OFFICE` intersect unclosed CAD partition linework in model space. Per established Connplex Zoning Studio integrity rules:
- Linework is **not** fabricated into a solid obstruction.
- Rooms are **not** silently marked verified.
- Decision status remains strictly **`VALID_REVIEW_REQUIRED`**.
- An explicit **-5.00 uncertainty penalty** is applied.

---

## 7. Blocked Regions

The following 4 regions lack verified closed outer boundaries and remain strictly blocked:
1. `dhule-basement`: Basement Floor Plan (Open linework, unclosed exterior boundary)
2. `dhule-ground`: Ground Floor Plan (Open storefront linework, unclosed boundary)
3. `vadodara-option-1`: Vadodara Option 1 (Framing rectangle only, unclosed planning plate)
4. `vadodara-option-2`: Vadodara Option 2 (Framing rectangle only, unclosed planning plate)

Candidate generation for these regions is blocked (`candidate_count = 0`, `preferred_candidate = null`).

---

## 8. Provenance & Frozen File Protection

All M0–M4 baseline files remain frozen, intact, and verified via SHA-256 checksums:
- `services/cad-interop/convert.py` (Frozen Aug 27 14:07)
- `services/cad-interop/extract_geometry.py` (Frozen Aug 27 14:08)
- `services/cad-interop/extract_geometry_v2.py` (Frozen Aug 27 15:23)
- `services/cad-interop/test/output/usable_planning_areas_v1.json` (Frozen)
- `services/cad-interop/test/output/zoning_layouts_v1.json` (Frozen)
- `services/cad-interop/test/output/zoning_layouts_v2.json` (Frozen)

---

## 9. Regression Status

Complete automated pipeline verification: **PASS (100%)** across M0, M1, M2, M3, M4, and M5.
