"""
File-based per-project storage for the zoning engine service.

Consistent with the rest of this codebase (services/cad-interop/test/output),
which already treats JSON files as the durable record rather than a database.
At this scale (a handful of projects, not a multi-tenant SaaS) a directory-per-
project layout is simpler to reason about and debug than standing up a second
database technology alongside the Node project-service's SQLite. If this needs
to scale later, each of these JSON files maps 1:1 to a spec data-model entity
(CADFile, GeometryObject set, RequirementSet, ZoningRun, Zone set, Export) and
can be migrated into real tables without changing the API contract.
"""
import json
import os
import shutil
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_ROOT = os.path.join(BASE_DIR, "storage")


def project_dir(project_id: str) -> str:
    d = os.path.join(STORAGE_ROOT, project_id)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    os.makedirs(os.path.join(d, "exports"), exist_ok=True)
    return d


def path_in(project_id: str, *parts) -> str:
    return os.path.join(project_dir(project_id), *parts)


def write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_json(path: str):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_upload(project_id: str, filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    dest = path_in(project_id, f"original{ext}")
    with open(dest, "wb") as f:
        f.write(content)
    return dest


def geometry_path(project_id: str) -> str:
    return path_in(project_id, "geometry.json")


def requirements_path(project_id: str) -> str:
    return path_in(project_id, "requirements.json")


def latest_run_path(project_id: str) -> str:
    return path_in(project_id, "latest_run.json")


def run_path(project_id: str, run_id: str) -> str:
    return path_in(project_id, "runs", f"{run_id}.json")


def layout_path(project_id: str) -> str:
    """The current architect-editable layout — starts as a copy of the selected
    candidate, then diverges as the architect edits (Product Principle #3:
    generate then edit, never destructively regenerate)."""
    return path_in(project_id, "layout_current.json")


def export_dir(project_id: str) -> str:
    d = path_in(project_id, "exports")
    os.makedirs(d, exist_ok=True)
    return d
