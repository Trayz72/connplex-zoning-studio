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
- raw text label positions (for the architect to read, not for us to interpret),
- the ENTIRE drawing's raw linework, uncropped, for two different manual paths:
  a whole-drawing backdrop to trace a boundary over (`raw_geometry`) and a richer
  structure with closed-shape/line ids for BoundaryStudio's click-to-select tools
  (`full_raw_geometry`) — see _build_full_raw_geometry below.

Every detection carries a confidence and the CAD evidence it came from (entity
handle, layer, area) so the frontend can present a Confirm/Ignore review step
before any of this is treated as authoritative — this mirrors the "Potential
Door, Confidence: 72%, [Confirm][Ignore]" workflow required by the master
context (Sec 11) instead of silently trusting a heuristic.

Deliberately ignores per-layer visibility state ($LAYER's off/frozen flags):
confirmed on a real file (theater_clean.dxf) that its own "column" layer is
saved OFF, meaning a real CAD viewer opening this file wouldn't show any of
its 170 real columns at all — almost certainly an incidental save-state
artifact (the drafter toggled it off while working on something else), not
an intentional "these columns don't exist." A structural column is a real
physical obstruction regardless of whether a layer happened to be toggled
off in the file's last save state; silently hiding it here risks a generated
zoning layout overlapping a real column that the tool never saw. This is why
every entity is walked and every closed shape is a candidate purely on its
own geometry/layer-name evidence — layer on/off/frozen state is never
consulted anywhere in this module.
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
MAX_INSERT_DEPTH = 8               # guards against a pathological/cyclic block-reference chain

# Entities that are pure annotation (dimension lines/arrows, leader callout
# lines) rather than real drawn geometry — real files carry hundreds of
# these (see _resolve_entities). Rendered for visual completeness but never
# allowed to feed boundary/obstacle detection: a dimension extension line or
# a leader line chaining into the wall-reconstruction network could only
# manufacture a false boundary, never find a real one.
ANNOTATION_ENTITY_TYPES = {"DIMENSION", "LEADER", "MLEADER"}

UNIT_TO_FEET = {
    0: None,       # Unspecified — must ask the user
    1: 1.0 / 12.0,  # Inches
    2: 1.0,         # Feet
    4: 0.00328084,  # Millimeters
    5: 0.0328084,   # Centimeters
    6: 3.28084,     # Meters
}

UNIT_NAME_TO_FEET = {
    "Inches": 1.0 / 12.0,
    "Feet": 1.0,
    "Millimeters": 0.00328084,
    "Centimeters": 0.0328084,
    "Meters": 3.28084,
}

COLUMN_LAYER_HINTS = ["column", "col", "grid", "struct"]
BOUNDARY_LAYER_HINTS = ["wall", "boundary", "outline"]

# Layer names that are near-universal AutoCAD sheet/drafting artifacts —
# a paper-space viewport border, a plot/print margin, a drawing-sheet
# format frame, a title block, or an area-calculation/dimension-helper
# shape drawn as a closed polyline directly in modelspace — never real
# building geometry, no matter how large. Found via a real file
# (theater_clean.dxf): a single VIEWPORT-layer sheet frame (117,059 sqft)
# and six duplicate MARGIN-layer sheet-margin rectangles (47,050 sqft
# each) out-ranked the file's real, wall-reconstructed ~7,116 sqft
# auditorium boundary purely on raw area, with no warning at all — none
# of those six were even distinct rooms, just the same margin rectangle
# repeated once per drawing sheet. "F.S.I."/"BUILT UP"/"title block" are
# the same non-physical-layer evidence ai_obstacle_classify.py already
# uses (there, as a live AI judgment call for obstacles *inside* an
# already-confirmed boundary); applied here as a plain substring check —
# these are universal CAD-sheet conventions, not a business/regulatory
# fact, so a static list is the right tool, not a reason to invent an
# architectural rule.
NON_PHYSICAL_LAYER_HINTS = [
    "viewport", "margin", "format", "title block", "titleblock",
    "plot", "f.s.i", "fsi", "built up", "builtup", "dim",
]

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
    # "chair"/"bike" added after real evidence: a real file's "CHAIRS" layer
    # (5,796 real shapes in one file, 296 in another) and "bike" layer (297
    # shapes, real bike-parking outlines) were both landing as
    # UNCLASSIFIED_OBSTACLE despite an unambiguous, literal layer name —
    # found by auditing what layer names actually sit behind unclassified
    # obstacles across every real file this pipeline has been tested
    # against, not a guess.
    ("FURNITURE", ["furn", "equip", "chair", "bike"]),
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


def _get_units(doc, unit_override=None):
    """unit_override (one of UNIT_NAME_TO_FEET's keys) lets an architect
    correct a file whose $INSUNITS is unspecified — see the endpoint that
    re-runs extract() with this set. When not overridden and $INSUNITS truly
    is 0, fall back to a real secondary signal instead of blindly assuming
    feet: $MEASUREMENT (0=imperial, 1=metric) and $LUNITS (linear units
    *display* format — 4 is "Architectural", which in practice means the
    drawing was authored with 1 drawing unit = 1 inch). This is still a
    guess, still marked needs_user_confirmation, but it's a guess backed by
    real header evidence rather than an arbitrary default — verified against
    theater_clean.dxf, whose real column width only makes sense (~2.25ft) at
    the inches assumption, not the old flat 1.0 (which read it as ~27ft)."""
    insunits = doc.header.get("$INSUNITS", 0)

    if unit_override and unit_override in UNIT_NAME_TO_FEET:
        return {
            "insunits_code": insunits,
            "detected_unit": unit_override,
            "feet_per_drawing_unit": UNIT_NAME_TO_FEET[unit_override],
            "needs_user_confirmation": False,
            "suggested_unit": None,
            "suggested_unit_reason": None,
            "source": "user_confirmed",
        }

    factor = UNIT_TO_FEET.get(insunits)
    detected_name = {0: "Unspecified", 1: "Inches", 2: "Feet", 4: "Millimeters", 5: "Centimeters", 6: "Meters"}.get(insunits, "Unknown")

    suggested_unit = None
    suggested_unit_reason = None
    if factor is None:
        measurement = doc.header.get("$MEASUREMENT", 0)
        lunits = doc.header.get("$LUNITS", 2)
        if measurement == 0:
            suggested_unit = "Inches"
            suggested_unit_reason = (
                "This file's $INSUNITS is unspecified, but its $MEASUREMENT/$LUNITS "
                "header (imperial, Architectural display format) matches how most "
                "real drawings without an explicit unit are actually authored — at "
                "1 drawing unit = 1 inch. Verify against one real dimension in the "
                "file before trusting this."
            )
        else:
            suggested_unit = "Millimeters"
            suggested_unit_reason = (
                "This file's $INSUNITS is unspecified, but its $MEASUREMENT header "
                "indicates a metric template — most such files are authored at "
                "1 drawing unit = 1 millimeter. Verify against one real dimension "
                "in the file before trusting this."
            )

    return {
        "insunits_code": insunits,
        "detected_unit": detected_name,
        "feet_per_drawing_unit": factor,
        "needs_user_confirmation": factor is None,
        "suggested_unit": suggested_unit,
        "suggested_unit_reason": suggested_unit_reason,
        "source": "file_header" if factor is not None else "heuristic_guess",
    }


def working_scale(units: dict) -> float:
    """The feet-per-drawing-unit factor extract() actually works at: the real
    file-header value when known, else the same header-based heuristic
    _get_units suggests, else a bare 1.0 fallback only when there's no
    evidence at all to go on. Shared with ai_cad_scan.py's _layer_stats so
    both agree on scale — that function used to fall back to a bare 1.0
    directly, which (found via theater_clean.dxf, whose real extent is
    ~1,514 x 807ft) reported its drawing_bbox_ft roughly 12x too large in the
    AI-scan prompt on any file with unspecified units, even after extract()
    itself was fixed to use the better heuristic."""
    return units["feet_per_drawing_unit"] or UNIT_NAME_TO_FEET.get(units.get("suggested_unit"), 1.0)


def _handle_of(e, fallback_idx):
    """Real top-level entities carry a stable DXF handle; entities produced by
    exploding a block INSERT (see _resolve_entities) are virtual copies with
    no handle of their own — fall back to a positional id so every shape still
    has *something* to show as provenance, without pretending it's a real
    DXF handle."""
    h = getattr(e.dxf, "handle", None)
    return str(h) if h else f"virtual-{fallback_idx}"


def _identity_tf(p):
    return (p[0], p[1])


def _resolve_entities(doc, msp):
    """Recursively resolve INSERT (block reference) entities into (entity,
    transform) pairs, where transform maps that entity's own block-local 2D
    coordinates into world (modelspace) coordinates. Real architectural DXFs
    very commonly draw repeated elements (columns, escalators, furniture
    symbols) as block inserts rather than raw geometry — ignoring INSERT
    entirely (this module's previous behavior) made every such element
    invisible to both extraction and rendering, confirmed on a real file:
    theater_clean.dxf draws 170 of its columns as INSERT references to a
    shared column block, none of which were previously seen at all.

    This deliberately does NOT use ezdxf's entity.virtual_entities() (or
    entity.copy().transform()) to do the transform — both were tested
    directly against this real file and found to silently produce the wrong
    sign on X for a *mirrored* insert (negative xscale, used by 2 of this
    file's 173 INSERTs: its title-block frame and one escalator symbol).
    Verified independently: multiplying the same INSERT's own matrix44()
    against a raw block-local point by hand gives the correct, real-world
    coordinate every time (mirrored or not) — that direct approach is what
    this function composes recursively (function composition, not matrix
    pre-multiplication, so a bug in any one level can't be misattributed to
    another) instead, depth-guarded against a pathological/cyclic reference.

    Also resolves DIMENSION entities the same way, for the same reason: a
    DIMENSION's visible lines/arrows/text are not on the entity itself, only
    on a real, already-world-coordinate anonymous block it references via
    dxf.geometry — confirmed directly (that block's own LINE coordinates
    already match the dimension's real position, unlike a normal INSERT
    block authored at a local origin), so no transform composition is
    needed there, just resolution into the same frame the DIMENSION was
    found in. Every entity sourced from a DIMENSION's geometry block, plus
    every top-level LEADER, is flagged in the returned annotation-id set —
    real client DXFs carry hundreds of these (112 DIMENSION + 136 LEADER on
    one real reference file), and before this they were entirely invisible:
    not rendered, not counted, nothing. They must still be excluded from
    boundary/obstacle detection (see extract()'s use of this set) — a
    dimension's extension line or a leader's callout line is annotation,
    never a real wall, and including it in wall-network reconstruction
    could only manufacture false boundary candidates, never find a real one.

    Returns (resolved, annotation_ids): resolved is a list of (entity,
    transform_fn) pairs — every entity in the drawing with directly-
    drawable geometry, paired with the function that converts its own local
    points into world coordinates (identity for anything already at the top
    level, not from a DIMENSION's block); annotation_ids is a set of
    id(entity) for entities that are annotation, not real geometry."""
    resolved = []
    annotation_ids = set()

    def make_child_transform(local_matrix, outer_fn):
        def fn(p):
            x, y, _z = local_matrix.transform((p[0], p[1], 0))
            return outer_fn((x, y))
        return fn

    def walk(entities, transform_fn, depth, in_annotation):
        for e in entities:
            t = e.dxftype()
            if t == "INSERT":
                if depth >= MAX_INSERT_DEPTH:
                    continue
                try:
                    local_matrix = e.matrix44()
                    block = doc.blocks.get(e.dxf.name)
                except Exception:
                    continue
                child_fn = make_child_transform(local_matrix, transform_fn)
                try:
                    walk(list(block), child_fn, depth + 1, in_annotation)
                except Exception:
                    continue
            elif t == "DIMENSION":
                if depth >= MAX_INSERT_DEPTH:
                    continue
                try:
                    block = doc.blocks.get(e.dxf.geometry)
                except Exception:
                    continue
                try:
                    walk(list(block), transform_fn, depth + 1, True)
                except Exception:
                    continue
            else:
                resolved.append((e, transform_fn))
                if in_annotation or t in ANNOTATION_ENTITY_TYPES:
                    annotation_ids.add(id(e))

    walk(list(msp), _identity_tf, 0, False)
    return resolved, annotation_ids


def _transform_circle(e, tf):
    """A CIRCLE under a rotation + uniform scale (the common real case) stays
    a circle; effective radius is measured from how far the transform moves a
    point one raw-radius away from center, so mirrored/rotated column blocks
    still come out the right size. A non-uniform scale would technically turn
    it into an ellipse, which this module doesn't model — not seen in any
    file tested so far, and noted here rather than silently mis-rendered as
    a differently-sized circle without comment."""
    c = (float(e.dxf.center[0]), float(e.dxf.center[1]))
    r = e.dxf.radius
    c2 = tf(c)
    edge2 = tf((c[0] + r, c[1]))
    r2 = math.hypot(edge2[0] - c2[0], edge2[1] - c2[1])
    return c2, r2


def _is_full_ellipse(e):
    try:
        return abs(abs(e.dxf.end_param - e.dxf.start_param) - 2 * math.pi) < 1e-6
    except Exception:
        return False


def _hatch_path_points(path, tf=_identity_tf):
    """A HATCH boundary path is either an explicit polyline (path.vertices,
    already ordered) or a chain of edges (line/arc segments) — both real,
    common cases in architectural DXFs (theater_clean.dxf's 23 HATCH entities
    are all edge-path). Returns an ordered point list approximating the path,
    tessellating any arc edges; anything else (elliptical/spline edges, not
    present in any file tested so far) is skipped rather than guessed at."""
    try:
        if getattr(path, "vertices", None):
            return [tf((float(v[0]), float(v[1]))) for v in path.vertices]
    except Exception:
        pass

    pts = []
    try:
        for edge in getattr(path, "edges", []):
            et = type(edge).__name__
            if et == "LineEdge":
                pts.append(tf((float(edge.start[0]), float(edge.start[1]))))
            elif et == "ArcEdge":
                cx, cy = float(edge.center[0]), float(edge.center[1])
                r = float(edge.radius)
                a0, a1 = math.radians(edge.start_angle), math.radians(edge.end_angle)
                if not getattr(edge, "is_counter_clockwise", True):
                    a0, a1 = a1, a0
                if a1 <= a0:
                    a1 += 2 * math.pi
                for i in range(8):
                    a = a0 + (a1 - a0) * i / 8
                    pts.append(tf((cx + r * math.cos(a), cy + r * math.sin(a))))
    except Exception:
        return []
    return pts


def _closed_points(e, tf=_identity_tf):
    """Return a list of (x, y) if this entity is a closed polyline/circle/
    closed spline/full ellipse, else None.

    LWPOLYLINE/POLYLINE/SPLINE/ELLIPSE go through ezdxf's generic path
    flattening (ezdxf.path.make_path(...).flattening(...)) rather than a bare
    vertex walk — a polyline segment with bulge (a rounded corner, common in
    real architectural drawings) previously got silently chorded into a
    straight line by connecting only the two endpoints, a real if usually
    minor area/shape error. Using the same flattening path _open_segments
    uses also keeps every function agreeing on what a curved boundary
    segment actually looks like."""
    t = e.dxftype()
    try:
        if t == "LWPOLYLINE":
            if not e.closed:
                return None
            path = ezdxf.path.make_path(e)
            pts = [tf((v.x, v.y)) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
        if t == "POLYLINE":
            if not e.is_closed:
                return None
            path = ezdxf.path.make_path(e)
            pts = [tf((v.x, v.y)) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
        if t == "CIRCLE":
            c, r = _transform_circle(e, tf)
            n = 16
            return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        if t == "SPLINE":
            if not getattr(e, "closed", False):
                return None
            path = ezdxf.path.make_path(e)
            pts = [tf((v.x, v.y)) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
        if t == "ELLIPSE":
            if not _is_full_ellipse(e):
                return None
            path = ezdxf.path.make_path(e)
            pts = [tf((v.x, v.y)) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
            return pts if len(pts) >= 3 else None
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


def _open_segments(e, tf=_identity_tf):
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
            return [(tf((s[0], s[1])), tf((end[0], end[1])))]
        except Exception:
            return []
    if t == "LEADER":
        try:
            pts = [tf((float(v[0]), float(v[1]))) for v in e.vertices]
            return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        except Exception:
            return []
    if t in ("LWPOLYLINE", "POLYLINE", "ARC", "SPLINE", "ELLIPSE"):
        try:
            path = ezdxf.path.make_path(e)
            pts = [tf((v.x, v.y)) for v in path.flattening(CURVE_FLATTEN_DISTANCE, CURVE_FLATTEN_MIN_SEGMENTS)]
        except Exception:
            return []
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return []


def _all_segments(e, tf=_identity_tf):
    """Every line-like, curved, or hatch-boundary entity, broken into 2-point
    segments in drawing units — the single source of truth for every raw-
    geometry backdrop (per-region, whole-drawing, and BoundaryStudio's richer
    full_raw_geometry), so they can't drift out of sync with each other."""
    t = e.dxftype()
    if t == "HATCH":
        segs = []
        try:
            for path in e.paths:
                pts = _hatch_path_points(path, tf)
                if len(pts) < 2:
                    continue
                for i in range(len(pts) - 1):
                    segs.append((pts[i], pts[i + 1]))
                segs.append((pts[-1], pts[0]))
        except Exception:
            return []
        return segs
    return _open_segments(e, tf)


def _dedupe_closed_shapes(closed_shapes):
    """A real block-based drawing very commonly draws one physical element
    (a column, in theater_clean.dxf's case) as BOTH a closed LWPOLYLINE
    outline and a HATCH fill covering the identical footprint — verified
    directly: every column block instance in that file emits exactly one of
    each, over the same 4 points. Without this, every such element would be
    double-counted as two separate obstacle candidates (confirmed: 170 real
    columns were producing ~340 obstacle entries before this). Two shapes
    are treated as duplicates of the same physical element when their area
    and centroid match closely; when they do, the explicit polyline is kept
    over its hatch twin (a literal outline is stronger evidence than a fill
    pattern), and a reconstructed shape is kept over a hatch twin for the
    same reason."""
    source_rank = {"explicit": 0, "reconstructed": 1, "hatch": 2}
    kept = {}
    for s in closed_shapes:
        c = s["polygon"].centroid
        key = (round(c.x, 1), round(c.y, 1), round(s["polygon"].area, 1))
        existing = kept.get(key)
        if existing is None or source_rank.get(s["source"], 3) < source_rank.get(existing["source"], 3):
            kept[key] = s
    return list(kept.values())


def _reconstruct_polygons_from_lines(entities, already_closed_handles, min_area_drawing_units, snap_tolerance_drawing_units=0.0, annotation_ids=frozenset()):
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
    for i, (e, tf) in enumerate(entities):
        if _handle_of(e, i) in already_closed_handles:
            continue  # already a closed shape in its own right; don't double-count its edges
        if id(e) in annotation_ids:
            continue  # a dimension extension line or leader is never a real wall segment
        if _layer_hint_score(str(e.dxf.layer), NON_PHYSICAL_LAYER_HINTS):
            continue  # a sheet frame/margin/title-block line is never a real wall segment either
        for a, b in _open_segments(e, tf):
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


MAX_FULL_RAW_LINES = 25000       # BoundaryStudio's richer whole-drawing view
MAX_FULL_RAW_TEXTS = 2000
MAX_WHOLE_DRAWING_RAW_LINES = 6000 * 3   # the simpler whole-drawing backdrop (draw-boundary-when-no-region fallback)
MAX_REGION_RAW_LINES = 6000      # one region's own cropped backdrop
MAX_RAW_TEXTS = 800


def _stride_sample(items, cap):
    """Even-stride sampling instead of a first-N cutoff — found via real
    testing (a real site plan with a dense hatched/dimensioned corner) that a
    first-N cutoff can exhaust the whole cap on one small cluster near the
    start of the entity list, leaving a 'backdrop' that shows only a tiny
    fraction of the drawing's real extent instead of the whole thing an
    architect tracing a boundary by hand actually needs to see. Returns
    (sampled_items, was_truncated)."""
    if len(items) <= cap:
        return items, False
    stride = len(items) / cap
    return [items[int(i * stride)] for i in range(cap)], True


def _build_full_raw_geometry(all_entities, closed_shapes, text_labels, scale, annotation_ids=frozenset()):
    """The ENTIRE drawing's raw linework, computed ONCE (up to MAX_FULL_RAW_LINES,
    the highest-fidelity cap of any consumer) and reused to derive every other
    raw-geometry view this module produces — the whole-drawing `raw_geometry`
    fallback, and every region's own cropped backdrop — instead of each
    re-walking and re-transforming every entity from scratch.

    This fixes a real, profiled performance bug: recomputing segments/
    transforms inside a per-region closure is O(regions x entities), measured
    at 88% of a 276s worst-case extraction on a real 100-region file
    (Vadodara, 63,607 entities). Filtering this single pre-built, already-in-
    feet list is O(regions x segments) with only cheap float comparisons, not
    transform math — brings the same file down to a few seconds.

    Every line carries a `category` ("geometry", "annotation", or "sheet") so
    real drawing content can be told apart from things that were never real
    wall/floor geometry, by anything downstream (BoundaryStudio dims and
    excludes both from wall-click candidacy, see extract()):
    - "annotation": a dimension extension line or leader callout.
    - "sheet": a line on a drafting-sheet-artifact layer (viewport frame,
      plot margin, title block, area-calculation callout — see
      NON_PHYSICAL_LAYER_HINTS). Found via a real file where a prominent,
      long diagonal MARGIN-layer line was rendered identically to a real
      wall and was the single most confusing thing on screen — visually
      the most prominent line in the whole drawing, but not architecture at
      all, and (before this fix) fully selectable as a "wall" in the Select
      Walls tool right alongside genuine walls.

    Every line also carries a `curve_group` (null, or a shared id) so a
    single curved DXF entity — ARC, SPLINE, a full-sweep ELLIPSE — that
    ezdxf's path-flattening breaks into many tiny straight fragments (a
    real 90-degree ARC on a real file flattened into 66 of them) can be
    selected as the one real curve it is with a single click, instead of
    requiring dozens of pixel-precise clicks on invisible fragments — found
    to be genuinely impractical, not just inconvenient, when a real
    architect tried to trace a boundary through a rounded wall corner.
    Deliberately scoped to entities that are inherently *one* continuous
    curve end to end: LWPOLYLINE/POLYLINE are left ungrouped (segment-level,
    unchanged) because one polyline can legitimately mix straight runs with
    a bulged corner, and grouping the whole entity would take away the
    already-real, separately-requested ability to select just one straight
    sub-portion of a wall (see BoundaryStudio's Shift+drag partial-select)."""
    lines = []
    circles = []
    truncated = False
    CURVE_GROUP_TYPES = ("ARC", "SPLINE", "ELLIPSE")

    for entity_idx, (e, tf) in enumerate(all_entities):
        if len(lines) >= MAX_FULL_RAW_LINES:
            truncated = True
            break
        t = e.dxftype()
        if id(e) in annotation_ids:
            category = "annotation"
        elif _layer_hint_score(str(e.dxf.layer) if e.dxf.hasattr("layer") else "", NON_PHYSICAL_LAYER_HINTS):
            category = "sheet"
        else:
            category = "geometry"
        curve_group = f"curve-{_handle_of(e, entity_idx)}" if t in CURVE_GROUP_TYPES else None
        try:
            if t in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "HATCH", "SPLINE", "ELLIPSE", "LEADER"):
                layer = str(e.dxf.layer)
                for a, b in _all_segments(e, tf):
                    lines.append({
                        "id": len(lines),
                        "a": [round(a[0] * scale, 3), round(a[1] * scale, 3)],
                        "b": [round(b[0] * scale, 3), round(b[1] * scale, 3)],
                        "layer": layer,
                        "category": category,
                        "curve_group": curve_group,
                    })
                    if len(lines) >= MAX_FULL_RAW_LINES:
                        truncated = True
                        break
            elif t == "CIRCLE":
                c, r = _transform_circle(e, tf)
                circles.append({
                    "center": [round(c[0] * scale, 3), round(c[1] * scale, 3)],
                    "radius": round(r * scale, 3),
                    "layer": str(e.dxf.layer),
                })
        except Exception:
            continue

    all_xs = [p[0] for ln in lines for p in (ln["a"], ln["b"])] + [t["position_ft"][0] for t in text_labels]
    all_ys = [p[1] for ln in lines for p in (ln["a"], ln["b"])] + [t["position_ft"][1] for t in text_labels]
    bounds_ft = (
        {"min_x": min(all_xs), "min_y": min(all_ys), "max_x": max(all_xs), "max_y": max(all_ys)}
        if all_xs and all_ys else {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 100}
    )

    return {
        "lines": lines,
        "circles": circles,
        "texts": text_labels[:MAX_FULL_RAW_TEXTS],
        "closed_shapes": [
            {
                "id": f"shape-{i}",
                "handle": s["handle"],
                "layer": s["layer"],
                "dxftype": s["dxftype"],
                "source": s.get("source", "explicit"),
                "area_sqft": round(s["area_sqft"], 3),
                "points_ft": s["points_ft"],
            }
            for i, s in enumerate(closed_shapes)
        ],
        "bounds_ft": bounds_ft,
        "truncated": truncated,
    }


def _simple_raw_geometry(full_raw, max_lines=MAX_WHOLE_DRAWING_RAW_LINES, max_texts=MAX_RAW_TEXTS):
    """The plain {lines, circles, texts, truncated} shape GeometryReviewStep/
    EditableCanvas's draw-boundary-by-hand fallback expects, derived from the
    already-built full_raw_geometry rather than re-walking entities."""
    lines = [[ln["a"], ln["b"]] for ln in full_raw["lines"]]
    sampled, stride_truncated = _stride_sample(lines, max_lines)
    return {
        "lines": sampled,
        "circles": [{"center": c["center"], "radius": c["radius"]} for c in full_raw["circles"]],
        "texts": [{"text": t["text"], "position": t["position_ft"]} for t in full_raw["texts"]][:max_texts],
        "truncated": stride_truncated or full_raw["truncated"],
    }


def _region_raw_geometry(full_raw, minx_ft, miny_ft, maxx_ft, maxy_ft, max_lines=MAX_REGION_RAW_LINES, max_texts=MAX_RAW_TEXTS):
    """One region's own cropped CAD backdrop — a bounding-box filter over the
    already-built full_raw_geometry (see _build_full_raw_geometry), not a
    fresh entity walk."""
    pad = max((maxx_ft - minx_ft), (maxy_ft - miny_ft)) * 0.05
    bx0, by0, bx1, by1 = minx_ft - pad, miny_ft - pad, maxx_ft + pad, maxy_ft + pad

    def in_box(pt):
        return bx0 <= pt[0] <= bx1 and by0 <= pt[1] <= by1

    matched = [[ln["a"], ln["b"]] for ln in full_raw["lines"] if in_box(ln["a"]) or in_box(ln["b"])]
    lines, truncated = _stride_sample(matched, max_lines)
    circles = [{"center": c["center"], "radius": c["radius"]} for c in full_raw["circles"] if in_box(c["center"])]
    texts = [{"text": t["text"], "position": t["position_ft"]} for t in full_raw["texts"] if in_box(t["position_ft"])][:max_texts]
    return {"lines": lines, "circles": circles, "texts": texts, "truncated": truncated}


def trace_boundary_from_segments(full_raw_geometry: dict, segment_ids: list, custom_segments: list = None) -> dict:
    """Given a set of line-segment ids the architect clicked (from
    full_raw_geometry.lines, already in feet) as 'these are the walls of my
    boundary', find the closed loop they form. Uses the same polygonize
    technique as the automatic wall-reconstruction pass, but scoped to
    exactly the segments a human picked instead of guessing across the whole
    drawing — the deliberate, fast 'select lines to assume as walls' path,
    distinct from clicking an existing closed shape or drawing freehand.

    custom_segments: literal [[x1,y1],[x2,y2]] coordinate pairs (already in
    feet) for a sub-portion of a wall the architect dragged out directly
    instead of picking the whole pre-computed segment — e.g. only half of a
    long wall is actually part of the boundary they're defining. These are
    real user-drawn geometry, not looked up against full_raw_geometry at
    all, so they work regardless of how the original line was segmented.

    Raises ValueError with a specific, actionable message if the selection
    doesn't close (some real feedback, not a bare 'invalid selection')."""
    by_id = {ln["id"]: ln for ln in full_raw_geometry["lines"]}
    lines = []
    for sid in segment_ids:
        ln = by_id.get(sid)
        if ln is None:
            continue
        a, b = tuple(ln["a"]), tuple(ln["b"])
        if a == b:
            continue
        lines.append(LineString([a, b]))

    for seg in (custom_segments or []):
        try:
            a, b = tuple(seg[0]), tuple(seg[1])
        except (IndexError, TypeError):
            continue
        if a == b:
            continue
        lines.append(LineString([a, b]))

    if len(lines) < 3:
        raise ValueError("Select at least 3 wall segments that form a closed loop.")

    polys = [p for p in polygonize(lines) if p.is_valid and p.area > 0]
    if not polys:
        raise ValueError(
            "These segments don't form a closed loop yet — there's a gap somewhere in the "
            "selection. Select the missing wall segment(s) to close it, or switch to Draw "
            "Boundary to finish it by hand."
        )

    best = max(polys, key=lambda p: p.area)
    return {
        "points_ft": [[round(x, 3), round(y, 3)] for x, y in best.exterior.coords][:-1],
        "area_sqft": round(best.area, 2),
    }


def build_manual_region(points_ft: list, mode: str, full_raw_geometry: dict, existing_source_handle: str = None) -> dict:
    """Build a region (boundary + contained obstacles + text labels), the same
    shape extract() produces per auto-detected candidate, from a boundary the
    architect defined directly — by clicking an existing closed shape, tracing
    selected wall segments, or drawing freehand. Operates entirely in feet
    (everything in full_raw_geometry already is), against the same closed-shape/
    text-label evidence the automatic pass already extracted, so a manually
    defined region gets the same real obstacle detection an automatic one does
    — this is not a lesser, obstacle-blind path."""
    poly = _safe_polygon(points_ft)
    if not poly:
        raise ValueError("This boundary isn't a valid closed shape (self-intersecting or zero-area). Adjust the points and try again.")

    b_area = poly.area
    minx, miny, maxx, maxy = poly.bounds

    obstacles = []
    for s in full_raw_geometry["closed_shapes"]:
        if existing_source_handle and s["handle"] == existing_source_handle:
            continue
        if s["area_sqft"] < MIN_OBSTACLE_AREA_SQFT or s["area_sqft"] > b_area * MAX_OBSTACLE_AREA_RATIO:
            continue
        s_poly = _safe_polygon(s["points_ft"])
        if not s_poly:
            continue
        inter = s_poly.intersection(poly).area
        if s_poly.area == 0 or inter / s_poly.area < CONTAINMENT_THRESHOLD:
            continue

        classification, layer_matched = _classify_obstacle_layer(s["layer"])
        is_squarish = 0.0
        try:
            sminx, sminy, smaxx, smaxy = s_poly.bounds
            w, h = smaxx - sminx, smaxy - sminy
            is_squarish = min(w, h) / max(w, h) if max(w, h) > 0 else 0
        except Exception:
            pass

        if layer_matched:
            confidence = "high"
        elif is_squarish > 0.6 and s["area_sqft"] < 20:
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
            "status": "PROPOSED",
        })

    region_texts = [
        t for t in full_raw_geometry.get("texts", [])
        if minx <= t["position_ft"][0] <= maxx and miny <= t["position_ft"][1] <= maxy
    ]

    mode_note = {
        "shape": "Selected directly from a closed shape in the source drawing. Verify before confirming.",
        "walls": "Traced from wall segments you selected. Verify before confirming, especially near the traced corners.",
        "draw": "Drawn by hand — this boundary has no direct support in the source CAD file. Verify carefully before confirming.",
    }.get(mode, "Manually defined. Verify before confirming.")

    return {
        "region_id": f"region-{uuid.uuid4().hex[:8]}",
        "boundary": {
            "source_handle": existing_source_handle or f"manual-{uuid.uuid4().hex[:8]}",
            "layer": "manual",
            "source": f"manual-{mode}",
            "area_sqft": round(b_area, 2),
            "points_ft": [[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords][:-1],
            "bounding_box_ft": {"min_x": round(minx, 2), "min_y": round(miny, 2), "max_x": round(maxx, 2), "max_y": round(maxy, 2)},
            "confidence": "medium" if mode in ("shape", "walls") else "low",
            "note": mode_note,
            "status": "PROPOSED",
        },
        "obstacles": obstacles,
        "text_labels": region_texts,
        "raw_geometry": _region_raw_geometry(full_raw_geometry, minx, miny, maxx, maxy),
    }


def extract(input_path: str, allowed_layers=None, min_boundary_area_sqft=None, unit_override: str = None) -> dict:
    """Main entry point. input_path may be .dwg or .dxf. Returns canonical geometry.

    allowed_layers / min_boundary_area_sqft: normally None (unfiltered, the
    default MIN_BOUNDARY_AREA_SQFT) — real overrides exist only for
    ai_cad_scan.py's AI-assisted rescan, which restricts extraction to a
    layer subset Claude identified as the real wall/floor layer(s) when the
    default full-drawing pass found nothing usable. Dimension/hatch/furniture
    noise on unrelated layers can fragment or dominate the segment network
    enough that the real boundary never wins pass 2's candidate selection —
    this is the deterministic engine's own logic re-run on a cleaner subset,
    not a different/less-trustworthy extraction path.

    unit_override (see _get_units) re-scales an already-uploaded file whose
    units were unspecified, per an architect's confirmation, without needing
    to re-upload."""
    dxf_path, conversion_note = resolve_dxf_path(input_path)

    doc, recovery_note = _read_dxf_with_recovery(dxf_path)
    msp = doc.modelspace()
    units = _get_units(doc, unit_override=unit_override)
    # If $INSUNITS is unspecified, use the header-based suggestion (see
    # _get_units) as the working scale rather than silently treating raw
    # units as feet — still flagged via needs_user_confirmation either way,
    # but a real evidence-backed guess beats an arbitrary 1:1 default (found
    # via theater_clean.dxf: raw-units-as-feet made every real dimension in
    # the file 12x too large).
    scale = working_scale(units)

    entities, annotation_ids = _resolve_entities(doc, msp)
    if allowed_layers:
        allowed_set = set(allowed_layers)
        entities = [(e, tf) for e, tf in entities if str(e.dxf.layer) in allowed_set]
    min_boundary_area_sqft = MIN_BOUNDARY_AREA_SQFT if min_boundary_area_sqft is None else min_boundary_area_sqft

    # --- Pass 1: find every closed shape and its polygon/area (in drawing units) ---
    closed_shapes = []
    closed_handles = set()
    for i, (e, tf) in enumerate(entities):
        if id(e) in annotation_ids:
            continue  # a dimension/leader can't be a real wall or column — see _resolve_entities
        if _layer_hint_score(str(e.dxf.layer), NON_PHYSICAL_LAYER_HINTS):
            continue  # a sheet frame/margin/title-block/area-callout is never real geometry — see NON_PHYSICAL_LAYER_HINTS
        t = e.dxftype()
        h = _handle_of(e, i)
        if t == "HATCH":
            try:
                for path in e.paths:
                    pts = _hatch_path_points(path, tf)
                    if len(pts) < 3:
                        continue
                    poly = _safe_polygon(pts)
                    if not poly:
                        continue
                    closed_shapes.append({
                        "handle": h, "layer": str(e.dxf.layer), "dxftype": "HATCH", "source": "hatch",
                        "polygon": poly, "area_sqft": poly.area * (scale ** 2),
                        "points_ft": [[round(x * scale, 3), round(y * scale, 3)] for x, y in poly.exterior.coords]
                    })
            except Exception:
                pass
            continue

        pts = _closed_points(e, tf)
        if not pts:
            continue
        poly = _safe_polygon(pts)
        if not poly:
            continue
        closed_shapes.append({
            "handle": h,
            "layer": str(e.dxf.layer),
            "dxftype": t,
            "source": "explicit",
            "polygon": poly,
            "area_sqft": poly.area * (scale ** 2),
            "points_ft": [[round(x * scale, 3), round(y * scale, 3)] for x, y in poly.exterior.coords]
        })
        closed_handles.add(h)

    closed_shapes = _dedupe_closed_shapes(closed_shapes)
    closed_handles = {s["handle"] for s in closed_shapes}

    # --- Pass 1b: reconstruct additional boundary candidates from discrete wall
    # line segments (LINE/open-polyline entities that together form a closed
    # loop but aren't one explicit closed shape in the source file) ---
    min_area_drawing_units = MIN_OBSTACLE_AREA_SQFT / max(scale ** 2, 1e-9)  # cheap pre-filter, tightened again in feet below
    snap_tolerance_drawing_units = WALL_SNAP_TOLERANCE_FT / max(scale, 1e-9)
    for rec in _reconstruct_polygons_from_lines(entities, closed_handles, min_area_drawing_units, snap_tolerance_drawing_units, annotation_ids):
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
    for e, tf in entities:
        if e.dxftype() in ("TEXT", "MTEXT"):
            try:
                txt = e.plain_text().strip() if hasattr(e, "plain_text") else str(getattr(e.dxf, "text", "")).strip()
                if not txt:
                    continue
                ins = e.dxf.insert
                pos = tf((float(ins[0]), float(ins[1])))
                text_labels.append({"text": txt, "position_ft": [round(pos[0] * scale, 3), round(pos[1] * scale, 3)]})
            except Exception:
                continue

    # Computed once, in feet, over every entity — every other raw-geometry
    # view below (the simple whole-drawing backdrop, each region's own crop)
    # is derived by filtering this instead of re-walking entities. See
    # _build_full_raw_geometry's own docstring for the real performance bug
    # this fixes.
    full_raw_geometry = _build_full_raw_geometry(entities, closed_shapes, text_labels, scale, annotation_ids)

    # Spatial index over every closed shape so each region only tests the
    # handful actually near it, instead of every region testing every shape
    # in the drawing. A real large multi-tenant file (Vadodara: 100 regions,
    # ~21,000 closed shapes) made the naive O(regions x shapes) version of
    # this loop a measurable chunk of a 276s worst-case extraction — most of
    # those region/shape pairs are nowhere near each other and can be ruled
    # out by a bounding-box query instead of a real shapely intersection.
    from shapely.strtree import STRtree
    shape_polys = [s["polygon"] for s in closed_shapes]
    shape_tree = STRtree(shape_polys) if shape_polys else None

    regions = []
    for boundary in chosen_boundaries:
        b_poly = boundary["polygon"]
        b_area = boundary["area_sqft"]
        minx, miny, maxx, maxy = b_poly.bounds

        obstacles = []
        nearby_idx = shape_tree.query(b_poly) if shape_tree is not None else []
        for idx in nearby_idx:
            s = closed_shapes[idx]
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
            "raw_geometry": _region_raw_geometry(full_raw_geometry, minx * scale, miny * scale, maxx * scale, maxy * scale)
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
        "schema_version": "1.1",
        "source_filename": os.path.basename(input_path),
        "conversion_note": conversion_note,
        "recovery_note": recovery_note,
        "units": units,
        "extraction_method": "generic-geometric (largest-closed-polyline heuristic + containment-based obstacle detection)",
        "total_entities_scanned": len(entities),
        "total_closed_shapes_found": len(closed_shapes),
        "region_count": len(regions),
        "regions": regions,
        "unclassified_text_count": len(text_labels),
        "raw_geometry": _simple_raw_geometry(full_raw_geometry),
        "full_raw_geometry": full_raw_geometry,
    }
