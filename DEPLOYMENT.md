# Deployment Guide

Written for whoever hosts this next — answers "can I put this on Render.com,"
what the directory structure means, and exactly what DWG/DXF support requires
operationally. Everything here was verified against this codebase directly
(commands run, output checked), not assumed from the spec.

## 1. Directory structure

```
connplex-v1/
├── apps/
│   └── web/                     Frontend — React + TypeScript + Vite SPA
│       ├── src/
│       │   ├── pages/           Route-level screens (Login, Projects, Intake, ZoningWorkspace, Admin)
│       │   ├── components/workspace/   The zoning canvas + its editing UI (the real product surface)
│       │   ├── services/        Typed fetch wrappers around each backend API
│       │   ├── api.ts           Auth + project CRUD calls (project service)
│       │   ├── AuthContext.tsx  App-wide session state + the route guard
│       │   └── types/live.ts    Shapes returned by the zoning-engine API
│       ├── vite.config.ts       Dev-only proxy: /api/pm → :3001, /api → :8000
│       └── dist/                Production build output (npm run build) — this is what you deploy
│
├── services/
│   ├── project/                 Backend #1 — Node/Express. Auth, sessions, project CRUD, user admin.
│   │   ├── src/
│   │   │   ├── routes/          auth.js, projects.js, admin.js
│   │   │   └── middleware.js    requireAuth / requireAdmin
│   │   ├── schema.sql           SQLite schema (users, projects, floors)
│   │   ├── data.sqlite          The actual database file — see §3, this needs a persistent disk
│   │   └── seed.js              Creates the bootstrap account (test@connplex.com)
│   │
│   ├── zoning-engine/           Backend #2 — Python/FastAPI. The real product: CAD parsing,
│   │   │                        auto-layout, seat/feasibility calc, PDF/DXF/DWG export.
│   │   ├── main.py              All API routes
│   │   ├── cad_extraction.py    DXF/DWG → geometry (boundary, columns, doors, etc.)
│   │   ├── layout_engine.py     Auto-layout generator
│   │   ├── seat_engine.py, feasibility_engine.py, chart_engine.py
│   │   ├── export_pdf.py, export_dxf.py
│   │   ├── storage.py           File-based per-project storage (see §3)
│   │   └── storage/              Per-project uploaded files + generated output — needs persistent disk
│   │
│   ├── rules-config/registry/   The "config over code" data — every business number
│   │   └── rules_registry_v1.json   (franchise tiers, seat types, planning norms, viability rules)
│   │       No admin UI edits this yet — see §5, it's a genuine open milestone (spec M2).
│   │
│   └── cad-interop/             DWG↔DXF conversion + the original (now UI-less) M0–M8 pipeline scripts
│       ├── convert.py           The function services/zoning-engine actually imports and calls
│       ├── ODAFileConverter     Thin wrapper script — see §4
│       ├── oda/                 253MB vendored ODA File Converter install — gitignored, install separately
│       └── test/output/         Frozen reference-drawing analysis output, kept for spot-checking only
│
└── docs/reference/              The two real Connplex reference DWGs + theater.dwg (test fixtures)
```

**Three things actually run in production**: the static frontend build, the
Node project-service (port 3001 in dev), and the Python zoning-engine (port
8000 in dev). Everything under `services/cad-interop/` other than
`convert.py`/`ODAFileConverter`/`oda/` is legacy analysis scripts, not a
running service — don't deploy it, it's not wired to anything live.

## 2. Can this run on Render.com?

**Yes, architecturally it fits Render's model** — a static site plus two web
services is exactly what Render is for. But there are three real gaps
between "runs on my machine" and "runs on Render" that need to be closed
first, not discovered after deploying:

### a) It's not one deployable unit today — it's three, talking over
   hardcoded dev-only proxying

