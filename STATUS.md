# STATUS

Last updated: 2026-08-31 (sixth session, same day — visual/professional polish pass)

## Is this deliverable? Can Connplex's architecture team start using it for zoning and seat counts?

**For the core workflow — yes.** Upload a real DWG/DXF → confirm detected geometry
→ enter requirements → auto-generate zoning → get real, computed seat counts
(with a choice of seat type/mix) → edit the result → export a matching PDF and
a real DXF/DWG — all of that is real, has been tested against real Connplex
files and outside files, and just had a second, adversarial pass today that
found and fixed 3 more real bugs (below) that would have blocked genuine daily
use, not just demo use.

**What was fixed today specifically because it would have blocked real use,**
found by asking "what happens the first time an actual architect uses this
day-to-day" rather than re-testing the happy path:

1. **A hard refresh, a bookmark, or a shared link to any project page was
   broken** — confirmed via direct curl testing this was a real 404/500, not
   a cosmetic dev-server quirk as previously assumed. Root cause: the backend
   API and the frontend's own page routes shared the same `/projects/...` URL
   prefix, so the dev proxy intercepted frontend page loads and sent them to
   the wrong backend. Fixed by moving the project/auth API to its own
   `/api/pm/...` namespace — verified with a genuine cold navigation (not
   client-side routing) straight to a project's zoning workspace, which now
   loads correctly and resumes exactly where the project was left off.
2. **There was no way for a second architect to get an account** — only one
   seed-script demo login existed. Added real registration
   (`POST /api/pm/auth/register`) and a sign-up flow on the login page.
   Verified live: created a second real account, auto-logged-in.
3. **Three feasibility checks were always "insufficient data" even when the
   data existed.** Clear height is collected at intake but was never fed into
   the feasibility engine; column-grid spacing was never computed from the
   CAD data at all. Both are now wired in — clear height via a confirmable
   number in the Requirements step (auto-suggested from intake, including
   correctly parsing the SOP's own `10'-0"` feet-inches notation, which had a
   real bug on first attempt: it was silently misread as 8.33 ft instead of
   10), and column-grid spacing computed geometrically from confirmed column
   positions. Verified end-to-end: what used to be `INSUFFICIENT_DATA` on 3
   of 9 rules is now a real `PASS`/`FAIL` on 8 of 9 — only fire-escape count
   remains unavailable (no CAD signal exists for that; not fabricated).

**What's still a real gap, stated plainly rather than glossed over:**

