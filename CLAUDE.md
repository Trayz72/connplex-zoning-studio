# CLAUDE.md

Guidance for any AI agent (Claude, Antigravity, or other) or human developer working
in this repository — the **Connplex Zoning Studio** codebase.

## Relationship to `connplex-cad`

The sibling directory `../connplex-cad` holds the original discovery/spec package for
this product (client SOPs, feasibility manual, ROI sheet, and the canonical
`Connplex_Zoning_Studio_Spec.pdf`), plus its own `CLAUDE.md`/`STATUS.md` written
before any code existed. **This repository (`connplex-v1`) is where the actual
implementation lives.** Treat `connplex-cad/Connplex_Zoning_Studio_Spec.pdf` as the
canonical product spec and source of truth for business rules; treat this file and
`STATUS.md` as the canonical guide to what's actually built and what's next.

## What actually exists here (read before assuming anything from the spec)

This is **not** the live three-tier service architecture the spec describes
(§5.1: separate Project/Auth, CAD Interop, Layout Engine, Rules/Config, and Drawing/
Export *services* called over an API). What actually exists is:

1. **`services/cad-interop/`** — a sequential pipeline of ~25 standalone Python
   scripts (not a running service) that were run once, by hand, against the two real
   reference drawings (Dhule, Vadodara) and froze their output as JSON/SVG under
   `services/cad-interop/test/output/`. That output directory is symlinked from
   `apps/web/public/cad-data`, so the frontend fetches it as static files — there is
   **no live CAD-upload-to-result pipeline** for a new/arbitrary property yet, only
   for the two properties already baked into `test/output/`. The pipeline's own
   milestone numbering (frozen-file provenance comments, report headers) is **M0
   through M8**, which is a different scheme from the spec's M0–M10 — see the mapping
   table below.
2. **`services/project/`** — a real, running Express + better-sqlite3 service
   (`npm start`, port 3001) that handles login and Project CRUD/intake only (spec
   §8.1). It has no knowledge of CAD files, zoning candidates, or any of the
   `services/cad-interop/` output — the two are not wired together. Opening any
   project's "Zoning Canvas" currently shows the same hardcoded Dhule dataset
   regardless of which project you opened (see `ZoningStudio.tsx`'s `cadState`/header,
   which hardcode "Dhule Cinema Hub" and a specific DWG filename).
