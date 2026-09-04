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

## 2026-09-04 — Screen-first auto-layout, real Add-Zone placement, canvas UX polish

Explicit ask, with a real human-made cinema layout supplied as a reference:
auto-layout should place screens only ("leave other things and dont put
them, just logically and optimally place screens"), everything else added
via "Add zone" (now including "+ Screen" itself), plus three reported bugs.

**Auto-layout is screens-only now.** `generate_candidate` (`layout_engine.py`)
no longer calls what was `_place_support_zones` — a run returns auditoriums
only, with a plain note ("N screen(s) placed on X sqft. Y sqft remains — add
Foyer/F&B/Washroom/... from Add zone") instead of guessing at support-zone
footprints before the architect has even seen the screens. The old ">30%
unallocated" health-check warning (which assumed support zones would consume
most of the floor) is gone — it would have fired on every run under the new
behavior.

**Zero-gap adjacency between auditoriums.** `_neighbor_gap_ft` — the scan's
clearance buffer was a flat `AISLE_CLEARANCE_FT` (3.5ft) against every
already-placed room regardless of type. Two auditoriums now get 0 gap (real
cinemas share a demising wall — confirmed directly against the 35_SEAT
preset's own source note, measured from a real client file built this way);
every other pairing keeps the real aisle clearance. Verified live: a fresh
4-screen run packs into a tight 2×2 block sharing walls, matching the
supplied reference layout's look, instead of the old gapped-everywhere
scatter.

**Bug: "can't add a new zone without making space first."** Root cause —
`ZoningWorkspace.tsx`'s `addZone` always dropped the new room at the
boundary's fixed top-left corner with zero collision awareness, which the
backend's real validation then silently rejected (that corner was almost
always already occupied). Fixed properly, not patched: extracted
`place_single_zone` from the old support-zone placer's per-type
entry-aware scoring (foyer-near-entry, F&B-sightline, washroom-hidden-
from-foyer, BOH-far-from-entry/exit) plus the auditorium preset-fit loop,
exposed via a new `POST /layout/zones` endpoint, called by every "Add
zone" button including the new "+ Screen". Also caught and fixed a real
lost-update race while testing this: rapid-clicking multiple Add Zone
buttons before the first request resolved could silently drop one of the
additions (both requests read the same pre-write layout snapshot) — fixed
by disabling the Add Zone/Delete Selected buttons while a save is in
flight, same as any other in-flight-disabled control in this app.

**Two smaller reported bugs**, both in `EditableCanvas.tsx`: the permanent
bottom caption ("Drag a room to move it...") was low-contrast and
redundant once a room's handles/sidebar fields are visible — removed.
Canvas mechanics got real polish: mouse-wheel zoom centered on the cursor
(previously only +/− buttons, always anchored to a corner), click-drag
panning of the background (a `pan` offset added to the viewBox, armed only
outside drawMode so precise boundary-tracing clicks are untouched),
Delete/Backspace to delete the selected room, Escape to deselect, and a
CSS transition on room fill/stroke so hover/selection feels less abrupt.

Verified live end-to-end on the real Connplex Tower project: fresh
auto-layout (both strategies) screens-only + adjacent; every Add Zone
button including Screen; the previously-broken race now serializes
correctly; an honest 422 ("No space available for a new Screen — even the
smallest auditorium preset doesn't fit") when space genuinely runs out;
pan/wheel-zoom/Delete/Escape; existing drag/resize + validation-rejection
(overlap, out-of-bounds) still intact.

## 2026-09-04 — Real back navigation, toolbar/button polish, surfaced two dead backend fields

Explicit ask: "add back button, proper button and their style, looks should
be great without touching any features. also if backend has some features
made which is useful and not yet have proper ui then add those." No layout
engine, extraction, or API logic touched — every change here is navigation
plumbing or presentation.

**Back navigation** — genuinely didn't exist before. The step header
(`ZoningWorkspace.tsx`) was a static breadcrumb with no click handlers at
all; going from, say, Requirements back to re-pick a boundary meant losing
your place entirely. Added `maxStepIndex` (how far this project has
actually gotten) and a `goToStep` wrapper around every `setStep` call that
tracks it — a step already visited is now a real link back to it in the
stepper, plus an explicit "← Back" button in the header that steps back
one at a time. An unreached step stays inert (clicking "5. Run" before
Requirements exists would just render nothing useful). Verified live:
walked forward to Requirements, clicked back to Upload, clicked "2. Select
Boundary" in the stepper to jump forward again — state held correctly
both directions.

**Button/control consistency** — the workspace's toolbars (Edit step's
"Add zone" row, Geometry Review's linework/draw-boundary row, Boundary
Studio's tool switcher and unit-confirmation banners) had each grown their
own one-off `style={{ fontSize: '0.7Xrem', padding: 'Ypx Zpx' }}` per
button, several slightly different numbers doing the same job, plus raw
unstyled `<select>`/checkbox elements sitting next to real `.btn`s. Added
real reusable classes to `index.css` instead — `.btn-sm`/`.btn-xs`,
`.select-control`, `.checkbox-label`, `.toolbar` — and a `.btn:focus-visible`
ring, the one real accessibility gap in an otherwise deliberate design
system (every `.btn` previously fell back to the browser's own default
outline, easy to lose against this dark theme). Applied throughout;
"Delete Selected" also switched from `.btn-secondary` with manually
red-colored text to the actual `.btn-danger` class that already existed
for exactly this.

**Two backend fields that had zero UI, found by diffing `GeometryResult`
against what's actually rendered**: `recovery_note` (set when a DXF wasn't
fully spec-compliant and ezdxf's fault-tolerant recovery reader had to
step in — a real, specific "geometry near the affected entities may be
incomplete, review carefully" warning, silently discarded on every
response until now) wasn't even declared in the TS type. `extraction_method`
and the entity/closed-shape counts were fetched but never shown either.
Added a "Source File" panel to Boundary Studio's sidebar (filename,
extraction method, entity/shape counts, conversion note when a DWG was
converted) and a warning banner for `recovery_note` when present, same
visual treatment as the existing units-confirmation banner. Verified live
against a real upload — filename/counts/method render correctly; the
recovery-note path is a straightforward conditional matching an
already-proven pattern, not separately live-tested (no malformed DXF on
hand this session to trigger it).

