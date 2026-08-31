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

There are now genuinely **two parallel systems** in this repo. Do not confuse them:

- **The legacy demo pipeline** (`services/cad-interop/`, M0–M8): a sequence of
  standalone scripts run once, by hand, against the two real reference drawings
  (Dhule, Vadodara), with output frozen as static JSON/SVG under
  `services/cad-interop/test/output/` (symlinked into `apps/web/public/cad-data`).
  Reachable in the UI via **"View Reference Demo"** / the `/projects/:id/canvas`
  route (`ZoningStudio.tsx`). It only ever shows those two properties' frozen
  geometry — uploading a different file here does nothing (`CadUploadModal.tsx` is
  a `setTimeout`-based simulation that never sends a file anywhere). Kept as a
  reference/demo because it's real, audited, and useful ground-truth data — not
  because it's the primary product flow anymore.
- **The real pipeline** (`services/zoning-engine/`, added in this session): a live
  FastAPI service that actually accepts an arbitrary DWG/DXF upload, extracts
  geometry generically (no per-file hardcoding), and runs the full flow through to
  PDF/DXF/DWG export. Reachable via **`/projects/:id/studio`** — this is what
  "Go to Zoning Canvas" on the intake page now links to, i.e. the primary flow.

1. **`services/zoning-engine/`** — the real, primary pipeline. FastAPI app
   (`main.py`, port 8000), file-based per-project storage
   (`storage.py` → `storage/<project_id>/`), and modules for each stage:
   - `cad_extraction.py` — generic DWG/DXF → canonical geometry. Converts DWG via
     the same ODA wrapper as the legacy pipeline (`cad-interop/convert.py`, reused
     directly), then parses DXF with `ezdxf`: every closed polyline above a minimum
     area is a boundary *candidate* (largest un-nested one per cluster becomes the
     boundary; multi-region sheets naturally yield multiple candidate regions), every
     smaller closed shape contained in a boundary is an obstacle candidate with a
     confidence score (layer-name hints + shape heuristics). Nothing is auto-trusted:
     every boundary/obstacle has a `status` of `PROPOSED` until the architect
     confirms or ignores it via the Geometry Review step.
   - `layout_engine.py` — generic auto-layout generator. Subtracts confirmed
     obstacles from the boundary, then a deterministic first-fit rectangle scan
     places auditoriums (largest `AuditoriumPreset` that still fits, tried first —
     this is what makes "maximize seat count" real) and then support zones in
     whatever remains. Produces two genuinely different strategies
     (`MAX_SEATS_PER_SCREEN`, `MAX_SCREEN_COUNT`), not cosmetic variants.
   - `seat_engine.py`, `feasibility_engine.py`, `chart_engine.py` — the same
     seat-packing / ViabilityRule-evaluation / Area-Seat-Chart logic the legacy
     pipeline's M8 scripts have, refactored into plain functions so the live
     endpoints can call them directly instead of shelling out to a script over a
     fixed file.
   - `export_dxf.py` / `export_pdf.py` — real exports. DXF via `ezdxf` (verified
     openable/re-parseable); DWG via the same ODA converter run in reverse
     (DXF→DWG, verified with `file` as a genuine AutoCAD 2018/2019/2020 DWG); PDF
     via `reportlab`, drawing the actual room geometry to scale plus the real Area
     & Seat Chart and feasibility results — not a static template.
   All of these read `services/rules-config/registry/rules_registry_v1.json` for
   every business number — nothing is hardcoded (`rules_registry.py`).
2. **`services/cad-interop/`** — unchanged from before this session, still the
   legacy/demo pipeline described above. Its M8 scripts
   (`generate_seat_layout.py`, `evaluate_feasibility.py`, `rescore_candidates.py`,
   `generate_area_seat_chart.py`, added earlier the same day) still work and are
   still how the reference-demo dataset gets its seat/feasibility/chart data.
