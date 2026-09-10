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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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
import cad_cleaner

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
    # Real screen width, architect-entered — unlocks FIRST_ROW_DISTANCE_RULE
    # (SOP §4.4/§9: first-row distance >= screen width), previously
    # permanently un-evaluable with no captured input for it. When set,
    # seat_engine.estimate_seats() uses it (if larger) as the effective
    # front setback instead of the bare SCREEN_TO_BACK_WALL_MIN_FT minimum,
    # so the seat-packing math satisfies the rule by construction — see
    # layout_engine.py/seat_engine.py.
    screen_width_ft: Optional[float] = None


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
    # How many of this boundary's real gaps (see BoundaryTraceError) were
    # bridged with an architect-confirmed straight-line assumption rather
    # than an actual selected wall — carried through only so build_manual_region
    # can say so in the review note; never affects the geometry itself.
    closed_gap_count: int = 0


class TraceBoundaryIn(BaseModel):
    segment_ids: list
    # A sub-portion of a single full_raw_geometry line the architect dragged
    # out directly (e.g. half of a long wall, when only part of it is
    # actually the boundary they want) rather than picking the whole
    # segment. Literal coordinates, not an id reference, since the point
    # is precisely that it's *not* one of the pre-computed whole segments.
    custom_segments: list = []


class SearchLabelIn(BaseModel):
    query: str


class SearchAreaIn(BaseModel):
    target_area_sqft: float


class CleanSelectionIn(BaseModel):
    shape_handles: List[str]
    # The project's own intake-form Carpet Area / Floor-Shop-No, when the
    # frontend has them — see cad_cleaner._carpet_area_check.
    target_area_sqft: Optional[float] = None
    label_hint: Optional[str] = None


class UnitOverrideIn(BaseModel):
    unit: str  # one of cad_extraction.UNIT_NAME_TO_FEET's keys: Feet | Inches | Meters | Centimeters | Millimeters


class LayoutUpdateIn(BaseModel):
    rooms: list
    boundary_points_ft: list
    obstacles: list = []
    circulation_area_sqft: Optional[float] = None


class AddZoneIn(BaseModel):
    room_type: str  # AUDITORIUM | FOYER | FNB | WASHROOM | BOX_OFFICE | MANAGER_ROOM | BOH | ELECTRICAL | PROJECTOR | STORE_ROOM | PASSAGE


class ScreenWallUpdateIn(BaseModel):
    screen_wall: str  # one of "min_x" | "max_x" | "min_y" | "max_y"


class ExportIn(BaseModel):
    project_meta: dict
    sheet_type: str = "Zoning Layout"
    format: Optional[str] = "dxf"  # dxf | dwg (export/cad only)


def _build_measurements(requirements: dict, confirmed_obstacles: list, boundary_area_sqft: float,
                         total_seats: int, screen_count: int, rooms: list = None) -> dict:
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
    # VR_FIRST_ROW_DISTANCE's metric — derived, not a fixed registry
    # constant, since the underlying formula (first_row_distance_ft >=
    # screen_width_ft) compares two per-project measured values, which
    # feasibility_engine.evaluate_rule's fixed-threshold design doesn't
    # support directly. first_row_distance_ft is read straight from each
    # auditorium's already-computed seat_estimate (see
    # seat_engine.estimate_seats) — the smallest (worst-case) margin across
    # every screen is reported, same "don't hide a real problem behind an
    # average" convention as every other per-screen check in this file.
    screen_width_ft = requirements.get("screen_width_ft")
    if screen_width_ft and rooms:
        margins = [
            r["seat_estimate"]["first_row_distance_ft"] - screen_width_ft
            for r in rooms
            if r["room_type"].startswith("AUDITORIUM") and r.get("seat_estimate", {}).get("first_row_distance_ft") is not None
        ]
        if margins:
            measurements["first_row_margin_ft"] = round(min(margins), 2)
    # VR_LAST_ROW_DISTANCE's metric — general theater-design guidance
    # (SMPTE / British Standards BS 5588: a back-row seat past ~120 ft from
    # the screen loses legible facial expression), unconditionally
    # computable (unlike first_row_margin_ft above, needs no architect-
    # supplied screen_width_ft) since seat_engine.estimate_seats always
    # reports each room's own real packed seating depth. The worst
    # (largest, farthest-from-screen) value across auditoriums is reported
    # — same "don't hide a real problem behind an average" convention as
    # first_row_margin_ft's own worst-case (smallest-margin) reporting.
    if rooms:
        last_row_distances = [
            r["seat_estimate"]["last_row_distance_ft"]
            for r in rooms
            if r["room_type"].startswith("AUDITORIUM") and r.get("seat_estimate", {}).get("last_row_distance_ft") is not None
        ]
        if last_row_distances:
            measurements["last_row_distance_ft"] = round(max(last_row_distances), 2)
    # VR_SUPPORT_ZONE_AREA_SHARE's metric — the client's own notes give a
    # 30-40% target share of total usable area for every non-screen
    # component combined (Box Office/Foyer/F&B/Washroom/etc, including the
    # derived PASSAGE remainder) — computed here, not stored per-room, so it
    # always reflects the current room list rather than going stale.
    if rooms and boundary_area_sqft:
        support_zone_area_sqft = sum(r["area_sqft"] for r in rooms if not r["room_type"].startswith("AUDITORIUM"))
        measurements["support_zone_area_pct_of_carpet"] = round(support_zone_area_sqft / boundary_area_sqft * 100, 2)
    return measurements


