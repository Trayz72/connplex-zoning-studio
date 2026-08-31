"""Real DXF export (spec Sec 43/8.7): writes the current editable layout back out
as an actual DXF file via ezdxf — openable and re-editable in AutoCAD or any DWG-
compatible viewer. Layer strategy follows spec Sec 6.2/Sec "CAD Architecture":
separate EXISTING vs PROPOSED information on distinct, meaningfully-named layers.
Also converts the DXF to a real DWG via the same ODA File Converter used for
import, so both formats genuinely round-trip through this app.
"""
import os
import sys

import ezdxf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cad-interop"))
from convert import convert as oda_convert  # noqa: E402

# Plain black/white line work — standard practice for a working AutoCAD
# file an architect re-opens to keep drafting: differentiate by layer NAME
# (which every layer here already has, meaningfully) and toggle layer
# visibility, not by a pre-baked color the architect didn't choose and that
# may clash with their own firm's layer/color standard. ACI 7 is AutoCAD's
# default foreground color (white on a dark viewport background, black on
# a white plot/printout) — the same color CAD line work is drawn in by
# default when a layer has no color of its own.
LAYER_NAMES = [
    "EXISTING-BOUNDARY", "EXISTING-OBSTACLE",
    "PROPOSED-AUDITORIUM", "PROPOSED-FOYER", "PROPOSED-FNB",
    "PROPOSED-WASHROOM", "PROPOSED-BOX_OFFICE", "PROPOSED-BOH",
    "PROPOSED-CIRCULATION", "ANNOTATION"
]


def _ensure_layers(doc):
    for name in LAYER_NAMES:
        if name not in doc.layers:
            doc.layers.add(name, color=7)


def export_layout_to_dxf(project_meta: dict, boundary_points_ft, obstacles, rooms, out_path: str, also_dwg: bool = True) -> dict:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2  # feet, matches this app's internal canonical unit
    _ensure_layers(doc)
    msp = doc.modelspace()

    if boundary_points_ft:
        msp.add_lwpolyline(boundary_points_ft, close=True, dxfattribs={"layer": "EXISTING-BOUNDARY"})

    for obs in obstacles or []:
        pts = obs.get("points_ft") if isinstance(obs, dict) else obs
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "EXISTING-OBSTACLE"})

    for room in rooms:
        layer = f"PROPOSED-{room['room_type'].split('_')[0]}" if room["room_type"].startswith("AUDITORIUM") else f"PROPOSED-{room['room_type']}"
        if layer not in doc.layers:
            doc.layers.add(layer, color=7)
        pts = room["geometry_points_ft"]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})

        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        label = f"{room['display_name']}\n{room['area_sqft']} sqft"
        seat_count = room.get("seat_estimate", {}).get("seat_count")
        if seat_count:
            label += f"\n{seat_count} seats"
        msp.add_text(room["display_name"], dxfattribs={"layer": "ANNOTATION", "height": 1.5, "insert": (cx - 5, cy)})
        msp.add_text(f"{room['area_sqft']} sqft" + (f" / {seat_count} seats" if seat_count else ""),
                      dxfattribs={"layer": "ANNOTATION", "height": 1.0, "insert": (cx - 5, cy - 2)})

    title = project_meta.get("property_name") or "Untitled Project"
    header_lines = [
        f"CONNPLEX ZONING STUDIO — ZONING LAYOUT (COMPUTATIONAL DRAFT)",
        f"Project: {title}   Code: {project_meta.get('project_code', '-')}",
        f"City/State: {project_meta.get('city','-')}, {project_meta.get('state','-')}",
        f"Revision: {project_meta.get('revision', 'R0')}   Generated: {project_meta.get('generated_at', '')}",
        "DISCLAIMER: Decision-support draft only — not a final architectural/structural/fire-engineering document."
    ]
    minx = min(p[0] for p in boundary_points_ft) if boundary_points_ft else 0
    maxy = max(p[1] for p in boundary_points_ft) if boundary_points_ft else 0
    for i, line in enumerate(header_lines):
        msp.add_text(line, dxfattribs={"layer": "ANNOTATION", "height": 1.2, "insert": (minx, maxy + 5 + i * 2)})

    doc.saveas(out_path)

    result = {"dxf_path": out_path, "dwg_path": None, "dwg_conversion_error": None}
    if also_dwg:
        try:
            dwg_path = oda_convert(out_path, "dwg", os.path.dirname(out_path))
            result["dwg_path"] = dwg_path
        except Exception as e:
            result["dwg_conversion_error"] = str(e)
    return result