3. **`services/rules-config/`** — added today (M8). The versioned Rules/Config
   registry the spec calls for (§21, §74–75, Product Principle #1): auditorium
   presets, seat types, franchise tiers, planning norms, and viability rules, all
   with `source` and `approval_status` provenance. Nothing before today read data
   from a registry like this — see "What was audited and fixed today" below.
4. **`apps/web/`** — a React + TypeScript + Vite SPA (`npm run dev`, port 5173,
   proxies `/auth` and `/projects` to the project service). Pages: Login, Projects
   dashboard, Project Intake, Zoning Studio (the main CAD/candidate/review workspace),
   plus an unused `ZoningCanvasPlaceholder`. This is a real, working UI — most of the
   "proper UI" work still needed is making it reflect *per-project* data instead of
   the one hardcoded demo dataset (see STATUS.md backlog).
5. **`docs/reference/`** — copies of the two reference DWGs plus `theater.dwg` (a
   native AutoCAD 2018+ working file). Note: `connplex-cad/STATUS.md` (written before
   this directory was found) says `theater.dwg` was missing — it is not; it's here,
   and also under `services/cad-interop/test/theater.dwg`.

### Milestone numbering: pipeline (M0–M8) vs spec (M0–M10) — do not conflate

| This pipeline's milestone | What it actually is | Nearest spec milestone(s) |
|---|---|---|
| M0–M2 | CAD conversion, geometry extraction, boundary reconstruction | Spec M1 (CAD Interop PoC) |
| M3 | Obstruction identification + usable-area calc | part of spec M1 |
| M4 | Deterministic zoning generation (candidates A–D, frozen geometry) | Spec M5 (auto-layout v1) merged with parts of M6 |
| M5 | Multi-candidate scoring + preferred-candidate selection | Spec M5/M10 (scoring) |
| M6 | Human architect review layer (`DecisionPanel`) | Spec's deferred roles/workflow (§8.6), pulled forward |
| M7 | Parametric revision loop (`RevisionPanel`) | Not explicitly in spec's M0–M10; closest to "regenerate around manual edits" (Product Principle #3, described as v-next) |
| **M8 (added today)** | Rules/Config registry, seat layout, feasibility engine, seat-aware rescoring, Area/Seat Chart | Spec **M2** (rules/config), **M3** (compliance engine), and the seat-count half of **M5/M6** (auto-layout objective + support-zone chart) |
| *(not started)* | Exact-match PDF/DWG drawing export | Spec **M8** |
| *(not started)* | Per-project persistence of a real CAD-upload run | Spec **M1** (production form) |

When you see "M8" in a report or filename in this repo, check the file's own header —
it always says which of the two numbering schemes it means.

## What was audited and fixed today (2026-08-31)

The user asked for an audit of feature/functionality mismatches before adding
anything new. Confirmed findings, all additive fixes (no frozen M0–M7 file was
modified):

1. **No seat modeling existed anywhere.** Grepped the entire codebase before
   writing anything: `seat` appeared exactly twice, both as flavor text in a
   reviewer-comment string, never as computed data. The spec's actual required
   client deliverable — the Area & Seat Chart with seat-type columns (§2.11 item 2)
   — could not have been produced. **Fixed**: `services/cad-interop/generate_seat_layout.py`
   computes a real, documented, deterministic seat count per auditorium (see its
   docstring for the exact methodology and its explicit assumptions).
2. **The optimization objective didn't match the locked stakeholder decision.**
   Spec §3 decision #5 locks "maximize total seat count" as the v1 objective; the
   frozen M5 scoring formula (area/circulation/adjacency/proportion/clearance/
   simplicity) had no seat term. **Fixed**: `rescore_candidates.py` adds a seats
   component (30/100 pts, the largest single factor) without touching the frozen
   M5 file, writing `zoning_decision_v2.json`.
3. **No feasibility/compliance engine existed.** Product Principle #4 requires every
   compliance result to show the specific rule and measured value, never a bare
   pass/fail. **Fixed**: `evaluate_feasibility.py`, reading the new rules registry.
   Its real output for all 4 zoning-ready floors is **`NOT_FEASIBLE`** — 3 hard rule
   failures each (carpet area below 6,000 sqft; ~29 seats/screen vs. the Feasibility
   Manual's 60-seat/screen hard minimum; 58 total seats vs. the legal 175-seat
   minimum). **This is a real, load-bearing finding, not a bug** — the frozen
   geometry pipeline's auditoriums (744/798 sqft) are far smaller than any SOP
   preset (smallest preset needs ≥1,350 sqft). Surface this to Connplex; don't treat
   it as something to silently paper over.
4. **`ValidationPanel.tsx` was fully hardcoded.** All ten checks were
   `passed: true` with canned text, regardless of any actual data. **Fixed**: now
   renders the real `evaluate_feasibility.py` output.
5. **Candidate score comparison was silently broken.** `cadService.ts` read
   `cand.scores?.total_score` from `zoning_layouts_v2.json` — but that file's
   candidate objects have no `scores`/`total_score` field at all (verified by
   inspecting the actual JSON). Every candidate card was therefore always falling
   through to the same hardcoded fallback numbers (23.0/20.0/18.0/10.6/8.5/10.0),
   regardless of which of the 4 candidates was selected. **Fixed**: now correctly
   joins per-candidate scores from the decision file by `candidate_id`. Verified live
   in-browser: Candidates A/B/C/D now show genuinely different scores (75.5/76.1/
   78.1/76.7 on Dhule First Floor).
6. Added `AreaSeatChartPanel.tsx` (new) rendering the real chart, wired into
   `ZoningStudio.tsx`; extended `RoomInspector.tsx` and `CandidatePanel.tsx` to show
   seat counts; removed a stale hardcoded score-delta claim in
   `CandidateCompareModal.tsx`.

All of the above was verified by actually running the scripts (see their printed
output) and loading the app in a browser (login → Projects → open a project's intake
→ "Go to Zoning Canvas" → confirmed real per-candidate scores, seat counts, the new
Area/Seat Chart table, and the real NOT_FEASIBLE compliance panel all render
correctly, across all 4 floors and all 4 candidates, with a clean `tsc --noEmit`).

## Non-negotiable rules (carried over from the spec/master-context governance model)

1. **Never invent architectural/regulatory facts.** Every number in
   `services/rules-config/registry/rules_registry_v1.json` carries a `source` and
   `approval_status`. If you need a new threshold, add it with real provenance and an
   honest status (`SOURCE_BACKED`, `ENGINEERING_ASSUMPTION`/`REQUIRES_APPROVAL`, or
   `TBD`) — never as a bare number in code.
2. **Config over code.** Application/pipeline code reads the rules registry; it must
   never hardcode a business/architectural number that belongs there. (`cadService.ts`
   still has one pre-existing violation of this — `min_area_sqft` fallback logic
   inline in the service layer — flagged in STATUS.md backlog, not fixed today.)
3. **Never modify the frozen M0–M7 files** (`convert.py`, `extract_geometry*.py`,
   `zoning_layouts_v1/v2.json`, `zoning_decision_v1.json`, etc. — see their own
   "Frozen File Protection" report sections for the exact list). Add new versioned
   files instead, the way `zoning_decision_v2.json` sits alongside `..._v1.json`.
4. **Mark uncertainty explicitly, don't silently resolve it.** This repo's own
   pipeline already does this well (`VALID_REVIEW_REQUIRED`, `BLOCKED_NO_VERIFIED_BOUNDARY`)
   — match that discipline in new code. The feasibility engine's `INSUFFICIENT_DATA`
   result (rather than a guessed pass) for clear height / column grid / fire escapes
   is the same principle.
5. **AI is assistive, not authoritative** on binding rules — an AI agent can propose
   a rule value with a source citation; it does not get to mark it `SOURCE_BACKED`
   without a human checking the actual source document.

## Running this project

```bash
# Backend (project/auth service — port 3001)
cd services/project && npm start        # demo login: test@connplex.com / password123

# Frontend (port 5173, proxies /auth and /projects to :3001)
cd apps/web && npm run dev

# Re-run the M8 pipeline stage after editing rules_registry_v1.json or the frozen
# geometry outputs change (order matters — each reads the previous stage's output):
cd services/cad-interop
python3 generate_seat_layout.py
python3 evaluate_feasibility.py
python3 rescore_candidates.py
python3 generate_area_seat_chart.py
```

CAD DWG→DXF conversion depends on the ODA File Converter, a ~250MB vendored binary
(gitignored — not in version control). It's already installed on this machine at
`~/.local/bin/ODAFileConverter` (symlinked into `services/cad-interop/oda/`); on a
fresh machine it must be reinstalled separately (download from
https://www.opendesign.com/guestfiles/oda_file_converter) before `convert.py` will
run — the M8 scripts above don't need it, only the frozen M0 stage does.

## Working conventions for AI agents on this project

Same as the discipline this repo's own reports already establish for itself: state
what you're changing and why before changing it, don't touch a frozen file, add new
versioned outputs instead of overwriting, and if something the spec calls for turns
out to be missing or wrong, say so explicitly (as this file does) rather than quietly
building around it. See `STATUS.md` for the current, prioritized backlog — that's
where to look for "what's next," not this file.
