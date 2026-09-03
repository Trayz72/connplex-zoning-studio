# LOG

A terse, chronological changelog — one entry per work session, newest first.
This is the "when did X happen / what shipped that day" index. For full
technical detail on any entry, see the matching section in `STATUS.md` (its
narrative "Update:" sections are in the same order as this file, just with
much more depth). For architecture, module boundaries, and standing rules,
see `CLAUDE.md`. Don't duplicate detail across all three files — this one
stays short on purpose.

Dates are only as precise as `STATUS.md` recorded them; sessions before
dates were consistently logged are numbered instead ("session N").

---

## 2026-09-02 — Select a whole curved wall with one click

Direct follow-up to the same day's sheet-artifact fix: the project owner
reported still being unable to select a curved wall in Select Walls, on the
same real `theater_clean.dxf`, and asked for deep analysis rather than
another quick patch.

**Root cause, found by tracing the exact ARC**: its endpoints connect
exactly (zero gap, verified directly) to the neighboring straight walls —
never a geometry-closure problem. The real issue is that ezdxf's path-
flattening breaks one real curved wall into dozens of individually tiny
straight fragments (this file's 4 real curves flatten into 66/74/64/64
fragments each), each independently clickable and each too small to
reliably hit. Selecting one curved wall meant dozens of pixel-precise
clicks on effectively invisible pieces.

**Fixed at the source**: `cad_extraction.py`'s `full_raw_geometry` now tags
every fragment of one continuous curved entity (ARC/SPLINE/full-sweep
ELLIPSE) with a shared `curve_group` id. `BoundaryStudio` groups by it —
click, hover, or deselect any one fragment and the whole real curve
responds, with the "Selected Walls" count showing logical units (1 curve =
1) instead of raw fragment counts. Deliberately scoped to ARC/SPLINE/
ELLIPSE only, not LWPOLYLINE/POLYLINE — a polyline can legitimately mix
straight runs with one bulged corner, and grouping the whole entity would
have undone the same day's earlier Shift+drag partial-wall-selection
feature.

**Also investigated and answered directly**: "why are there other rendered
layouts" — confirmed, not assumed, that this file's 5 similar auditorium
shapes are real distinct hand-drawn rooms, not a duplication bug: all 513
modelspace entities have unique DXF handles, and no block is inserted a
suspicious number of times (the one repeated block — a column symbol — is
inserted 150 times, consistent with this file's documented ~170 real
columns). Matches this exact file's own prior documented history: a real
multi-screen theater complex.

Verified live end-to-end via direct pointer-event dispatch at exact
DOM-derived coordinates (a sub-1px-wide fragment isn't reliably clickable
through screenshot-based automation either, which is itself more evidence
for the bug): one click selected all 74/74 fragments of the file's largest
curve group (confirmed by reading back every fragment's actual rendered
color, not just the UI count), one click again deselected all 74. `tsc
--noEmit` clean; backend imports cleanly. Committed on
`curve-whole-selection-fix`, pushed, fast-forward merged to `master`, and
pushed per the project owner's standing request to keep master current.

The project owner reported, from real use on their own uploaded
`theater_clean.dxf`: a "curved wall" that couldn't be selected in Select
Walls, 500+ candidate regions with impossibly large sqft values, and asked
for precise partial-wall selection ("just half a wall") plus a way to
collapse the region list. Root-caused rather than patched symptom-by-symptom.

**Real root cause, one fix for two symptoms**: the file's `MARGIN`-layer
sheet-margin line — visually the single most prominent diagonal line in the
whole drawing — was rendered and selectable identically to a real wall
(nothing distinguished "drafting artifact" from "architecture" for wall
click-candidacy). Separately, the live project had been unit-confirmed as
"Feet" instead of the header-suggested "Inches", inflating every area 144x
and pushing hundreds of small real objects (columns, hatch fills) over the
boundary-candidate size threshold — reproduced and fixed live via the real
`/cad/units` endpoint, not guessed at.

- **New "sheet" line category** (`cad_extraction.py`, alongside the
  existing "annotation" one for dimension/leader lines): any line on a
  `NON_PHYSICAL_LAYER_HINTS` layer (viewport/margin/format/title-block/
  plot/F.S.I./built-up/dim) is now dimmed, excluded from wall-network
  reconstruction, and excluded from wall-click candidacy in
  `BoundaryStudio`. Verified: region count on the real file dropped from 9
  to 3, and the top region flipped from a "reconstructed, low confidence"
  guess to a real "explicit, medium confidence" closed polyline once
  margin-line contamination was removed from the wall network — clean
  enough to auto-advance past manual review entirely.