# ---------- CAD upload & geometry confirmation ----------

@app.post("/api/projects/{project_id}/cad")
async def upload_cad(
    project_id: str, file: UploadFile = File(...),
    target_area_sqft: float = Form(None), label_hint: str = Form(None),
):
    """target_area_sqft/label_hint are optional — the frontend sends them
    from the project's own intake record (Carpet Area / Floor-Shop-No) when
    available, so the very first automatic candidate ranking already reflects
    what a salesperson already told the app about this property, instead of
    a blind size-only guess. See cad_extraction._form_match_info."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".dwg", ".dxf"):
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload a .dwg or .dxf file.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Uploaded file is empty.")

    saved_path = storage.save_upload(project_id, file.filename, content)

    try:
        geometry = cad_extraction.extract(saved_path, target_area_sqft=target_area_sqft, label_hint=label_hint)
    except Exception as e:
        raise HTTPException(422, f"Could not extract geometry from this file: {e}")

    geometry["uploaded_filename"] = file.filename
    geometry["uploaded_at"] = storage.now_iso()
    storage.write_json(storage.geometry_path(project_id), geometry)
    return geometry


@app.post("/api/projects/{project_id}/cad/ai-scan")
def ai_scan_cad(project_id: str, target_area_sqft: float = None, label_hint: str = None):
    """Re-runs extraction on the already-uploaded file, but with Claude first
    picking which CAD layer(s) actually hold the wall/floor-boundary geometry
    — a dedicated alternative to the default full-drawing pass, for files
    where dimension/hatch/furniture layer noise buries the real boundary
    (confirmed against real client files where this recovers geometry the
    default pass found none of). Never fabricates geometry: only re-runs the
    same deterministic extractor cad_extraction.extract() already uses,
    scoped to Claude's chosen layers.

    target_area_sqft/label_hint (optional query params, same intake-form
    values the original upload used) are passed straight through so a
    re-scan keeps the same form-driven ranking — see upload_cad above."""
    saved_path = None
    for ext in (".dwg", ".dxf"):
        candidate = storage.path_in(project_id, f"original{ext}")
        if os.path.isfile(candidate):
            saved_path = candidate
            break
    if not saved_path:
        raise HTTPException(404, "No CAD file has been uploaded for this project yet.")

    try:
        geometry = ai_cad_scan.ai_rescan(saved_path, target_area_sqft=target_area_sqft, label_hint=label_hint)
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


@app.post("/api/projects/{project_id}/clean/search-label")
def clean_search_label(project_id: str, body: SearchLabelIn):
    """Form-based boundary selection for the Clean CAD stage: a salesperson
    types a room/space label (e.g. 'Screen 1', 'Suite 200') and this finds
    every matching text already drawn in the file, each paired with its
    smallest enclosing closed shape — see cad_cleaner.search_labels."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    return {"matches": cad_cleaner.search_labels(geometry["full_raw_geometry"], body.query)}


@app.post("/api/projects/{project_id}/clean/search-area")
def clean_search_area(project_id: str, body: SearchAreaIn):
    """Proactive boundary suggestion for the Clean CAD stage, driven by the
    project's own intake Carpet Area — see cad_cleaner.search_by_area."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    return {"matches": cad_cleaner.search_by_area(geometry["full_raw_geometry"], body.target_area_sqft)}


@app.post("/api/projects/{project_id}/clean/preview")
def clean_preview(project_id: str, body: CleanSelectionIn):
    """Live before/after readout for one or more selected closed shapes
    (need not be adjacent or connected) before the salesperson commits —
    never silently trusted, per this app's own confirm-before-authoritative
    convention, just simplified for this stage's non-architect audience."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    try:
        regions = cad_cleaner.build_clean_regions(geometry["full_raw_geometry"], body.shape_handles)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"regions": cad_cleaner.preview_summary(regions, target_area_sqft=body.target_area_sqft, label_hint=body.label_hint)}


