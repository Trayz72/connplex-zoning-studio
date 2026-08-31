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

### c) The DWG conversion path needs a GUI toolkit on a headless server — untested on Render specifically

This is the biggest unknown, so it gets its own section — see §4. Short
version: DWG import/export goes through ODA File Converter, which is a Qt
GUI application that requires a display server even for silent batch
conversion. Verified on this dev machine (which has a real X11 session):
`services/cad-interop/ODAFileConverter` sets `DISPLAY=:0` and it works
because a real display exists here. **A Render Web Service is headless — no
X server at all.** This needs a custom Docker image with `Xvfb` (a virtual
framebuffer) installed and started before the app, plus every X11/Qt
runtime library ODA File Converter needs. This has not been tested on
Render specifically in this session — treat it as the top risk item to
validate first, not something to assume will "just work" because it works
here.

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

## 4. What §2c actually requires, concretely

If you go the Docker route on Render for `services/zoning-engine`:

1. Base image with the X11/Qt runtime libraries ODA File Converter links
   against (confirmed via `ldd` on this dev machine — the binary itself has
   no *missing* library dependencies here because this machine already has
   a full desktop install; a minimal server base image will be missing most
   of them and you'll need to add them explicitly).
2. Install `xvfb`.
3. Install/copy in the ODA File Converter binary (~253MB — it's gitignored
   in this repo on purpose, so it has to be fetched or baked into the image
   as a separate build step, not pulled from `git clone`).
4. Start `Xvfb` before the app (commonly `xvfb-run -a <start command>`, or
   a supervisor script that launches Xvfb, exports `DISPLAY` to point at
   it, then starts uvicorn).
5. Verify ODA File Converter's license terms permit this exact usage
   (server-side, unattended, batch conversion as part of a paid product) —
   this session didn't verify licensing terms and neither should you assume
   they're fine without checking ODA's own license directly.

## 5. Spec milestones — honest status, not "mostly done"

The spec (`Connplex_Zoning_Studio_Spec.pdf` §9) defines M0–M10. Checked each
one's actual acceptance criteria against this codebase directly (including
live-testing two of them this session and finding real gaps, not assuming
past session notes were still accurate):

| Milestone | Status | Note |
|---|---|---|
| M0 — Foundational skeleton | Done, one gap fixed this session | Spec calls for Postgres; this uses SQLite (§2 explains the tradeoff). **The "cannot reach canvas with incomplete intake" acceptance criterion was failing** — verified live, a fresh project with no intake data loaded the full workspace with zero gate. Fixed this session (`ZoningWorkspace.tsx` now redirects to intake if incomplete). |
| M1 — CAD interop PoC | Partial | DXF works natively; DWG works via ODA for 2 of 3 reference files (theater.dwg fails — see §3). APS (spec's recommended path) was never implemented, only the ODA fallback. |
| M2 — Rules/config layer + admin UI | **Partial — real gap** | The registry itself exists and is genuinely data-driven (`rules_registry_v1.json`), but **no admin UI to edit it exists** — confirmed by search, there's no CRUD screen anywhere in `apps/web/src`. Today, changing a rule value means hand-editing JSON and redeploying, which is exactly what Product Principle #2 says not to do. This is a real, unimplemented milestone, not a polish item. |
| M3 — Feasibility engine | Done | Clear height + column-grid spacing wired in; a "Feasibility Check" view shows pass/fail per rule. |
| M4 — Manual zoning canvas | Done | Move/resize/live area-seat panel/overlap warnings all real and tested this session and prior ones. |
| M5 — Auto-layout v1 (auditoriums) | Done | Maximizes seats, avoids obstacles, respects seats-per-screen floor. |
| M6 — Auto-layout v2 (support zones) | **Partial** | Foyer/F&B/Washroom/Box Office/BOH are all placed automatically — but the spec's specific adjacency rules (washrooms hidden from foyer sightline, F&B visible from entry, foyer at entry level) are **not implemented**; placement is a generic largest-fit rectangle scan with no sightline/adjacency awareness. Real gap against the spec's stated acceptance criteria for this milestone. |
| M7 — Area & Seat Chart | Done | Live panel matches the reference table's column structure; PDF export reproduces it. |
| M8 — Exact-match export | Done | Rewritten to match the real Connplex sheet format (title block, legends, revisions, area/seat chart) — verified visually against real exports multiple times this project. Logo is a drawn approximation, not their vector art (documented, not hidden). |
| M9 — Versioning/housekeeping | **Partial** | Revision auto-increments correctly on each export (R0→R1→…, verified). **No export-history view exists** — past exports live in `storage/<project>/exports/` but there's no UI listing them, so the spec's "show full export history" deliverable isn't there. |
| M10 — Polish | **Partial** | No search/filter on the project dashboard (spec explicitly calls for city/state/status/tier filters). The `floors` table exists and is unused, correctly leaving room for multi-floor later per spec — confirmed by schema review. Error-state handling improved this session (top-level error boundary added). A brand-new user genuinely can complete the full pipeline unaided today — verified live, repeatedly, this session. |

**Bottom line: M0, M3, M4, M5, M7, M8 are done. M1 is real but incomplete
for DWG. M2, M6, M9, M10 each have a genuine, specific, unimplemented piece**
— not vague polish, but concrete missing deliverables (an admin UI, sightline
rules, an export-history screen, dashboard search). Building all four
properly is a meaningfully sized chunk of work, not a quick pass — worth
prioritizing rather than doing partially across all four at once.
