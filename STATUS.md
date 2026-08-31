# STATUS

Last updated: 2026-08-31 (EOD handoff session)

## Where this stands right now

A working prototype: CAD→geometry→candidate-generation→scoring→review pipeline
(built pre-existing, M0–M7), plus a new M8 layer added today that closes the
biggest functional gap — **real seat counts, a real feasibility engine, and the
actual required Area/Seat Chart deliverable, none of which existed before today.**
The app runs end-to-end for the two real reference properties (Dhule, 4 of its 6
floor plans; Vadodara is fully blocked). It is **not yet wired for an arbitrary new
property** — that's the top item in the backlog below.

Full detail on what was audited, what was found broken, and what was fixed is in
`CLAUDE.md` — this file is the forward-looking punch list.

## Verified working right now (tested live in-browser today)

- Login → Projects dashboard → project intake → "Go to Zoning Canvas".
- 4 zoning-ready Dhule floors (First/Second/Third/Fourth), each with 4 real,
  independently-scored candidates (previously all 4 candidates silently showed
  identical fallback scores — fixed, see CLAUDE.md item 5).
- Real seat counts per auditorium, per candidate (previously did not exist anywhere).
- Real Area & Seat Chart matching the spec's exact required table structure.
- Real feasibility/compliance panel (previously 10 hardcoded `passed: true` checks)
  — current honest result: **all 4 floors are NOT_FEASIBLE** against Connplex's own
  Feasibility Manual (carpet area, seats/screen, total legal seats all fail). This is
  a genuine finding about the existing frozen geometry, not a bug in today's work.
- 4th floor's `VALID_REVIEW_REQUIRED` / uncertainty-penalty flow still works
  end-to-end with the new seat-aware scores layered on top.
- `tsc --noEmit` clean; `npm run build` succeeds; both dev servers verified running
  together (Vite on 5173 proxying to Express on 3001).

## Priority backlog (ordered — this is what "the rest" should tackle)

### 1. Seat-maximizing geometry candidate ("Candidate E") — the highest-complexity remaining piece

**Why this is next:** today's audit proved the auto-generated auditoriums (744 sqft,
798 sqft) are far too small — below every SOP preset, yielding ~29 seats/screen
against a 60-seat/screen hard requirement. Rescoring the *existing* 4 candidates with
a seat-aware objective (done today) can't fix this, because all 4 frozen candidates
already allocate roughly the same, too-small auditorium footprint — there is no
seat-maximizing option among them to prefer. The actual fix has to generate a new
geometry candidate that trades non-auditorium area for auditorium area.

**Why this wasn't attempted today:** it means writing a new placement algorithm
against the irregular usable-area polygon (avoiding real obstructions), which is a
focused, visually-iterative geometry task — exactly the kind of work better done with
live visual feedback in an IDE than blind in a terminal. Spec §7.2 already specifies
the intended staged approach; this is that work.

**Concrete plan:**
- Inputs available: `services/cad-interop/test/output/usable_planning_areas_v1.json`
  (usable polygon per region, obstructions already subtracted) and
  `resolved_obstructions_v1.json` (hard obstruction polygons).
- Algorithm (per spec §7.2 step 1, and `05_zoning_engine_and_optimization` doc):
  greedily grow/place auditorium rectangles along the floor plate's long axis from the
  `AuditoriumPreset` list in `services/rules-config/registry/rules_registry_v1.json`
  (60/90/125-seat), skipping/shrinking around `StructuralElement`/obstruction polygons,
  stopping when no further auditorium clears the minimum area, then placing support
  zones in the remainder using the existing candidate A–D logic as a template.
- Output contract: a new candidate object shaped exactly like the existing
  candidates in `zoning_layouts_v2.json` (same `rooms[]` schema), so it drops straight
  into `generate_seat_layout.py` → `evaluate_feasibility.py` →
  `rescore_candidates.py` → `generate_area_seat_chart.py` with **zero changes** to
  those four scripts.
