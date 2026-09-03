"""
Connplex Zoning Studio — Zoning Engine Service.

Owns the real (not simulated) CAD-upload -> geometry-confirmation -> requirements
-> auto-layout -> seat/feasibility -> architect-editable-layout -> PDF/DXF/DWG
export pipeline for an arbitrary uploaded project, replacing the previous
demo-only flow (CadUploadModal.tsx ran a setTimeout-based fake progress bar and
never sent a file anywhere; ZoningCanvas.tsx displayed one pre-baked SVG image
with hand-tuned percentage hotspots).

Runs alongside services/project (Node/Express, auth + project CRUD) rather than
replacing it — this service knows nothing about users/auth/login; the frontend
calls both. See CLAUDE.md for the module-boundary rationale.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import storage
import cad_extraction
import layout_engine
import rules_registry
import seat_engine
import feasibility_engine
import chart_engine
import export_dxf
import export_pdf
import ai_zoning_engine
import ai_cad_scan
import ai_obstacle_classify

app = FastAPI(title="Connplex Zoning Engine")
# No cookies flow through this service (it has no auth of its own — see the
# module docstring above), so a wildcard origin doesn't expose a logged-in
# user's session the way it would on services/project. Still worth locking
# to the real frontend origin once deployed rather than leaving this open
# to any site — set FRONTEND_ORIGIN (same value as services/project's) to
# do that; unset, it keeps today's wildcard behavior for local dev.
_allowed_origin = os.environ.get("FRONTEND_ORIGIN")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_allowed_origin] if _allowed_origin else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Schemas ----------

class RequirementsIn(BaseModel):
    property_type: str = "EXISTING_BUILDING"   # EXISTING_BUILDING | OPEN_LAND
    max_auditoriums: int = 4
    franchise_tier_id: Optional[str] = None
    support_zone_area_overrides_sqft: dict = {}
    # Architect-confirmed clear height in feet — pre-filled by the frontend from
    # the project's intake beam_bottom_clear_height (free text, parsed
    # client-side) but always editable/confirmable here, never trusted blind.
    # Feeds VR_CLEAR_HEIGHT_EXISTING, which was previously always
    # INSUFFICIENT_DATA even when this value existed at intake.
    clear_height_ft: Optional[float] = None
    # Architect-marked main entrance, real user input (nothing in CAD
    # extraction detects doors) — feeds the SOP's entry-sightline placement
    # rules (spec M6) when present; those rules are skipped, not guessed
    # at, when this is None. Now captured at boundary-selection time
    # (BoundaryStudio), not just at this step — still stored here since it's
    # a real business input alongside the others, not CAD-derived geometry.
    entry_point_ft: Optional[Tuple[float, float]] = None
    # Architect-marked fire/emergency exit point(s), zero or more, same
    # honest "ask, don't guess" reasoning as entry_point_ft — feeds
    # layout_engine's entry-to-exit placement direction and its explicit
    # cross-movement check (spec SOP Sec 2.8: "no cross-movement between
    # entry/exit flows"). Optional: a floor's exits are frequently not yet
    # decided at zoning-design time, and the generator still produces a
    # real layout without them (falls back to entry-only orientation).
    exit_points_ft: Optional[List[Tuple[float, float]]] = None


class GeometryUpdateIn(BaseModel):
    regions: list


class ZoningRunIn(BaseModel):
    region_id: str


class CandidateSelectIn(BaseModel):
    candidate_id: str


class ManualRegionIn(BaseModel):
    points_ft: list
    mode: str = "draw"                    # "shape" | "walls" | "draw" — provenance only, for the review note
    source_shape_handle: Optional[str] = None  # when mode="shape", the all_closed_shapes handle it was picked from


class TraceBoundaryIn(BaseModel):
    segment_ids: list
    # A sub-portion of a single full_raw_geometry line the architect dragged
    # out directly (e.g. half of a long wall, when only part of it is
    # actually the boundary they want) rather than picking the whole
    # segment. Literal coordinates, not an id reference, since the point
    # is precisely that it's *not* one of the pre-computed whole segments.
    custom_segments: list = []


class UnitOverrideIn(BaseModel):
    unit: str  # one of cad_extraction.UNIT_NAME_TO_FEET's keys: Feet | Inches | Meters | Centimeters | Millimeters


class LayoutUpdateIn(BaseModel):
    rooms: list
    boundary_points_ft: list
    obstacles: list = []
    circulation_area_sqft: Optional[float] = None


class ExportIn(BaseModel):
    project_meta: dict
    sheet_type: str = "Zoning Layout"
    format: Optional[str] = "dxf"  # dxf | dwg (export/cad only)


def _build_measurements(requirements: dict, confirmed_obstacles: list, boundary_area_sqft: float,
                         total_seats: int, screen_count: int) -> dict:
    """Shared measurement builder for feasibility evaluation — used at run time,
    on every layout read, and on export, so the three call sites can't drift out
    of sync on which real signals get wired in."""
    column_points = [o["points_ft"] for o in confirmed_obstacles if o.get("classification") == "COLUMN"]
    grid_width, grid_length = layout_engine.estimate_column_grid_spacing(column_points)
    measurements = {
        "carpet_area_sqft": round(boundary_area_sqft, 2),
        "seats_per_screen": round(total_seats / screen_count, 2) if screen_count else 0,
        "total_project_seats": total_seats,
        "screen_count": screen_count,
    }
    if requirements.get("clear_height_ft") is not None:
        measurements["clear_height_ft"] = requirements["clear_height_ft"]
    if grid_width is not None:
        measurements["column_grid_width_ft"] = grid_width
        measurements["column_grid_length_ft"] = grid_length
    return measurements


# ---------- CAD upload & geometry confirmation ----------

@app.post("/api/projects/{project_id}/cad")
async def upload_cad(project_id: str, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".dwg", ".dxf"):
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload a .dwg or .dxf file.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Uploaded file is empty.")

    saved_path = storage.save_upload(project_id, file.filename, content)

    try:
        geometry = cad_extraction.extract(saved_path)
    except Exception as e:
        raise HTTPException(422, f"Could not extract geometry from this file: {e}")

    geometry["uploaded_filename"] = file.filename
    geometry["uploaded_at"] = storage.now_iso()
    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


@app.post("/api/projects/{project_id}/cad/ai-scan")
def ai_scan_cad(project_id: str):
    """Re-runs extraction on the already-uploaded file, but with Claude first
    picking which CAD layer(s) actually hold the wall/floor-boundary geometry
    — a dedicated alternative to the default full-drawing pass, for files
    where dimension/hatch/furniture layer noise buries the real boundary
    (confirmed against real client files where this recovers geometry the
    default pass found none of). Never fabricates geometry: only re-runs the
    same deterministic extractor cad_extraction.extract() already uses,
    scoped to Claude's chosen layers."""
    saved_path = None
    for ext in (".dwg", ".dxf"):
        candidate = storage.path_in(project_id, f"original{ext}")
        if os.path.isfile(candidate):
            saved_path = candidate
            break
    if not saved_path:
        raise HTTPException(404, "No CAD file has been uploaded for this project yet.")

    try:
        geometry = ai_cad_scan.ai_rescan(saved_path)
    except ai_cad_scan.AiCadScanError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(422, f"AI CAD scan failed: {e}")

    existing = storage.read_json(storage.geometry_path(project_id)) or {}
    geometry["uploaded_filename"] = existing.get("uploaded_filename", os.path.basename(saved_path))
    geometry["uploaded_at"] = storage.now_iso()
    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