- **Real unit-mismatch plausibility check**: confirming a unit that
  produces more than 20 candidate regions (a real single floor plate
  essentially never does) now shows a warning naming the file's actual
  suggested unit, with a one-click fix. The existing oversized-single-
  boundary check didn't catch this at all — that case's largest region was
  ~463,000 sqft, comfortably under its own 500,000 sqft cutoff.
- **Partial-wall selection, the precision fix directly asked for**:
  Shift+drag along a wall in Select Walls now selects just the dragged
  sub-portion (e.g. half a long wall) instead of only ever the whole
  pre-computed segment. New `custom_segments` param on
  `POST /boundary/trace` accepts literal coordinates alongside segment ids.
  Gated on Shift specifically — an early ungated version hijacked ordinary
  panning any time a pan gesture happened to start on a wall line (most of
  the canvas, in a dense drawing), found by testing the feature against
  itself, not assumed safe.
- **Region-candidate list now collapses** behind a "Show all N" toggle
  above 8 candidates (showing the 5 largest by default) instead of
  flooding the whole sidebar — a real case had 537 buttons.

Verified live end-to-end, all four interaction paths distinctly: plain
click selects/deselects a whole wall, plain drag pans (including starting
on a wall line — the regression the Shift-gating fix above was for),
Shift+drag selects a real partial sub-segment, and clicking a selected
partial removes it. `POST /boundary/trace` with only `custom_segments` (no
`segment_ids`) verified independently via curl to close a real polygon.
`tsc --noEmit` clean; all backend modules import cleanly.

Both this batch and the previous same-day entry below were committed on
feature branches (`entry-exit-boundary-hardening`,
`boundary-studio-precision-fixes`), pushed, and fast-forward merged to
`master` per the project owner's explicit request.

## 2026-09-02 — Entry/exit-aware auto-layout, captured at boundary-selection time

The project owner asked for full-pipeline testing/assessment, more logical
zoning placement with entry/exit circulation in mind, and — the concrete
new feature — capturing the main entrance and exit point(s) at
boundary-selection time rather than later in Requirements. All delivered
and verified live, not just implemented.

**New: `EntryExitPicker`** (`apps/web/src/components/workspace/EntryExitPicker.tsx`),
a shared component now used in two places:
- **Primary capture point — `BoundaryStudio`**: every boundary-selection
  path (auto-detect, click-a-shape, wall-trace, freehand-draw, or picking a
  candidate region) now lands on a new "Mark Entrance & Exits" sub-step
  before advancing to Geometry Review, showing the real chosen boundary
  outline. A `PendingChoice` state replaces all four previous direct
  `onBoundaryChosen` calls. Both entry and exit stay optional — never a
  hard block — consistent with the rest of this codebase's "advisory, never
  a silent blocker" stance.
- **Secondary review/edit point — `RequirementsStep`**: kept (not removed),
  now pre-filled from what was marked in BoundaryStudio via two new props
  threaded through `ZoningWorkspace`'s state, so an architect who changes
  their mind can still adjust it later without going back a whole step.

**Backend: exit points are now real input, not just entry.** `RequirementsIn.exit_points_ft`
(list of `[x,y]`, backend) / `Requirements.exit_points_ft` (frontend) —
verified end-to-end: marked in BoundaryStudio → survives to Requirements →
persists in `requirements.json` → consumed by `layout_engine.py`.

