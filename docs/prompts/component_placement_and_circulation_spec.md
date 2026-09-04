# Component Placement & Circulation Upgrade — Spec for a Future Session

## 0. How to use this document

This is a **prompt/spec for a future AI coding session**, not a description of
work already done. It was produced by studying two real, dimensioned Connplex
zoning drawings the user shared (annotated renders of a 3-screen multiplex —
Screen 1/44 seats, Screen 2/58, Screen 3/63, "NET USAGE AREA 7,030 SQ FT") and
cross-referencing them against what `layout_engine.py` actually does today.
The same class of drawing already lives in this repo at `docs/reference/`
(`1022_MARUTI NANDAN...DHULE...dwg`, `1045- KESHAV LANDMARK_VADODARA...dwg`,
`theater.dwg` — the first two convert cleanly via
`services/cad-interop/convert.py`; `theater.dwg` currently fails ODA
conversion with "XData size exceeded", a pre-existing, unrelated issue worth
noting but out of scope here). A future session should **open one of these
converted DXFs directly** (`python3 -c "import sys; sys.path.insert(0,
'services/cad-interop'); from convert import convert; convert('docs/reference/1045-
KESHAV LANDMARK_VADODARA ,GUJRAT_ZONING LAYOUT_20.05.2026.dwg', 'dxf',
'<scratch dir>')"` then read it with `ezdxf`) rather than relying solely on
this document's prose description of the two screenshots, since the real
geometry (exact door widths, corridor widths, column grid) is more precise
than anything transcribed here.

The user's own framing for this task: **treat the current SOP/registry
content as a soft limit, not a hard boundary.** Where the SOP is silent,
reason like a real architect and implement it, tagging the result
`ENGINEERING_ASSUMPTION` / `REQUIRES_APPROVAL` in `rules_registry_v1.json`,
exactly the convention already used for `SIDE_CLEARANCE_ASSUMPTION_FT`,
`SUPPORT_ZONE_CIRCULATION_RESERVE_RATIO`, etc. Don't block real design-quality
improvements on the SOP extract being incomplete — flag the gap and proceed.

## 1. What already exists (read before touching anything)

The placement engine is `services/zoning-engine/layout_engine.py` (860 lines).
It is already more sophisticated than a naive rectangle-packer:

- `compute_usable_area()` / `_scan_place_with_fallback()` /
  `_enclosed_obstacle_area()` — a **two-tier obstacle model**: a strict
  polygon with every confirmed obstacle subtracted, and a column-tolerant
  fallback polygon (obstacles minus `COLUMN`) used only when no
  obstacle-free placement exists, scored by how much of the room's own area
  the enclosed column eats.
- `_has_sightline()` + `prefer_fn` in `place_single_zone()` — a real
  line-of-sight model already drives two qualitative SOP rules
  (`WASHROOM_ADJACENCY_RULE`: not visible from foyer; `FNB_ADJACENCY_RULE`:
  visible from entry) as *soft* scoring preferences, not hard constraints.
- `estimate_column_grid_spacing()` — clusters confirmed `COLUMN` obstacle
  centroids into grid lines along X/Y, refusing to fabricate a spacing from
  fewer than 2 distinct lines per axis. **Currently only feeds the
  after-the-fact `VR_COLUMN_GRID_WIDTH/LENGTH_EXISTING` viability check** —
  it does not yet influence placement itself. That's the single biggest gap
  identified in §4.2 below.
- `validate_rooms()` — checks overlap, boundary containment, and
  obstacle-collision (with the same column tolerance). **It has no
  connectivity/reachability check today** — a room can validate as "fine"
  while being sealed off from any door or corridor. That's the biggest gap
  in §4.1.
- `rules_registry_v1.json`'s `planning_norms` already encodes real,
  cited numbers: `AISLE_CLEARANCE_FT`/`CENTRAL_AISLE_MIN_FT` = 3.5ft,
  `SCREEN_TO_BACK_WALL_MIN_FT` = 3.0ft, `FOYER_REQUIRED_FUNCTIONS` (Box
  office, Waiting, F&B, Washrooms, Electrical room, Server room, Store
  room — SOURCE_BACKED, §4.4/§9), and `FIRST_ROW_DISTANCE_RULE`
  (`first_row_distance_ft >= screen_width_ft`) which is **currently
  `SOURCE_BACKED_NOT_EVALUABLE`** because intake never captures a
  `screen_width_ft` field. That single missing field blocks real
  screen-geometry reasoning — see §4.3.