- Acceptance: the new candidate should clear ≥55–60 seats/screen on at least the
  First floor (the largest usable area of the 4 ready floors, 5,242 sqft boundary),
  or, if it genuinely cannot, that itself is the answer Connplex needs — write it up
  plainly (this floor may simply not support the seats-per-screen bar at any layout,
  which is a real business finding, not a code problem).

### 2. Wire a real per-project CAD pipeline (not just the two hardcoded demo properties)

`ZoningStudio.tsx` currently hardcodes "Dhule Cinema Hub" / a specific DWG filename in
its header regardless of which project you opened (see the `cadState` initial value).
`services/project` (project CRUD) and `services/cad-interop` (the pipeline) are
completely disconnected — there's no code path from "user uploads a DWG on a new
project" to a real pipeline run. To make this a real multi-project tool:
- Add an endpoint (new, in `services/project` or a new small service) that accepts a
  DWG upload for a given project, shells out to `services/cad-interop/convert.py` and
  the rest of the pipeline, and stores results keyed by `project_id` instead of the
  hardcoded `test/output/` directory.
- Update `CadUploadModal.tsx` (`isDemoData` flag already exists in the type — it's
  currently always presenting demo data) to actually trigger this.
- This is a real backend/plumbing project, not a quick fix — budget real time for it.

### 3. Exact-match PDF/DWG export (spec M8 / this repo has nothing here yet)

Nothing in this repo produces the client-facing PDF or a re-exported DWG. Spec §7.3
and M8 require validating against the two real reference PDFs (title block, Area/Seat
Chart, legends, revision log) as the acceptance test. The new `area_seat_chart_v1.json`
from today is the right input data for the chart portion of this.

### 4. `config over code` cleanup in `cadService.ts`

`min_area_sqft` is still computed inline (`rm.room_type.includes('AUDITORIUM') ? 600 : ...`)
instead of read from `rules_registry_v1.json`'s `auditorium_presets`/room minimums.
Low effort, flagged but not fixed today to keep today's diff focused on the seat/
feasibility gap.

### 5. UI polish (this is the "rest for antigravity" category — good iterative-IDE work)

- `ZoningCanvasPlaceholder.tsx` is dead/unused — either wire it up or remove it.
- Deep-linking to `/projects/:id/canvas` 404s on a raw browser navigation (confirmed
  today) — works fine via in-app client-side links. Likely needs SPA fallback
  configured for whatever serves the production build (not just `vite dev`, which
  should handle this by default — worth a closer look).
- Franchise-tier selection UI (Express/Signature/Luxuriance) doesn't exist yet in the
  intake form even though the registry now has the data — spec flags the Express/
  Smart naming conflict (open item #2, still unresolved, needs a Connplex decision).
- General visual polish, loading states, and mobile/responsive behavior were not
  in scope today.

## Open items still requiring a Connplex decision (unchanged from spec §10)

1. APS/ODA licensing approval for production-grade DWG interop (today's work
   confirms the *free* ODA File Converter path works for DWG→DXF conversion at
   prototype scale — that may reduce urgency on this, but production terms/support
   still need sign-off).
2. Franchise tier naming: "Express" (brochure) vs. "Smart" (ROI sheet) — unresolved,
   encoded in the registry with an explicit `naming_conflict_note`.
3. Whether 55–60 seats/screen (SOP) and 60 seats/screen (Feasibility Manual) should
   both gate, or be reconciled into one number — today's registry keeps them as two
   separate rules per CLAUDE.md governance; a Connplex decision could collapse this.
4. Which franchise tier governs a given project (user-selected vs. inferred vs.
   sales-negotiated) — still open, blocks item 5 above (foyer:screen ratio target).
5. Whether "Net Usage Area" is a second export type for every project or was
   Dhule-specific — still open, blocks the M8/export work in item 3.

## How to verify this status yourself

```bash
cd services/cad-interop
python3 generate_seat_layout.py && python3 evaluate_feasibility.py \
  && python3 rescore_candidates.py && python3 generate_area_seat_chart.py
# then:
cd ../project && npm start &
cd ../../apps/web && npm run dev
# open http://localhost:5173, log in as test@connplex.com / password123,
# open any project's intake form, click "Go to Zoning Canvas".
```