@app.get("/api/projects/{project_id}/geometry")
def get_geometry(project_id: str):
    geom = storage.read_json(storage.geometry_path(project_id))
    if not geom:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    return geom


@app.post("/api/projects/{project_id}/geometry/ai-classify")
def ai_classify_geometry(project_id: str):
    """Improves classification of already-extracted obstacles that the
    deterministic layer-name heuristic couldn't confidently place — never
    invents or moves geometry, only assigns a real classification (or
    IGNORED, for a layer Claude judges non-physical) to a shape
    cad_extraction.py already found. See ai_obstacle_classify.py for the
    real evidence (up to 36% of obstacles unclassified on one real file)
    this responds to. Every result still requires the architect's own
    Confirm/Ignore before it can drive a zoning run."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")

    try:
        geometry = ai_obstacle_classify.classify_unclassified_obstacles(geometry)
    except ai_obstacle_classify.AiClassifyError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(422, f"AI obstacle classification failed: {e}")

    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


@app.put("/api/projects/{project_id}/geometry")
def update_geometry(project_id: str, body: GeometryUpdateIn):
    """Architect confirms/ignores detected boundary + obstacles (spec Sec 11:
    'Uncertain CAD detection must not silently become authoritative')."""
    existing = storage.read_json(storage.geometry_path(project_id))
    if not existing:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    existing["regions"] = body.regions
    storage.write_json(storage.geometry_path(project_id), existing)
    return existing


@app.post("/api/projects/{project_id}/cad/units")
def confirm_units(project_id: str, body: UnitOverrideIn):
    """An architect correcting a file whose $INSUNITS was unspecified (see
    cad_extraction._get_units) — re-runs extraction against the original
    upload at the confirmed scale, without needing to re-upload the file.
    Every region/full_raw_geometry number this project has depends on scale,
    so this replaces the whole geometry record rather than patching a field."""
    if body.unit not in cad_extraction.UNIT_NAME_TO_FEET:
        raise HTTPException(400, f"Unknown unit '{body.unit}'. Use one of: {list(cad_extraction.UNIT_NAME_TO_FEET)}.")
    original_path = storage.find_original_upload(project_id)
    if not original_path:
        raise HTTPException(404, "No CAD file has been uploaded for this project yet.")

    try:
        geometry = cad_extraction.extract(original_path, unit_override=body.unit)
    except Exception as e:
        raise HTTPException(422, f"Could not re-extract geometry at the confirmed unit: {e}")

    existing = storage.read_json(storage.geometry_path(project_id)) or {}
    geometry["uploaded_filename"] = existing.get("uploaded_filename")
    geometry["uploaded_at"] = existing.get("uploaded_at") or storage.now_iso()
    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


@app.post("/api/projects/{project_id}/boundary/trace")
def trace_boundary(project_id: str, body: TraceBoundaryIn):
    """Given wall-line segments an architect clicked in the raw CAD view,
    find the closed loop they form — the 'select lines to assume as walls'
    boundary-definition path, distinct from clicking an existing closed
    shape or drawing freehand (see build_manual_region)."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    try:
        return cad_extraction.trace_boundary_from_segments(
            geometry["full_raw_geometry"], body.segment_ids, body.custom_segments
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/projects/{project_id}/regions/manual")
def create_manual_region(project_id: str, body: ManualRegionIn):
    """Add a region from a boundary the architect defined directly (clicked
    shape / traced walls / freehand draw) rather than one the automatic
    heuristic proposed. Gets the same real obstacle-containment detection an
    automatic region does (see build_manual_region) and is appended to this
    project's regions exactly like an auto-detected one, so the existing
    Geometry Review step (confirm boundary, confirm/ignore each obstacle)
    works on it unchanged."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    try:
        region = cad_extraction.build_manual_region(
            body.points_ft, body.mode, geometry["full_raw_geometry"], existing_source_handle=body.source_shape_handle
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    geometry["regions"].append(region)
    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


# ---------- Requirements ----------

@app.put("/api/projects/{project_id}/requirements")
def set_requirements(project_id: str, body: RequirementsIn):
    data = body.model_dump()
    storage.write_json(storage.requirements_path(project_id), data)
    return data


@app.get("/api/projects/{project_id}/requirements")
def get_requirements(project_id: str):
    data = storage.read_json(storage.requirements_path(project_id))
    if not data:
        raise HTTPException(404, "No requirements set for this project yet.")
    return data


# ---------- Zoning run (real auto-layout + seats + feasibility) ----------

@app.post("/api/projects/{project_id}/zoning-runs")
def run_zoning(project_id: str, body: ZoningRunIn):
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    requirements = storage.read_json(storage.requirements_path(project_id))
    if not requirements:
        raise HTTPException(400, "Project requirements must be submitted before running zoning.")

    region = next((r for r in geometry["regions"] if r["region_id"] == body.region_id), None)
    if not region:
        raise HTTPException(404, f"Region '{body.region_id}' not found in this project's extracted geometry.")
    if region["boundary"]["status"] != "CONFIRMED":
        raise HTTPException(400, "The floor boundary must be CONFIRMED (not left PROPOSED) before a zoning run — "
                                  "uncertain CAD detection must not silently become authoritative.")

    confirmed_obstacle_records = [o for o in region["obstacles"] if o["status"] == "CONFIRMED"]
    unresolved = [o for o in region["obstacles"] if o["status"] == "PROPOSED"]

    # Full obstacle dicts (with classification), not bare points — layout_engine
    # needs classification to know which obstacles a room may legitimately
    # enclose (a confirmed COLUMN) vs which must keep blocking placement
    # (wall/stair/washroom/etc — see layout_engine.compute_usable_area).
    candidates = layout_engine.generate_candidates(region["boundary"]["points_ft"], confirmed_obstacle_records, requirements)

    for cand in candidates:
        measurements = _build_measurements(requirements, confirmed_obstacle_records, cand["boundary_area_sqft"],
                                            cand["total_seats"], cand["screen_count"])
        cand["feasibility"] = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
        cand["area_seat_chart"] = chart_engine.build_chart(cand)
        for room in cand["rooms"]:
            if room["room_type"].startswith("AUDITORIUM"):
                room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])

    run_id = uuid.uuid4().hex[:12]
    run_record = {
        "run_id": run_id,
        "region_id": body.region_id,
        "requirements": requirements,
        "unresolved_obstacle_count": len(unresolved),
        "candidates": candidates,
        "created_at": storage.now_iso()
    }
    storage.write_json(storage.run_path(project_id, run_id), run_record)
    storage.write_json(storage.latest_run_path(project_id), run_record)

    if candidates:
        best = max(candidates, key=lambda c: c["total_seats"])
        layout = {
            "region_id": body.region_id,
            "source_candidate_id": best["candidate_id"],
            "boundary_points_ft": region["boundary"]["points_ft"],
            "obstacles": [o for o in region["obstacles"] if o["status"] == "CONFIRMED"],
            "rooms": best["rooms"],
            "circulation_area_sqft": best["circulation_area_sqft"],
            # Previously dropped here — the candidate's own generation-time
            # warnings (undersized presets, unmarked entrance, low utilization
            # w/ real cause) never survived past selection, so the "Warnings &
            # Notes" panel had nothing to show for the common case of an
            # architect never touching the strategy switcher.
            "warnings": best.get("warnings", []),
            "revision": "R0",
            "updated_at": storage.now_iso()
        }
        storage.write_json(storage.layout_path(project_id), layout)

    return run_record


@app.get("/api/projects/{project_id}/zoning-runs/latest")
def get_latest_run(project_id: str):
    run = storage.read_json(storage.latest_run_path(project_id))
    if not run:
        raise HTTPException(404, "No zoning run has been executed for this project yet.")
    return run


# ---------- AI-assisted zoning (Claude proposes the layout directly) ----------

@app.post("/api/projects/{project_id}/ai-zoning-runs")
def run_ai_zoning(project_id: str, body: ZoningRunIn):
    """Same inputs/shape contract as /zoning-runs, but the candidate comes from
    ai_zoning_engine (Claude reasoning over the real floor geometry) instead of
    the deterministic packer. The resulting candidate is appended to the same
    latest-run record so the existing select-candidate/layout/export endpoints
    work on it completely unchanged."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    requirements = storage.read_json(storage.requirements_path(project_id))
    if not requirements:
        raise HTTPException(400, "Project requirements must be submitted before running zoning.")

    region = next((r for r in geometry["regions"] if r["region_id"] == body.region_id), None)
    if not region:
        raise HTTPException(404, f"Region '{body.region_id}' not found in this project's extracted geometry.")
    if region["boundary"]["status"] != "CONFIRMED":
        raise HTTPException(400, "The floor boundary must be CONFIRMED (not left PROPOSED) before a zoning run — "
                                  "uncertain CAD detection must not silently become authoritative.")

    confirmed_obstacle_records = [o for o in region["obstacles"] if o["status"] == "CONFIRMED"]

    try:
        candidate = ai_zoning_engine.generate_ai_candidate(region["boundary"]["points_ft"], confirmed_obstacle_records, requirements)
    except ai_zoning_engine.AiZoningError as e:
        raise HTTPException(502, str(e))

    measurements = _build_measurements(requirements, confirmed_obstacle_records, candidate["boundary_area_sqft"],
                                        candidate["total_seats"], candidate["screen_count"])
    candidate["feasibility"] = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
    candidate["area_seat_chart"] = chart_engine.build_chart(candidate)
    for room in candidate["rooms"]:
        if room["room_type"].startswith("AUDITORIUM"):
            room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])

    run = storage.read_json(storage.latest_run_path(project_id))
    if not run or run.get("region_id") != body.region_id:
        run = {
            "run_id": uuid.uuid4().hex[:12],
            "region_id": body.region_id,
            "requirements": requirements,
            "unresolved_obstacle_count": len([o for o in region["obstacles"] if o["status"] == "PROPOSED"]),
            "candidates": [],
            "created_at": storage.now_iso(),
        }
    # Replace a previous AI candidate rather than accumulating one per click —
    # only the deterministic candidates are meant to persist as a fixed pair.
    run["candidates"] = [c for c in run["candidates"] if c["strategy"] != "AI_ASSISTED"] + [candidate]
    storage.write_json(storage.run_path(project_id, run["run_id"]), run)
    storage.write_json(storage.latest_run_path(project_id), run)
    return run