3. **`services/project/`** — unchanged: a real, running Express + better-sqlite3
   service (`npm start`, port 3001) for login and Project CRUD/intake (spec §8.1).
   Still has no knowledge of CAD/zoning data — that all lives in
   `services/zoning-engine/storage/`, keyed by the same `project_id`.
4. **`services/rules-config/`** — the versioned Rules/Config registry (spec §21,
   §74–75, Product Principle #1). Now read by *both* pipelines.
5. **`apps/web/`** — React + TypeScript + Vite SPA (`npm run dev`, port 5173,
   proxies `/auth` + `/projects` to :3001 and `/api` to the zoning-engine on
   :8000). Routes: `/login`, `/projects`, `/projects/:id/intake`,
   **`/projects/:id/studio`** (new — the real workspace,
   `pages/ZoningWorkspace.tsx` + `components/workspace/*`), `/projects/:id/canvas`
   (legacy demo, `pages/ZoningStudio.tsx`), and an unused `ZoningCanvasPlaceholder`.
6. **`docs/reference/`** — copies of the two reference DWGs plus `theater.dwg` (a
   native AutoCAD 2018+ working file), all genuinely usable as real test uploads
   against `/studio` now.

### Milestone numbering: pipeline (M0–M8) vs spec (M0–M10) — do not conflate

| This pipeline's milestone | What it actually is | Nearest spec milestone(s) |
|---|---|---|
| M0–M2 | CAD conversion, geometry extraction, boundary reconstruction | Spec M1 (CAD Interop PoC) |
| M3 | Obstruction identification + usable-area calc | part of spec M1 |
| M4 | Deterministic zoning generation (candidates A–D, frozen geometry) | Spec M5 (auto-layout v1) merged with parts of M6 |
| M5 | Multi-candidate scoring + preferred-candidate selection | Spec M5/M10 (scoring) |
| M6 | Human architect review layer (`DecisionPanel`) | Spec's deferred roles/workflow (§8.6), pulled forward |
| M7 | Parametric revision loop (`RevisionPanel`) | Not explicitly in spec's M0–M10; closest to "regenerate around manual edits" (Product Principle #3, described as v-next) |
| **M8 (added same day, part 1)** | Rules/Config registry, seat layout, feasibility engine, seat-aware rescoring, Area/Seat Chart — for the legacy demo pipeline | Spec **M2** (rules/config), **M3** (compliance engine), and the seat-count half of **M5/M6** |
| **`services/zoning-engine/` (added same day, part 2)** | Real generic CAD upload, geometry confirmation, auto-layout, editable canvas, PDF/DXF/DWG export | Spec **M1** (production CAD ingestion), **M4** (manual canvas), **M5/M6** (auto-layout, now generic), **M8** (export) — see below |

When you see "M8" in a report or filename in `services/cad-interop/`, it means the
legacy pipeline's own scheme, not the spec's M8. `services/zoning-engine/` isn't
numbered against either scheme — it's the real implementation of several spec
milestones at once, described in its own module docstrings.

## What was built in this session (2026-08-31)

The user asked, in two parts: first, to audit the existing pipeline for feature
mismatches against the spec (see "Part 1" below); then, having confirmed the
CAD-upload → intake-form → zoning → editable-result → PDF/CAD-export flow was not
actually implemented anywhere (upload was a `setTimeout` simulation; the canvas was
a static image with hand-tuned percentage hotspots, not real geometry), to build
that flow for real, "without any loopholes." Part 2 is that build.

### Part 2 — the real pipeline (`services/zoning-engine/`)

Verified, not assumed — every claim below was actually run and checked:

- **Generic extraction, not per-file hardcoding.** Before writing
  `cad_extraction.py`, read `services/cad-interop/extract_geometry_v2.py` in full —
  its `extract_dhule()`/`extract_vadodara()` functions reference hand-transcribed
  entity handles (e.g. `"6A8"`) and fixed pixel bounding boxes specific to those
  two files; it cannot process anything else. The new extractor uses only real
  geometry (closed-polyline area, containment, layer-name hints) and was verified
  against three independent inputs: the real Dhule DXF (correctly found 7 candidate
  regions including the true floor-plan boundaries, with zero hardcoded knowledge
  of this file), a synthetic 20m×15m DXF with 4 columns + 1 furniture piece built
  fresh via `ezdxf` (100% correct boundary/column/furniture classification), and a
  hand-typed minimal DXF dropped through the actual browser upload UI (correctly
  rejected with a real, specific ezdxf error the first time it was malformed, then
  correctly parsed once fixed).
- **Every uncertain detection requires human confirmation before it can drive a
  zoning run** — `main.py`'s `/zoning-runs` endpoint returns 400 if the boundary
  isn't `CONFIRMED`. This isn't a UI nicety; it's enforced server-side.
- **Generic auto-layout**, not a retrofit onto the frozen Dhule geometry. Verified
  on a real ~6,874 sqft Dhule region: `MAX_SEATS_PER_SCREEN` produced 1 screen
  (125-seat-preset-sized, 162 real seats) while `MAX_SCREEN_COUNT` produced 2
  screens (60-seat-preset-sized each, 126 total seats) — two genuinely different,
  correctly-computed trade-offs, not cosmetic variants.
- **Real interactive editing**, not hotspots on a picture. `EditableCanvas.tsx`
  renders actual room polygons as SVG bound to real feet-coordinates (`getScreenCTM`
  for pointer↔user-space conversion), with working drag-to-move and drag-to-resize
  (corner handles), live client-side collision hinting, and server-side geometry
  validation (`layout_engine.validate_rooms`) on every commit. Verified live in a
  real browser session: a drag that would push a room outside the boundary or onto
  a confirmed obstacle is rejected with the specific overlap area in square feet,
  the invalid position is **not** persisted (confirmed via direct API query after
  the rejection), and — after a bug found and fixed this session — the canvas
  visually snaps the room back rather than leaving it at the rejected position. A
  valid move (confirmed via direct PUT, then a full page reload) persists and
  correctly recomputes circulation area and the Area & Seat Chart.
- **Real exports.** PDF verified by rendering to PNG and visually inspecting both
  pages (floor plan drawn to scale with real room colors/labels/seat counts, plus
  the Area & Seat Chart table and real feasibility results). DXF verified by
  reading it back with `ezdxf` (28 real entities across correctly-named layers).
  DWG verified with the `file` command as a genuine `DWG AutoDesk AutoCAD
  2018/2019/2020` file, produced by converting the exported DXF through the same
  ODA File Converter used for import — a real round trip, not a stub.
- **A UX gap was found and fixed mid-session**: if CAD extraction found zero usable
  regions, there was no way back to the upload step. `GeometryReviewStep` now has
  a "Replace CAD File" / "Upload a Different File" affordance.

Known, honestly-scoped limitations of Part 2 (not fixed this session — see
STATUS.md backlog): a hard `npm run build` / cold browser navigation straight to
`/projects/:id/studio` 404s on Vite's dev server (works fine via in-app client-side
navigation; pre-existing behavior, same as the legacy `/canvas` route); one cosmetic
stale-state edge case in the live collision-hint banner. PDF format matching is now
covered in Part 3 below (was a bigger gap when this paragraph was first written).

