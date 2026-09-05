"""Real DXF export (spec Sec 43/8.7): writes the current editable layout back out
as an actual DXF file via ezdxf — openable and re-editable in AutoCAD or any DWG-
compatible viewer. Layer strategy follows spec Sec 6.2/Sec "CAD Architecture":
separate EXISTING vs PROPOSED information on distinct, meaningfully-named layers.
Also converts the DXF to a real DWG via the same ODA File Converter used for
import, so both formats genuinely round-trip through this app.
"""
import math
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
    "PROPOSED-WASHROOM", "PROPOSED-BOX_OFFICE", "PROPOSED-BOH", "PROPOSED-PASSAGE",
    "PROPOSED-CIRCULATION", "ANNOTATION", "ANNOTATION-DOOR", "ANNOTATION-ENTRY-EXIT"
]

# ACI 3 (green) for entry, ACI 1 (red) for exit — distinct from the plain
# ACI 7 (black/white) line work everywhere else, same green/red convention
# EntryExitPicker.tsx already uses on the frontend for "IN"/"E1" markers.
_ENTRY_ACI = 3
_EXIT_ACI = 1

# Which points_ft direction is "into the room" from each screen_wall value
# (see layout_engine._screen_wall_for_rect) — used to draw a door's leaf
# line swung perpendicular off the wall.
_INTERIOR_DIR = {"min_y": (0, 1), "max_y": (0, -1), "min_x": (1, 0), "max_x": (-1, 0)}


def _door_glyph_points_ft(room, door):
    """A simplified 2D door symbol for a room's door (see
    layout_engine._doors_for_screen_wall for the {wall, offset_ft, width_ft}
    shape): the opening's two endpoints, plus a straight leaf line swung
    perpendicular into the room. Deliberately not a swing arc — that needs
    angle trigonometry this pass can't visually verify is right; a straight
    leaf line is a real, unambiguous, standard-enough simplified door symbol
    for a computational-draft export."""
    x, y = room["origin_ft"]
    w, h = room["width_ft"], room["depth_ft"]
    wall, off, dw = door["wall"], door["offset_ft"], door["width_ft"]
    if wall == "min_y":
        p1, p2 = (x + off, y), (x + off + dw, y)
    elif wall == "max_y":
        p1, p2 = (x + off, y + h), (x + off + dw, y + h)
    elif wall == "min_x":
        p1, p2 = (x, y + off), (x, y + off + dw)
    else:  # max_x
        p1, p2 = (x + w, y + off), (x + w, y + off + dw)
    dx, dy = _INTERIOR_DIR.get(wall, (0, 0))
    leaf_end = (p1[0] + dx * dw, p1[1] + dy * dw)
    return p1, p2, leaf_end


def _ensure_layers(doc):
    for name in LAYER_NAMES:
        if name not in doc.layers:
            doc.layers.add(name, color=7)


def _flip(pt):
    """points_ft is Y-down (screen/SVG convention — see cad_extraction.py's
    _identity_tf), but DXF is natively Y-up (north = larger Y) — every point
    written into this new file negates Y back so it opens right-side-up in
    AutoCAD/any DWG viewer instead of inheriting the app's internal screen
    convention."""
    return (pt[0], -pt[1])


def _nearest_boundary_edge_point(pt, boundary_points_ft):
    """Same construction as export_pdf.py's own — see that module's copy
    for the full reasoning. Returns (snapped_point, tangent_unit,
    outward_normal_unit) or None."""
    n = len(boundary_points_ft)
    if n < 2:
        return None
    cx = sum(p[0] for p in boundary_points_ft) / n
    cy = sum(p[1] for p in boundary_points_ft) / n
    best_dist, result = None, None
    for i in range(n):
        ax, ay = boundary_points_ft[i]
        bx, by = boundary_points_ft[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-9:
            continue
        t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / seg_len_sq))
        sx, sy = ax + t * dx, ay + t * dy
        dist = math.hypot(pt[0] - sx, pt[1] - sy)
        if best_dist is None or dist < best_dist:
            seg_len = math.sqrt(seg_len_sq)
            tangent = (dx / seg_len, dy / seg_len)
            n1 = (-tangent[1], tangent[0])
            to_pt = (sx - cx, sy - cy)
            normal = n1 if (n1[0] * to_pt[0] + n1[1] * to_pt[1]) >= 0 else (-n1[0], -n1[1])
            best_dist = dist
            result = ((sx, sy), tangent, normal)
    return result


