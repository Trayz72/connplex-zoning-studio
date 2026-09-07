"""Regression coverage for the plot/site-boundary vs. building-footprint
disambiguation fix (see cad_extraction.py's SUSPECTED_PLOT_BOUNDARY_*
constants). A real client file ("CHAUDHARY ,palanpur gujrat @ COMPLEX
30.05.26 final.dxf") produced a much larger plain rectangle on AutoCAD's
meaningless default layer "0" (the property/plot-boundary line) ranked
ahead of the real, smaller, wall-hinted building footprint, with no note
attached — BoundaryStudio.tsx's own boundaryIsClean/autoMode check then
silently auto-advanced past the correct candidate before an architect ever
saw the other 9 candidates. These tests use a small synthetic DXF that
reproduces the same shape (a big plain rectangle on layer "0" + a smaller
irregular polygon on a wall-hinted layer) rather than depending on the real
uploaded file, so this can't regress silently."""
import ezdxf

import cad_extraction


def test_a_genuine_line_pattern_hatch_boundary_is_flagged_as_net_usage_hatch(tmp_path):
    """cad_extraction.py's own HATCH-handling comment in Pass 1: a real,
    non-solid pattern hatch (ANSI31/ANSI32/ANGLE/etc — never hardcoded by
    name, since real firms use many different pattern names for the same
    convention) covering a closed shape is the standard architectural way of
    marking "net usage area" — found by directly inspecting a real client
    file's DXF hatch attributes (pattern_name="ANSI31", solid_fill=0) after
    the file's own printed "NET USAGE AREA" text label matched that exact
    hatch's computed area to within 0.003%, while an unrelated solid-fill
    hatch elsewhere in the same file did not."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    hatch = msp.add_hatch(dxfattribs={"layer": "AH Hatches WALL"})
    hatch.set_pattern_fill("ANSI31", scale=2.0)
    hatch.paths.add_polyline_path([(0, 0), (100, 0), (100, 80), (0, 80)], is_closed=True)
    dxf_path = str(tmp_path / "line_hatch.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["region_count"] == 1
    b = result["regions"][0]["boundary"]
    assert b["source"] == "hatch"
    assert b["hatch_pattern"] == "ANSI31"
    assert b["is_net_usage_hatch"] is True


def test_a_solid_fill_hatch_boundary_is_not_flagged_as_net_usage_hatch(tmp_path):
    """A solid_fill hatch is a flat color fill — not lines at all — so it
    must NOT be treated as the drawing's own net-usage-area marking
    convention, even though it's still a real, legitimate hatch-sourced
    boundary candidate otherwise (source == "hatch" stays unchanged)."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    hatch = msp.add_hatch(dxfattribs={"layer": "AH Hatches WALL"})
    hatch.set_solid_fill()
    hatch.paths.add_polyline_path([(0, 0), (60, 0), (60, 60), (0, 60)], is_closed=True)
    dxf_path = str(tmp_path / "solid_hatch.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    b = result["regions"][0]["boundary"]
    assert b["source"] == "hatch"
    assert b["hatch_pattern"] == "SOLID"
    assert b["is_net_usage_hatch"] is False


def test_a_plain_explicit_polyline_boundary_has_no_hatch_pattern(tmp_path):
    """A closed shape that was never a HATCH entity at all (an ordinary
    closed LWPOLYLINE, e.g. a plot boundary line) must report
    hatch_pattern=None and is_net_usage_hatch=False, never a stale/incorrect
    value carried over from some other candidate."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True, dxfattribs={"layer": "0"})
    dxf_path = str(tmp_path / "plain_polyline.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    b = result["regions"][0]["boundary"]
    assert b["source"] == "explicit"
    assert b["hatch_pattern"] is None
    assert b["is_net_usage_hatch"] is False


def _write_plot_and_building_dxf(path):
    """A 20,000 sqft plain rectangle on layer "0" (no wall/boundary naming
    evidence, a perfect 4-corner rectangle — a real plot/site-boundary
    line's own drafting convention) plus a disjoint, irregular 2,600 sqft
    L-shape on a wall-hinted layer (the real building footprint's own
    convention, using the exact real layer name found in the source
    client file) elsewhere in the same drawing."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2  # feet — no unit-conversion scaling in play
    msp = doc.modelspace()
    plot_pts = [(0, 0), (200, 0), (200, 100), (0, 100)]
    msp.add_lwpolyline(plot_pts, close=True, dxfattribs={"layer": "0"})
    building_pts = [(300, 0), (350, 0), (350, 40), (330, 40), (330, 60), (300, 60)]
    msp.add_lwpolyline(building_pts, close=True, dxfattribs={"layer": "AH Hatches WALL"})
    doc.saveas(path)


def _region_for_layer(result, layer):
    return next(r for r in result["regions"] if r["boundary"]["layer"] == layer)


def test_plain_unnamed_layer_rectangle_gets_flagged_when_a_smaller_wall_hinted_candidate_exists(tmp_path):
    dxf_path = str(tmp_path / "plot_and_building.dxf")
    _write_plot_and_building_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["region_count"] == 2

    plot_region = _region_for_layer(result, "0")
    building_region = _region_for_layer(result, "AH Hatches WALL")

    assert plot_region["boundary"]["area_sqft"] > building_region["boundary"]["area_sqft"]
    assert plot_region["boundary"]["note"] is not None
    assert "plot" in plot_region["boundary"]["note"].lower()
    assert plot_region["boundary"]["confidence"] == "low"


def test_wall_hinted_building_footprint_stays_clean(tmp_path):
    dxf_path = str(tmp_path / "plot_and_building.dxf")
    _write_plot_and_building_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path)
    building_region = _region_for_layer(result, "AH Hatches WALL")

    assert building_region["boundary"]["note"] is None
    assert building_region["boundary"]["confidence"] == "high"


def test_flagged_plot_boundary_is_sorted_after_the_real_building_footprint(tmp_path):
    """The whole point of the fix: BoundaryStudio.tsx defaults to
    regions[0] as its primary "DETECTED AUTOMATICALLY" candidate, so the
    flagged plot boundary must not be regions[0] once a cleaner candidate
    exists — even though it's the larger shape and would have sorted first
    under the old area-only ordering."""
    dxf_path = str(tmp_path / "plot_and_building.dxf")
    _write_plot_and_building_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["regions"][0]["boundary"]["layer"] == "AH Hatches WALL"


def test_a_genuinely_rectangular_single_boundary_file_is_never_flagged(tmp_path):
    """No sibling candidate exists to compare against at all here — a file
    with exactly one real, rectangular floor plate (common and entirely
    legitimate) must never be flagged just for being a plain rectangle on
    an unhelpfully named layer. Guards against over-triggering: this
    heuristic requires a materially smaller, wall-hinted sibling candidate
    to exist, not just "looks like a rectangle on layer 0" alone."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True, dxfattribs={"layer": "0"})
    dxf_path = str(tmp_path / "single_rectangle.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["region_count"] == 1
    assert result["regions"][0]["boundary"]["note"] is None


def _write_plot_swallowing_nested_building_dxf(path):
    """A real, deeper case found on the same client file after the first fix
    landed: the plot boundary doesn't just outrank the real building, it can
    fully CONTAIN it (>60%) — and the nesting-collapse pass (which runs
    before any note/confidence is attached) used to only exempt a container
    from swallowing a nested candidate when it was implausibly large
    (>500,000 sqft). A 151,899 sqft plot rectangle is nowhere near that, so
    a real, wall-hinted 8,297 sqft building nested inside it was silently
    demoted to being just one more "obstacle" of the plot line — never
    reachable as its own selectable region at all, not merely mis-ranked.
    This reproduces that shape: a 30,000 sqft plain rectangle on layer "0"
    fully containing a 4,000 sqft rectangle on a wall-hinted layer."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 150), (0, 150)], close=True, dxfattribs={"layer": "0"})
    msp.add_lwpolyline([(20, 20), (70, 20), (70, 100), (20, 100)], close=True, dxfattribs={"layer": "WALL"})
    doc.saveas(path)


def test_a_real_building_nested_inside_a_suspected_plot_boundary_still_gets_its_own_region(tmp_path):
    dxf_path = str(tmp_path / "plot_swallowing_building.dxf")
    _write_plot_swallowing_nested_building_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["region_count"] == 2

    building_region = _region_for_layer(result, "WALL")
    plot_region = _region_for_layer(result, "0")

    assert building_region["boundary"]["area_sqft"] == 4000.0
    assert building_region["boundary"]["note"] is None
    assert building_region["boundary"]["confidence"] == "high"
    assert not any(o["layer"] == "WALL" for o in plot_region["obstacles"]), (
        "the nested building must surface as its own region, not get swallowed "
        "as an obstacle of the plot boundary that contains it"
    )


def test_a_similarly_sized_unnamed_layer_rectangle_is_not_flagged(tmp_path):
    """The area-multiple gate matters: a second candidate that's only
    slightly smaller (not "materially smaller") than the unnamed-layer
    rectangle should not trip the heuristic — a real building can
    legitimately have two similarly-sized wings, one with better layer
    naming than the other, and that's not evidence either one is a plot
    line."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True, dxfattribs={"layer": "0"})
    # ~18,000 sqft — under SUSPECTED_PLOT_BOUNDARY_MIN_AREA_MULTIPLE (2.0x)
    # smaller than the 20,000 sqft candidate above, not materially smaller.
    msp.add_lwpolyline([(300, 0), (390, 0), (390, 200), (300, 200)], close=True, dxfattribs={"layer": "WALL"})
    dxf_path = str(tmp_path / "similar_sized.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    plot_region = _region_for_layer(result, "0")
    assert plot_region["boundary"]["note"] is None