@app.post("/api/projects/{project_id}/clean/confirm")
def clean_confirm(project_id: str, body: CleanSelectionIn):
    """Finalizes the selected boundary(ies): exports a clean DXF/DWG
    containing only the outline plus kept COLUMN/DUCT obstacles, then
    re-runs the normal extraction pipeline against that clean file and
    overwrites geometry.json — the hand-off point into the existing,
    untouched Geometry Review step. Response shape matches POST .../cad
    exactly so the frontend can transition the same way it does after a
    normal upload."""
    geometry = storage.read_json(storage.geometry_path(project_id))
    if not geometry or not geometry.get("full_raw_geometry"):
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")

    try:
        regions = cad_cleaner.build_clean_regions(geometry["full_raw_geometry"], body.shape_handles)
    except ValueError as e:
        raise HTTPException(422, str(e))

    export_result = cad_cleaner.export_clean_cad(regions, storage.clean_dxf_path(project_id), also_dwg=True)

    try:
        # A lower boundary-area floor than the default (150 sqft, sized to
        # reject furniture-scale junk in an arbitrary raw upload) — a clean
        # file's OUTLINE layer was already deliberately chosen by the user
        # in Clean CAD, not a heuristic guess, so there's no "furniture
        # mistaken for a floor plate" risk to guard against here. Without
        # this, cleaning a legitimately small room (a real case: a 51.5 sqft
        # toilet) produced "no candidate boundary was found automatically"
        # on re-extraction even though the outline was right there, forcing
        # an extra manual "Select Closed Shape" click to recover it.
        clean_geometry = cad_extraction.extract(export_result["dxf_path"], min_boundary_area_sqft=cad_cleaner.MIN_CLEAN_BOUNDARY_AREA_SQFT)
    except Exception as e:
        raise HTTPException(422, f"Cleaned file could not be re-extracted: {e}")

    clean_geometry["uploaded_filename"] = geometry.get("uploaded_filename")
    clean_geometry["uploaded_at"] = storage.now_iso()
    clean_geometry["cleaned_from_regions"] = [r["region_id"] for r in regions]
    storage.write_json(storage.geometry_path(project_id), clean_geometry)
    return clean_geometry


@app.get("/api/projects/{project_id}/clean/download")
def clean_download(project_id: str, format: str = "dxf"):
    """Lets a salesperson download the cleaned file directly, without
    necessarily continuing into the zoning pipeline."""
    if format not in ("dxf", "dwg"):
        raise HTTPException(400, "format must be 'dxf' or 'dwg'.")
    path = storage.clean_dxf_path(project_id) if format == "dxf" else storage.clean_dwg_path(project_id)
    if not os.path.isfile(path):
        raise HTTPException(404, f"No clean .{format} file exists yet for this project — run Clean & Continue first.")
    media_type = "application/dxf" if format == "dxf" else "application/octet-stream"
    return FileResponse(path, filename=os.path.basename(path), media_type=media_type)


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
    except cad_extraction.BoundaryTraceError as e:
        # detail is a dict, not a bare string, so the frontend can draw the
        # real gap points on the canvas instead of just showing text — see
        # BoundaryTraceError's own docstring for why this beats a generic
        # "there's a gap somewhere" message. gap_pairs_ft additionally lets
        # it offer a real "close this gap" action per pair, with the actual
        # distance shown — never auto-applied server-side, see that
        # function's own docstring for why.
        raise HTTPException(422, {"message": str(e), "gap_points_ft": e.gap_points_ft, "gap_pairs_ft": e.gap_pairs_ft})
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
            body.points_ft, body.mode, geometry["full_raw_geometry"],
            existing_source_handle=body.source_shape_handle, closed_gap_count=body.closed_gap_count
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


def _candidate_geometry_errors(boundary_points_ft, confirmed_obstacles, candidate_rooms):
    """Shared validation gate used before a generated candidate (from any of
    the three engines — deterministic packer, AI-assisted, or CP-SAT
    optimizer) is allowed to become the saved editable layout. Returns a
    list of validate_rooms-style error dicts, or None if the candidate is
    geometrically clean.

    Exists because update_layout re-validates the WHOLE room list on every
    single edit (see its own docstring) — if a defective candidate were ever
    saved unvalidated, the first edit attempt afterward would reject over
    rooms the architect never touched, permanently blocking editing with no
    diagnostic trail. That exact symptom already happened once for real, via
    a stale Passage (now fixed by making Passage derived instead of stored;
    this room type was called Foyer at the time — see rules_registry_v1.json's
    support_zone_defaults entries for the 2026-09-10 terminology swap); this
    closes the same failure mode for every other room type, defensively —
    not because it's been observed on a real project, but because the
    placement engine is complex enough that a future regression could produce
    one (see this session's own top_k-starvation bug for how a placement bug
    can slip past code review and unit tests until it's live)."""
    real_rooms = [r for r in candidate_rooms if r["room_type"] != "PASSAGE"]
    validation = layout_engine.validate_rooms(boundary_points_ft, confirmed_obstacles, real_rooms)
    return None if validation["valid"] else validation["errors"]


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
                                            cand["total_seats"], cand["screen_count"], cand["rooms"])
        cand["feasibility"] = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
        cand["area_seat_chart"] = chart_engine.build_chart(cand)
        for room in cand["rooms"]:
            if room["room_type"].startswith("AUDITORIUM"):
                room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])
        cand["internal_geometry_error"] = _candidate_geometry_errors(
            region["boundary"]["points_ft"], confirmed_obstacle_records, cand["rooms"]
        )

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

    # Never auto-select a candidate with a real geometry defect as the
    # editable layout — see the internal_geometry_error comment above. A
    # defective candidate is still returned in run_record for inspection
    # (the frontend can show it, disabled), just never silently saved as
    # the thing an architect starts editing.
    valid_candidates = [c for c in candidates if c.get("internal_geometry_error") is None]
    if valid_candidates:
        best = max(valid_candidates, key=lambda c: c["total_seats"])
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
                                        candidate["total_seats"], candidate["screen_count"], candidate["rooms"])
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


