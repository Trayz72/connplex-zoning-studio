"""
Generic CAD geometry extraction — replaces the per-file hardcoded extraction in
services/cad-interop/extract_geometry_v2.py (whose extract_dhule()/extract_vadodara()
functions reference hand-transcribed entity handles like "6A8" and fixed pixel
bounding boxes specific to those two files — verified by reading that file; it
cannot process an arbitrary upload).

This module makes no attempt to *identify room types* (that would be hallucination
per the project's own anti-hallucination rule) — it only extracts geometry:
- one or more boundary candidates (closed polylines above a minimum area),
- obstacle/column candidates contained inside a boundary,
- raw text label positions (for the architect to read, not for us to interpret).

Every detection carries a confidence and the CAD evidence it came from (entity
handle, layer, area) so the frontend can present a Confirm/Ignore review step
before any of this is treated as authoritative — this mirrors the "Potential
Door, Confidence: 72%, [Confirm][Ignore]" workflow required by the master
context (Sec 11) instead of silently trusting a heuristic.
"""
import os
import sys
import math
import uuid

import ezdxf
import ezdxf.recover
import ezdxf.path
from collections import Counter
from ezdxf.lldxf.const import DXFStructureError
import shapely
from shapely.geometry import Polygon, LineString, MultiLineString
from shapely.validation import make_valid
from shapely.ops import polygonize

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cad-interop"))
from convert import convert as oda_convert  # noqa: E402  (reuses the proven, generic ODA wrapper)

MIN_BOUNDARY_AREA_SQFT = 150.0     # below this, a closed shape is furniture/fixtures, not a floor boundary
# Above this, a closed shape is implausible as a single real indoor floor
# plate — found via a real uploaded file whose $INSUNITS was unspecified,
# where the "largest closed polyline" heuristic latched onto a drawing
# sheet-border/title-block frame (a very common real DXF artifact) instead
# of the actual building outline, producing a "boundary" of several million
# sqft. For scale: even IKEA's largest stores, among the biggest single-
# floor retail plates that exist, run well under 500,000 sqft. Not treated
# as disqualifying — the architect still sees and can confirm it if it's
# genuinely intended — but it's flagged low-confidence with an explicit
# note, sorted after plausible candidates, and (see the nesting-collapse
# loop below) no longer allowed to swallow smaller real candidates nested
# inside it.
MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT = 500000.0
MAX_OBSTACLE_AREA_RATIO = 0.10     # an "obstacle" larger than 10% of its boundary's area is probably itself a room, not a column
# ezdxf.path.Path.flattening(distance, segments) — segments is a per-curve
# minimum that dominates in practice, so this stays reasonable across the
# wildly different drawing-unit scales real files show up in (mm, m, or
# unspecified raw units); distance is a secondary refinement only.
CURVE_FLATTEN_DISTANCE = 0.01
CURVE_FLATTEN_MIN_SEGMENTS = 8
# Real wall junctions that are visually closed but off by a fraction of an
# inch are common enough in real client DXFs that not tolerating them at all
# left genuine floor boundaries completely unrecoverable — see
# _reconstruct_polygons_from_lines's own docstring for the real case this
# was found against. 0.3ft (~3.6in) is loose enough to close that kind of
# real gap without merging two walls that are genuinely meant to be separate.
WALL_SNAP_TOLERANCE_FT = 0.3
MIN_OBSTACLE_AREA_SQFT = 0.3       # ignore microscopic closed shapes (hatch fragments, tick marks)
CONTAINMENT_THRESHOLD = 0.6        # fraction of an obstacle's area that must fall inside a boundary to count as "in" it

UNIT_TO_FEET = {
    0: None,       # Unspecified — must ask the user
    1: 1.0 / 12.0,  # Inches
    2: 1.0,         # Feet
    4: 0.00328084,  # Millimeters
    5: 0.0328084,   # Centimeters
    6: 3.28084,     # Meters
}

