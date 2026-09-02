# STATUS

Last updated: 2026-09-02 (fourteenth session — full-project audit + priority security fixes)

## Update: full audit, three real security bugs fixed

Ran a full audit of the codebase (app-breaking bugs, incomplete/stubbed
features, backlog verification, code quality, test coverage) at the user's
request, then fixed the findings in priority order: critical bugs first,
feature completeness second, code quality third.

**Confirmed still accurate**: `tsc --noEmit` clean, no dead legacy-pipeline
references remain, config-over-code is respected in the live pipeline. **Zero
automated tests exist anywhere in the repo** (no test files, no CI config) —
every fix below was verified manually (server boot, `tsc --noEmit`, `python3
-c "import main"`), not by a regression suite. This is the single largest
gap in engineering rigor at this point and should be next after this list.

**Critical — fixed this session:**

1. **Session cookie was a forgeable, unsigned plaintext user ID.**
   `services/project/src/db.js` stores real users, but `cookie-parser` was
   initialized with no secret (`services/project/src/index.js`), and both
   `middleware.js`'s `requireAuth` and `auth.js`'s `GET /me` trusted
   `req.cookies.session_user_id` at face value — a client could set that
   cookie to any user's UUID and be fully authenticated as them with zero
   password check. **Fixed**: `cookieParser(process.env.COOKIE_SECRET || …)`
   now signs the cookie; `SESSION_COOKIE_OPTIONS` sets `signed: true`; both
   `requireAuth` and `GET /me` now read `req.signedCookies` instead of
   `req.cookies`, so a tampered/unsigned cookie is rejected outright.
   `COOKIE_SECRET` must be set in any real deployment (the fallback is
   dev-only and clearly marked as such).