# ---------- Optimizer (CP-SAT "Optimize Layout") ----------

@app.post("/api/projects/{project_id}/zoning-runs/optimize")
def run_optimized_zoning(project_id: str, body: ZoningRunIn):
    """Same inputs/shape contract as /zoning-runs and /ai-zoning-runs, but
    the candidate comes from placement.solver's CP-SAT combinatorial
    optimizer (layout_engine.generate_optimized_candidate) instead of the
    deterministic greedy packer or Claude. Deliberately its own endpoint,
    not folded into /zoning-runs' own candidate pair — CP-SAT can take real
    time on a hard instance (placement.solver.TIME_LIMIT_SECONDS), so this
    is an explicit, opt-in action the architect requests. Appends to the
    same latest-run record so the existing select-candidate/layout/export
    endpoints work on it completely unchanged."""
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
    boundary_points_ft = region["boundary"]["points_ft"]
    usable_poly = layout_engine.compute_usable_area(boundary_points_ft, confirmed_obstacle_records)
    if usable_poly.is_empty or usable_poly.area <= 0:
        raise HTTPException(400, "No usable area remains after confirmed obstacles are subtracted.")

    candidate = layout_engine.generate_optimized_candidate(usable_poly, boundary_points_ft, requirements,
                                                             confirmed_obstacle_records)

    measurements = _build_measurements(requirements, confirmed_obstacle_records, candidate["boundary_area_sqft"],
                                        candidate["total_seats"], candidate["screen_count"], candidate["rooms"])
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
    # Replace a previous optimized candidate rather than accumulating one per
    # click — same convention as the AI-assisted candidate above.
    run["candidates"] = [c for c in run["candidates"] if c["strategy"] != "OPTIMIZED"] + [candidate]
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

    # Validated fresh here rather than trusting a stored internal_geometry_error
    # field, since this candidate may have come from the deterministic packer,
    # the AI-assisted engine, or the CP-SAT optimizer (ai-zoning-runs and
    # zoning-runs/optimize don't set that field at all) — whichever engine
    # produced it, a real overlap must never get saved as the editable layout
    # unvalidated (see _candidate_geometry_errors for why).
    confirmed_obstacle_records = [o for o in region["obstacles"] if o["status"] == "CONFIRMED"]
    errors = _candidate_geometry_errors(region["boundary"]["points_ft"], confirmed_obstacle_records, candidate["rooms"])
    if errors is not None:
        raise HTTPException(500, {
            "message": "This candidate has an internal geometry defect and can't be selected as the editable "
                       "layout — this is an engine bug, not something wrong with your project. Try the other "
                       "strategy or re-run zoning.",
            "errors": errors,
        })

    # Same Passage hierarchy check _replace_passage_with_derived runs on every
    # later edit — checked here too so a freshly selected, never-yet-edited
    # candidate carries it from the start rather than only appearing after
    # the first manual change.
    passage_room = next((r for r in candidate["rooms"] if r["room_type"] == "PASSAGE"), None)
    other_rooms = [r for r in candidate["rooms"] if r["room_type"] != "PASSAGE"]
    passage_warning = _passage_hierarchy_warning(passage_room, other_rooms)

    layout = {
        "region_id": run["region_id"],
        "source_candidate_id": candidate["candidate_id"],
        "boundary_points_ft": region["boundary"]["points_ft"],
        "obstacles": confirmed_obstacle_records,
        "rooms": candidate["rooms"],
        "circulation_area_sqft": candidate["circulation_area_sqft"],
        "warnings": candidate.get("warnings", []) + ([passage_warning] if passage_warning else []),
        "revision": "R0",
        "updated_at": storage.now_iso()
    }
    storage.write_json(storage.layout_path(project_id), layout)
    return _enrich_layout(project_id, layout)


def _screen_wall_door_conflict_note(room):
    """Real cinema design never puts an entry/exit on the projection
    wall (see layout_engine._screen_wall_for_rect's own docstring: the
    screen and the doors patrons walk in through are always opposite walls,
    never the same one). A soft, per-room note — like obstacle_note/
    screen_width_note — not a hard block: the architect may be mid-edit
    (about to move the door, or the screen wall, next) and rejecting the
    edit outright would be more disruptive than just flagging it."""
    conflicting = [d for d in room.get("doors", []) if d.get("wall") == room.get("screen_wall")]
    if not conflicting:
        return None
    return (
        f"{len(conflicting)} door(s) are on this room's screen wall — real cinema design keeps "
        f"entries off the projection wall. Move the door(s) or reassign the screen wall before finalizing."
    )