Right now the frontend calls relative paths (`/api/pm/...`, `/api/...`) and
`vite.config.ts`'s dev server proxies those to `localhost:3001`/`:8000`.
That proxy doesn't exist in a production static-site deploy. You need one
of:
- A reverse proxy in front of all three (nginx, or Render's own routing if
  you put all three behind one custom domain with path-based rules), so the
  relative paths keep working unmodified, **or**
- Change the frontend to call each backend's real Render URL directly, and
  open CORS on both backends for the frontend's real origin specifically
  (not `*` — see §2c).

Either way, this needs deciding and testing before deploy, not after.

### b) Both backends write to local disk, and Render's default web service disk is ephemeral

- `services/project/data.sqlite` (users, projects) and
- `services/zoning-engine/storage/` (every uploaded CAD file, generated
  geometry, and export)

are both plain files on local disk. On a standard Render Web Service, local
disk is wiped on every deploy, restart, or scale event. **This will silently
lose every user account and every project the moment it happens** unless you
attach a Render **Persistent Disk** to both services.

Two important consequences of doing that, not just a checkbox:
1. A Persistent Disk attaches to **one instance only** — you cannot run
   `services/project` as more than one replica once it depends on local
   SQLite + a persistent disk (confirmed by code review: `generateNextProjectCode()`
   and `node:sqlite` here assume single-process access — see STATUS.md's
   punch list item 12 for the exact race-condition reasoning). Fine for a
   small internal team; a real constraint if this ever needs to scale
   horizontally.
2. This is exactly why the original spec's target architecture (§5.3) was
   **Postgres + S3-compatible object storage**, not SQLite + local files —
   what's built today is explicitly the v1 prototype simplification. Render
   has managed Postgres and works fine with any S3-compatible bucket
   (including actual S3, or Render's own object storage if available on
   your plan) — migrating to that is the real fix if this needs to survive
   deploys cleanly and scale, rather than a Render-specific workaround.

### c) The DWG conversion path needs a GUI toolkit on a headless server — resolved via Docker + Xvfb, built and verified locally

Resolved this session — see §4 for the concrete implementation
(`services/zoning-engine/Dockerfile`). Short version: DWG import/export
goes through ODA File Converter, a Qt GUI application that requires a
display server even for silent batch conversion, which a bare Render Web
Service doesn't have. The fix is a Docker image with `Xvfb` (a virtual
framebuffer) plus ODA File Converter itself, started before the app.

**Verified, not assumed** — built the real image locally (`docker build`,
Docker was available on this dev machine) and tested it end-to-end:
- A real 2.1MB client DWG (Dhule reference file) uploaded through the
  actual `/api/projects/{id}/cad` HTTP endpoint inside a running container
  converted correctly and extracted identically to the known-good DXF
  result (54,586 entities scanned, 7 regions, correct Feet units) — a
  byte-for-byte match with the equivalent DXF upload tested earlier the
  same session.
- The reverse direction (DXF→DWG, the export path) also verified directly
  inside the same container: a real 1.8MB DXF converted to a valid 327KB
  DWG, exit code 0.