# ---------- Editable layout ----------

@app.get("/api/projects/{project_id}/layout")
def get_layout(project_id: str):
    layout = storage.read_json(storage.layout_path(project_id))
    if not layout:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")
    return _enrich_layout(project_id, layout)


@app.post("/api/projects/{project_id}/layout/select-candidate")
def select_candidate(project_id: str, body: CandidateSelectIn):
    run = storage.read_json(storage.latest_run_path(project_id))
    if not run:
        raise HTTPException(404, "No zoning run exists for this project yet.")
    candidate = next((c for c in run["candidates"] if c["candidate_id"] == body.candidate_id), None)
    if not candidate:
        raise HTTPException(404, "Candidate not found in the latest zoning run.")

    geometry = storage.read_json(storage.geometry_path(project_id))
    region = next(r for r in geometry["regions"] if r["region_id"] == run["region_id"])
    layout = {
        "region_id": run["region_id"],
        "source_candidate_id": candidate["candidate_id"],
        "boundary_points_ft": region["boundary"]["points_ft"],
        "obstacles": [o for o in region["obstacles"] if o["status"] == "CONFIRMED"],
        "rooms": candidate["rooms"],
        "circulation_area_sqft": candidate["circulation_area_sqft"],
        "warnings": candidate.get("warnings", []),
        "revision": "R0",
        "updated_at": storage.now_iso()
    }
    storage.write_json(storage.layout_path(project_id), layout)
    return _enrich_layout(project_id, layout)