def _recompute_room_derived_fields(room: dict, column_polys: list, screen_width_ft: float = None, entry_point=None):
    """Recomputes a room's seat_estimate/preset_fit/obstacle_note from its
    current, real geometry — shared by update_layout (an architect's
    move/resize/edit), add_zone (a freshly placed room), and
    update_screen_wall (a reassigned screen) so all three paths stay honest
    about a room that now encloses a confirmed column, carries a door too
    close to itself, or has changed which wall its screen is on, rather than
    leaving a stale value from before the edit/placement.

    Real, reported defect this also fixes: reshaping an auditorium (a drag-
    resize) used to leave screen_wall pointing at whatever wall was nearest
    the entry at PLACEMENT time, even after the reshape made a different
    wall the sensible one — doors stayed geometrically valid (re-clamped to
    their own wall's new length below) but could end up "on the right wall
    for a shape that no longer exists." Unless the architect has explicitly
    pinned it via update_screen_wall (screen_wall_manual, set only there),
    screen_wall is now recomputed here from the room's CURRENT bbox the
    exact same way _build_auditorium_room derives it at placement time —
    same _screen_wall_for_rect + _OPPOSITE_WALL pair, just re-run on demand.
    Doors themselves are still only re-clamped (offset/width to the
    possibly-now-different wall length), never silently moved to a new
    wall — _screen_wall_door_conflict_note below is the safety net for
    whatever that leaves inconsistent, same as before this fix."""
    if (room.get("room_type", "").startswith("AUDITORIUM") and not room.get("screen_wall_manual")
            and entry_point is not None and room.get("origin_ft") is not None):
        x, y = room["origin_ft"]
        door_wall = layout_engine._screen_wall_for_rect(x, y, room["width_ft"], room["depth_ft"], entry_point, restrict_to_depth_axis=True)
        room["screen_wall"] = layout_engine._OPPOSITE_WALL[door_wall]

    room_poly = layout_engine.poly_from_points(room["geometry_points_ft"])
    enclosed_area = sum(room_poly.intersection(cp).area for cp in column_polys) if column_polys else 0.0

    if room["room_type"].startswith("AUDITORIUM"):
        layout_engine._clamp_doors_to_room(room)
        cfg = room.get("seat_config") or {}
        screen_wall = room.get("screen_wall") or "min_y"
        span_ft, seat_depth_ft = layout_engine._seat_axis_dims(room["width_ft"], room["depth_ft"], screen_wall)
        lateral_clearance_ft = rules_registry.planning_norm("DOOR_SEAT_LATERAL_CLEARANCE_FT") or 2.5
        side_exclusions = layout_engine._side_door_exclusions(
            room["width_ft"], room["depth_ft"], screen_wall, room.get("doors", []), lateral_clearance_ft
        )
        room["seat_estimate"] = seat_engine.estimate_seats(
            span_ft, seat_depth_ft,
            primary_seat_type_id=cfg.get("primary_seat_type_id", seat_engine.DEFAULT_SEAT_TYPE_ID),
            secondary_seat_type_id=cfg.get("secondary_seat_type_id"),
            primary_ratio_pct=cfg.get("primary_ratio_pct", 100),
            front_row_count=cfg.get("front_row_count"),
            enclosed_obstacle_area_sqft=enclosed_area,
            screen_width_ft=screen_width_ft,
            side_exclusions=side_exclusions,
        )
        room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])
        if room["seat_estimate"].get("note"):
            room["obstacle_note"] = room["seat_estimate"]["note"]
        else:
            room.pop("obstacle_note", None)
        conflict_note = _screen_wall_door_conflict_note(room)
        if conflict_note:
            room["screen_wall_note"] = conflict_note
        else:
            room.pop("screen_wall_note", None)
    elif enclosed_area > 0.5:
        room["obstacle_note"] = (
            f"{round(enclosed_area, 1)} sqft of confirmed obstacle(s) (e.g. a structural column) fall "
            f"inside this room's footprint — plan furniture/layout around the obstacle position(s)."
        )
    else:
        room.pop("obstacle_note", None)