- Two real bugs found only by actually running this in a container (not by
  reading ODA's install docs): the .deb's own declared dependencies cover
  the main binary but not the Qt "xcb" platform plugin, which is dlopen'd
  at runtime — missing `libxkbcommon0`/`libfontconfig1` first (binary
  wouldn't even start), then a second, larger set
  (`libxkbcommon-x11-0`/`libxcb-icccm4`/`libxcb-image0`/`libxcb-keysyms1`/
  `libxcb-render-util0`/`libxcb-render0`/`libxcb-shape0`/`libxcb-xkb1`)
  once the platform-plugin-specific failure ("Could not load the Qt
  platform plugin 'xcb'") pointed at the real culprit. Both found via
  `docker exec` + `ldd` against the actual plugin `.so` files, not guessed.

**Not yet verified**: actual behavior on Render's real infrastructure
(only local `docker build`/`docker run` — see the render.yaml comment on
this service for the free tier's 512MB RAM caveat), and ODA File
Converter's own reliability gap is unchanged (`theater.dwg` still fails
with a real ODA limitation unrelated to any of this, see the table below).

Also lock down before any real deploy (both confirmed live, not
theoretical):
- `services/zoning-engine`'s CORS is `allow_origins=["*"]` — fine for local
  dev, must be restricted to the real frontend origin.
- `services/project`'s CORS (`origin: true, credentials: true`) reflects
  any request origin for credentialed requests — same fix needed.
- Session cookies aren't marked `secure` yet — add that once served over
  HTTPS (Render terminates TLS for you automatically, so this is just a
  one-line code change, not an infra task).

**Recommended order if you're doing this**: get the two backends deployed
and talking to the frontend first with SQLite + local disk + a Persistent
Disk (fastest path to "it's up"), confirm DXF-only upload works end-to-end
in that environment, *then* tackle the Xvfb/ODA Docker image for DWG
support as a separate, isolated step you can test on its own. That way a
DWG-conversion problem doesn't block getting the rest of the app live.

## 3. Is DXF natively supported? What about DWG?

**DXF: yes, natively, no external dependency.** `cad_extraction.py` parses
DXF directly with `ezdxf` (a pure Python library) — no binary, no display
server, nothing else to install. This will work on any host, Render
included, with zero extra setup. If you want the lowest-risk path to a
working deployment, DXF-only is it.

**DWG: yes, but via a real conversion step your server has to run, not
something ezdxf does natively.** DWG is Autodesk's proprietary binary
format; `ezdxf` cannot read it directly. The pipeline handles this by
shelling out to **ODA File Converter** (a free tool from the Open Design
Alliance) to convert DWG→DXF on the way in and DXF→DWG on the way out
(`services/cad-interop/convert.py`, reused by `cad_extraction.py` and
`export_dxf.py`). This is the spec's own documented **fallback** path — the
spec's *recommended* path is Autodesk Platform Services (a paid, metered
cloud API), which was never implemented here; ODA is what's actually
running.

Freshly re-verified in this session, not assumed from an earlier one:

| File | Result |
|---|---|
| Real Dhule reference DWG | Converts successfully (DWG→DXF, 5.1MB output) |
| Real Vadodara reference DWG | Converts successfully (confirmed in an earlier session, unchanged) |
| `docs/reference/theater.dwg` | **Fails**: `XData size exceeded: <object> (2B00BC)` — a real ODA File Converter limitation on this specific file's extended entity data, not a bug in this codebase. No workaround exists today short of a different converter (e.g. real APS). |

So: **your server can absolutely do the DWG↔DXF conversion under the hood**
— that's exactly what it's built to do — but "your server" specifically
means a machine (or Docker image) with ODA File Converter and a virtual
display installed, per §2c. It is not something that runs inside the Python
process with no external dependency the way DXF parsing does, and it is not
100% reliable on every possible DWG file (theater.dwg is proof of that, not
a hypothetical edge case).

**On the spec's *recommended* path (Autodesk Platform Services) instead of
ODA** — actually checked this session, not assumed: Autodesk's **Model
Derivative API** (the product most people mean by "APS conversion") cannot
produce DXF output at all. Checked directly against Autodesk's own
`GET /formats` reference response: the dictionary of valid *target* formats
is `dwg, fbx, ifc, iges, obj, step, stl, svf, svf2, thumbnail` — no `dxf`
key exists, and `dxf` only appears as a *source* format for viewer
translation (SVF2), never as something you get back out. It is not a
drop-in replacement for ODA File Converter. Autodesk's **Design Automation
API for AutoCAD** *can* do a real DWG→DXF conversion (it runs actual
headless AutoCAD in their cloud), but that's a much heavier integration —
package an AppBundle, define an Activity, submit WorkItems, and write real
AutoCAD script/AutoLISP commands — plus a different, pricier billing model.
Neither is a quick swap for what's built here; going that route is a
multi-day project of its own, not a config change.

## 4. What §2c actually requires, concretely

Built and verified locally this session — `services/zoning-engine/Dockerfile`
and the corresponding `render.yaml` entry (docker runtime, `dockerContext: .`
so it can reach `services/cad-interop/convert.py` and
`services/rules-config/registry/`, both sibling directories the app already
depends on at runtime). What it does, and what running it locally
(`docker build` + `docker run` + real HTTP uploads against the container)
actually surfaced:

1. **Base image**: `python:3.12-slim` (Debian bookworm, glibc 2.36 — ODA
   states 2.28+ required).
2. **ODA File Converter fetched at build time**, not committed — 253MB,
   gitignored on purpose. Verified directly: the download URL
   (`opendesign.com/guestfiles/get?filename=...`) 301-redirects straight to
   a presigned S3 object with no login/EULA click-through in front of it, so
   a plain `wget` in the Dockerfile works. Pinned to version 27.1, matching
   what's already vendored for local dev at `services/cad-interop/oda/`.
   `apt-get install ./oda.deb` (not `dpkg -i`) so apt resolves the
   package's *own* declared dependencies — but see next point, that's not
   the whole story.
3. **`xvfb`**, plus a real, non-obvious library list found only by running
   this in an actual container: the .deb's declared dependencies cover
   ODAFileConverter's main binary, but Qt's "xcb" platform plugin
   (`plugins/platforms/libqxcb.so`) is loaded via `dlopen()` at runtime, so
   its own missing shared libraries never appear in a build-time `ldd`
   check against the main binary — they only surface when you actually try
   to run a conversion, as
   `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`. Running
   `ldd` directly against `libqxcb.so` inside a live container was the only
   way to get the real list:
   `libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
   libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-xkb1`, plus
   `libxkbcommon0`/`libfontconfig1` needed just for the main binary to
   start, and the `libxcb-util.so.1`→`.so.0` symlink ODA's own install
   notes call out for "modern Linux." All of this was confirmed by
   installing the packages into a *running* container and successfully
   converting a real client DWG before ever baking the fix into the image.
4. **Start command** launches Xvfb, polls for its X11 socket to actually
   exist (fixed-length `sleep` is a real race — Xvfb's startup time
   varies), then execs uvicorn on Render's `$PORT`.
5. **Verified end-to-end**: a real 2.1MB client DWG uploaded through the
   actual `/api/projects/{id}/cad` endpoint inside a running container
   converted and extracted identically to the known-good DXF result
   (54,586 entities, 7 regions, correct Feet units). The reverse direction
   (DXF→DWG, the export path) verified the same way: a real 1.8MB DXF
   converted to a valid 327KB DWG, exit code 0.

**Still open, deliberately not resolved here**:
- Real Render infrastructure behavior is untested (local Docker only) —
  the free plan's 512MB RAM is a real risk for a Qt6 GUI subprocess on top
  of the FastAPI process itself; if large/complex DWGs OOM or time out in
  practice, the fix is upgrading the plan, not more code.
- ODA File Converter's license terms for this exact usage (server-side,
  unattended, batch conversion as part of a paid product) were not formally
  verified against ODA's own EULA text this session — the download itself
  has no click-through gate, which is a real signal but not a substitute
  for actually reading the license if that matters for your situation.

## 5. Spec milestones — honest status, not "mostly done"

The spec (`Connplex_Zoning_Studio_Spec.pdf` §9) defines M0–M10. Checked each
one's actual acceptance criteria against this codebase directly (including
live-testing every one of them, not assuming past session notes were still
accurate):

