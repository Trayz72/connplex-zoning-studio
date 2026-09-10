"""
CAD cleaning — turns an arbitrary, cluttered CAD upload into a stripped-down
file containing only the outline, columns, and ducts for one or more
selected areas, before it ever reaches the architect-facing Geometry Review
step. Built for a non-technical (e.g. sales) user: point at the piece of the
drawing that matters, get back a clean file.

Deliberately does no new parsing or containment math of its own — boundary
selection and obstacle detection are entirely cad_extraction.py's existing
full_raw_geometry / build_manual_region (the same real containment/
classification logic BoundaryStudio's "click a closed shape" tool already
uses), so a cleaned region is exactly as trustworthy as a manually-defined
region anywhere else in this app. This module only decides, from an already-
built region, which of its contained obstacles are "obstacles, internal
walls, or components" to strip (everything except COLUMN/DUCT) and how to
serialize what's left back out as a DXF/DWG a salesperson can hand off.
"""
import os

import ezdxf
from shapely.geometry import Point
from shapely.strtree import STRtree

import cad_extraction

KEPT_CLASSIFICATIONS = ("COLUMN", "DUCT")

CLEAN_LAYER_NAMES = ["OUTLINE", "COLUMN", "DUCT"]

# Passed as cad_extraction.extract()'s min_boundary_area_sqft override when
# re-extracting a clean file (see main.py's /clean/confirm) — far below the
# default 150 sqft, which exists to reject furniture-scale junk in an
# arbitrary raw upload. A clean file's OUTLINE layer was already
# deliberately chosen by the user in Clean CAD, not a heuristic guess, so
# that risk doesn't apply here; a real, if unusually small, room shouldn't
# need an extra manual re-selection click just to be found again. Still
# strictly positive so a truly degenerate zero-area sliver can't pass.
MIN_CLEAN_BOUNDARY_AREA_SQFT = 1.0


def _bbox_of(points_ft):
    xs = [p[0] for p in points_ft]
    ys = [p[1] for p in points_ft]
    return {"min_x": round(min(xs), 2), "min_y": round(min(ys), 2), "max_x": round(max(xs), 2), "max_y": round(max(ys), 2)}


def _shape_by_handle(full_raw_geometry: dict, handle: str):
    for s in full_raw_geometry.get("closed_shapes", []):
        if s["handle"] == handle:
            return s
    return None


def search_labels(full_raw_geometry: dict, query: str) -> list:
    """Case-insensitive substring match of `query` (a room/space name a
    salesperson types, e.g. "Screen 1", "Suite 200") against every text
    label already drawn in the file, paired with the smallest closed shape
    that contains that label's position — the label's own immediate
    enclosing outline is what a person means by a room name, not whichever
    outer outline happens to also contain it (e.g. a suite nested inside a
    whole-floor outline). Returns matches most-specific-first; a match with
    no enclosing shape still comes back (shape_handle: None) so the caller
    can say so rather than silently dropping it."""
    q = (query or "").strip().lower()
    if not q:
        return []

    matching_texts = [t for t in full_raw_geometry.get("texts", []) if q in (t.get("text") or "").lower()]
    if not matching_texts:
        return []

    # Polygons built once and spatially indexed, not rebuilt from scratch for
    # every text match against every shape — the naive O(matches x shapes)
    # version of this (each _safe_polygon() reconstructed fresh per pair) was
    # measured at 45.7s for just 52 matches against a real 21,894-closed-shape
    # file (Keshav Landmark), the exact "worked on a small synthetic file,
    # fell over on a real one" pattern already found and fixed elsewhere in
    # this app's boundary-candidate collapse pass — the fix here is the same
    # STRtree query-then-verify pattern used throughout cad_extraction.py.
    closed_shapes = full_raw_geometry.get("closed_shapes", [])
    shapes_with_polys = []
    for s in closed_shapes:
        poly = cad_extraction._safe_polygon(s["points_ft"])
        if poly:
            shapes_with_polys.append((s, poly))
    shape_tree = STRtree([p for _, p in shapes_with_polys]) if shapes_with_polys else None

    matches = []
    for t in matching_texts:
        pos = Point(t["position_ft"])
        best = None
        nearby_idx = shape_tree.query(pos) if shape_tree is not None else []
        for idx in nearby_idx:
            s, poly = shapes_with_polys[idx]
            if not poly.contains(pos):
                continue
            if best is None or s["area_sqft"] < best["area_sqft"]:
                best = s

        matches.append({
            "text": t.get("text") or "",
            "position_ft": t["position_ft"],
            "shape_handle": best["handle"] if best else None,
            "shape_area_sqft": round(best["area_sqft"], 2) if best else None,
            "shape_bounding_box_ft": _bbox_of(best["points_ft"]) if best else None,
        })

    matches.sort(key=lambda m: (m["shape_area_sqft"] is None, m["shape_area_sqft"] or 0))
    return matches