### Part 3 — PDF export rebuilt to match the real Connplex sheet format

The user supplied a real Connplex reference PDF (Keshav Landmark, Vadodara, DRG
ZL-01-R1) and asked exports to match its format/logo/style. Read the reference
PDF in full first, then rewrote `export_pdf.py` from a generic two-page report
into a single-sheet template matching the real drawing's exact structure and
section order: floor plan on the left; a right info column with General Notes
→ Notes → Legends → "AREA CHART(SQ.FT.) & SEAT CHART" (same seven columns as
the real sheet) → Revisions log → Drawing Issued log with FOR APPROVAL/FOR GFC
checkboxes → Key Plan box → project info block → DRG NO/TITLE/SCALE/DRAWN
BY/CHECKED BY/DATE stamp → CONNPLEX SMART THEATRES company block with their
real address/contact details (both taken directly from the reference PDF) and
a drawn approximation of their yellow/black logo badge.

Verified by rendering to PNG and comparing against the reference side by side
— this caught and fixed real bugs: every sidebar section's label text was
overlapping its own content (a vertical-spacing bug, not a cosmetic nit — it
made the first line of every box illegible), and the Area/Seat Chart's
LOCATION column was truncating "SCREEN 1 (AUDITORIUM)" to "SCREEN 1 (AUDITO".
Re-verified through the live Export PDF button afterward (still a real 200 OK,
not just the standalone script).