@app.put("/api/projects/{project_id}/layout")
def update_layout(project_id: str, body: LayoutUpdateIn):
    """Architect edit (move/resize/add/delete a zone). Real validation — an
    invalid edit (overlap, outside boundary, obstacle collision) is rejected with
    the specific reason, never silently accepted (Product Principle #4).

    PASSAGE is never part of what's validated or stored here — see
    _replace_passage_with_derived's own docstring for why: it's always
    recomputed as the real leftover remainder after every other room in
    body.rooms, the same way generate_candidate's own auto-layout pass
    already does, so it can never be the thing an edit gets rejected for."""
    existing = storage.read_json(storage.layout_path(project_id))
    if not existing:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")

    real_rooms = [r for r in body.rooms if r["room_type"] != "PASSAGE"]

    # body.obstacles carries classification (points_ft + classification), same
    # as generate_candidates below — validate_rooms only hard-blocks on
    # non-COLUMN obstacles (a room may legitimately enclose a column).
    validation = layout_engine.validate_rooms(body.boundary_points_ft, body.obstacles, real_rooms)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "Layout edit rejected — geometry validation failed.", "errors": validation["errors"]})

    # An architect dragging/resizing a room onto a confirmed column is allowed
    # (validate_rooms above only warns, doesn't block — see its own comment),
    # but the seat count and obstacle_note need to stay honest about it after
    # the edit too, not just at auto-layout time — recomputed per room below
    # from the real, current geometry rather than left stale from before the
    # edit.
    column_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in body.obstacles if o.get("classification") == "COLUMN"]
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    for room in real_rooms:
        _recompute_room_derived_fields(room, column_polys, screen_width_ft=requirements.get("screen_width_ft"),
                                        entry_point=requirements.get("entry_point_ft"))

    final_rooms, circulation, passage_warning = _replace_passage_with_derived(body.boundary_points_ft, body.obstacles, real_rooms, requirements)

    updated = {
        "region_id": existing["region_id"],
        "source_candidate_id": existing.get("source_candidate_id"),
        "boundary_points_ft": body.boundary_points_ft,
        "obstacles": body.obstacles,
        "rooms": final_rooms,
        "circulation_area_sqft": round(circulation, 2),
        # existing warnings are carried forward unchanged, not recomputed —
        # they describe how the auto-layout originally generated this
        # candidate (unmarked entrance, undersized presets, etc.), which a
        # manual edit doesn't retroactively change the truth of. The Passage
        # hierarchy warning is the one exception: recomputed fresh on every
        # edit (it describes the layout's CURRENT state, not how it was
        # generated) — any stale copy from a previous edit is dropped first
        # (see _is_passage_hierarchy_warning) so it can't accumulate duplicates
        # across repeated edits instead of just reflecting the latest check.
        "warnings": [w for w in existing.get("warnings", []) if not _is_passage_hierarchy_warning(w)] + ([passage_warning] if passage_warning else []),
        "revision": existing.get("revision", "R0"),
        "updated_at": storage.now_iso()
    }
    storage.write_json(storage.layout_path(project_id), updated)
    return _enrich_layout(project_id, updated)


_PASSAGE_HIERARCHY_WARNING_PREFIX = "Passage ("


def _is_passage_hierarchy_warning(warning_text):
    """Identifies a previously-persisted _passage_hierarchy_warning string so
    it can be dropped before appending a freshly-recomputed one — both
    callers persist the layout's `warnings` list across edits, and this
    warning (unlike the others in that list) needs to reflect current state,
    not accumulate a stale copy from every past edit."""
    return warning_text.startswith(_PASSAGE_HIERARCHY_WARNING_PREFIX)


def _passage_hierarchy_warning(passage_room, real_rooms):
    """Team's own placement standards: Passage (the derived leftover-
    remainder room — called Foyer before the 2026-09-10 terminology swap)
    has no fixed min/max, but must be larger than every auxiliary
    (non-auditorium) room and smaller than every auditorium — a soft check
    ("warnings, not blockers," per the same document), not enforced by
    construction, since Passage is whatever real area happens to be left
    over once everything else is placed. Returns a plain-English warning
    string, or None when the hierarchy holds (or there's nothing real to
    compare against yet)."""
    if not passage_room:
        return None
    passage_area = passage_room["area_sqft"]
    auxiliary_areas = [r["area_sqft"] for r in real_rooms if not r["room_type"].startswith("AUDITORIUM")]
    auditorium_areas = [r["area_sqft"] for r in real_rooms if r["room_type"].startswith("AUDITORIUM")]
    if auxiliary_areas and passage_area < max(auxiliary_areas):
        biggest = max(auxiliary_areas)
        return (
            f"Passage ({passage_area:,.0f} sqft) is smaller than another support zone ({biggest:,.0f} sqft) — "
            f"the team's own placement standards call for Passage to be the largest non-auditorium space."
        )
    if auditorium_areas and passage_area > min(auditorium_areas):
        smallest = min(auditorium_areas)
        return (
            f"Passage ({passage_area:,.0f} sqft) is larger than an auditorium ({smallest:,.0f} sqft) — "
            f"the team's own placement standards call for Passage to stay smaller than every auditorium."
        )
    return None