## 2026-09-03 — One-click gap closing for boundary tracing, opt-in and never silent

Direct response to "there's a button to auto fill those gaps and close the
shape, but it doesn't intelligently close them yet" against the trace-gap
diagnostics from an earlier session. Added a real "close this gap" action,
but deliberately not a fully-automatic one: `WALL_SNAP_TOLERANCE_FT`
already rules out floating-point artifacts before a gap is ever shown, so
by the time one reaches the architect it's a real, deliberate absence —
sometimes a drafting slip worth one click to bridge, sometimes a real
doorway with no wall drawn across it, and this codebase's "never invent
architectural facts" principle means the difference has to stay a human
decision, not something silently auto-applied.

Backend: `_pair_dangling_endpoints` (nearest-neighbor matching of the
existing dangling-endpoint list) turns the flat list of gap markers into
real pairs with actual distances, carried on `BoundaryTraceError` and the
422 response as `gap_pairs_ft`. Frontend: a "Close this gap (X.X ft)"
button per pair — the real distance is shown so the architect judges each
one, not this UI — that adds a straight synthetic connector and
immediately re-traces. The connector renders in its own dashed,
distinctly-colored style on the canvas (never mistaken for a real selected
wall), and the count of bridged gaps carries through to the boundary's
review note (`build_manual_region`'s `closed_gap_count`) so Geometry
Review — which otherwise auto-advances a "clean" boundary in 1.6s — still
stops for a human on one that required an assumption. "Undo all" clears
every bridge back to real geometry only.

Verified live: selected 4 real wall segments from a real client file that
don't close, got 3 real gap markers with a paired "Close this gap
(3.15 ft)" button, clicked it, watched the trace immediately succeed with
the note "1 gap bridged with a straight line, not real drawn geometry —
verify against the file before confirming" surfaced in the UI.

**Also found and fixed in passing, unrelated to the above**: the exact
same stray write from an earlier session's log entry recurred —
`60_SEAT.min_area_sqft` had silently changed 1350→1500 again, bundled with
an unrelated full-file reformat, discovered only because `git status`
showed the registry as modified when nothing in this session's own work
touched it. Reverted via `git checkout`, same as last time. Root cause is
still unconfirmed — `services/project` has no request logging, so there's
still no way to see who/what is writing this — worth actually adding that
logging if it happens a third time.

## 2026-09-03 — Real human-designed cinema DWG comparison → added a missing small-auditorium preset

Given a real, already-executed Connplex zoning deliverable (`IINFINITY FF
(1).dwg`, a 3.5MB client file, uploaded and converted through the new
Docker/ODA DWG pipeline as its first real independent test) plus a
screenshot of the human architect's actual finished 4-screen layout for it
— asked to compare the tool's own auto-layout output against real work, not
a demo file, and improve the tool from what that comparison showed.

**Validation, not just comparison**: our extracted "NET USAGE AREA"
(8,580.8 sqft) matched the human's own on-drawing label ("NET USAGE AREA
8,537 SQ FT") to within 0.5% — real confirmation that unit detection
(Millimeters, correctly read from this file's header) and area computation
are right on a genuinely complex real file (47,184 entities, 4,245 closed
shapes), independent of every earlier test file.

**A real scope boundary surfaced**: none of the 18 auto-detected candidate
regions covered the human's actual built cinema — only small, individual
room-sized boxes (screens, entry) did, because the human had already
subdivided the floor with real interior walls, leaving no single unbroken
outer polyline for the "biggest closed shape" heuristic to find. Confirmed
this is architecturally correct behavior for what it's given, not a bug:
the tool's automatic detection is built for "empty shell, about to be
zoned" files, not "already-built, review this" ones — worth knowing, not
worth changing without deciding it's actually in scope.

**The real, fixable gap**: reconstructed the human's actual per-screen room
polygons directly from the file's geometry (matched each "Screen N" text
label to its enclosing wall polygon) and found real dimensions — Screen 1:
959.3 sqft/24.7×38.9ft/34 seats (Premium Recliner), Screen 2: 1273.4
sqft/64 seats, Screen 3: 1086.2 sqft/64 seats, Screen 4: 928.2 sqft/34
seats (17 Duo Lounger units). Running our own auto-layout against the
matching real empty zone elsewhere in the same file (8,580.8 sqft, 18 real
columns) could only fit 2–3 screens (202–262 total seats) at any strategy —
because the registry's smallest auditorium preset (`60_SEAT`, 1,350 sqft /
30ft min width) is larger than 3 of the human's 4 real screens. The
generator was never actually broken; it structurally couldn't reach a
format tier that real Connplex designs use.