COLUMN_LAYER_HINTS = ["column", "col", "grid", "struct"]
BOUNDARY_LAYER_HINTS = ["wall", "boundary", "outline"]

# Standard AutoCAD architectural layer-naming conventions (A-DOOR, A-GLAZ,
# A-FURN, etc. per the AIA CAD Layer Guidelines most real firms follow) — this
# reads real metadata already present in the file, the same evidence-based
# technique already used for COLUMN_LAYER_HINTS above, not an invented rule.
# Order matters: checked most-specific-first so e.g. "door" doesn't also
# match a generic "furniture" catch-all.
#
# WALL was added because an interior partition wall drawn as its own closed
# shape (a real shape nested inside the outer boundary — e.g. a stairwell
# core, a lift shaft, a service duct enclosure) was previously only reachable
# via the generic UNCLASSIFIED_OBSTACLE bucket even when its own layer name
# said exactly what it was. It reuses the same "wall"/"boundary" vocabulary
# BOUNDARY_LAYER_HINTS already trusts for the *outer* boundary's own
# confidence score below — same evidence, applied to an interior shape
# instead of the one chosen as the region's boundary.
WALL_LAYER_HINTS = ["wall", "partition", "shear"]
OBSTACLE_LAYER_HINTS = [
    ("COLUMN", COLUMN_LAYER_HINTS),
    ("WALL", WALL_LAYER_HINTS),
    ("DOOR", ["door", "-dr", "_dr"]),
    ("WINDOW", ["window", "glaz", "-win", "_win"]),
    ("STAIRCASE", ["stair", "stnc"]),
    ("WASHROOM_FIXTURE", ["sanit", "toilet", "plumb", "fixture"]),
    ("FURNITURE", ["furn", "equip"]),
]


def _classify_obstacle_layer(layer_name):
    """Match a closed shape's layer name against known architectural layer
    conventions. Returns (classification, matched) — matched=False means no
    layer evidence exists, so the caller must fall back to shape heuristics
    or an honest UNCLASSIFIED_OBSTACLE rather than guessing a type."""
    for classification, hints in OBSTACLE_LAYER_HINTS:
        if _layer_hint_score(layer_name, hints):
            return classification, True
    return "UNCLASSIFIED_OBSTACLE", False


def _get_units(doc):
    insunits = doc.header.get("$INSUNITS", 0)
    factor = UNIT_TO_FEET.get(insunits)
    return {
        "insunits_code": insunits,
        "detected_unit": {0: "Unspecified", 1: "Inches", 2: "Feet", 4: "Millimeters", 5: "Centimeters", 6: "Meters"}.get(insunits, "Unknown"),
        "feet_per_drawing_unit": factor,
        "needs_user_confirmation": factor is None
    }