def _replace_passage_with_derived(boundary_points_ft, obstacles, real_rooms, requirements):
    """PASSAGE is never a room an architect (or auto-layout) independently
    places or resizes — it's always whatever contiguous usable area is left
    once every other room is accounted for (see layout_engine._build_passage_room,
    already used by generate_candidate's own auto-layout pass). Called from
    both update_layout and add_zone right after real_rooms is finalized, so
    Passage can never go stale or overlap anything: it's derived fresh from
    the ACTUAL current room list every single time, not stored and
    validated like an ordinary room. Returns (rooms_with_fresh_passage,
    circulation_area_sqft, passage_hierarchy_warning_or_None) — the area is
    _build_passage_room's own leftover_slack (the real, small, genuinely-
    disconnected pockets Passage itself didn't claim), not a coarse
    boundary-minus-rooms estimate; the warning is recomputed fresh every
    call (unlike the layout's other, frozen-at-generation-time warnings —
    see both call sites), since an edit can easily change whether Passage's
    hierarchy still holds. (This room type was called FOYER before the
    2026-09-10 terminology swap — see rules_registry_v1.json's
    support_zone_defaults entries.)"""
    fallback_poly = layout_engine.compute_usable_area(boundary_points_ft, obstacles, exclude_classifications=("COLUMN",)) if obstacles else layout_engine.poly_from_points(boundary_points_ft)
    real_room_polys = [layout_engine.poly_from_points(r["geometry_points_ft"]) for r in real_rooms]
    entry_point = requirements.get("entry_point_ft") if requirements else None
    passage_room, leftover_slack = layout_engine._build_passage_room(fallback_poly, real_room_polys, real_rooms, entry_point)
    final_rooms = real_rooms + ([passage_room] if passage_room else [])
    return final_rooms, leftover_slack, _passage_hierarchy_warning(passage_room, real_rooms)


@app.post("/api/projects/{project_id}/layout/zones")
def add_zone(project_id: str, body: AddZoneIn):
    """Adds exactly one new room to the current layout at a real, collision-free
    position found by layout_engine.place_single_zone — the same entry-aware
    scan-and-fit machinery auto-layout itself uses for screens, run against the
    layout's actual current rooms/obstacles. Replaces the frontend's old blind
    fixed-corner placement, which had no collision awareness at all and relied
    on this endpoint's sibling (update_layout)'s validation to reject the
    overlap it produced almost every time.

    Rejects with an honest 422 (never invents a placement that doesn't fit —
    Product Principle #4) when nothing fits anywhere for this zone type.

    PASSAGE can't be requested here — see _replace_passage_with_derived's own
    docstring: it's never independently placed, always recomputed as the
    real leftover remainder after this call's real_rooms is finalized."""
    if body.room_type == "PASSAGE":
        raise HTTPException(422, "Passage is computed automatically from the remaining space — it can't be added manually.")

    existing = storage.read_json(storage.layout_path(project_id))
    if not existing:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")

    boundary_points_ft = existing["boundary_points_ft"]
    obstacles = existing.get("obstacles", [])
    real_rooms = [r for r in existing["rooms"] if r["room_type"] != "PASSAGE"]
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}

    usable_poly = layout_engine.compute_usable_area(boundary_points_ft, obstacles)
    fallback_poly = layout_engine.compute_usable_area(boundary_points_ft, obstacles, exclude_classifications=("COLUMN",)) if obstacles else usable_poly
    column_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in obstacles if o.get("classification") == "COLUMN"]
    duct_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in obstacles if o.get("classification") == "DUCT"]
    bbox = layout_engine.poly_from_points(boundary_points_ft).bounds

    placed_polys = [layout_engine.poly_from_points(r["geometry_points_ft"]) for r in real_rooms]
    placed_types = ["AUDITORIUM" if r["room_type"].startswith("AUDITORIUM") else r["room_type"] for r in real_rooms]

    room, message = layout_engine.place_single_zone(
        usable_poly, fallback_poly, column_polys, placed_polys, placed_types, bbox,
        body.room_type, requirements, franchise_tier_id=requirements.get("franchise_tier_id"), duct_polys=duct_polys
    )
    if not room:
        raise HTTPException(422, message)

    _recompute_room_derived_fields(room, column_polys, screen_width_ft=requirements.get("screen_width_ft"),
                                    entry_point=requirements.get("entry_point_ft"))
    real_rooms = real_rooms + [room]

    final_rooms, circulation, passage_warning = _replace_passage_with_derived(boundary_points_ft, obstacles, real_rooms, requirements)

    updated = {
        "region_id": existing["region_id"],
        "source_candidate_id": existing.get("source_candidate_id"),
        "boundary_points_ft": boundary_points_ft,
        "obstacles": obstacles,
        "rooms": final_rooms,
        "circulation_area_sqft": round(circulation, 2),
        # See update_layout's identical handling above — the Passage hierarchy
        # warning is recomputed fresh every call, so any stale copy from a
        # previous edit/add is dropped before appending the current one.
        "warnings": [w for w in existing.get("warnings", []) if not _is_passage_hierarchy_warning(w)] + ([passage_warning] if passage_warning else []),
        "revision": existing.get("revision", "R0"),
        "updated_at": storage.now_iso()
    }
    storage.write_json(storage.layout_path(project_id), updated)
    return _enrich_layout(project_id, updated)