2. **Cross-tenant data exposure**: `requireAuth` was already correctly wired
   onto the whole projects router (a prior session's fix, still in place),
   but none of the actual queries in `services/project/src/routes/projects.js`
   filtered by `created_by` — any authenticated user (including a brand-new
   self-registered one) could list, read, edit, or delete every other
   client's projects, not just their own. **Fixed**: `GET /`, `GET /:id`,
   `PATCH /:id`, and `DELETE /:id` all now scope to `created_by = req.user.id`
   unless the requester is an admin (existing `is_admin` flag), returning 404
   rather than 403 on someone else's project id so existence isn't leaked.
3. **`select-candidate` endpoint had a misleading schema**: `main.py`'s
   `POST /layout/select-candidate` declared its body as `ZoningRunIn` (field
   `region_id`) but actually consumed that value as a candidate id — a
   natural `{"candidate_id": …}` payload was silently ignored by Pydantic and
   produced a confusing 404 instead of a validation error. **Fixed**: added a
   dedicated `CandidateSelectIn` model with a correctly-named `candidate_id`
   field; updated the one caller (`apps/web/src/services/zoningEngineApi.ts`)
   to match.

**Still open, not fixed this session** (see Priority backlog below for the
pre-existing items; these are new/reprioritized based on the audit):

- No automated test suite or CI at all — highest-priority follow-up now that
  the critical auth bugs are closed.
- `services/zoning-engine` has no authentication and defaults to
  `allow_origins=["*"]` when `FRONTEND_ORIGIN` is unset — fine on the Render
  deployment (env var is set there) but wide open on any other deployment
  target. Needs the same kind of explicit lockdown the project service now
  has, or at minimum a startup warning when the env var is missing.
- `data.sqlite` (bcrypt-hashed demo/seed users) is committed to git — not a
  live secret leak today, but a bad habit that will become a real one the day
  seed data is replaced with real client data without updating `.gitignore`.
- `ai_zoning_engine.py` hardcodes `MODEL_ID = "claude-opus-5"` with no env
  override — a single point of failure if that model id is ever retired.

## Update: standard flow is now upload -> auto-generated, exportable layout, with zero required clicks

Direct response to client feedback: the flow required an architect to
individually Confirm/Ignore every detected obstacle (443 of them on Dhule's
largest region), then click through a candidate-picker, before ever seeing a
layout — real, reported friction, not a hypothetical. The ask: CAD in,
boundary/columns/walls/obstacles identified correctly, available space
computed, a real auto-generated layout out, exportable — with manual editing
available as an option, never required for the standard path.

- **`cad_extraction.py`**: interior wall shapes (closed shapes on a wall/
  partition-hinted CAD layer that aren't the region's own outer boundary) are
  now classified `WALL` instead of falling into the generic
  `UNCLASSIFIED_OBSTACLE` bucket — same evidence-based layer-hint technique
  already used for COLUMN/DOOR/WINDOW/STAIRCASE/etc. Verified on the real
  Dhule DWG: 83 shapes on its largest region that were previously
  unclassified are now correctly identified as WALL.
- **`GeometryReviewStep.tsx`**: every detected obstacle now pre-confirms
  (treated as real, avoided) instead of requiring an individual click — the
  conservative direction, since over-avoiding a shape costs a little usable
  area while silently ignoring a real one risks a room drawn on top of an
  actual wall or column. When the boundary itself is clean (no extraction
  warning), the screen shows what was detected and auto-proceeds after a
  short pause. A boundary that carries a warning — the same implausible-size/
  reconstructed-with-no-evidence cases the prior session's hang fix
  introduced — always stops for a human, in every mode; that gate is never
  skipped, verified directly against `theater_clean.dxf`'s real 16M+ sqft
  frame candidates. A "Review Detected Geometry Manually" escape hatch is
  always available.
- **`RunStep.tsx`**: auto-runs on mount and auto-selects the higher-seat-
  count candidate (the same choice the backend's initial-layout write
  already makes) instead of requiring a "Run Zoning" click and then a "Use
  This Layout" click.
- **`ZoningWorkspace.tsx`**: added a "Layout Strategy" switcher in the edit
  sidebar so the alternate strategy (max seats/screen vs max screen count)
  stays reachable after landing on the auto-generated layout, rather than
  being a blocking step beforehand.
- **`types/live.ts`**: fixed `Obstacle.classification`, which was still
  typed as only `COLUMN | UNCLASSIFIED_OBSTACLE` — a real, pre-existing gap
  (the backend has emitted DOOR/WINDOW/STAIRCASE/WASHROOM_FIXTURE/FURNITURE
  since a prior session) — while adding WALL.

Verified against the real Dhule DWG (7 regions, up to 443 obstacles) and the
real `theater_clean.dxf` (59 regions, including the implausible sheet-border
frames from the prior session's hang fix): full upload -> auto geometry
review -> defaulted requirements -> auto-run -> auto-select -> PDF export ran
end-to-end with zero required clicks beyond the two ordinary "continue"
actions, producing 666 seats across 4 auditoriums on Dhule's largest region —
identical to the historical baseline, confirming no regression. `tsc
--noEmit` clean. Merged straight to `master` and pushed (this change doesn't
touch persistence, so it isn't blocked on the pending Postgres migration on
`dev` — see below).

**What this does not change**: the Requirements step (property type,
franchise tier, clear height, entrance) is still a real, brief user input —
those are business decisions, not something a CAD file can supply, and
leaving them unmarked already uses sensible defaults/skips the rules that
need them rather than guessing. Manual editing (drag/resize, add/delete
zones, per-room seat mix) is untouched and still fully available from the
same EDIT screen the auto-generated layout lands on.

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

## Update: deployed to Render, fixed a real "Run Auto-Layout" hang

The app is now live: pushed to GitHub (`Trayz72/connplex-zoning-studio`) and
deployed to Render's free tier as three services (`connplex-web` static
site, `connplex-project`, `connplex-zoning-engine`). Before that could work
at all, three real cross-origin issues needed fixing — see the commit
"Prepare for cross-origin hosting" for detail (env-driven API base URLs,
`sameSite:'none'` cookies for cross-site auth, locked-down CORS). All
verified working live: login, dashboard, and the deployed frontend calling
both deployed backends.

### Fixed: a real "stuck on Running..." bug, found from a live user report with real files

The user hit an actual hang on the deployed app — "Run Auto-Layout" spun on
"Running..." forever on a real uploaded file. Reproduced locally with the
exact files (`theater.dxf`/`theater_clean.dxf`) rather than guessing, and
found two compounding real bugs:

1. **The boundary-detection heuristic picked a drawing sheet-border/title-
   block frame instead of the real building outline.** The file's
   `$INSUNITS` was unspecified, and "largest closed polyline" — which
   normally works fine — latched onto a frame several **million** square
   feet in size (one candidate was 16.8M sqft; for scale, that's larger
   than the Pentagon). Worse, the nesting-collapse logic then treated the
   real building outline, nested inside that frame, as suppressed rather
   than its own candidate. Fixed: an oversized candidate (>500,000 sqft,
   a deliberately generous bound — even IKEA's biggest stores are under
   that) no longer suppresses real candidates nested inside it, gets
   flagged `confidence: low` with an explicit on-screen warning explaining
   what likely happened, and is sorted after plausible-sized regions so an
   architect doesn't land on it by default. Also fixed a real, separate gap
   found while building this: the backend already computed this kind of
   warning `note` field for boundaries (previously only for reconstructed-
   from-line-segments boundaries) but **the frontend never rendered it
   anywhere** — added it to `GeometryReviewStep.tsx`, and fixed the
   TypeScript type, which was missing the `note` field and `'low'` as a
   valid confidence value entirely.
2. **Even with a huge boundary confirmed, the auto-layout grid-scanner had
   no upper bound on how long it could run.** At the fixed `GRID_STEP_FT`
   of 2.0 ft, a multi-million-sqft bounding box means millions of grid
   positions, each doing a real shapely polygon containment check — for
   multiple auditorium presets, times up to 4 auditoriums, times 2
   strategies. This is what "Running..." forever actually was. Fixed with
   an adaptive grid step (`_grid_step_for_bbox`) that scales up once a
   boundary would need more than 40,000 cells, so a pathological boundary
   degrades to a coarse, fast, honest result instead of running
   indefinitely — a defensive fix that holds regardless of *why* a boundary
   might end up huge, not just this specific root cause.

Verified, not assumed: re-ran the exact same file that hung before. The
465,659 sqft region (now offered first) completes in **0.26s**. Even the
worst case — deliberately confirming one of the 16.8M sqft frame regions
despite the warning — now completes in **1.7s** instead of hanging.
Re-verified the real Dhule file still produces the exact same seat counts
as every prior session (666/240 seats) — no regression on the normal case.

## Update: real selection-persistence bug, and color-coding removed from CAD/DXF/DWG + canvas

The user reported that selecting a room to resize/move it "should be simple
and bug free" — implying it wasn't. It wasn't: a real, reproducible bug.

### Fixed: a room never actually stayed selected

`EditableCanvas.tsx`'s SVG had `onClick={() => onSelectRoom(null)}` on the
whole canvas, meant to deselect on a background click. But clicking a room
fires `handlePointerDown` first (which calls `stopPropagation()` on the
**pointerdown** event and selects the room) — `stopPropagation()` on
pointerdown does **not** stop the separate, later **click** event the
browser generates from that same pointerdown+pointerup pair, and click
bubbles independently up to the SVG regardless. So every room-select click
immediately triggered the SVG's own `onClick` right after, deselecting
whatever was just selected. Since resize handles only render when
`isSelected`, this meant they'd flash in and vanish — matching exactly what
was reported. Fixed by moving the deselect logic onto `onPointerDown`
instead of `onClick`: a pointerdown that reaches the SVG's own handler can
only have originated on the background (any pointerdown starting on a room
or handle already calls `stopPropagation()`, so it never reaches this
handler at all), so this is not a mixed-event-type footgun the way the
original was.

Verified properly, not just by reading the diff: dispatched the exact
pointerdown→pointerup→click sequence via JS against a real room element
and confirmed 8 resize handles remained in the DOM afterward (previously
this exact sequence removed them); then did a real mouse-driven test in
the browser — selected an auditorium, dragged a corner handle to resize it
(65×45 → 88×45 ft, 162 → 225 seats, confirmed persisted server-side via a
direct API read, not just the UI), attempted a move onto confirmed
obstacles (correctly rejected with the real overlap amounts, reverted
cleanly, selection stayed intact throughout — the existing collision
validation was never broken, it just couldn't be reached before because
nothing stayed selected long enough to drag).

### Removed: per-room-type color coding from CAD export and the canvas — kept in the PDF

Asked to remove color from "CAD" so exports look professional. Before
changing anything, checked what the DXF/DWG export actually did (a
per-layer AutoCAD color index — not a solid fill, already reasonably
standard practice) and, since the whole point of this export format was
always to match Connplex's real drawings, went and found the actual real
reference PDF in this session (`1045- KESHAV LANDMARK...` — the same one
this whole export pipeline was built against) to check whether color was
actually part of "professional" here before guessing. **The real Connplex
drawing itself uses colored room fills** — sent it to the user directly
rather than assume. Given that, asked two scoped follow-up questions
instead of applying one blanket answer: keep the PDF colored (it now
genuinely matches Connplex's real deliverable — the point of the feature),
but strip color from the DXF/DWG file and the editing canvas.

- `export_dxf.py`: every layer (`EXISTING-BOUNDARY`, `PROPOSED-AUDITORIUM`,
  etc.) now uses ACI color 7 (AutoCAD's default black/white foreground) —
  differentiation is by layer *name* only, which is how a real architect
  toggles/isolates room types in AutoCAD anyway, not a pre-baked color that
  might clash with their firm's own layer standard. Verified by reading
  the generated DXF back with `ezdxf` and confirming every layer's
  `dxf.color` is 7 — not by eyeballing a render.
- `EditableCanvas.tsx`: rooms render as a single neutral gray box
  (`#8b949e`) regardless of type — identified only by their label, exactly
  like a real monochrome CAD drawing relies on labels, not memorized
  colors. Verified via a live DOM query that only one fill color exists
  across every room polygon now (previously six, one per room type).
- `export_pdf.py`: **unchanged**, deliberately — still uses the pastel
  `ROOM_FILL` palette, now confirmed correct rather than assumed, since it
  matches what Connplex's own real drawing does.

## Update: deployment prep + all four remaining spec milestones (M2, M6, M9, M10)

Triggered by a DevOps-focused ask: can this be hosted on Render.com, what's
the directory structure, is DXF/DWG really supported, and — after that —
build out every milestone that wasn't done yet. Full detail (Render
feasibility, DWG/Xvfb requirement, directory map) is in the new
**[DEPLOYMENT.md](DEPLOYMENT.md)**, not repeated here. This section covers
the milestone work and the production-readiness cleanup.

### Production-readiness cleanup

- **Unified the color palette.** The interactive canvas and the PDF export
  used completely uncoordinated colors for the same room types (washrooms
  purple on-screen, blue in the PDF; back-of-house gray on-screen, pink in
  the PDF). One coordinated hue family now, saturated for the dark canvas,
  pastel for the printed PDF, scoped to exactly the room types the pipeline
  produces.
- **Removed real dead weight**: two broken legacy test scripts referencing
  routes that no longer exist, a stale "View Reference Demo" link to the
  deleted `/canvas` route, and a symlink bundling **39MB of frozen legacy
  demo data into every production frontend build** for no reason — `dist/`
  went from 39MB to 252KB.
- **Fixed a real spec-compliance gap**, found by testing it directly: a
  project with incomplete intake data could be reached at
  `/projects/:id/studio` via direct URL with zero gate — the intake page
  only ever disabled a button, it never actually blocked the route.

### M2 — Rules/Config admin UI (was a real, unimplemented gap — now done)

Built `/admin/rules`: a real CRUD UI over all 5 registry categories (seat
types, auditorium presets, franchise tiers, planning norms, viability
rules), each record editable as raw JSON with its full provenance
(`source`, `approval_status`) visible, not hidden behind a dumbed-down form.

The write path deliberately lives in `services/project` (`routes/
rulesConfig.js`), not `services/zoning-engine`, even though the registry
file itself is read by the zoning engine — because `services/project` has
real admin auth and `services/zoning-engine` has none by design. Putting a
write endpoint on the auth-less service would have meant anyone who could
reach it could rewrite business rules with zero login. Every save writes a
timestamped backup of the whole file first (a basic safety net, not full
RuleSet version history, which is a deliberately bigger, separate model for
zoning-run inputs per the spec).

Fixed a real bug found while building this: `rules_registry.py`'s cache
never invalidated, so an edit — even by hand-editing the JSON file directly
— would silently not take effect until the zoning-engine process was
restarted. Now checks the file's mtime on every load, so a change made by
either service (or a human editing the file) takes effect on the very next
request, no restart needed. Verified end-to-end in the browser: edited a
real seat-type's `notes` field through the admin UI, confirmed the change
landed on disk with a backup written, and confirmed a fresh read via
`rules_registry.py` (simulating the running zoning-engine) saw the new
value immediately.

### M6 — Adjacency-aware auto-layout (was a real, unimplemented gap — now done)

The SOP's actual rules (§4.4/§9, reproduced in spec §2.8) are: "Foyer (at
main entry level)...", "F&B: visible from entry...", "Washrooms: ... not
directly visible from foyer." Implementing these honestly required facing a
real gap first: **nothing in this codebase has ever had a concept of where
a building's entrance is** — confirmed by grep, not assumed. CAD extraction
doesn't detect doors. Rather than invent a plausible-sounding rule (e.g.
"assume the entrance is on the boundary's longest edge"), which the
project's own anti-hallucination principle rules out, added a real way for
the architect to provide this — a click-to-mark entry-point picker on the
real confirmed boundary outline, in the Requirements step
(`EntryPointPicker` in `RequirementsStep.tsx`). When left unmarked, the
sightline rules are honestly skipped with a stated reason, not guessed at.