@app.put("/api/projects/{project_id}/layout")
def update_layout(project_id: str, body: LayoutUpdateIn):
    """Architect edit (move/resize/add/delete a zone). Real validation — an
    invalid edit (overlap, outside boundary, obstacle collision) is rejected with
    the specific reason, never silently accepted (Product Principle #4)."""
    existing = storage.read_json(storage.layout_path(project_id))
    if not existing:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")

    # body.obstacles carries classification (points_ft + classification), same
    # as generate_candidates below — validate_rooms only hard-blocks on
    # non-COLUMN obstacles (a room may legitimately enclose a column).
    validation = layout_engine.validate_rooms(body.boundary_points_ft, body.obstacles, body.rooms)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "Layout edit rejected — geometry validation failed.", "errors": validation["errors"]})

    # An architect dragging/resizing a room onto a confirmed column is allowed
    # (validate_rooms above only warns, doesn't block — see its own comment),
    # but the seat count and obstacle_note need to stay honest about it after
    # the edit too, not just at auto-layout time — recomputed per room below
    # from the real, current geometry rather than left stale from before the
    # edit.
    column_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in body.obstacles if o.get("classification") == "COLUMN"]
    for room in body.rooms:
        room_poly = layout_engine.poly_from_points(room["geometry_points_ft"])
        enclosed_area = sum(room_poly.intersection(cp).area for cp in column_polys) if column_polys else 0.0

        if room["room_type"].startswith("AUDITORIUM"):
            cfg = room.get("seat_config") or {}
            room["seat_estimate"] = seat_engine.estimate_seats(
                room["width_ft"], room["depth_ft"],
                primary_seat_type_id=cfg.get("primary_seat_type_id", seat_engine.DEFAULT_SEAT_TYPE_ID),
                secondary_seat_type_id=cfg.get("secondary_seat_type_id"),
                primary_ratio_pct=cfg.get("primary_ratio_pct", 100),
                enclosed_obstacle_area_sqft=enclosed_area,
            )
            room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])
            if room["seat_estimate"].get("note"):
                room["obstacle_note"] = room["seat_estimate"]["note"]
            else:
                room.pop("obstacle_note", None)
        elif enclosed_area > 0.5:
            room["obstacle_note"] = (
                f"{round(enclosed_area, 1)} sqft of confirmed obstacle(s) (e.g. a structural column) fall "
                f"inside this room's footprint — plan furniture/layout around the obstacle position(s)."
            )
        else:
            room.pop("obstacle_note", None)

    boundary_poly = layout_engine.poly_from_points(body.boundary_points_ft)
    room_area = sum(r["area_sqft"] for r in body.rooms)
    # A confirmed COLUMN is excluded here too — a room may now legitimately
    # enclose one, so it's no longer "lost" area the way a wall/stair/washroom
    # genuinely is (matches layout_engine.generate_candidate's own
    # fallback_poly-based usable-area accounting).
    non_column_obstacle_points = [o["points_ft"] for o in body.obstacles if o.get("classification") != "COLUMN"]
    obstacle_area = sum(layout_engine.poly_from_points(o).area for o in non_column_obstacle_points) if non_column_obstacle_points else 0
    circulation = body.circulation_area_sqft if body.circulation_area_sqft is not None else max(
        boundary_poly.area - room_area - obstacle_area, 0.0
    )

    updated = {
        "region_id": existing["region_id"],
        "source_candidate_id": existing.get("source_candidate_id"),
        "boundary_points_ft": body.boundary_points_ft,
        "obstacles": body.obstacles,
        "rooms": body.rooms,
        "circulation_area_sqft": round(circulation, 2),
        # Carried forward unchanged, not recomputed — these describe how the
        # auto-layout originally generated this candidate (unmarked entrance,
        # undersized presets, etc.), which a manual edit doesn't retroactively
        # change the truth of.
        "warnings": existing.get("warnings", []),
        "revision": existing.get("revision", "R0"),
        "updated_at": storage.now_iso()
    }
    storage.write_json(storage.layout_path(project_id), updated)
    return _enrich_layout(project_id, updated)