def _closed_points(e):
    """Return a list of (x, y) if this entity is a closed polyline/circle, else None.

    LWPOLYLINE/POLYLINE go through ezdxf's generic path flattening rather than
    a bare e.get_points()/vertex walk — a polyline segment with bulge (a
    rounded corner, common in real architectural drawings) previously got
    silently chorded into a straight line by connecting only the two
    endpoints, which is a real, if usually minor, area/shape error. Using the
    same flattening path as _open_segments below also keeps both functions
    agreeing on what a curved boundary segment actually looks like."""
    t = e.dxftype()
    try:
        if t == "LWPOLYLINE":
            if not e.closed:
                return None
            path = ezdxf.path.make_path(e)
            pts = [(v.x, v.y) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
        if t == "POLYLINE":
            if not e.is_closed:
                return None
            path = ezdxf.path.make_path(e)
            pts = [(v.x, v.y) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
        if t == "CIRCLE":
            c = e.dxf.center
            r = e.dxf.radius
            n = 16
            return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    except Exception:
        return None
    return None


def _safe_polygon(points):
    try:
        poly = Polygon(points)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.geom_type != "Polygon" or poly.area <= 0:
            return None
        return poly
    except Exception:
        return None


def _layer_hint_score(layer_name, hints):
    name = (layer_name or "").lower()
    return any(h in name for h in hints)


def _open_segments(e):
    """Break any line-like entity into individual 2-point segments, in drawing
    units. Covers the very common real-world case of a boundary drawn as
    discrete wall LINE segments rather than one closed polyline — the same
    'composite wall segments, no single closed polyline' situation the master
    context notes even Connplex's own Dhule basement/ground floors hit.

    ARC/SPLINE/ELLIPSE and bulged LWPOLYLINE/POLYLINE segments go through
    ezdxf's generic path flattening — found via real testing against actual
    client DXFs that a floor boundary's wall network is very often not pure
    LINE/straight-polyline: a single ARC forming one wall corner (327 of them
    in one real file) previously meant that entity contributed zero segments
    here, leaving a gap polygonize() cannot close — the reconstruction found
    nothing at all for that boundary, not just an inaccurate one."""
    t = e.dxftype()
    if t == "LINE":
        try:
            s, end = e.dxf.start, e.dxf.end
            return [((s[0], s[1]), (end[0], end[1]))]
        except Exception:
            return []
    if t in ("LWPOLYLINE", "POLYLINE", "ARC", "SPLINE", "ELLIPSE"):
        try:
            path = ezdxf.path.make_path(e)
            pts = [(v.x, v.y) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
        except Exception:
            return []
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return []


def _reconstruct_polygons_from_lines(entities, already_closed_handles, min_area_drawing_units, snap_tolerance_drawing_units=0.0):
    """Chain together every LINE/open-polyline segment in the drawing (via
    shapely's polygonize, which finds closed rings in an arbitrary network of
    line segments) to recover boundaries that exist as discrete wall segments
    rather than one explicit closed polyline. Returns candidate shapes in the
    same shape as the explicit-closed-shape pass, tagged source="reconstructed"
    with lower confidence and the contributing layer names for provenance —
    this is an inference, not something present verbatim in the file, and must
    be reviewed like any other uncertain detection.

    Performance note: a real architectural drawing can have tens of thousands
    of LINE segments (dimension marks, hatching, furniture). polygonize() over
    all of them is fine (GEOS's planar-graph algorithm), but naively attributing
    each resulting polygon back to a source layer by testing it against every
    segment is O(polygons x segments) and was measured to hang on a real 800+
    entity drawing. Fixed with a spatial index (STRtree) for that lookup, and
    by discarding sub-threshold polygons (found: hundreds of tiny ones from
    hatching/furniture) before doing any attribution work at all.

    snap_tolerance_drawing_units: real client DXFs routinely have walls drawn
    as segments that don't *quite* meet at corners/T-junctions — a few
    thousandths of a unit off, invisible on screen, but polygonize() requires
    exact coincidence and silently finds no ring at all across a gap that
    small. Found via real testing: a genuine floor boundary (a real retail
    unit, ~1,400 sqft) was completely unrecoverable at zero tolerance and
    recovered cleanly once nearby endpoints were snapped together first —
    shapely.set_precision quantizes every coordinate to this grid size before
    polygonize runs, which is the standard fix for near-but-not-quite-closed
    line networks. 0 (the default) preserves the exact old behavior."""
    from shapely.strtree import STRtree

    segments = []
    layer_by_segment = []
    for e in entities:
        if str(e.dxf.handle) in already_closed_handles:
            continue  # already a closed shape in its own right; don't double-count its edges
        for a, b in _open_segments(e):
            if a == b:
                continue
            segments.append(LineString([a, b]))
            layer_by_segment.append(str(e.dxf.layer))

    if len(segments) < 3:
        return []

    if snap_tolerance_drawing_units > 0:
        snapped = shapely.set_precision(MultiLineString(segments), grid_size=snap_tolerance_drawing_units)
        snapped_segments, snapped_layers = [], []
        for seg, layer in zip(snapped.geoms, layer_by_segment):
            if seg.is_empty or seg.length == 0:
                continue  # collapsed to a point by snapping — not a real segment any more
            snapped_segments.append(seg)
            snapped_layers.append(layer)
        segments, layer_by_segment = snapped_segments, snapped_layers
        if len(segments) < 3:
            return []

    candidate_polys = [p for p in polygonize(segments) if p.is_valid and p.area >= min_area_drawing_units]
    if not candidate_polys:
        return []

    tree = STRtree(segments)
    results = []
    for poly in candidate_polys:
        boundary = poly.exterior
        nearby_idx = tree.query(boundary.buffer(1e-6))
        touching_layers = [layer_by_segment[i] for i in nearby_idx if segments[i].distance(boundary) < 1e-6]
        dominant_layer = Counter(touching_layers).most_common(1)[0][0] if touching_layers else "unknown"
        results.append({
            "handle": f"reconstructed-{uuid.uuid4().hex[:8]}",
            "layer": dominant_layer,
            "dxftype": "RECONSTRUCTED_FROM_LINES",
            "source": "reconstructed",
            "polygon": poly,
        })
    return results


def resolve_dxf_path(input_path: str):
    """input_path may be .dwg or .dxf; returns (real_dxf_path, conversion_note).
    Shared by extract() and ai_cad_scan.py so both agree on how a DWG upload
    gets converted, instead of ai_cad_scan.py duplicating (and risking
    drifting from) this logic."""
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".dwg":
        out_dir = os.path.dirname(input_path)
        dxf_path = oda_convert(input_path, "dxf", out_dir)
        return dxf_path, "Converted from DWG to DXF via ODA File Converter."
    if ext == ".dxf":
        return input_path, None
    raise ValueError(f"Unsupported CAD file extension '{ext}'. Only .dwg and .dxf are supported.")


def _read_dxf_with_recovery(dxf_path: str):
    """Real-world DXF files are frequently not fully spec-compliant (missing
    subclass markers, out-of-order sections, etc.) — a strict reader failing on
    the first defect would make this extractor far less generic than it claims
    to be. Try a normal strict read first (fast, and gives the cleanest data);
    if that raises a structural error, fall back to ezdxf's recovery reader,
    which tolerates and audits around many real-world malformations. Only if
    both genuinely fail do we give up — never silently return partial garbage."""
    try:
        return ezdxf.readfile(dxf_path), None
    except DXFStructureError as e:
        doc, auditor = ezdxf.recover.readfile(dxf_path)
        note = (f"This DXF was not fully spec-compliant ({e}); recovered {len(auditor.errors)} "
                f"structural issue(s) automatically. Geometry below may be incomplete near the "
                f"affected entities — review carefully.")
        return doc, note


def extract(input_path: str, allowed_layers=None, min_boundary_area_sqft=None) -> dict:
    """Main entry point. input_path may be .dwg or .dxf. Returns canonical geometry.

    allowed_layers / min_boundary_area_sqft: normally None (unfiltered, the
    default MIN_BOUNDARY_AREA_SQFT) — real overrides exist only for
    ai_cad_scan.py's AI-assisted rescan, which restricts extraction to a
    layer subset Claude identified as the real wall/floor layer(s) when the
    default full-drawing pass found nothing usable. Dimension/hatch/furniture
    noise on unrelated layers can fragment or dominate the segment network
    enough that the real boundary never wins pass 2's candidate selection —
    this is the deterministic engine's own logic re-run on a cleaner subset,
    not a different/less-trustworthy extraction path."""
    dxf_path, conversion_note = resolve_dxf_path(input_path)

    doc, recovery_note = _read_dxf_with_recovery(dxf_path)
    msp = doc.modelspace()
    units = _get_units(doc)
    scale = units["feet_per_drawing_unit"] or 1.0  # if unspecified, extract in raw units and flag for confirmation

    entities = list(msp)
    if allowed_layers:
        allowed_set = set(allowed_layers)
        entities = [e for e in entities if str(e.dxf.layer) in allowed_set]
    min_boundary_area_sqft = MIN_BOUNDARY_AREA_SQFT if min_boundary_area_sqft is None else min_boundary_area_sqft

    # --- Pass 1: find every closed shape and its polygon/area (in drawing units) ---
    closed_shapes = []
    closed_handles = set()
    for e in entities:
        pts = _closed_points(e)
        if not pts:
            continue
        poly = _safe_polygon(pts)
        if not poly:
            continue
        closed_shapes.append({
            "handle": str(e.dxf.handle),
            "layer": str(e.dxf.layer),
            "dxftype": e.dxftype(),
            "source": "explicit",
            "polygon": poly,
            "area_sqft": poly.area * (scale ** 2),
            "points_ft": [[round(x * scale, 3), round(y * scale, 3)] for x, y in poly.exterior.coords]
        })
        closed_handles.add(str(e.dxf.handle))

    # --- Pass 1b: reconstruct additional boundary candidates from discrete wall
    # line segments (LINE/open-polyline entities that together form a closed
    # loop but aren't one explicit closed shape in the source file) ---
    min_area_drawing_units = MIN_OBSTACLE_AREA_SQFT / max(scale ** 2, 1e-9)  # cheap pre-filter, tightened again in feet below
    snap_tolerance_drawing_units = WALL_SNAP_TOLERANCE_FT / max(scale, 1e-9)
    for rec in _reconstruct_polygons_from_lines(entities, closed_handles, min_area_drawing_units, snap_tolerance_drawing_units):
        poly = rec["polygon"]
        closed_shapes.append({
            "handle": rec["handle"], "layer": rec["layer"], "dxftype": rec["dxftype"], "source": "reconstructed",
            "polygon": poly, "area_sqft": poly.area * (scale ** 2),
            "points_ft": [[round(x * scale, 3), round(y * scale, 3)] for x, y in poly.exterior.coords]
        })

    # --- Pass 2: boundary candidates = large closed shapes, largest first.
    # CIRCLE-derived shapes are excluded from *boundary* candidacy — floor
    # plates are essentially never literally circular, and a large circle is
    # much more likely to be a door-swing arc or an annotation than a real
    # boundary (found via real testing: a door-swing CIRCLE was large enough to
    # get mistaken for a second floor region). Circles remain eligible as
    # *obstacles* (columns are often drawn as circles) via the pass below,
    # which is unaffected by this filter. ---
    boundary_candidates = sorted(
        [s for s in closed_shapes if s["area_sqft"] >= min_boundary_area_sqft and s["dxftype"] != "CIRCLE"],
        key=lambda s: s["area_sqft"],
        reverse=True
    )

    # Collapse nested/overlapping candidates: keep the largest in each disjoint cluster
    # as a boundary; anything mostly-contained inside an already-picked boundary is not
    # itself a separate boundary (it becomes an obstacle/room candidate in pass 3).
    #
    # Exception: an implausibly large candidate (see MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT —
    # almost always a sheet-border/title-block frame, not a real floor) does not get to
    # swallow whatever real candidate is nested inside it. Without this, a file with a
    # frame drawn around the actual building outline would silently lose that real
    # boundary entirely — demoted to an "obstacle" of the frame instead of being
    # offered as its own selectable region.
    chosen_boundaries = []
    for cand in boundary_candidates:
        nested_in_existing = False
        for b in chosen_boundaries:
            if b["area_sqft"] > MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT:
                continue
            inter = cand["polygon"].intersection(b["polygon"]).area
            if cand["polygon"].area > 0 and inter / cand["polygon"].area > CONTAINMENT_THRESHOLD:
                nested_in_existing = True
                break
        if not nested_in_existing:
            chosen_boundaries.append(cand)

    # --- Pass 3: text labels (raw, uninterpreted) ---
    text_labels = []
    for e in entities:
        if e.dxftype() in ("TEXT", "MTEXT"):
            try:
                txt = e.plain_text().strip() if hasattr(e, "plain_text") else str(getattr(e.dxf, "text", "")).strip()
                if not txt:
                    continue
                ins = e.dxf.insert
                text_labels.append({"text": txt, "position_ft": [round(ins[0] * scale, 3), round(ins[1] * scale, 3)]})
            except Exception:
                continue

    MAX_RAW_LINES = 6000
    MAX_RAW_TEXTS = 800

    def extract_raw_geometry(minx, miny, maxx, maxy):
        """The actual underlying CAD drawing near this region — rendered as a
        light backdrop in the editor so the architect can see the real source
        drawing under the generated zoning, the way a real CAD viewer does.
        Capped per region so a huge real drawing (Vadodara: 2000+ closed shapes
        alone) doesn't ship an unbounded payload to the browser."""
        pad = max((maxx - minx), (maxy - miny)) * 0.05
        bx0, by0, bx1, by1 = minx - pad, miny - pad, maxx + pad, maxy + pad
        lines, circles, texts = [], [], []
        truncated = False
        for e in entities:
            if len(lines) >= MAX_RAW_LINES:
                truncated = True
                break
            t = e.dxftype()
            try:
                if t in ("LINE", "LWPOLYLINE", "POLYLINE"):
                    for a, b in _open_segments(e):
                        if not (bx0 <= a[0] <= bx1 and by0 <= a[1] <= by1) and not (bx0 <= b[0] <= bx1 and by0 <= b[1] <= by1):
                            continue
                        lines.append([[round(a[0] * scale, 3), round(a[1] * scale, 3)],
                                      [round(b[0] * scale, 3), round(b[1] * scale, 3)]])
                        if len(lines) >= MAX_RAW_LINES:
                            truncated = True
                            break
                elif t == "CIRCLE":
                    c, r = e.dxf.center, e.dxf.radius
                    if bx0 <= c[0] <= bx1 and by0 <= c[1] <= by1:
                        circles.append({"center": [round(c[0] * scale, 3), round(c[1] * scale, 3)], "radius": round(r * scale, 3)})
                elif t in ("TEXT", "MTEXT") and len(texts) < MAX_RAW_TEXTS:
                    ins = e.dxf.insert
                    if bx0 <= ins[0] <= bx1 and by0 <= ins[1] <= by1:
                        txt = e.plain_text().strip() if hasattr(e, "plain_text") else str(getattr(e.dxf, "text", "")).strip()
                        if txt:
                            texts.append({"text": txt, "position": [round(ins[0] * scale, 3), round(ins[1] * scale, 3)]})
            except Exception:
                continue
        return {"lines": lines, "circles": circles, "texts": texts, "truncated": truncated}

    regions = []
    for boundary in chosen_boundaries:
        b_poly = boundary["polygon"]
        b_area = boundary["area_sqft"]
        minx, miny, maxx, maxy = b_poly.bounds

        obstacles = []
        for s in closed_shapes:
            if s["handle"] == boundary["handle"]:
                continue
            if s["area_sqft"] < MIN_OBSTACLE_AREA_SQFT or s["area_sqft"] > b_area * MAX_OBSTACLE_AREA_RATIO:
                continue
            inter = s["polygon"].intersection(b_poly).area
            if s["polygon"].area == 0 or inter / s["polygon"].area < CONTAINMENT_THRESHOLD:
                continue

            classification, layer_matched = _classify_obstacle_layer(s["layer"])
            is_squarish = 0.0
            try:
                sminx, sminy, smaxx, smaxy = s["polygon"].bounds
                w, h = smaxx - sminx, smaxy - sminy
                is_squarish = min(w, h) / max(w, h) if max(w, h) > 0 else 0
            except Exception:
                pass

            if layer_matched:
                confidence = "high"
            elif is_squarish > 0.6 and s["area_sqft"] < 20:
                # Shape alone doesn't tell us *what* it is without a layer hint —
                # only a column is safe to infer this way (compact + squarish is
                # a strong structural-column signal in practice); anything else
                # without layer evidence stays honestly unclassified.
                classification = "COLUMN"
                confidence = "medium"
            else:
                confidence = "low"

            obstacles.append({
                "id": f"obstacle-{uuid.uuid4().hex[:8]}",
                "source_handle": s["handle"],
                "layer": s["layer"],
                "dxftype": s["dxftype"],
                "area_sqft": round(s["area_sqft"], 3),
                "points_ft": s["points_ft"],
                "classification": classification,
                "confidence": confidence,
                "status": "PROPOSED"  # frontend must move this to CONFIRMED or IGNORED before a zoning run
            })

        region_texts = [t for t in text_labels if minx * scale <= t["position_ft"][0] <= maxx * scale
                         or True]  # position_ft already scaled above; keep simple bbox-in-feet filter below
        region_texts = [t for t in text_labels
                         if (minx * scale) <= t["position_ft"][0] <= (maxx * scale)
                         and (miny * scale) <= t["position_ft"][1] <= (maxy * scale)]

        is_reconstructed = boundary.get("source") == "reconstructed"
        has_wall_hint = _layer_hint_score(boundary["layer"], BOUNDARY_LAYER_HINTS)
        if is_reconstructed:
            boundary_layer_conf = "medium" if has_wall_hint else "low"
        else:
            boundary_layer_conf = "high" if has_wall_hint else "medium"

        is_implausibly_large = b_area > MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT
        if is_implausibly_large:
            boundary_layer_conf = "low"
            plausibility_note = (
                f"This shape is {b_area:,.0f} sqft — far larger than any real single indoor "
                f"floor plate. Most likely a drawing sheet border or title-block frame was "
                f"picked up instead of the actual building outline (common when a DXF file's "
                f"units aren't specified — see units.needs_user_confirmation). Check the other "
                f"candidate regions below before confirming this one."
            )
        else:
            plausibility_note = None

        regions.append({
            "region_id": f"region-{uuid.uuid4().hex[:8]}",
            "boundary": {
                "source_handle": boundary["handle"],
                "layer": boundary["layer"],
                "source": boundary.get("source", "explicit"),
                "area_sqft": round(b_area, 2),
                "points_ft": boundary["points_ft"],
                "bounding_box_ft": {
                    "min_x": round(minx * scale, 2), "min_y": round(miny * scale, 2),
                    "max_x": round(maxx * scale, 2), "max_y": round(maxy * scale, 2)
                },
                "confidence": boundary_layer_conf,
                "note": " ".join(filter(None, [
                    ("Reconstructed from discrete wall line segments — not one explicit closed "
                     "polyline in the source file. Verify this boundary carefully before confirming."
                     if is_reconstructed else None),
                    plausibility_note
                ])) or None,
                "status": "PROPOSED"
            },
            "obstacles": obstacles,
            "text_labels": region_texts,
            "raw_geometry": extract_raw_geometry(minx, miny, maxx, maxy)
        })

    # Plausible-sized regions first (largest among them first, same as before),
    # implausibly-large ones (see MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT) pushed to the
    # end — the frontend defaults to reviewing regions[0], so an oversized
    # sheet-border/frame candidate should never be what an architect lands on
    # first by default.
    regions.sort(key=lambda r: (
        r["boundary"]["area_sqft"] > MAX_PLAUSIBLE_BOUNDARY_AREA_SQFT,
        -r["boundary"]["area_sqft"]
    ))

    return {
        "schema_version": "1.0",
        "source_filename": os.path.basename(input_path),
        "conversion_note": conversion_note,
        "recovery_note": recovery_note,
        "units": units,
        "extraction_method": "generic-geometric (largest-closed-polyline heuristic + containment-based obstacle detection)",
        "total_entities_scanned": len(entities),
        "total_closed_shapes_found": len(closed_shapes),
        "region_count": len(regions),
        "regions": regions,
        "unclassified_text_count": len(text_labels)
    }