With a real entry point, `layout_engine.py`'s `_place_support_zones` now:
places the Foyer at the position closest to the entrance; prefers an F&B
position with an unobstructed sightline from the entrance; prefers a
Washroom position *without* a sightline from the Foyer. Placement still
succeeds even when a preference can't be satisfied (a warning says so
honestly instead of the room silently vanishing or the rule being silently
faked).

Found and fixed two real bugs while verifying this against actual geometry,
not just reading the code back:
1. A naive sightline check made the Foyer block its own "F&B visible from
   entry" rule on every real test, because the Foyer legitimately sits
   between the literal entry point and everything else by design — the
   Foyer is now excluded from what counts as "blocking" that specific
   check (the SOP's real intent is "visible once you're in from the entry
   area," not an unobstructed line through where the foyer itself stands).
2. The Washroom's "hidden from foyer" check started its sightline at the
   Foyer's own centroid, which trivially self-intersects the Foyer polygon
   it starts inside of — meaning the check would have reported every
   placement as "hidden" regardless of real geometry. Fixed the same way.

Verified two ways: an isolated geometry test (open room, no obstacles)
proving both rules can genuinely be satisfied when the floor plate allows
it; and a real run against the actual ~500-column Dhule floor, which
correctly and honestly reports it *couldn't* always achieve a clear
sightline given that much column density — a real result, not a bug, and
exactly the kind of honest "couldn't do it, here's why" the project's
principles call for over a silently-faked success.

### M9 — Export history (was a real, unimplemented gap — now done)

Added `storage.append_export_record`/`read_export_history` and a `GET
/export-history` endpoint — every PDF/DXF/DWG export now appends a record
(revision, format, timestamp, drawn-by, checked-by, remarks) to
`storage/<project>/exports/history.json`. `ExportPanel.tsx` shows the full
history and now has an optional remarks field before each export ("e.g.
Revised after client walkthrough"). Verified live: exported the same
project twice with different remarks, confirmed both appear correctly
ordered (newest first) with the right auto-incremented revision numbers.

### M10 — Dashboard search/filter (was a real, unimplemented gap — now done)

Added free-text search (property name, client name, project code) and
city/state/status filters to the project dashboard, backed by a real
server-side `WHERE` query in `GET /projects` (not a client-side filter over
an already-fetched list) plus a `GET /projects/filters` endpoint returning
the distinct values actually present, so the dropdowns reflect real data.
Verified each filter independently against seeded test projects with known
city/state/status values.

**Deliberately not implemented**: filtering by franchise tier. That value
lives per-region in `services/zoning-engine`'s requirements data, not on
the Project record in `services/project` at all — filtering the dashboard
by it would mean querying a second service per row, not a real filter.
Flagging this as an open architecture question (should franchise tier move
to the Project record, captured at intake?) rather than silently skipping
it without a trace.

## Update: real authentication, admin/user management, brutal-testing pass

Triggered by the user reporting they couldn't log in or register. Root cause
of *that specific* symptom: the backend services (`services/project`,
`services/zoning-engine`) had been stopped at the end of the previous
session and nobody had restarted them — there was no actual login bug at
that moment. **This is now a standing operational risk worth naming
explicitly: this app has no persistent hosting yet (see "Not deployed
anywhere" below), so every session that stops the dev processes leaves the
app unreachable until someone restarts them by hand.** Don't treat "restart
the two services" as a one-off fix; it needs to stop being manual (see
Punch List, Critical, item 1).

Investigating "why can't I log in" further surfaced something much more
important than that one symptom, though: **authentication was almost
entirely decorative.**

### Fixed: authentication was bypassable, not just occasionally broken

- `services/project/src/routes/projects.js` resolved the current user with
  a function that **silently fell back to "the first user ever created in
  the database" whenever no session cookie was present.** Every project
  list/read/create/update/delete endpoint was reachable with zero
  authentication — anyone with network access to port 3001 could see and
  modify every project without ever logging in. This was a real bug, not a
  documented "single-tenant simplification" — nothing in the spec or prior
  session notes called for this. Fixed: `requireAuth` middleware
  (`services/project/src/middleware.js`) now rejects with a real 401 when
  there's no valid session, applied to the entire `/projects` router and
  the new `/admin` router.
- **The frontend had no route guard at all.** `/projects`,
  `/projects/:id/intake`, `/projects/:id/studio` all rendered — and made API
  calls — whether or not anyone was logged in. Combined with the bug above,
  logging in was, practically speaking, optional. Fixed: `AuthContext.tsx` +
  a `RequireAuth` wrapper in `App.tsx` that checks a real session via the
  new `GET /api/pm/auth/me` endpoint and redirects to `/login` otherwise.
  Verified live: cleared the session, navigated straight to `/projects` and
  `/admin`, confirmed both bounce to `/login`; confirmed `/projects` returns
  a real 401 with no cookie via direct `curl`, not just a UI-level redirect.
- **Email matching was case-sensitive** (`auth.js` compared raw
  `req.body.email` against the stored value). Registering as
  `Jane@Firm.com` and later logging in as `jane@firm.com` — a completely
  ordinary thing for a real person to do — silently failed with "Invalid
  email or password." Reproduced directly (not assumed): registered
  `MixedCase@Example.com`, logged in as `mixedcase@EXAMPLE.com`, watched it
  fail before the fix and succeed after. This is a second, very plausible
  explanation for "why can't I log in," independent of the services being
  down. Fixed by normalizing (trim + lowercase) email on both register and
  login. **Not retroactive**: any account created before this fix keeps
  whatever casing it was originally registered with — real accounts here
  (`test@connplex.com`, `architect2@connplex.com`) both happen to already be
  lowercase, so this doesn't affect them, but it's worth knowing if a
  future account written directly to the DB (not through the API) ever has
  mixed case.

### Added: admin account + user management

- `users.is_admin` (schema + migration for the existing DB — SQLite has no
  `ADD COLUMN IF NOT EXISTS`, handled by checking `PRAGMA table_info` first).
- The very first account ever created in a database with no admin yet is
  auto-promoted to admin on server start (standard self-hosted-tool
  bootstrap pattern) — in every environment this project has run in so far,
  that's the seeded `test@connplex.com`. Confirmed live: on this session's
  DB, `test@connplex.com` came up `is_admin: true` automatically.
- `services/project/src/routes/admin.js` (mounted at `/api/pm/admin`, admin-
  only): `GET /users` (every account + how many projects each created),
  `PATCH /users/:id` (promote/demote — refuses to demote the last remaining
  admin, verified live: attempted it, got a 409 with a clear message),
  `DELETE /users/:id` (refuses to delete yourself while logged in as that
  account, and refuses to delete a user who still owns projects rather than
  either silently failing on the FK constraint or silently orphaning their
  data — verified both refusals live).
- `apps/web/src/pages/AdminPage.tsx` at `/admin`: a real table, promote/
  revoke and delete-with-inline-confirm (same pattern as project delete).
  Verified live in the browser as both an admin (full table, actions work)
  and a fresh non-admin account (clean "you don't have admin access" state,
  not a crash or a blank table).
- Navbar (dashboard) now shows who's logged in, an "Admin" badge, and a
  "Manage Users" link — only rendered for an actual admin.

### Fixed: two more real bugs found by deliberately trying to break things

- **A `ZeroDivisionError` crashed every zoning run against a region too
  small/oddly-shaped to fit even the smallest auditorium preset**, as an
  unhandled 500 with a raw Python traceback — not simulated, hit for real
  while testing a small synthetic floor plate. Root cause:
  `_place_support_zones` in `layout_engine.py` computed each support zone's
  target size as a fraction of total auditorium area; when 0 auditoriums
  fit, every target became `0`, and `target_area / w` where `w =
  sqrt(0) = 0` is a bare division by zero. Fixed: zones with a `0` target
  are now skipped with an honest warning ("its target area is 0 sqft
  because no auditorium could be placed...") instead of crashing the whole
  run. Re-verified the same input now returns `HTTP 200` with clear
  warnings instead of `HTTP 500`.
- **No top-level error boundary anywhere in the frontend** — confirmed by
  grep, not assumed. Any unhandled render error, anywhere in the tree, blank-
  screened the entire app with no recovery path and no indication anything
  was even wrong. Added `ErrorBoundary.tsx` wrapping the whole app in
  `main.tsx`: shows what broke and a "Back to Projects" button instead of a
  silent white screen.

### Full punch list for the next version

Organized by how much it matters before real people rely on this daily, not
by how interesting it is to build. Items already covered above are marked
done; the rest are genuinely unaddressed and should be triaged, not assumed
covered by anything above.

**Critical — before this can be called "shippable" to anyone outside this session:**

1. **No persistent hosting.** Confirmed today — the entire app going
   unreachable is one `stop` or one machine restart away, with a manual
   two-command recovery. This has now caused real end-user-visible downtime
   at least once (this session's "why can't I log in"). Needs an actual
   always-on host (even a single small VM running both services under
   something like `pm2`/`systemd` would fix this) before anyone is told to
   rely on this day-to-day. See "Running this project" in CLAUDE.md for the
   exact processes that need to stay up.
2. **`services/zoning-engine` has zero authentication of its own** — by
   original design (see CLAUDE.md's module-boundary notes: "this service
   knows nothing about users/auth"), on the assumption the frontend is the
   only caller. Combined with wide-open CORS (`allow_origins=["*"]`) on that
   service, anyone who can reach port 8000 directly (not just through the
   web UI) can read/write/export **any** project's CAD data by guessing or
   observing a project ID — no login required, independent of the auth
   fixes above (those only cover `services/project`). Fine for a trusted
   internal network; not fine the moment this is reachable from the open
   internet. Needs a real decision (shared-secret header from the trusted
   frontend, or teaching zoning-engine to validate the same session cookie)
   before any deployment outside a private network — this is bigger than a
   quick patch and changes a documented module boundary, so flagging rather
   than silently changing it.
3. **`services/project`'s CORS (`origin: true, credentials: true`)
   reflects any request origin and allows credentialed requests from it** —
   effectively as open as a wildcard for a credentialed API. Needs to be
   locked to the real deployed frontend origin(s) via an env var once one
   exists; there's no real production origin yet to lock it to today.
4. **No automated test suite anywhere** — no unit tests, no integration
   tests, no e2e tests, in either service or the frontend. Every "verified"
   claim in this file (including today's) was a manual, one-off curl/browser
   session, not a regression suite. That's how the `ZeroDivisionError` above
   went unnoticed through several prior sessions of manual "happy path"
   testing on room shapes that happened not to trigger it. At minimum:
   backend unit tests for `layout_engine.py`/`seat_engine.py`/
   `feasibility_engine.py` (pure functions, cheap to test, exactly where
   today's crash lived) and one real end-to-end test of upload→zone→export.
5. **No CI.** Nothing runs `tsc`, a lint, or any test automatically on a
   change — every check in this session's history was a human (or an AI
   session) remembering to run it by hand.

**Important — real gaps that will surface in ordinary use, not edge cases:**

6. No "forgot password" flow. A real user *will* forget their password;
   today there is no recovery path at all except an admin deleting and
   re-registering... except delete-user is blocked once they own any
   projects (correctly, but that leaves no path forward at all right now).
7. No rate limiting or lockout on login attempts — `POST /auth/login` can
   be hit as fast as the network allows, indefinitely, from anywhere it's
   reachable.
8. No email verification on registration — anyone can register with any
   email address, including one they don't own. Low risk on a trusted
   internal tool, real risk the moment this is opened more broadly.
9. No CSRF protection beyond `sameSite: 'lax'` cookies — adequate for
   same-site navigation, not a substitute for a real CSRF token if this
   ever serves a different frontend origin.
10. Session cookies aren't marked `secure` — fine over local HTTP today,
    **must** be set before serving this over HTTPS (an insecure cookie
    still works over HTTPS, it's just also sendable over plain HTTP, which
    defeats the point) — tie this to whenever hosting (item 1) happens.
11. Password policy is length-only (≥8 chars) — no complexity/breach-list
    check. Reasonable for v1, worth a decision if this scales past a small
    trusted team.
12. `generateNextProjectCode()` reads the current max and inserts in two
    separate steps with no transaction. Tested this deliberately with 8
    concurrent project-creation requests — no collision, because
    `node:sqlite` here is synchronous and Node's single-threaded event loop
    doesn't interleave between the read and the write within one process.
    **This stops being safe the moment `services/project` ever runs as more
    than one process** (e.g. a load-balanced/clustered production
    deployment) — two separate OS processes reading/writing the same
    SQLite file genuinely can race. Worth a real unique-constraint-retry
    loop before scaling past one process, not before then.
13. Every authenticated user currently sees **every** project from every
    other user — there's no per-user visibility scoping, only the
    (now-real) requirement to be logged in as *someone*. This matches how
    the app has behaved since projects/registration were added and may be
    the intended "one shared team workspace" model — but it was never an
    explicit decision, just what fell out of not building per-user
    filtering. Worth Connplex explicitly confirming this is desired before
    calling it final, especially now that admin/member roles exist.
14. `PATCH /admin/users/:id` and `DELETE /admin/users/:id` have no audit
    trail — nothing records *which* admin promoted/deleted *which* account,
    or when. Fine for a two-or-three-person team; a real gap the moment
    "manage them" needs to answer "who did this."
15. Deleting a user who owns projects is correctly *refused* rather than
    silently breaking, but there's no UI path to actually resolve that
    (reassign their projects to someone else, or bulk-delete their
    projects first) — right now an admin has to go delete each of that
    user's projects individually from the dashboard before the user delete
    will succeed.

**Polish / nice-to-have — real, but lower priority:**

16. `services/zoning-engine/main.py`'s `select-candidate` endpoint's request
    schema field is literally named `region_id` but is actually used as
    `candidate_id` (`"""body.region_id is reused here as candidate_id for
    simplicity of the shared schema."""`). The frontend already calls it
    correctly, so this isn't a live bug — but it's a genuine landmine
    (a natural `{"candidate_id": ...}` call would silently be ignored by
    Pydantic and produce a misleading "Candidate not found" 404 instead of
    a clear validation error). Confirmed this by tripping over it myself
    during this session's testing. Worth a proper `candidate_id` field name
    next time this endpoint is touched.
17. Mobile: spot-checked the login page and dashboard at a 375px viewport —
    both reflow cleanly with no overflow. **Not checked**: the zoning canvas
    editor (`EditableCanvas.tsx`), which is a drag/resize-heavy SVG
    interface that was explicitly built and tuned for mouse interaction
    this session — real touch-drag behavior on a small screen is genuinely
    unverified, not just "probably fine."
18. No structured logging, error tracking (e.g. Sentry), or metrics in
    either backend service — today, a production error is only visible if
    someone happens to be tailing the process's stdout.
19. No documented database backup strategy for either the SQLite file
    (`services/project/data.sqlite`) or the zoning-engine's per-project
    file storage (`services/zoning-engine/storage/`) — both are the only
    copy of real project data once this is in real use.
20. No pagination or search on the project dashboard or the admin user
    list — fine at today's scale (single digits to low dozens), will need
    it before either list realistically reaches "many projects, many
    users."
21. Items 1–7 from the pre-existing "Priority backlog" below (franchise-
    tier UI gaps, production SPA routing fallback, multi-floor scoping,
    exact PDF/DWG template parity, background zoning-run jobs) are all
    still open and unchanged by this session — see that section rather than
    treating this list as replacing it.

## Update: dashboard cleanup, real project delete, richer CAD component classification

Directly in response to: "remove all the other projects", "add the delete
projects button", "make application clean", and "accurately capture
components based on cad uploaded."

- **Project delete is now real, not just a UI affordance.** `DELETE /projects/:id`
  in `services/project` removes the project row (and its `floors` rows);
  `DELETE /api/projects/{id}` in `services/zoning-engine` removes that
  project's uploaded CAD/geometry/zoning-runs/layout/exports on disk. The
  dashboard's new delete button asks for an inline confirmation on the card
  itself (no native browser `confirm()` popup — kept consistent with the
  rest of the UI) before calling both. Verified live: created a project,
  deleted it through the UI, confirmed via a direct API call that it was
  actually gone from the database, not just removed from the page's local
  state.
- **Cleared all 37 pre-existing projects** (all test/demo data accumulated
  across this project's testing sessions — none were real client records)
  using the new delete endpoints, plus 3 orphaned ad-hoc test directories
  under `services/zoning-engine/storage/` that predated per-project cleanup.
  Dashboard starts clean.
- **Removed the entire legacy demo pipeline** (`/canvas` and `/placeholder`
  routes, `pages/ZoningStudio.tsx`, `pages/ZoningCanvasPlaceholder.tsx`,
  `pages/ReviewRevisionWorkflow.tsx`, `services/cadService.ts`,
  `types/zoning.ts`, all of `components/zoning/*`) — confirmed via grep that
  nothing in the real `/studio` pipeline referenced any of it, and that no
  in-app link pointed at either route (`ProjectIntakePage` already always
  navigated to `/studio`). This was the original fake pipeline the whole
  project replaced (`CadUploadModal.tsx` ran a fake progress bar and never
  uploaded anything — see `main.py`'s own docstring) — leaving it in the
  repo, reachable by typing a URL, was dead weight that could show someone a
  pre-baked fake Dhule layout and look like a real result. Removing it also
  shrank the real production JS bundle from 305KB to 226KB (59 to 45
  modules) — a genuine size reduction, not just fewer files on disk.
- **More accurate CAD component classification.** Obstacles inside a
  confirmed boundary were previously only ever tagged `COLUMN` (via a layer-
  name hint) or a catch-all `UNCLASSIFIED_OBSTACLE`. Expanded the same
  evidence-based layer-name-hint technique (real DXF layer metadata, not an
  invented rule — matches standard AIA CAD layer-naming conventions like
  A-DOOR, A-GLAZ, A-COLS that most real architectural files, including
  Connplex's own, already follow) to also recognize DOOR, WINDOW, STAIRCASE,
  WASHROOM_FIXTURE, and FURNITURE layers, each still carrying its own
  confidence and requiring the same Confirm/Ignore review — nothing here is
  presented with more certainty than the evidence supports. Verified on the
  real Dhule DWG: 36 obstacles that would previously have been dumped into
  the generic "unclassified" bucket are now correctly tagged `STAIRCASE`
  from their real CAD layer name. Verified on the real Vadodara DWG too
  (no regression — that file's layer names don't happen to hint at any of
  the new categories, so it correctly still returns `COLUMN`/
  `UNCLASSIFIED_OBSTACLE` only, rather than guessing).
- **Consistent branding across every screen** — added the same small "CZ"
  brand mark to both the navbar (dashboard, and by inheritance every page
  using it) and the login card, previously plain text only. Refined the
  project dashboard's cards (hover elevation, cleaner badges, project count
  in the subtitle) and empty state (a real empty-state treatment instead of
  a plain paragraph).

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

**Update, seventh session:** the legacy demo pipeline described in this
paragraph (`/projects/:id/canvas`, the pre-baked Dhule/Vadodara reference
demo) has since been removed entirely — see "Update: dashboard cleanup, real
project delete, richer CAD component classification" near the top of this
file. `/projects/:id/studio` is now the only zoning pipeline in the app.

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

### 5. ~~`config over code` cleanup in the legacy `cadService.ts`~~ — resolved (removed)

`cadService.ts` and the whole legacy `/canvas` demo pipeline it belonged to
were deleted in the seventh session rather than fixed — see "Update: dashboard
cleanup..." near the top of this file. `/studio` (the only remaining
pipeline) already reads registry-driven minimums throughout
`services/zoning-engine/`, so this item no longer applies.

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
2. ~~Franchise tier naming: "Express" (brochure) vs. "Smart" (ROI sheet)~~ —
   **resolved 2026-09-01**: "Express" is the canonical client-facing name,
   "Smart" kept as a known alias in the registry's `aka` field. Not a
   Connplex-confirmed decision — the project owner made this call directly;
   flag it to Connplex if their own usage later disagrees.
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