def _enrich_layout(project_id: str, layout: dict) -> dict:
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    candidate_shape = {
        "rooms": layout["rooms"],
        "circulation_area_sqft": layout["circulation_area_sqft"],
        "boundary_area_sqft": layout_engine.poly_from_points(layout["boundary_points_ft"]).area
    }
    total_seats = sum(r.get("seat_estimate", {}).get("seat_count", 0) for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM"))
    screen_count = len([r for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM")])
    measurements = _build_measurements(requirements, layout.get("obstacles", []), candidate_shape["boundary_area_sqft"],
                                        total_seats, screen_count)
    layout = dict(layout)
    layout["feasibility"] = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
    layout["area_seat_chart"] = chart_engine.build_chart(candidate_shape)
    layout["total_seats"] = total_seats
    layout["screen_count"] = screen_count
    return layout


# ---------- Export ----------

@app.post("/api/projects/{project_id}/export/pdf")
def export_pdf_endpoint(project_id: str, body: ExportIn):
    layout = storage.read_json(storage.layout_path(project_id))
    if not layout:
        raise HTTPException(404, "No editable layout exists for this project yet.")

    enriched = _enrich_with_requirements(project_id, layout)
    rev = _bump_revision(project_id)
    meta = dict(body.project_meta)
    meta["revision"] = rev
    meta["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    region_meta = {"net_usage_area_sqft": f"{layout_engine.poly_from_points(layout['boundary_points_ft']).area:,.0f}"}
    out_path = os.path.join(storage.export_dir(project_id), f"{project_id}_{body.sheet_type.replace(' ', '_')}_{rev}.pdf")
    export_pdf.render_pdf(meta, layout["boundary_points_ft"], layout["rooms"], enriched["area_seat_chart"], enriched["feasibility"],
                           out_path, body.sheet_type, obstacles=layout.get("obstacles"), region_meta=region_meta)
    storage.append_export_record(project_id, {
        "revision": rev, "sheet_type": body.sheet_type, "format": "pdf",
        "filename": os.path.basename(out_path), "generated_at": datetime.now(timezone.utc).isoformat(),
        "drawn_by": meta.get("drawn_by", "-"), "checked_by": meta.get("checked_by", "-"),
        "remarks": meta.get("remarks", "")
    })
    return FileResponse(out_path, filename=os.path.basename(out_path), media_type="application/pdf")


@app.post("/api/projects/{project_id}/export/cad")
def export_cad_endpoint(project_id: str, body: ExportIn):
    layout = storage.read_json(storage.layout_path(project_id))
    if not layout:
        raise HTTPException(404, "No editable layout exists for this project yet.")

    rev = _bump_revision(project_id)
    meta = dict(body.project_meta)
    meta["revision"] = rev
    meta["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out_path = os.path.join(storage.export_dir(project_id), f"{project_id}_ZoningLayout_{rev}.dxf")
    result = export_dxf.export_layout_to_dxf(meta, layout["boundary_points_ft"], layout["obstacles"], layout["rooms"], out_path, also_dwg=(body.format == "dwg"))

    if body.format == "dwg":
        if not result["dwg_path"]:
            raise HTTPException(500, f"DXF export succeeded but DWG conversion failed: {result['dwg_conversion_error']}")
        storage.append_export_record(project_id, {
            "revision": rev, "sheet_type": body.sheet_type, "format": "dwg",
            "filename": os.path.basename(result["dwg_path"]), "generated_at": datetime.now(timezone.utc).isoformat(),
            "drawn_by": meta.get("drawn_by", "-"), "checked_by": meta.get("checked_by", "-"),
            "remarks": meta.get("remarks", "")
        })
        return FileResponse(result["dwg_path"], filename=os.path.basename(result["dwg_path"]), media_type="application/octet-stream")

    storage.append_export_record(project_id, {
        "revision": rev, "sheet_type": body.sheet_type, "format": "dxf",
        "filename": os.path.basename(result["dxf_path"]), "generated_at": datetime.now(timezone.utc).isoformat(),
        "drawn_by": meta.get("drawn_by", "-"), "checked_by": meta.get("checked_by", "-"),
        "remarks": meta.get("remarks", "")
    })
    return FileResponse(result["dxf_path"], filename=os.path.basename(result["dxf_path"]), media_type="application/dxf")


@app.get("/api/projects/{project_id}/export-history")
def get_export_history(project_id: str):
    """Spec M9 deliverable: 'a project can show its full export history.'
    Every past PDF/DXF/DWG export, newest first, with the revision it was
    generated at and whatever drawn-by/checked-by/remarks were supplied."""
    return {"history": storage.read_export_history(project_id)}


def _enrich_with_requirements(project_id: str, layout: dict) -> dict:
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    total_seats = sum(r.get("seat_estimate", {}).get("seat_count", 0) for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM"))
    screen_count = len([r for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM")])
    boundary_area = layout_engine.poly_from_points(layout["boundary_points_ft"]).area
    measurements = _build_measurements(requirements, layout.get("obstacles", []), boundary_area, total_seats, screen_count)
    feasibility = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
    chart = chart_engine.build_chart({"rooms": layout["rooms"], "circulation_area_sqft": layout["circulation_area_sqft"]})
    return {"feasibility": feasibility, "area_seat_chart": chart}


def _bump_revision(project_id: str) -> str:
    layout = storage.read_json(storage.layout_path(project_id))
    current = layout.get("revision", "R0") if layout else "R0"
    n = int(current[1:]) + 1 if current.startswith("R") else 1
    new_rev = f"R{n}"
    if layout:
        layout["revision"] = new_rev
        storage.write_json(storage.layout_path(project_id), layout)
    return new_rev


@app.delete("/api/projects/{project_id}")
def delete_project_data(project_id: str):
    """Remove this project's uploaded CAD, geometry, zoning runs, layout and
    exports. Called alongside the project-service's own project delete so no
    orphaned files are left behind. Idempotent — deleting a project that never
    had any CAD/zoning data here is not an error."""
    import shutil
    d = storage.project_dir(project_id)
    shutil.rmtree(d, ignore_errors=True)
    return {"deleted": True}


@app.get("/api/seat-types")
def get_seat_types():
    """Seat types with enough real registry data to drive the packing math —
    what the architect can choose between when configuring an auditorium's
    seat mix at edit time (spec Sec 20: seat mix is user-configurable)."""
    return {"seat_types": seat_engine.selectable_seat_types()}


@app.get("/api/franchise-tiers")
def get_franchise_tiers():
    """Real registry data for the Requirements step's tier picker — the
    frontend previously hardcoded these area/screen ranges as static text,
    which had drifted out of sync with rules_registry_v1.json (e.g. showing
    Express as 2,500-7,000 sqft when the registry says 5,000-7,000)."""
    return {"franchise_tiers": rules_registry.franchise_tiers()}


@app.get("/api/health")
def health():
    return {"status": "ok"}
