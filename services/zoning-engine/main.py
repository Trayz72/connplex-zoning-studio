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
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import storage
import cad_extraction
import layout_engine
import seat_engine
import feasibility_engine
import chart_engine
import export_dxf
import export_pdf

app = FastAPI(title="Connplex Zoning Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- Schemas ----------

class RequirementsIn(BaseModel):
    property_type: str = "EXISTING_BUILDING"   # EXISTING_BUILDING | OPEN_LAND
    max_auditoriums: int = 4
    franchise_tier_id: Optional[str] = None
    support_zone_area_overrides_sqft: dict = {}


class GeometryUpdateIn(BaseModel):
    regions: list


class ZoningRunIn(BaseModel):
    region_id: str


class LayoutUpdateIn(BaseModel):
    rooms: list
    boundary_points_ft: list
    obstacles: list = []
    circulation_area_sqft: Optional[float] = None


class ExportIn(BaseModel):
    project_meta: dict
    sheet_type: str = "Zoning Layout"
    format: Optional[str] = "dxf"  # dxf | dwg (export/cad only)


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


@app.get("/api/projects/{project_id}/geometry")
def get_geometry(project_id: str):
    geom = storage.read_json(storage.geometry_path(project_id))
    if not geom:
        raise HTTPException(404, "No CAD geometry uploaded for this project yet.")
    return geom


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

    confirmed_obstacles = [o["points_ft"] for o in region["obstacles"] if o["status"] == "CONFIRMED"]
    unresolved = [o for o in region["obstacles"] if o["status"] == "PROPOSED"]

    candidates = layout_engine.generate_candidates(region["boundary"]["points_ft"], confirmed_obstacles, requirements)

    for cand in candidates:
        measurements = {
            "carpet_area_sqft": cand["boundary_area_sqft"],
            "seats_per_screen": cand["seats_per_screen"],
            "total_project_seats": cand["total_seats"],
            "screen_count": cand["screen_count"]
        }
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


# ---------- Editable layout ----------

@app.get("/api/projects/{project_id}/layout")
def get_layout(project_id: str):
    layout = storage.read_json(storage.layout_path(project_id))
    if not layout:
        raise HTTPException(404, "No editable layout exists for this project yet — run zoning first.")
    return _enrich_layout(project_id, layout)


@app.post("/api/projects/{project_id}/layout/select-candidate")
def select_candidate(project_id: str, body: ZoningRunIn):
    """body.region_id is reused here as candidate_id for simplicity of the shared schema."""
    run = storage.read_json(storage.latest_run_path(project_id))
    if not run:
        raise HTTPException(404, "No zoning run exists for this project yet.")
    candidate = next((c for c in run["candidates"] if c["candidate_id"] == body.region_id), None)
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

    obstacle_points = [o["points_ft"] for o in body.obstacles]
    validation = layout_engine.validate_rooms(body.boundary_points_ft, obstacle_points, body.rooms)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "Layout edit rejected — geometry validation failed.", "errors": validation["errors"]})

    for room in body.rooms:
        if room["room_type"].startswith("AUDITORIUM"):
            cfg = room.get("seat_config") or {}
            room["seat_estimate"] = seat_engine.estimate_seats(
                room["width_ft"], room["depth_ft"],
                primary_seat_type_id=cfg.get("primary_seat_type_id", seat_engine.DEFAULT_SEAT_TYPE_ID),
                secondary_seat_type_id=cfg.get("secondary_seat_type_id"),
                primary_ratio_pct=cfg.get("primary_ratio_pct", 100),
            )
            room["preset_fit"] = seat_engine.best_fit_preset(room["area_sqft"])

    boundary_poly = layout_engine.poly_from_points(body.boundary_points_ft)
    room_area = sum(r["area_sqft"] for r in body.rooms)
    obstacle_area = sum(layout_engine.poly_from_points(o).area for o in obstacle_points) if obstacle_points else 0
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
    measurements = {
        "carpet_area_sqft": round(candidate_shape["boundary_area_sqft"], 2),
        "seats_per_screen": round(total_seats / screen_count, 2) if screen_count else 0,
        "total_project_seats": total_seats,
        "screen_count": screen_count
    }
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
        return FileResponse(result["dwg_path"], filename=os.path.basename(result["dwg_path"]), media_type="application/octet-stream")
    return FileResponse(result["dxf_path"], filename=os.path.basename(result["dxf_path"]), media_type="application/dxf")


def _enrich_with_requirements(project_id: str, layout: dict) -> dict:
    requirements = storage.read_json(storage.requirements_path(project_id)) or {}
    total_seats = sum(r.get("seat_estimate", {}).get("seat_count", 0) for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM"))
    screen_count = len([r for r in layout["rooms"] if r["room_type"].startswith("AUDITORIUM")])
    boundary_area = layout_engine.poly_from_points(layout["boundary_points_ft"]).area
    measurements = {
        "carpet_area_sqft": round(boundary_area, 2),
        "seats_per_screen": round(total_seats / screen_count, 2) if screen_count else 0,
        "total_project_seats": total_seats,
        "screen_count": screen_count
    }
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


@app.get("/api/seat-types")
def get_seat_types():
    """Seat types with enough real registry data to drive the packing math —
    what the architect can choose between when configuring an auditorium's
    seat mix at edit time (spec Sec 20: seat mix is user-configurable)."""
    return {"seat_types": seat_engine.selectable_seat_types()}


@app.get("/api/health")
def health():
    return {"status": "ok"}