- `auditorium_presets` (4 tiers, 35/60/90/125 seats) already carry real
  measured width/length ranges from an executed Connplex file, not
  invented numbers — but nothing about screen aspect ratio, throw
  distance, or viewing angle. Presets are purely a footprint-size lookup.
- Room types currently placeable: `FOYER`, `BOX_OFFICE`, `F&B`,
  `WASHROOM`, `BOH` (a single lumped "Electrical / Server / Store" zone —
  see §4.1's finding that the reference drawings model these as separate,
  independently-located rooms). No `PASSAGE`/`CORRIDOR` room type exists;
  circulation is currently just unbuilt leftover area governed by
  `SUPPORT_ZONE_CIRCULATION_RESERVE_RATIO` (0.18, `ENGINEERING_ASSUMPTION`),
  not a real, connected, dimensioned corridor.
- No `Door`/`Entry`/`Exit` object exists anywhere in `models.py` or the
  room schema. Entry/exit today is a single project-level
  `entry_point`/`exit_points_ft` pair (used only to bias which side the
  foyer/F&B faces via `_entry_exit_scan_flip`), not a per-room door.

## 2. What the reference drawings show that the current engine doesn't model

Both reference drawings (and the two screenshots reviewed this session)
share a consistent real-world pattern worth encoding as a design language,
not just an SOP citation:

1. **Two separate circulation systems, not one.** A public/front-of-house
   route (main entry → central Foyer, with Box Office and F&B directly
   visible from it, per the existing sightline rules) is distinct from a
   dedicated perimeter **egress passage** (labeled "2514 MM WIDE PASSAGE" in
   the screenshots, running the full width of the building at the rear/side)
   that each auditorium's **exit** discharges into directly — never back
   through the Foyer/F&B/Box Office. The engine today has no notion of two
   distinct corridor systems; `SUPPORT_ZONE_CIRCULATION_RESERVE_RATIO`
   treats all circulation as one undifferentiated reserve.