| Milestone | Status | Note |
|---|---|---|
| M0 — Foundational skeleton | Done | Spec calls for Postgres; this uses SQLite (§2 explains the tradeoff). The "cannot reach canvas with incomplete intake" acceptance criterion was failing (verified live) — fixed and re-verified: `ZoningWorkspace.tsx` now redirects to intake if incomplete. |
| M1 — CAD interop PoC | Partial | DXF works natively; DWG works via ODA for 2 of 3 reference files (theater.dwg fails — see §3). APS (spec's recommended path) was never implemented, only the ODA fallback. Unchanged this session — this is a licensing/vendor decision, not a code gap. |
| M2 — Rules/config layer + admin UI | **Done** | Built `/admin/rules` — a real CRUD UI over all 5 registry categories (seat types, auditorium presets, franchise tiers, planning norms, viability rules), gated to actual admin sessions (the write path lives in `services/project`, which has real auth — `services/zoning-engine` has none by design, so it was never a safe place for a write endpoint). Every save writes a timestamped backup first. Verified end-to-end: edited a real seat-type record through the UI, confirmed the change landed on disk, and confirmed `services/zoning-engine` picked it up **without a restart** (fixed a real bug along the way — its registry cache never invalidated). |
| M3 — Feasibility engine | Done | Clear height + column-grid spacing wired in; a "Feasibility Check" view shows pass/fail per rule. |
| M4 — Manual zoning canvas | Done | Move/resize/live area-seat panel/overlap warnings all real and tested this session and prior ones. |
| M5 — Auto-layout v1 (auditoriums) | Done | Maximizes seats, avoids obstacles, respects seats-per-screen floor. |
| M6 — Auto-layout v2 (support zones) | **Done, with an honest scope note** | The SOP's adjacency rules ("F&B visible from entry", "washrooms not directly visible from foyer", "foyer at main entry level") are real geometric sightline checks now (`layout_engine.py`), driven by a real architect-marked entry point (a new click-to-mark picker in the Requirements step — nothing in CAD extraction detects doors, so this is genuine user input, not inferred). When no entry point is marked, the rules are honestly skipped with a stated reason rather than guessed at. Verified two ways: an isolated geometry test proving the mechanism succeeds when the floor plate allows it, and a real run against the actual 500-column Dhule floor, which correctly reports it *couldn't* always satisfy the sightline preference — a genuine result given that much column density, not a bug. |
| M7 — Area & Seat Chart | Done | Live panel matches the reference table's column structure; PDF export reproduces it. |
| M8 — Exact-match export | Done | Rewritten to match the real Connplex sheet format (title block, legends, revisions, area/seat chart) — verified visually against real exports multiple times this project. Logo is a drawn approximation, not their vector art (documented, not hidden). |
| M9 — Versioning/housekeeping | **Done** | Revision auto-increments correctly on each export (R0→R1→…, verified). Added a real export-history log (`storage/<project>/exports/history.json`, one record per export with revision/format/timestamp/drawn-by/checked-by/remarks) and a UI panel showing it, plus an optional remarks field before each export. Verified: exported twice with different remarks, confirmed both showed up correctly ordered with the right revision numbers. |
| M10 — Polish | **Done** | Added search (property/client/project #) and city/state/status filters to the project dashboard, backed by a real server-side query — verified all four independently against seeded test data. Franchise-tier filtering deliberately **not** included: that data lives per-region in `services/zoning-engine`'s requirements, not on the Project record, so filtering by it from the dashboard would mean querying a second service per row rather than a real filter — flag this as a future decision, not a silently dropped feature. The `floors` table exists and is unused, correctly leaving room for multi-floor later per spec. Error-state handling improved (top-level error boundary added). A brand-new user genuinely can complete the full pipeline unaided today — verified live, repeatedly. |

**Bottom line: M0, M2, M3, M4, M5, M6, M7, M8, M9, M10 are done. M1 is real
but incomplete for DWG** (theater.dwg, and the spec's recommended APS path
was never built — both are vendor/licensing decisions, not something a code
change closes without a licensing decision from Connplex first).