def search_by_area(full_raw_geometry: dict, target_area_sqft: float, tolerance_fraction: float = None) -> list:
    """Given the project's own stated intake-form Carpet Area, proactively
    finds which closed shape(s) already in the file are close to that real
    figure — the salesperson doesn't have to already know which shape is
    the right one; this surfaces it the moment the file is uploaded. Same
    "form drives boundary detection" principle cad_extraction._form_match_info
    already applies to the automatic region-candidate pipeline, just over
    Clean CAD's much broader "any closed shape in the file" pool instead of
    pre-ranked region candidates. Sorted closest-match-first. Purely a
    suggestion — never auto-selects anything, the same as everywhere else
    in this app uncertain detection stays proposed until a human clicks."""
    if not target_area_sqft or target_area_sqft <= 0:
        return []
    tolerance = tolerance_fraction if tolerance_fraction is not None else cad_extraction.FORM_MATCH_AREA_TOLERANCE_FRACTION

    matches = []
    for s in full_raw_geometry.get("closed_shapes", []):
        area = s["area_sqft"]
        if area <= 0:
            continue
        rel_error = abs(area - target_area_sqft) / target_area_sqft
        if rel_error > tolerance:
            continue
        matches.append({
            "shape_handle": s["handle"],
            "shape_area_sqft": round(area, 2),
            "shape_bounding_box_ft": _bbox_of(s["points_ft"]),
            "rel_error_pct": round(rel_error * 100, 1),
        })
    matches.sort(key=lambda m: m["rel_error_pct"])
    return matches


def build_clean_regions(full_raw_geometry: dict, shape_handles: list) -> list:
    """One region per selected closed-shape handle, via the exact same
    build_manual_region() an architect's own "click a shape" tool calls —
    'one or more boundaries, connected or not' falls out for free since each
    selection is resolved independently rather than merged into one polygon."""
    if not shape_handles:
        raise ValueError("Select at least one boundary to clean.")

    regions = []
    seen = set()
    for handle in shape_handles:
        if handle in seen:
            continue
        seen.add(handle)
        shape = _shape_by_handle(full_raw_geometry, handle)
        if not shape:
            raise ValueError(f"Selected shape '{handle}' was not found in this file's extracted geometry.")
        region = cad_extraction.build_manual_region(
            points_ft=shape["points_ft"],
            mode="shape",
            full_raw_geometry=full_raw_geometry,
            existing_source_handle=handle,
        )
        regions.append(region)
    return regions


def partition_kept(region: dict) -> dict:
    """The actual cleaning decision: a region's boundary/outline is always
    kept; its contained obstacles split into kept (COLUMN, DUCT) vs. dropped
    (WALL, DOOR, WINDOW, STAIRCASE, WASHROOM_FIXTURE, FURNITURE,
    UNCLASSIFIED_OBSTACLE) — matches the brief exactly: remove obstacles,
    internal/not-needed walls, and other components from the selected
    boundary except columns, ducts, and the outline."""
    kept = [o for o in region["obstacles"] if o["classification"] in KEPT_CLASSIFICATIONS]
    dropped = [o for o in region["obstacles"] if o["classification"] not in KEPT_CLASSIFICATIONS]
    return {"kept": kept, "dropped": dropped}


def _carpet_area_check(region: dict, target_area_sqft, label_hint):
    """Clean CAD's own honest-in-both-directions check, built on
    cad_extraction._form_match_info: that function is deliberately silent
    on a mismatch (correct when ranking many automatic candidates — see its
    own docstring), but here the user has already committed to ONE shape,
    so a mismatch is exactly the signal worth surfacing, not suppressing.
    Returns None when no target was supplied — nothing to validate
    against, not a fabricated warning."""
    if not target_area_sqft or target_area_sqft <= 0:
        return None
    area = region["boundary"]["area_sqft"]
    is_match, note = cad_extraction._form_match_info(
        area, region["text_labels"], target_area_sqft, label_hint
    )
    if is_match:
        return {"matches": True, "note": note}
    rel_error = abs(area - target_area_sqft) / target_area_sqft
    return {
        "matches": False,
        "note": (
            f"This boundary is {rel_error * 100:.0f}% off your stated carpet area "
            f"({target_area_sqft:,.0f} sqft) — double-check this is the right selection."
        ),
    }