2. **Every auditorium has its own labeled ENTRY and EXIT**, positioned on
   the wall nearest the shared circulation core, not on the far/rear wall.
   The projector room sits on the *opposite* wall from the entry/exit
   cluster — i.e. audience enters/exits near the screen-adjacent end,
   projection booth is at the true rear. This is the opposite of a naive
   assumption ("exit should be far from entry"); it matches real multiplex
   practice (minimize walking distance from the public route, keep the
   projection booth against the building's structural rear wall).
3. **The vertical-circulation core (stairs, lifts, shafts) sits inside or
   directly against the Foyer**, not as a separate zone the Foyer routes
   around. This is exactly the "confirmed COLUMN may be enclosed by a
   support zone" logic already in `_enclosed_obstacle_area`/fallback
   placement, generalized: the whole services core (stairs + lifts +
   shafts), not just a bare structural column, gets wrapped by the Foyer.
4. **Electrical Room is placed front-and-public**, directly off the main
   circulation, near an exit — not hidden in a back corner as
   "Back-of-House" naming might suggest. Placement is driven by where the
   incoming utility service enters the building, which the engine has no
   way to know today (no such input exists) — flag this as an
   `ENGINEERING_ASSUMPTION` default (place adjacent to the nearest exterior
   wall/exit) with a note that it should defer to a real utility-entry
   point once intake captures one.
5. **Column-grid dimension strings are present in the DXF itself** (visible
   as `5865`, `4127`, `6980`, `4468`, `4672`, `5361` mm callouts in the
   dimensioned screenshot) — real structural bay spacing, carried as DXF
   `DIMENSION` entities, not just inferred from column obstacle positions.
   `cad_extraction.py` already has DIMENSION-entity transform handling
   (per the transform-composition work from the orientation-fix session)
   but does not currently extract dimension *values* as structured column-
   grid data — only as generic linework. That's a second source of grid
   spacing beyond `estimate_column_grid_spacing`'s column-centroid
   clustering, likely more reliable when present, worth reading if it's
   there before falling back to centroid clustering.

## 3. Goal

Make the auto-layout engine place every component — auditoriums, their
doors, the foyer, its required sub-functions, and the circulation that
connects them — the way a real cinema architect would on a real structural
grid, instead of independent rectangles that merely avoid overlapping each
other and hard obstacles.

## 4. Objectives

### 4.1 Foyer, passage, accessibility, and per-component entry/exit

- **Add a `Door` concept** to the room schema (`models.py` — check its
  current `Room`/`EditableLayout` shape before adding fields): each door is
  `{room_id, wall: 'N'|'S'|'E'|'W' (or an edge index), offset_ft, width_ft,
  kind: 'ENTRY'|'EXIT'|'BOTH'}`, positioned along the room's own polygon
  edge, not a free-floating point. Auditoriums get at least one ENTRY and
  one EXIT door (may be adjacent on the same wall for small presets, must be
  on the circulation-facing wall per §2 finding 2); size doors from occupant
  load once an egress-width-per-person figure exists in the registry
  (currently doesn't — add as `ENGINEERING_ASSUMPTION`/`REQUIRES_APPROVAL`,
  do not invent a code-compliant number without flagging it as such).
- **Add `PASSAGE`/`CORRIDOR` as a real, placeable room type**, not leftover
  reserve area. Minimum width: the SOP-sourced `CENTRAL_AISLE_MIN_FT` (3.5ft)
  governs in-auditorium seating aisles specifically and should **not** be
  reused for an egress corridor width — add a distinct
  `EGRESS_PASSAGE_MIN_WIDTH_FT` norm (the reference drawings' 2514mm ≈
  8.25ft is real evidence, but a single sample isn't a code citation — add
  it as `ENGINEERING_ASSUMPTION`/`REQUIRES_APPROVAL` referencing this
  observed value, not `SOURCE_BACKED`, unless the SOP text itself has a
  number).
- **Model two distinct circulation graphs**, matching §2 finding 1: a
  front-of-house route (entry → foyer → each auditorium's ENTRY door,
  passing Box Office/F&B per their existing visibility rules) and an egress
  route (each auditorium's EXIT door → perimeter passage → a building
  exit), and keep them from crossing through unrelated enclosed rooms.
- **Add a real connectivity/reachability check to `validate_rooms()`**: for
  every room with a door, verify a corridor-or-foyer polygon touches (or is
  within some small tolerance of) that door's position — i.e. every
  component is actually reachable, not just non-overlapping. This is the
  concrete, testable form of "accessibility of each component."
- **Split `BOH` into placeable sub-rooms** (`ELECTRICAL`, `SERVER`,
  `STORE`) as an *optional* mode (keep the current lumped `BOH` as the
  default — this is a real scope increase, not a drop-in replacement),
  since the reference drawings show these placed independently rather than
  as one lumped block, and Electrical specifically defies a "hide it in
  back" default (§2 finding 4).

### 4.2 Column policy — when to include, when not, how much

- **Use `estimate_column_grid_spacing()` (and, if pursued, DXF `DIMENSION`
  values per §2 finding 5) to drive placement, not just post-hoc
  viability scoring.** Once a real grid is detected (its own existing
  "refuse with <2 lines" conservatism is correct and should stay), snap
  candidate room edges in `_scan_place`/`_scan_place_best` to the nearest
  grid line or a fixed sub-bay offset, the way a real structural design
  would — rooms in the reference drawings visibly align to bay lines, not
  arbitrary positions.
- **Tolerance should differ by room type, not be one global constant.**
  Keep `_enclosed_obstacle_area`'s existing tolerant-fallback mechanism, but
  tune the acceptance threshold per room type instead of the current single
  implicit tolerance: essentially zero tolerance inside an auditorium's
  actual seating zone (a column mid-row blocks sightlines and seats — real
  design routes around this, not through it; at most one column may be
  tolerated, and only at the very rear/side of the seating zone, never
  mid-bowl), much higher tolerance for FOYER/F&B/circulation-core rooms
  (§2 finding 3 — wrapping the services core is normal and expected there).
- **Don't hardcode a fixed max column count.** Cap by *area impact*
  (already the right mechanism via `_enclosed_obstacle_area`), scaled per
  room type as above, rather than an arbitrary "N columns allowed" number.
- Obstacle *classification* (structural vs. non-structural) is already
  handled upstream in `cad_extraction.py`'s layer-hint heuristics — no
  change needed there; this objective is entirely about what the placement
  engine *does* with an already-confirmed `COLUMN`.

### 4.3 Best fit for the screen (and the auditorium around it)

- **Capture `screen_width_ft` at intake** (or derive a default from the
  matched `auditorium_presets` tier if the user doesn't override) —
  this single missing field is what currently keeps `FIRST_ROW_DISTANCE_RULE`
  `SOURCE_BACKED_NOT_EVALUABLE` in the registry. Wiring it through
  `RequirementsStep.tsx` → intake → `feasibility_engine.py` turns an
  already-cited SOP rule into a real, evaluated check instead of a
  permanently-skipped one.
- **Add real screen-geometry reasoning, not just an area/dimension-range
  match.** Today `_place_auditoriums` picks a preset by seat count and fits
  its `width_min_ft`/`length_min_ft..length_max_ft` box; it has no concept
  of screen aspect ratio, throw-distance-to-width ratio, or viewing angle
  from the worst-case seat. At minimum: derive a target screen width from
  the room width (screen width is conventionally somewhat less than the
  room's clear width, to leave side masking/clearance — this needs a real
  ratio; don't invent one silently, add it as
  `ENGINEERING_ASSUMPTION`/`REQUIRES_APPROVAL` in `planning_norms` the same
  way `SIDE_CLEARANCE_ASSUMPTION_FT` was added), then use
  `SCREEN_TO_BACK_WALL_MIN_FT` (already SOURCE_BACKED) and the new
  `FIRST_ROW_DISTANCE_RULE` together to validate that the chosen room depth
  actually gives a legible first row, not just enough total area for the
  seat count.
- **Orient the screen wall toward the circulation-facing side**, matching
  §2 finding 2 (projector at true rear, entry/exit near the public route) —
  today's screen-wall indicator graphic in `EditableCanvas.tsx` (added in
  the prior round) draws a geometrically-derived indicator on the room's
  *top* bounding-box edge unconditionally; once real doors exist (§4.1),
  drive the screen-wall side from the door positions instead of an
  assumed top edge, so the graphic and the actual design intent match.
- **Seat-row geometry (existing `seat_engine.py`/the seat-row rendering
  added this round) should key off the same screen-wall side**, so rows
  run perpendicular to the real screen wall, not an assumed one — currently
  low-risk since seat rows are drawn spread evenly across the room without
  reference to which wall is "front," which happens to look right only
  because the current screen-wall indicator also always assumes the top
  edge. Fixing §4.1's door model removes that coincidental coupling, so fix
  both together rather than independently.

## 5. Implementation strategy (suggested order — re-plan if scope changes)

1. **Data model first**: add `Door`, `PASSAGE` room type, and
   `screen_width_ft` to whatever `models.py`/intake schema currently holds
   rooms/requirements. Nothing downstream can be built without these.
2. **Registry entries**: add `EGRESS_PASSAGE_MIN_WIDTH_FT`, an
   egress-width-per-person figure, and a screen-width-to-room-width ratio to
   `planning_norms`, all tagged `ENGINEERING_ASSUMPTION`/`REQUIRES_APPROVAL`
   per the existing convention — do this before writing code that consumes
   them, so the code reads real registry values from day one instead of
   inline constants that need a later migration.
3. **`layout_engine.py`**: implement the two-circulation-graph model and
   grid-snapping in placement; extend `validate_rooms()` with the
   reachability check.
4. **`feasibility_engine.py`**: wire up the now-evaluable
   `FIRST_ROW_DISTANCE_RULE`.
5. **Frontend**: `RequirementsStep.tsx` (capture `screen_width_ft`),
   `EditableCanvas.tsx` (draw real doors; derive the screen-wall indicator
   and seat-row orientation from door position instead of assumed top
   edge), `ExportPanel`/`export_dxf.py`/`export_pdf.py` (render doors and
   passages in exports — check both files' current obstacle/room drawing
   loops for the right insertion point).
6. **Tests**: extend `services/zoning-engine/tests/test_layout_engine.py`
   with cases for grid-snapping, per-room-type column tolerance, and the
   new reachability check — follow the existing pattern of a synthetic
   `RECT_BOUNDARY` fixture, and validate each new test is a real regression
   guard the same way this session's orientation tests were validated
   (break the fix, confirm the test fails, restore it).

## 6. Explicitly out of scope for a first pass

Real occupant-load/egress-code compliance (actual fire-code egress-width
tables, travel-distance-to-exit limits) — the objectives above ask for the
*data model and placement logic* to support doors, passages, and
reachability; making the numbers legally code-compliant for a specific
jurisdiction is a separate, much bigger effort requiring a real code
citation, not an assumption this session/next session should invent.
Flag every number in this category as `REQUIRES_APPROVAL` rather than
guessing at compliance.