def _draw_entry_exit_markers(msp, entry_point_ft, exit_points_ft, boundary_points_ft, door_width_ft=6.0):
    """A real door-in-the-wall glyph for the building's own main entrance/
    exit (matches export_pdf.py's own — see that module's copy for the
    full reasoning) — an opening cut into the boundary line plus a leaf
    line swung inward, same construction as every room's own
    _door_glyph_points_ft, on their own layer so an architect can toggle
    them independently of room/door annotation."""
    def draw_one(pt, color, label):
        hit = _nearest_boundary_edge_point(pt, boundary_points_ft)
        if hit is None:
            return
        (sx, sy), (tx, ty), (nx, ny) = hit
        half = door_width_ft / 2
        p1 = (sx - tx * half, sy - ty * half)
        p2 = (sx + tx * half, sy + ty * half)
        leaf_end = (p1[0] - nx * door_width_ft, p1[1] - ny * door_width_ft)
        msp.add_line(_flip(p1), _flip(p2), dxfattribs={"layer": "ANNOTATION-ENTRY-EXIT", "color": color, "lineweight": 50})
        msp.add_line(_flip(p1), _flip(leaf_end), dxfattribs={"layer": "ANNOTATION-ENTRY-EXIT", "color": color})
        label_pt = _flip((sx + nx * door_width_ft * 1.1, sy + ny * door_width_ft * 1.1))
        msp.add_text(label, dxfattribs={"layer": "ANNOTATION-ENTRY-EXIT", "color": color, "height": door_width_ft * 0.5,
                                         "insert": (label_pt[0] - door_width_ft * 0.9, label_pt[1])})

    if entry_point_ft is not None:
        draw_one(entry_point_ft, _ENTRY_ACI, "ENTRY")
    for i, ep in enumerate(exit_points_ft or [], start=1):
        draw_one(ep, _EXIT_ACI, f"EXIT {i}")


def export_layout_to_dxf(project_meta: dict, boundary_points_ft, obstacles, rooms, out_path: str, also_dwg: bool = True,
                          entry_point_ft=None, exit_points_ft=None) -> dict:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2  # feet, matches this app's internal canonical unit
    _ensure_layers(doc)
    msp = doc.modelspace()

    if boundary_points_ft:
        msp.add_lwpolyline([_flip(p) for p in boundary_points_ft], close=True, dxfattribs={"layer": "EXISTING-BOUNDARY"})

    for obs in obstacles or []:
        pts = obs.get("points_ft") if isinstance(obs, dict) else obs
        msp.add_lwpolyline([_flip(p) for p in pts], close=True, dxfattribs={"layer": "EXISTING-OBSTACLE"})

    for room in rooms:
        layer = f"PROPOSED-{room['room_type'].split('_')[0]}" if room["room_type"].startswith("AUDITORIUM") else f"PROPOSED-{room['room_type']}"
        if layer not in doc.layers:
            doc.layers.add(layer, color=7)
        pts = room["geometry_points_ft"]
        msp.add_lwpolyline([_flip(p) for p in pts], close=True, dxfattribs={"layer": layer})

        # label_point_ft (server-computed via shapely representative_point())
        # is guaranteed to fall inside the room's true polygon — a plain
        # vertex-mean centroid can land outside a concave shape (Foyer's own
        # leftover-remainder polygon). Falls back to vertex-mean for any
        # older cached layout without the field.
        if "label_point_ft" in room:
            cx, cy = room["label_point_ft"][0], -room["label_point_ft"][1]
        else:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = -sum(p[1] for p in pts) / len(pts)
        label = f"{room['display_name']}\n{room['area_sqft']} sqft"
        seat_count = room.get("seat_estimate", {}).get("seat_count")
        if seat_count:
            label += f"\n{seat_count} seats"
        msp.add_text(room["display_name"], dxfattribs={"layer": "ANNOTATION", "height": 1.5, "insert": (cx - 5, cy)})
        msp.add_text(f"{room['area_sqft']} sqft" + (f" / {seat_count} seats" if seat_count else ""),
                      dxfattribs={"layer": "ANNOTATION", "height": 1.0, "insert": (cx - 5, cy - 2)})

        for door in room.get("doors", []):
            p1, p2, leaf_end = _door_glyph_points_ft(room, door)
            msp.add_line(_flip(p1), _flip(p2), dxfattribs={"layer": "ANNOTATION-DOOR"})
            msp.add_line(_flip(p1), _flip(leaf_end), dxfattribs={"layer": "ANNOTATION-DOOR"})

    if boundary_points_ft:
        _draw_entry_exit_markers(msp, entry_point_ft, exit_points_ft, boundary_points_ft)

    title = project_meta.get("property_name") or "Untitled Project"
    header_lines = [
        f"CONNPLEX ZONING STUDIO — ZONING LAYOUT (COMPUTATIONAL DRAFT)",
        f"Project: {title}   Code: {project_meta.get('project_code', '-')}",
        f"City/State: {project_meta.get('city','-')}, {project_meta.get('state','-')}",
        f"Revision: {project_meta.get('revision', 'R0')}   Generated: {project_meta.get('generated_at', '')}",
        "DISCLAIMER: Decision-support draft only — not a final architectural/structural/fire-engineering document."
    ]
    minx = min(p[0] for p in boundary_points_ft) if boundary_points_ft else 0
    # min_y in points_ft's Y-down convention is the topmost (most-north)
    # point — negated, that's the largest DXF-native Y, so the header text
    # still lands above the boundary once written in DXF's own Y-up space.
    maxy = -min(p[1] for p in boundary_points_ft) if boundary_points_ft else 0
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