def preview_summary(regions: list, target_area_sqft: float = None, label_hint: str = None) -> list:
    """Per-region kept/dropped counts for a before/after readout on the
    selection screen — read-only, nothing here mutates a region. Kept
    deliberately simple (counts by classification, not a per-item
    confirm/ignore list like GeometryReviewStep) since this stage's audience
    is a salesperson cleaning a file, not an architect reviewing one.

    target_area_sqft/label_hint (both default None, so every existing
    caller is unaffected) are the project's own intake-form Carpet Area /
    Floor-Shop-No, when available — see _carpet_area_check."""
    summary = []
    for region in regions:
        split = partition_kept(region)
        kept_by_classification, dropped_by_classification = {}, {}
        for o in split["kept"]:
            kept_by_classification[o["classification"]] = kept_by_classification.get(o["classification"], 0) + 1
        for o in split["dropped"]:
            dropped_by_classification[o["classification"]] = dropped_by_classification.get(o["classification"], 0) + 1
        summary.append({
            "region_id": region["region_id"],
            "source_handle": region["boundary"]["source_handle"],
            "boundary_area_sqft": region["boundary"]["area_sqft"],
            # Same real, already-computed figure as boundary_area_sqft above —
            # deliberately re-exposed under Connplex's own business term (see
            # this feature's plan doc for why this isn't a new "minus walls"
            # computation: no sourced formula for that exists anywhere in the
            # registry/SOP extract).
            "net_usage_area_sqft": region["boundary"]["area_sqft"],
            "boundary_points_ft": region["boundary"]["points_ft"],
            "kept_count": len(split["kept"]),
            "dropped_count": len(split["dropped"]),
            "kept_by_classification": kept_by_classification,
            "dropped_by_classification": dropped_by_classification,
            "carpet_area_check": _carpet_area_check(region, target_area_sqft, label_hint),
        })
    return summary


def _flip(pt):
    """points_ft is Y-down (see cad_extraction.py's _identity_tf); DXF is
    natively Y-up. Same negate-Y-on-write convention export_dxf.py already
    uses so this file opens right-side-up in any real CAD viewer."""
    return (pt[0], -pt[1])


def _ensure_clean_layers(doc):
    for name in CLEAN_LAYER_NAMES:
        if name not in doc.layers:
            doc.layers.add(name, color=7)  # plain default line work, same convention as export_dxf.py


def export_clean_cad(regions: list, output_path: str, also_dwg: bool = False) -> dict:
    """Writes a fresh DXF (ezdxf.new — never reopening the messy original)
    containing only each region's outline plus its kept COLUMN/DUCT
    obstacles, then optionally the DWG twin via the same ODA wrapper
    export_dxf.py already reuses for its own DXF->DWG step. Same
    {dxf_path, dwg_path, dwg_conversion_error} return contract as
    export_dxf.export_layout_to_dxf, so callers/endpoints can treat a clean
    export exactly like the existing layout export."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2  # feet, matches this app's internal canonical unit
    _ensure_clean_layers(doc)
    msp = doc.modelspace()

    for region in regions:
        boundary_pts = region["boundary"]["points_ft"]
        msp.add_lwpolyline([_flip(p) for p in boundary_pts], close=True, dxfattribs={"layer": "OUTLINE"})
        for obstacle in partition_kept(region)["kept"]:
            msp.add_lwpolyline([_flip(p) for p in obstacle["points_ft"]], close=True,
                                dxfattribs={"layer": obstacle["classification"]})

    doc.saveas(output_path)

    result = {"dxf_path": output_path, "dwg_path": None, "dwg_conversion_error": None}
    if also_dwg:
        try:
            result["dwg_path"] = cad_extraction.oda_convert(output_path, "dwg", os.path.dirname(output_path))
        except Exception as e:
            result["dwg_conversion_error"] = str(e)
    return result