- **Multi-floor buildings need a workaround, not a clean workflow yet.** Today
  each "project" holds one floor's active zoning state. A multi-floor upload
  (like the real Dhule file, which contains 7 candidate regions) correctly
  detects all the floors, but committing to more than one at a time means
  creating a separate project per floor (same upload, different confirmed
  region each time — distinguish them by `property_name`, e.g. "Dhule —
  2nd Floor", since `project_code` auto-increments and can't be reused). This
  works today; it's just not as smooth as a proper floor switcher inside one
  project. The database schema already has an unused `floors` table anticipating
  this (spec decision #9) — activating it is the natural next feature, not a
  redesign.
- **Not deployed anywhere Connplex staff could reach it yet.** Everything above
  is verified running locally in this session. Someone (Antigravity, or Connplex's
  own infra) needs to actually host the three services (`services/project`,
  `services/zoning-engine`, `apps/web`) somewhere reachable — see "Running this
  project" in CLAUDE.md for exact commands; nothing here needs a rewrite to
  deploy, just a place to run it continuously.
- **Deployment must include a working SPA fallback.** The routing bug above was
  fixed for the dev proxy; whatever serves the production build in the end
  (nginx, a Node static server, etc.) needs to serve `index.html` for unmatched
  paths too, or this exact class of bug returns in production. Test it the same
  way this session did: `curl` a deep route directly.
- Real vector logo artwork (still a redraw, not their actual file — see the PDF
  format section below) and exact-format DWG template parity remain open, as
  before.

## Update: visual polish pass — CAD backdrop, resize UX, numeric editing, PDF export quality

Directly in response to specific user feedback: resizing rooms was hard, and
the exported/rendered output needed to look professional rather than just
functional. Checked the whole editing → zoning → export path and fixed what
was real, not cosmetic-only:

- **Resize handles were the actual reported problem.** Root cause: they were
  sized in feet (so they shrank as you zoomed out) and their clickable hit
  area was identical to their visible size — a few pixels at any real zoom
  level — and only the 4 corners had handles at all. Rewrote
  `EditableCanvas.tsx`: handles now render at a fixed screen-pixel size
  regardless of zoom, each has a much larger invisible 26px hit circle around
  a 9px visible dot, and all 8 positions (4 corners + 4 edges) are draggable
  with correct per-handle cursors. Verified with a real mouse drag (not a
  simulated event) — shrank the Dhule auditorium from 1,350 to 1,066 sqft
  smoothly on the first attempt.
- **Added a numeric fallback**, `RoomDimensionEditor.tsx` — exact X/Y/width/
  depth fields next to the seat config panel, for when a precise dimension
  matters more than a drag. It feeds the same `PUT /layout` validation a drag
  does, so an overlapping value is rejected the same honest way.
- **The original CAD linework can now be shown as a backdrop** under the
  interpreted zoning layers (walls/columns/text at 35% opacity), both during
  geometry review and while editing, via a `showCadLinework` toggle. New
  `extract_raw_geometry()` in `cad_extraction.py` feeds it, capped at 6,000
  lines / 800 text entities per region with an honest "partial — capped for
  size" note when a region is truncated, rather than silently dropping data.
- **PDF export had two real, visible defects on genuine complex geometry** —
  only surfaced by exporting the actual edited Dhule floor, not the earlier
  simple synthetic-room test:
  1. The floor-plan box spanned the full sheet height regardless of the
     drawing's own shape, leaving roughly half the sheet blank white space
     for a region that's wider than it is tall.
  2. Long room names ("FOOD & BEVERAGE / CONCESSION") overflowed narrow
     rooms' drawn boundaries once the font-shrink loop hit its floor size.

  Fixed both in `export_pdf.py`: the plan now auto-rotates 90° when that
  orientation would use the sheet meaningfully better — the same call a
  drafter makes fitting a plan to a sheet; only geometry rotates, room-name
  text is still drawn upright and readable. Added a real title/scale header
  and a genuine computed overall-dimension callout at the bottom (the
  region's actual bounding size in ft-in, not an invented round scale
  figure). Long room names now wrap onto a second line before the font is
  allowed to shrink past legibility. Verified by re-exporting the same real
  Dhule project before/after and comparing renders directly — confirmed the
  blank space is gone and no label overflows any room anymore.

## Update: per-room seat-type/mix selection at edit time

The architect can now pick a seat type (or mix two types by a front/back row
ratio) per auditorium *after* zoning, on the canvas. Backend:
`seat_engine.py` was generalized from a single hardcoded seat type
(`SLIDER_SOFA`) to work off any registry seat type that has real width + row-
step data (`selectable_seat_types()` — currently Slider Sofa, Duo Lounger,
Premium Recliner, Duo Premium Recliner; Front Lounger and the Lunar Lounger
are excluded because the SOP extract never gave them a row step, and a value
wasn't invented for them), plus a two-type proportional-depth-split mix
(explicitly documented as a heuristic, not a claimed company standard — no
seat-mix ratio rule is decided yet). New endpoint `GET /api/seat-types`; rooms
now carry an optional `seat_config`; `PUT /layout` recomputes real seat counts
and the Area/Seat Chart from it. Verified with real API calls: Premium
Recliner alone gave 72 seats vs. 63 for Slider Sofa in the same room (denser
footprint, less clearance needed); a 60/40 Sofa/Duo-Lounger mix gave 55 seats
split 35/20 — all real, computed numbers, not placeholders.

## Update: real-world stress testing found and fixed 4 genuine bugs

Downloaded real DXF floor plans from the internet (not project test data) and
ran them through the full pipeline to test the "does this work on any floor
plan" claim honestly, then re-ran the existing regression set (Dhule,
Vadodara, the synthetic file) to make sure nothing broke. Found and fixed:

1. **A boundary drawn as 5 separate wall LINE segments (no closed polyline at
   all) produced zero regions.** This is the single most important fix today —
   it's the same "composite wall segments, no single closed polyline" case
   that even Connplex's own Dhule basement/ground floors hit (noted in the
   legacy pipeline's own frozen documentation). `cad_extraction.py` now also
   reconstructs closed boundaries from a network of line segments via
   `shapely.ops.polygonize` (`_reconstruct_polygons_from_lines`), tagged
   `source: "reconstructed"` with lower confidence and an explicit note —
   never presented with the same certainty as an explicit closed polyline.
2. **A door-swing arc (a CIRCLE entity) was large enough to get mistaken for
   its own separate floor region.** Floor plates are essentially never
   literally circular; circles are now excluded from *boundary* candidacy
   (still eligible as *obstacles* — columns are often circles).
3. **The line-reconstruction pass hung indefinitely on the real, complex Dhule
   file** (1000+ entities) — a naive per-polygon-per-segment layer-attribution
   loop was O(polygons × segments). Fixed with an STRtree spatial index and by
   discarding sub-threshold polygons before attribution. Re-verified: Dhule
   now extracts in 1.8s, Vadodara (the largest file, 2200+ closed shapes) in
   3.6s — both previously untimed because this bug didn't exist until the
   reconstruction feature was added, but it's a real fix, not a regression
   note.
4. **A malformed DXF (LWPOLYLINE entities missing required coordinate data)
   crashed with a raw Python traceback if it reached deep enough.** Added an
   automatic fallback to `ezdxf.recover` for spec-violations that are
   genuinely recoverable, and confirmed the API still returns a clean 422 with
   a specific message (not a 500) for the subset that truly aren't — verified
   with the actual broken file, which even `ezdxf.recover` correctly refuses.

Full regression re-run after all four fixes: Dhule (7 regions, 1.8s), Vadodara
(63 regions, 3.6s), the synthetic ezdxf file (1 region), and both internet
files (1 region each, one via reconstruction) all still pass. `theater.dwg`
(a raw AutoCAD working file, not a finished deliverable) still correctly fails
at DWG→DXF conversion — confirmed this is a genuine limitation of the free ODA
File Converter itself (`XData size exceeded`), not something fixable in this
codebase; the two real production Zoning Layout DWGs convert and extract fine.

**Honest answer to "can zoning be done on any provided floor plan":** yes for
real architectural CAD output with a discoverable boundary (explicit or
reconstructable from walls) — verified today on 5 independent real/external
files plus the 2 production Connplex files. No for files with corrupted
entity data, or DWGs whose embedded data exceeds what the free ODA converter
handles (a licensing/tooling question the original spec already flagged, not
a code gap).

## Update: PDF export now matches Connplex's real drawing format

The user supplied a real Connplex reference PDF (Keshav Landmark, Vadodara,
DRG ZL-01-R1) and asked the exported PDF to match its format, logo, and style.
`export_pdf.py` was rewritten to that exact structure: single portrait sheet,
floor plan on the left, and a right info column in the same order as the real
sheet — General Notes, Notes, Legends, Area Chart(Sq.Ft.)&Seat Chart (same
column set: LOCATION/AREA/LOUNGER/SOFA SLIDER/DUO LOUNGER/PREMIUM
RECLINER/TOTAL SEATS), Revisions log, Drawing Issued log with FOR
APPROVAL/FOR GFC checkboxes, Key Plan box, the project info block, the DRG
NO/TITLE/SCALE/DRAWN BY/CHECKED BY/DATE stamp, and a CONNPLEX SMART THEATRES
company block with their real address/contact info and a drawn approximation
of their yellow/black logo badge (no vector asset file was available to this
session, so it's a faithful redraw in their real brand colors, not a traced
copy). Verified by rendering to PNG and comparing side-by-side against the
real reference: found and fixed several label/content text-collisions and a
truncated table column in the process. Re-tested through the live Export PDF
button afterward — still a real 200 OK export end-to-end. See CLAUDE.md for
the honest gap that remains (exact vector logo artwork).

## Where this stands right now

The full normal-flow loop the product is supposed to provide is now real and
working end-to-end for an **arbitrary uploaded property**, not just the two
pre-baked reference drawings: upload a DWG/DXF → confirm what was detected →
enter requirements → run auto-layout → get real seat estimates → edit the result
on an interactive canvas → export PDF/DXF/DWG. All of it was built and verified
live in a browser this session, against files this session generated on the spot
(not just the Dhule/Vadodara demo data).

The legacy demo pipeline (Dhule/Vadodara, `/projects/:id/canvas`) still exists and
still works — kept as a reference/demo, reachable via a "View Reference Demo" link
— but it is no longer the primary flow. `/projects/:id/studio` (the new
`services/zoning-engine/` pipeline) is what "Go to Zoning Canvas" now opens.

Full technical detail on what was built, and exactly how each claim was verified,
is in `CLAUDE.md` ("What was built in this session" → Part 2). This file is the
forward-looking punch list.

## Verified working right now (tested live, this session)

- Real file upload via actual drag-and-drop (`DataTransfer`/`File` API) through
  the real UI, hitting a real multipart POST to `services/zoning-engine`, which
  really runs `ezdxf` parsing (and ODA DWG→DXF conversion when needed) on the
  uploaded bytes — proven on 3 independent files, including one dropped through
  the browser that the backend correctly rejected the first time (malformed) and
  correctly accepted the second time (fixed), with the real, specific ezdxf error
  shown to the user in between.
- Real geometry-review/confirm UI: boundary + every obstacle rendered as actual
  SVG polygons at their real coordinates (not a raster image), each with a
  Confirm/Ignore control; a zoning run is refused server-side until the boundary
  is confirmed.
- Real requirements form → real auto-layout run producing two genuinely different
  strategies (verified different room counts/sizes/seat totals on a real ~6,874
  sqft Dhule region, not cosmetic variants).
- Real seat counts and real feasibility results per candidate, using the same
  rules registry as the legacy pipeline.
- Real interactive canvas: drag-to-move and drag-to-resize work via actual pointer
  events and `getScreenCTM`-based coordinate transforms; an edit that would go
  outside the boundary or onto a confirmed obstacle is rejected server-side with
  the specific overlap in square feet, is confirmed (via direct API query) to
  never persist, and the canvas visually reverts (fixed a bug this session where
  it didn't). A valid edit persists and survives a full page reload, with
  circulation area and the Area & Seat Chart correctly recomputed.
- Real exports: PDF (rendered to PNG and visually inspected — real floor plan to
  scale, real Area & Seat Chart, real feasibility results, real title block with
  the actual project data and an incrementing revision number), DXF (read back
  with `ezdxf`, 28 real entities on correctly-named layers), DWG (verified with
  `file` as genuine AutoCAD 2018/2019/2020 format, produced via a real DXF→DWG
  ODA conversion).
- `tsc --noEmit` clean, `npm run build` succeeds, all three services (project on
  :3001, zoning-engine on :8000, vite on :5173) run together correctly.

## Priority backlog

### 1. Franchise-tier selection + fuller requirement inputs in the UI

`RequirementsStep.tsx` only asks for property type, max auditoriums, and an
optional franchise tier. The spec's full required-input list (§7 in the master
context: seat-mix percentage, foyer/F&B/circulation area *preferences* rather
than just engine defaults, number of entrances/exits, existing entrance/exit
preservation, floor height) isn't collected yet. The registry
(`franchise_tiers`, `support_zone_area_overrides_sqft` param already exists
server-side) supports most of this — it's a UI-only gap.

### 2. Production SPA routing

Confirmed this session (same pre-existing issue as before, on the new route too):
a cold navigation straight to `/projects/:id/studio` 404s on Vite's dev server;
in-app client-side navigation works fine. This is almost certainly fine under
`vite dev` for local work, but **must be checked before any real deployment** —
whatever serves the production `dist/` build needs an SPA fallback (serve
`index.html` for any unmatched path). Nginx/most static hosts need one line of
config for this; verify it's actually configured wherever this gets deployed.

### 3. Multi-region / multi-floor CAD sheets in the real pipeline

`cad_extraction.py` already returns multiple candidate regions when a sheet
contains more than one floor plan (verified against the real Dhule DXF — 7
regions found), and `GeometryReviewStep` already lets the architect switch
between them and confirm one — but `zoning-runs`/the editable layout are scoped
to a single `region_id` per project today. A project with a multi-floor sheet
currently only carries one floor's zoning result forward. Spec §3 decision #9
says single-floor-per-project is fine for v1 as long as the schema doesn't block
adding more later — worth confirming the current per-project (not per-region)
storage in `storage.py` doesn't quietly become that blocker as this gets built
out further.

### 4. PDF format matching — mostly done; one honest gap remains

**Update (third session):** `export_pdf.py` was rewritten to match the real
Connplex sheet structure/order/style exactly (see the update note at the top
of this file) — this used to be the biggest gap and now isn't. What's left:
- The logo is a drawn approximation (yellow/black, right wordmark/colors) —
  not their actual vector artwork. Drop their real logo file (SVG/PNG) into
  `services/zoning-engine/` and swap `_draw_logo()` in `export_pdf.py` for an
  image draw (`reportlab.lib.utils.ImageReader` + `c.drawImage`) to close this
  the rest of the way — that's a ~15-minute change once the asset exists.
- Fonts are Helvetica (reportlab's built-in), not whatever exact typeface
  Connplex's drawings use — close enough visually, not byte-identical.
- `export_dxf.py`'s DWG/DXF output still doesn't attempt exact layer-name/
  block-structure parity with Connplex's AutoCAD templates (spec §7.3's own
  acceptance test needs their real DWG template, not just the reference PDF).

### 5. `config over code` cleanup in the legacy `cadService.ts`

Unchanged from before this session — `min_area_sqft` is still computed inline in
`apps/web/src/services/cadService.ts` (the *legacy* demo-pipeline service) instead
of read from the registry. Low effort; only affects `/canvas`, not `/studio`
(which already reads registry-driven minimums throughout
`services/zoning-engine/`).

### 6. Minor: stale collision-hint banner

`EditableCanvas.tsx`'s live orange "Overlap / out of bounds" hint (client-side,
cosmetic — separate from the real server-side validation, which is correct) was
observed once this session staying visible slightly longer than expected after a
rejected drag. The underlying data was never wrong (confirmed via direct API
query each time) — this is purely a UI-hint staleness edge case, not a
correctness issue. Worth a closer look if it recurs, not urgent.

### 7. Background/async zoning runs

`POST /zoning-runs` runs synchronously today (~1–2s on the floor sizes tested).
Spec §58 calls for background job processing for anything long-running. Fine at
today's scale; revisit if candidate generation gets slower (e.g. a proper
constraint solver instead of the current greedy packer) or floor plates get much
larger.

