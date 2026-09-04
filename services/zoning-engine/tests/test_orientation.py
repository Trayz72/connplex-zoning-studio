"""Regression coverage for the CAD-upload orientation fix (see
cad_extraction.py's _identity_tf docstring): DXF is natively Y-up, this
app's SVG-based web viewer is Y-down, and every extracted coordinate must be
flipped exactly once to render right-side-up. A prior version of this module
did no flip at all, and every uploaded drawing rendered vertically mirrored,
deterministically, on every file — these tests exist so that regression
can't silently come back."""
import os
import tempfile

import ezdxf

import cad_extraction
import export_dxf


def _write_notch_dxf(path):
    """An unambiguous orientation marker: a 100x50 rectangle with a small
    square notch cut from its real top-left corner only (x in [0,10], y in
    [40,50] in DXF's own native Y-up coordinates) — asymmetric on both axes,
    so a flip, a mirror, or a rotation would each move the notch to a
    different, distinguishable corner."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    pts = [(0, 0), (100, 0), (100, 50), (10, 50), (10, 40), (0, 40), (0, 0)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "0"})
    doc.saveas(path)


def test_identity_tf_flips_y_not_x():
    x, y = cad_extraction._identity_tf((3.0, 7.0))
    assert x == 3.0
    assert y == -7.0


def test_extraction_notch_lands_in_correct_screen_corner(tmp_path):
    """Direct reproduction of this fix's own manual verification (see
    LOG.md): a rectangle with a notch cut from its real top-left corner
    only. $INSUNITS is explicitly feet here, so no unit-conversion scaling
    applies — the extracted points_ft must be exactly the DXF-native points
    with Y negated, landing the notch in points_ft's own min-x/min-y
    quadrant (screen top-left, the Y-down convention this app renders
    with)."""
    dxf_path = str(tmp_path / "notch_test.dxf")
    _write_notch_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path)
    assert result["region_count"] >= 1
    boundary_pts = {(round(p[0], 3), round(p[1], 3)) for p in result["regions"][0]["boundary"]["points_ft"]}

    expected = {(0.0, 0.0), (100.0, 0.0), (100.0, -50.0), (10.0, -50.0), (10.0, -40.0), (0.0, -40.0)}
    assert boundary_pts == expected


def test_export_dxf_roundtrips_back_to_original_orientation(tmp_path):
    """The only two consumers of points_ft that write into an inherently
    Y-up target (DXF; reportlab's PDF canvas) must compensate the flip on
    the way out — verified end-to-end here for the DXF path: extract a
    known file, export it straight back out, and confirm the exported DXF's
    points match the ORIGINAL file's real DXF-native coordinates exactly."""
    dxf_path = str(tmp_path / "notch_test.dxf")
    _write_notch_dxf(dxf_path)
    original_points = {(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (10.0, 50.0), (10.0, 40.0), (0.0, 40.0)}

    extracted = cad_extraction.extract(dxf_path)
    boundary_pts = extracted["regions"][0]["boundary"]["points_ft"]

    out_path = str(tmp_path / "roundtrip.dxf")
    export_dxf.export_layout_to_dxf({"property_name": "test"}, boundary_pts, [], [], out_path, also_dwg=False)

    doc = ezdxf.readfile(out_path)
    msp = doc.modelspace()
    boundary_entity = next(e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "EXISTING-BOUNDARY")
    exported_points = {(round(p[0], 3), round(p[1], 3)) for p in boundary_entity.get_points("xy")}

    assert exported_points == original_points