_VALID_SCREEN_WALLS = ("min_x", "max_x", "min_y", "max_y")


@app.post("/api/projects/{project_id}/layout/rooms/{room_id}/screen-wall")
def update_screen_wall(project_id: str, room_id: str, body: ScreenWallUpdateIn):
    """Re-orients an already-placed screen: which of the room's own 4 walls
    is the real projection-screen wall. width_ft/depth_ft/geometry_points_ft
    never change here — the room's box footprint is exactly the same either
    way, only the label of which wall the screen sits on. That's enough:
    _recompute_room_derived_fields (via _seat_axis_dims) reads screen_wall to
    decide which raw box extent feeds seat_engine as the screen-parallel
    span vs. the audience depth, so this one field flip is what actually
    changes the seat estimate — a genuine 90-degree reorientation onto an
    adjacent wall recomputes seat rows/columns along the other axis, and
    reassigning to the opposite wall keeps the same axis (just flips which
    end the screen is at). A narrow, single-field, single-room endpoint
    rather than folding this into the generic layout PUT (which re-validates
    every other room's geometry too) — same reasoning as add_zone being its
    own endpoint rather than a special case of update_layout.

    Nothing is written on any rejection here (unknown room/invalid wall) —
    the frontend's existing revert-on-rejection handling for every other
    committed edit (ZoningWorkspace.persistLayout's catch path) applies
    unchanged, satisfying the same "never leave an edit half-applied" rule
    every other write path in this file already follows."""
    if body.screen_wall not in _VALID_SCREEN_WALLS:
        raise HTTPException(422, f"screen_wall must be one of {', '.join(_VALID_SCREEN_WALLS)}.")

    existing = storage.read_json(storage.layout_path(project_id))
    if not existing:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")

    room = next((r for r in existing["rooms"] if r["room_id"] == room_id), None)
    if not room or not room["room_type"].startswith("AUDITORIUM"):
        raise HTTPException(404, "No auditorium with that room_id in this layout.")

    room["screen_wall"] = body.screen_wall
    # Marks this architect's choice as deliberate so _recompute_room_derived_fields
    # never silently overrides it on a later reshape (see that function's own
    # docstring) — the whole point of this endpoint existing is that the
    # architect is overriding the auto-derived wall, not proposing a new
    # auto-derivation.
    room["screen_wall_manual"] = True
    obstacles = existing.get("obstacles", [])
    column_polys = [layout_engine.poly_from_points(o["points_ft"]) for o in obstacles if o.get("classification") == "COLUMN"]
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    _recompute_room_derived_fields(room, column_polys, screen_width_ft=requirements.get("screen_width_ft"),
                                    entry_point=requirements.get("entry_point_ft"))

    existing["updated_at"] = storage.now_iso()
    storage.write_json(storage.layout_path(project_id), existing)
    return _enrich_layout(project_id, existing)


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
                                        total_seats, screen_count, layout["rooms"])
    entry_point = requirements.get("entry_point_ft")
    exit_points = requirements.get("exit_points_ft") or []
    layout = dict(layout)
    layout["feasibility"] = feasibility_engine.evaluate(requirements.get("property_type", "EXISTING_BUILDING"), measurements)
    layout["area_seat_chart"] = chart_engine.build_chart(candidate_shape)
    layout["total_seats"] = total_seats
    layout["screen_count"] = screen_count
    layout["entry_point_ft"] = entry_point
    layout["exit_points_ft"] = exit_points
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

    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    entry_point = requirements.get("entry_point_ft")
    exit_points = requirements.get("exit_points_ft") or []

    region_meta = {"net_usage_area_sqft": f"{layout_engine.poly_from_points(layout['boundary_points_ft']).area:,.0f}"}
    out_path = os.path.join(storage.export_dir(project_id), f"{project_id}_{body.sheet_type.replace(' ', '_')}_{rev}.pdf")
    export_pdf.render_pdf(meta, layout["boundary_points_ft"], layout["rooms"], enriched["area_seat_chart"], enriched["feasibility"],
                           out_path, body.sheet_type, obstacles=layout.get("obstacles"), region_meta=region_meta,
                           entry_point_ft=entry_point, exit_points_ft=exit_points)
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

    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    entry_point = requirements.get("entry_point_ft")
    exit_points = requirements.get("exit_points_ft") or []

    out_path = os.path.join(storage.export_dir(project_id), f"{project_id}_ZoningLayout_{rev}.dxf")
    result = export_dxf.export_layout_to_dxf(meta, layout["boundary_points_ft"], layout["obstacles"], layout["rooms"], out_path,
                                              also_dwg=(body.format == "dwg"), entry_point_ft=entry_point,
                                              exit_points_ft=exit_points)

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
    measurements = _build_measurements(requirements, layout.get("obstacles", []), boundary_area, total_seats, screen_count, layout["rooms"])
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