**`layout_engine.py` actually uses entry AND exit now, not just entry:**
1. **Auditorium placement was completely blind to entry/exit before this
   session** — confirmed by reading the code: only `_place_support_zones`
   ever read `entry_point_ft`; the auditorium packer used a fixed
   bottom-left-corner scan regardless of where the entrance was. Fixed with
   `_entry_exit_scan_flip`/`_mirror_for_scan`/`_unmirror_rect`: the scan
   now runs in a coordinate space mirrored about the floor plate's own
   center along whichever axes point from the entrance toward the exits'
   centroid (or, with no exit marked, away from the entrance toward the
   plate's far side), so screens fill starting near the entrance and
   proceed toward the exit — a real geometric reading of the SOP's "entry
   -> foyer -> auditorium" sequencing (§2.8), not full circulation-path
   routing this rectangle packer was never going to do honestly.
   **Verified two ways**: a direct unit test (entry/exit on opposite sides
   of a 300x150ft floor placed all 4 screens starting from the entry-side
   corner, no overlaps/out-of-bounds) and live in the browser (built a
   fresh 220x100ft test floor, marked entrance right / exit left, ran the
   real pipeline end-to-end — Screen 1 landed against the entrance wall,
   Screen 4 against the exit wall, in between in order).
2. **Back-of-house now placed away from both entry and exit** — new
   `BOH` case in `_place_support_zones`: staff-only space was previously
   just whatever first-fit landed on; now scored to maximize distance from
   the entrance and every marked exit, keeping it out of the public flow
   path the same way a real architect would.
3. **New cross-movement warning**, closing a real, previously-unused gap:
   the registry already had a qualitative `SEPARATE_ENTRY_EXIT_FLOW`
   planning norm ("no cross-movement between entry/exit flows") sourced
   from the SOP, sitting completely unreferenced in code. Added
   `MIN_ENTRY_EXIT_SEPARATION_FT` (15ft, `ENGINEERING_ASSUMPTION` — the SOP
   states the qualitative rule but no distance) as this engine's honest
   line-of-sight proxy: an exit marked within that distance of the entrance
   now surfaces a real warning citing §4.4/§9, never a hard block. Verified
   both branches directly (fires when close, silent when far).

**Testing/assessment pass, this session**: re-verified the real Dhule/
theater_clean.dxf-derived project, the whole boundary→requirements→run→edit→export
chain with entry/exit data flowing through correctly, all three exports
(PDF/DXF/DWG) still producing valid files with the new entry-oriented
layout, the admin Rules & Config registry correctly surfacing the new
planning norm with full provenance and live-editability, and the light
theme (added same day, see below) rendering correctly on the admin/login
pages it wasn't directly touched on. `tsc --noEmit` clean; all Python
modules (`main`, `layout_engine`, `cad_extraction`, `feasibility_engine`)
import cleanly.

**Honest gap, stated plainly**: marked entry/exit points aren't drawn on
the exported PDF/DXF/DWG yet — the export templates (`export_pdf.py`/
`export_dxf.py`) weren't touched this session. The placement *logic* uses
them for real; the *drawing* doesn't show them yet. A real follow-up, not
a hidden one.

**Also found while wrapping up, not part of the intended work**: a `git
diff` check before finishing turned up a real, unexplained change to
`auditorium_presets` → `60_SEAT.min_area_sqft` (1350 → 1500 sqft, a
SOURCE_BACKED SOP number) already written to disk, plus a full
re-serialization of the rest of the file — confirmed via the admin write
path's own timestamped backup (`routes/rulesConfig.js` writes one before
every save), which still held the correct 1350. That backup mechanism only
fires on a real `PUT /admin/rules-config/:category`, i.e. an actual save
through the admin UI; root cause of *that specific request* isn't
confirmed — no request logging exists in `services/project` to trace it
(a real, separate gap). Restored the file to its last-committed state and
reapplied only the one intended addition (`MIN_ENTRY_EXIT_SEPARATION_FT`)
by hand, verified back to a clean 2-line diff and confirmed
`rules_registry.py` reads the correct 1350 again. Flagging this plainly
rather than assuming it was harmless — a silently wrong auditorium-preset
minimum is exactly the kind of business number this registry exists to
protect.

## 2026-09-02 — Three real bugs fixed on a real user-uploaded file, plus a global light theme

The project owner uploaded their own real file (`theater_clean.dxf`, via
their actual "Connplex Tower" project) and reported the boundary-selection
step wasn't precise enough, plus that the dark theme made an uploaded
drawing hard to read. Investigated the real file directly (not guessed)
and found three genuine, previously-undiscovered bugs:

1. **Boundary candidates could be pure sheet-drafting artifacts.**
   `cad_extraction.py`'s boundary ranking had no concept of "this layer is
   never real geometry" — on this file, a single VIEWPORT-layer sheet frame
   (117,059 sqft) and six duplicate MARGIN-layer sheet-margin rectangles
   (47,050 sqft each, all identical — not six real rooms) outranked the
   file's real, wall-reconstructed geometry purely on raw area, with no
   warning. Fixed with `NON_PHYSICAL_LAYER_HINTS` (viewport/margin/format/
   title-block/plot/F.S.I./built-up/dim), reusing the same "layer name is
   real evidence" pattern the codebase already used positively for
   columns/walls, and the same non-physical-layer judgment
   `ai_obstacle_classify.py` already made for obstacles — applied here to
   boundary *candidacy*, not just after-the-fact obstacle cleanup. Verified:
   the same file now returns 9 real, wall-reconstructed candidate regions,
   correctly low-confidence with a "verify carefully" note, no duplicates.