## Open items still requiring a Connplex decision (unchanged from spec §10)

1. APS/ODA licensing approval for production-grade DWG interop — this session's
   work confirms the *free* ODA File Converter path genuinely works for both
   DWG→DXF (import) and DXF→DWG (export) at prototype scale; may reduce urgency,
   but production terms/support still need sign-off for scale/reliability
   guarantees.
2. Franchise tier naming: "Express" (brochure) vs. "Smart" (ROI sheet) —
   unresolved, encoded in the registry with an explicit `naming_conflict_note`.
3. Whether 55–60 seats/screen (SOP) and 60 seats/screen (Feasibility Manual)
   should both gate, or be reconciled into one number — registry keeps them
   separate per CLAUDE.md governance; a Connplex decision could collapse this.
4. Which franchise tier governs a given project (user-selected vs. inferred vs.
   sales-negotiated) — still open, affects the foyer:screen ratio target used by
   `layout_engine.py`.
5. Whether "Net Usage Area" is a second export type for every project or was
   Dhule-specific — still open, affects export template scope (backlog item 4).

## How to verify this status yourself

```bash
cd services/project && npm start &
cd services/zoning-engine && python3 -m uvicorn main:app --port 8000 &
cd apps/web && npm run dev
# open http://localhost:5173, log in as test@connplex.com / password123,
# create or open a project, complete intake, click "Go to Zoning Canvas",
# upload any real .dwg/.dxf (docs/reference/ has three), confirm the detected
# boundary/obstacles, submit requirements, run zoning, pick a candidate, try
# dragging a room, then use the Export buttons in the right sidebar.
```