Added a new `35_SEAT` preset to `rules_registry_v1.json` — config, not
code — sourced explicitly as `real_client_file` (not `SOP`, since it's
measured off an executed drawing, not the standards document) and marked
`REQUIRES_APPROVAL` rather than `SOURCE_BACKED`, same provenance discipline
every other entry in the registry already follows. Re-ran the same zoning
run afterward: "Maximize Screen Count" now produces 4 screens (was 3 max),
matching the human's real screen count exactly. Total seats (156 vs. the
human's 196) still differ — the preset system uses one fixed target size
per tier rather than the human's per-screen variation — but the structural
ceiling that made 4 screens impossible is gone.

## 2026-09-03 — QA pass against a real messy floor plan + admin test account

Created a fixed-credential admin account (`admin@connplex.com`) for admin-side
testing, and QA'd the full pipeline end-to-end as an architect would, using
one of the real client DWG/DXF files already in this repo's own
`services/cad-interop/test/` fixtures (Maruti Nandan Business Hub, Dhule —
54,586 entities, 37 layers, 9,406 raw lines, doors/windows/columns/stairs/
parking, not a synthetic test file) rather than a clean demo drawing.

Verified working end-to-end on that real file: extraction (7 plausible
candidate regions, correct Feet detection with no unit ambiguity), the
region-choice UI (`Choose a Different Boundary`), manual boundary drawing
(`Draw Boundary` tool), the Geometry Review obstacle confirm/ignore
controls (previously never actually exercised in this project's testing —
it auto-advances past itself in 1.6s on any boundary the extractor doesn't
flag, so a human only sees it by deliberately catching the "Choose a
Different Boundary" button in time or hand-drawing a boundary, which never
auto-advances), entry/exit marking, requirements, auto-layout, and PDF/DXF/
DWG export.

Found and fixed four real bugs:
- **PDF export silently dropped feasibility entirely.** `render_pdf()`
  accepted a `feasibility` argument and never used it anywhere in the
  file — a layout that read "NOT FEASIBLE" on-screen (this real file's
  1033-column structural grid fails the 20ft/30ft column-spacing minimums)
  exported to a professional PDF with zero trace of that failure. Added a
  `FEASIBILITY` block to the sheet listing the overall result and every
  failing/unevaluable rule.
- **Area & Seat Chart's "FOYER" row reads as a contradiction next to its
  own warning.** The chart's `FOYER` line is a rollup of all support zones
  (Box Office + Washrooms + F&B + BOH), not a literal Foyer room — but the
  sidebar table strips the explanatory suffix to fit, so seeing "FOYER
  2,466 sqft" right under "Could not place Foyer" reads as the app
  contradicting itself. Added the full label back as a hover tooltip.