2. **BoundaryStudio's auto-advance ignored ambiguous units entirely.**
   It only checked whether the top boundary candidate had a `note` — not
   `geometry.units.needs_user_confirmation`. A file with unspecified
   `$INSUNITS` but a boundary that happened to look clean would silently
   skip past the one screen with the actual units-confirmation control,
   landing the architect on Geometry Review with a read-only warning and no
   way to fix it. Fixed by adding units-confirmation to the same gate.
3. **A rule that genuinely passed still displayed failure-sounding text.**
   Every `message_template` in the rules registry is authored describing
   the FAIL condition only (e.g. "Clear height below 10'-0" minimum — NOT
   VIABLE."); `feasibility_engine.py` used it unconditionally for both PASS
   and FAIL, distinguished only by a subtle text-color difference in the
   frontend. Confirmed directly via the API: `clear_height_ft: 12.0` against
   a `10.0` threshold genuinely returned `"result": "PASS"`, yet displayed
   that exact failure sentence. Fixed: a passed rule now always gets a
   neutral, accurate message built from the real measured value instead of
   reusing the failure template. Re-verified live: the same project's
   feasibility panel changed from a false "NOT FEASIBLE" to the honest
   "INSUFFICIENT DATA" (missing column-grid/fire-escape signals only), with
   clear height correctly shown as passing.

Also shipped a real global light theme (`index.css`'s `[data-theme="light"]`
block + `theme.ts` + `<ThemeToggle>`, wired into all 5 page headers),
directly in response to the readability complaint — the entire component
tree already read colors exclusively through CSS variables (zero hardcoded
hex in any component going in), so this was a real, complete theme, not a
partial patch. Fixed the handful of hardcoded whites in `EditableCanvas.tsx`
(room labels, selection outline, resize handles) that would otherwise have
gone invisible against a light canvas.

Continued the same real project's flow through to Run/Edit to directly
answer "can it auto-zone with the right size and seat dimensions": on the
corrected 9,098 sqft region, it auto-placed 4 auditoriums (avoiding all 20
real confirmed columns) sized 3,500 sqft/195 seats each, plus Foyer/F&B/
Washroom/Box&Office/Back-of-house support zones — real, computed, editable
output, not a placeholder.

`tsc --noEmit` clean; all three Python modules import cleanly.

## 2026-09-02 — Verification session (no code changes)

The project owner asked for a feature ("identify the workable area,"
human-in-the-loop boundary selection + a clean-CAD-file path) that turned
out to already exist — `BoundaryStudio.tsx` + `cad_extraction.py`. Rather
than take `STATUS.md`'s word for it, ran a real, adversarial verification
pass end-to-end, live, against a file this pipeline had never seen before.

- **Uploaded the real Dhule production DWG** through the actual browser
  UI: upload → DWG→DXF conversion → automatic boundary detection →
  auto-advance straight to Requirements, matching `STATUS.md`. `theater.dwg`
  still fails conversion with the same documented, honest `XData size
  exceeded` ODA limitation (not a regression).
- **Built a fresh synthetic stress-test DXF** (never run through this
  codebase before) combining: a closed LWPOLYLINE boundary with a bulged
  (arc) corner, 5 column INSERTs incl. one mirrored+rotated, a HATCH drawn
  directly over one column (the known double-count case), a full ELLIPSE,
  an unclosed SPLINE, a DIMENSION and a LEADER, and an MTEXT label — across
  6 AIA-convention layers. Ran `cad_extraction.extract()` on it directly
  first (Python, no HTTP): all 5 columns correctly resolved (including the
  mirrored one — confirms the hand-composed-transform fix still holds),
  HATCH-over-column correctly deduped to one obstacle not two, ellipse
  correctly classified FURNITURE, DIMENSION/LEADER correctly excluded from
  boundary/obstacle candidacy, and the unclosed spline was still caught (as
  low-confidence `UNCLASSIFIED_OBSTACLE`, tagged `RECONSTRUCTED_FROM_LINES`)
  by the line-network reconstruction fallback rather than silently dropped.
  Found one real authorship bug in the test fixture itself along the way
  (a bulge value of -1.0 produces a radius-30 semicircle, not a gentle
  corner round — not a `cad_extraction.py` bug, just a test-data mistake,
  caught and fixed before drawing any conclusion from it).
- **Re-ran the same file through the actual browser UI**: identical
  behavior — clean auto-detect, auto-advance to Requirements, and the Edit
  canvas correctly rendered the curved boundary, the reconstructed blob
  shape, and the ellipse, with an honest itemized `NOT_FEASIBLE` result
  (specific rule + measured value per failure, never a bare boolean) for
  this deliberately tiny/odd 2,304 sqft test floor — a correct result for
  that input, not a bug.
- **Ran all three exports** (PDF/DXF/DWG) on that run and verified the
  actual files on disk, not just the 200 OK: PDF is a real 1-page PDF 1.4
  document; DXF re-parses cleanly with `ezdxf` (22 entities across
  correctly-named layers); DWG is confirmed by `file` as genuine `DWG
  AutoDesk AutoCAD 2018/2019/2020` format.

**Conclusion, stated plainly**: for real architectural floor-plan DXF/DWG
content (the product's actual scope — not a generic "render every DXF
entity type" viewer), parsing → boundary selection → the rest of the
pipeline is genuinely working, on a file this session authored fresh, not
just the two known reference files. Entity types outside this scope
(SOLID/3DFACE/POINT/MLINE/etc. — rare in floor-plan wall/boundary geometry)
remain untested and are a real, honest scope boundary, not a hidden gap.

Created this file and confirmed `CLAUDE.md`/`STATUS.md` already exist and
are current — did not recreate them. Cleaned up test projects and temp
upload files afterward. No source files changed.

## 2026-09-02 — Seventeenth session

Full DXF entity-type audit: found DIMENSION/LEADER entities were completely
unrendered (their real geometry lives in a referenced anonymous block, not
the entity itself). Fixed, and categorized all such entities as `annotation`
vs `geometry` so dimension/leader lines can never manufacture a false wall
during boundary reconstruction. Documented a deliberate non-fix (frozen/off
layers are still extracted — a real column is a real obstruction regardless
of a save-state toggle). Added `"chair"`/`"bike"` layer hints (reclassified
11,150 real shapes from unclassified to FURNITURE). Added
`ai_obstacle_classify.py` — an AI-assisted second pass for obstacles the
layer-name heuristic still can't place, always leaving final
confirm/ignore to the architect. See `STATUS.md` top section for full detail.

## 2026-09-02 — Sixteenth-adjacent session (BoundaryStudio hardening + full automation)

Stress-tested `BoundaryStudio` against 10 files including the real, huge
Vadodara file (~21,000 closed shapes). Found and fixed a 276s→7.5s extraction
bottleneck (O(regions×entities) → precomputed once), a 16-32ms→0.1-0.8ms
frontend hover-scan bottleneck (spatial grid index), a 100-button region
switcher UI flood, and completely unhandled SPLINE/ELLIPSE entities. Added
full upload→boundary→zoning→seats→export automation with manual
boundary/layout editing kept as opt-in, never required.

## 2026-09-01/02 — BoundaryStudio added (human-in-the-loop boundary selection)

The feature this project's owner asked for again on 2026-09-02, already
built here: a step between Upload and Geometry Review rendering the entire
drawing uncropped, with three real selection tools (click a closed shape,
click wall segments and trace the loop, freehand draw) plus the automatic
candidates as quick-pick chips. Found and fixed two real correctness bugs
surfaced while building it: 170 real columns were invisible (undetected
INSERT/block-reference resolution, plus a silent ezdxf mirroring bug worked
around by hand-composing transforms), and a file with unspecified DXF units
was silently assumed wrong by ~12x with no way to correct it.

## Security audit session

Fixed a forgeable/unsigned session cookie (real auth bypass), cross-tenant
project data exposure (any logged-in user could read/edit/delete anyone
else's projects), and a misleading API schema on `select-candidate`.

## 2026-09-01 — Real-file CAD extraction fixes, AI CAD-scan, hand-drawn boundaries

Batch-tested 16 real client DXFs (5 initially found zero usable regions).
Fixed curved-wall-segment handling (ARC/bulged polylines) in boundary
reconstruction and near-miss wall-junction snapping. Added "Scan with AI"
(`ai_cad_scan.py`) for files still broken after the deterministic fix —
Claude only ever picks which CAD layer holds real geometry, never invents
geometry itself. Added an inline hand-drawn-boundary flow inside Geometry
Review as a second escape hatch.

## Client-feedback session — zero-required-clicks standard flow

Direct response to reported friction (443 individual obstacle
confirm/ignore clicks before ever seeing a layout on one real file). Made
the standard path upload → auto-detected/auto-confirmed geometry →
auto-run → auto-selected candidate → editable/exportable layout, with every
manual step (boundary pick, obstacle review, layout editing) staying
available as opt-in, never required. A boundary carrying a real warning
(implausible size, reconstructed with no evidence) still always stops for a
human — that gate is never skipped.

## Render deployment session

Deployed to Render (`connplex-web`, `connplex-project`,
`connplex-zoning-engine`). Fixed cross-origin auth (`sameSite:'none'`
cookies, locked-down CORS, env-driven API base URLs). Found and fixed a
real "stuck on Running..." hang from a live user report: an unspecified-
units file's boundary heuristic picked a multi-million-sqft sheet-border
frame instead of the real building outline, and the auto-layout grid
scanner had no upper bound on cell count. Both fixed with explicit size
sanity checks / an adaptive grid step.

## Selection-persistence + color-coding session

Fixed a real bug where selecting a room to resize never actually stayed
selected (a `pointerdown`/`click` event-type mismatch in the deselect
handler). Removed per-room-type color from the DXF/DWG export and the
editing canvas after checking a real Connplex reference PDF — kept color in
the PDF specifically because the real reference drawing uses it there.

## Deployment-prep session — M2, M6, M9, M10

Built the Rules/Config admin UI (`/admin/rules`, real CRUD with provenance
shown), adjacency-aware auto-layout (foyer nearest entrance, F&B visible
from entry, washrooms hidden from foyer sightline — gated on a real
architect-marked entry point, never guessed), export history, and dashboard
search/filter.

## Authentication + admin-management session

Root-caused a "can't log in" report to stopped dev processes, then found
something bigger while investigating: `services/project` silently
authenticated as "the first user in the database" whenever no session
cookie was present — a real, total auth bypass, not a documented
simplification. Fixed, added a real frontend route guard, fixed
case-sensitive email login, added admin accounts + user management, added a
global error boundary, fixed a `ZeroDivisionError` crash on undersized
floor plates.

## Real-world stress-testing session

Downloaded real DXF floor plans from outside this project entirely and ran
them through the full pipeline. Found and fixed: boundaries drawn as
disconnected wall segments with no closed polyline (reconstructed via
`shapely.polygonize`), a door-swing arc mistaken for its own floor region,
an O(polygons×segments) hang on complex files, and a malformed-DXF crash
(now a clean 422, with an `ezdxf.recover` fallback for genuinely
recoverable spec violations).

## PDF-format-matching session

Rewrote `export_pdf.py` to match a real supplied Connplex reference PDF
(Keshav Landmark, Vadodara) exactly: floor plan placement, General
Notes/Legends/Area & Seat Chart/Revisions/Drawing-Issued-log
structure/order, project info block, and a drawn approximation of their
logo (no vector asset available that session).

## Per-room seat-type/mix session

Generalized seat computation from one hardcoded seat type to any registry
seat type with real dimension data, plus a two-type mix by front/back row
ratio.

## Visual-polish session

Fixed resize handles (were pixel-tiny at any real zoom level — now fixed
screen-size with a much larger hit area, all 8 positions draggable). Added
a numeric X/Y/width/depth editor as an alternative to dragging. Added a CAD
linework backdrop toggle. Fixed two real PDF layout bugs (wasted blank
space on non-square regions, long room names overflowing their boxes).

## Dashboard-cleanup session

Made project delete real end-to-end (was previously a UI-only affordance).
Removed the entire legacy demo pipeline (`/canvas`, hardcoded to two
specific reference files, replaced by the generic `/studio` pipeline).
Expanded obstacle classification beyond COLUMN/UNCLASSIFIED to
DOOR/WINDOW/STAIRCASE/WASHROOM_FIXTURE/FURNITURE via layer-name evidence.

## Earlier sessions (M0–M8 legacy pipeline + `zoning-engine` v1 build)

See `CLAUDE.md`'s "What was built in this session (2026-08-31)" for the
detailed record of building the real `services/zoning-engine` pipeline from
scratch (generic CAD extraction, human-confirmation gating, generic
auto-layout with two genuinely different strategies, real interactive
canvas editing, real PDF/DXF/DWG export) alongside auditing and fixing the
original legacy `services/cad-interop` demo pipeline (seat modeling,
scoring-objective mismatch, a fully-hardcoded compliance panel, a silently-
broken candidate-score join).