**Honest gap, stated plainly:** the logo is a redraw in Connplex's real brand
colors, not their actual vector artwork — no logo asset file was available to
this session. Swapping in a real logo file later is a small, contained change
(see STATUS.md backlog item 4 for exactly where).

### Part 1 — audit and fixes to the legacy demo pipeline (earlier the same day)

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
6. **Uncertain CAD detection must not silently become authoritative.** Every
   boundary/obstacle `cad_extraction.py` finds starts `PROPOSED`; `main.py` refuses
   to run a zoning run against a region whose boundary isn't `CONFIRMED`. Don't
   relax this to make testing more convenient — it's the enforcement of spec §11.
7. **A rejected edit must never be silently persisted or left in an ambiguous
   visual state.** `layout_engine.validate_rooms` runs server-side on every layout
   PUT; the frontend must revert to the last-known-good state on rejection (see the
   `EditableCanvas`/`ZoningWorkspace` revert fix in "What was built" above for why
   this needed an explicit fix, not just an error toast).

## Running this project

```bash
# 1. Project/auth service — port 3001, routes live under /api/pm/*
cd services/project && npm start        # demo login: test@connplex.com / password123
                                         # or use "Create an account" on the login page

# 2. Zoning engine (the real pipeline) — port 8000, routes live under /api/*
cd services/zoning-engine && python3 -m uvicorn main:app --port 8000
# (pip install -r requirements.txt first on a fresh machine — fastapi, uvicorn,
# python-multipart, ezdxf, shapely, reportlab, pydantic; all already present here)

# 3. Frontend — port 5173, proxies /api/pm to :3001 and /api (everything else) to :8000
cd apps/web && npm run dev
# open http://localhost:5173 -> log in (or create an account) -> open a project's
# intake -> "Go to Zoning Canvas" -> lands on /projects/:id/studio, the real
# upload/edit/export workspace. "View Reference Demo" in its header links to the
# old static Dhule/Vadodara demo.
```

**Route namespacing matters here — don't casually add a bare `/projects` or
`/auth` backend route again.** They used to be unprefixed and it caused a real
bug: the frontend's own pages (`/projects/:id/studio`, `/projects/:id/intake`,
`/projects/:id/canvas`) share that exact prefix, so the dev proxy intercepted
page loads meant for the SPA and sent them to the Node backend instead —
invisible via client-side navigation, but a real 404/500 on every hard refresh
or shared link (confirmed with a direct `curl`, not assumed). `services/project`
now lives entirely under `/api/pm/*`; `services/zoning-engine` under `/api/*`
(minus `/api/pm`, which the Vite proxy matches first since it's the more
specific rule — order matters in `vite.config.ts`'s `proxy` object). If you add
a new frontend route, make sure its path doesn't collide with either prefix,
and if you add a new backend route, put it under one of those two namespaces,
never bare.

To re-run the legacy pipeline's M8 stage after editing `rules_registry_v1.json` (only
affects the `/canvas` reference-demo dataset, not `/studio`):
```bash
cd services/cad-interop
python3 generate_seat_layout.py && python3 evaluate_feasibility.py \
  && python3 rescore_candidates.py && python3 generate_area_seat_chart.py
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