- **A hand-drawn boundary's confidence caption falsely claimed heuristic
  provenance.** Geometry Review always appended "(largest un-nested closed
  polyline...)" to the confidence line regardless of `boundary.source` —
  correct for an auto-detected region, false for one the architect just
  drew by hand. Now branches on `source` and points at the real
  hand-drawn-boundary warning already shown just below it.
- **`Boundary.source`'s TS type didn't include the manual-boundary values
  the backend actually sends** (`manual-shape`/`manual-walls`/
  `manual-draw` from `build_manual_region`) — was typed as only
  `'explicit' | 'reconstructed'`. Widened to match reality.

Also chased down and ruled out two apparent bugs as false alarms: a
`ReferenceError: pan is not defined` + `RangeError: Maximum call stack
size exceeded` pair in the console turned out to be stale Vite HMR state
from a dev server that had been running for hours through earlier large
refactors (confirmed via `grep` — no real reference remained in source;
fixed by a clean dev-server restart, not a code change), and a
triple-`n`-looking "Connnplex" in one zoomed screenshot was a font-
rendering artifact, not a real typo (source reads "Connplex" everywhere).

Flagging two things found but not changed, since both are product
judgment calls rather than clear defects: (1) a very elongated floor plate
(this file's main region is 762 x 164ft, a 4.6:1 aspect ratio) wastes most
of the page on the fixed-portrait-A2 PDF sheet even after the existing
rotate-to-fit logic picks the better of its two orientations — the sheet
format itself has no good answer for that aspect ratio; (2) Geometry
Review's 1.6s auto-advance is deliberate and documented (see its own
comments), but on a real 1,033-obstacle region it means literally nobody
ever sees the obstacle list before it's confirmed — worth a product
decision on whether high obstacle counts should be one more auto-advance
gate alongside the existing "boundary has a note" / "units unconfirmed"
ones.

## 2026-09-02 — Fixed zoom drift, added wheel zoom, added precise gap markers for boundary tracing

Direct follow-up to the same day's curve-selection fix: after finally
being able to select the curved wall, the trace still failed with "these
segments don't form a closed loop" and no way to find out where, and the
project owner separately reported "zooming in and out isn't good enough,
can't drag to see other parts of the CAD file."

**Root cause of the zoom complaint**: `BoundaryStudio`'s viewBox was
anchored to a fixed top-left corner, not the current view's center — every
zoom-in via the +/- buttons shrank the view toward that corner, so
whatever the architect was trying to zoom into drifted toward the
bottom-right on nearly every click, needing a re-pan almost every time.
Rewrote the pan/zoom model around a real view-center point instead of a
top-left offset — fixes the drift for free (shrinking a range around its
own center doesn't move it) and enables real cursor-anchored zoom. Added
mouse-wheel zoom (missing entirely before — only 1.3x button clicks
existed) and raised the zoom ceiling from 40x to 4000x (this file's real
extent is ~1,514 x 807ft; 40x still showed ~37ft across at "fully zoomed
in"). Found and fixed a real bug while building this: the wheel
listener's own effect had no dependency on which of the component's three
conditional render branches was active, so it silently attached to a
stale/null ref and did nothing the first time you landed on the real
canvas — fixed by depending on the branch-selecting state directly.

**The trace failure was investigated, not assumed fixable**: re-ran the
exact failed selection with the same snap-tolerance precision the
automatic wall-reconstruction pass already uses — no difference. This
specific room's wall network genuinely doesn't close there; a real gap,
not something to silently paper over. But "there's a gap somewhere" gave
no way to find it in a large, dense drawing, so
`trace_boundary_from_segments` now computes the actual dangling-endpoint
coordinates (any point reached by exactly one selected segment) and
returns them; `BoundaryStudio` draws them as red markers directly on the
canvas plus one "Zoom to gap N" button per marker.

Verified live end-to-end, all three fixes together: wheel-zoomed smoothly
through 6+ steps with the cursor's target point staying visually fixed
each time; deliberately selected an incomplete set of segments (the
curve + 3 unconnected nearby walls) and confirmed the real response ("7
open ends marked on the drawing") with 7 correctly-placed markers, then
confirmed "Zoom to gap 1" jumped the view exactly onto the true open
endpoint. `tsc --noEmit` clean; backend imports cleanly. Committed on
`zoom-pan-and-gap-diagnostics`, pushed, fast-forward merged to `master`,
pushed.

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
