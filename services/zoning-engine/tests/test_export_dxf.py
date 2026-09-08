"""Regression coverage for export_dxf.py's room-label fitting. Found while
auditing the export stage for polish: DXF room labels had no fitting logic
at all before this — a fixed 1.5ft text height and a fixed -5 unit offset
regardless of room size, so a long display_name (an architect's own rename,
e.g. "IMAX Dolby Atmos Premium Experience") on a small screen would overflow
straight into a neighboring room with nothing to stop it. export_pdf.py
already had this problem and a fix for it (_fit_room_name); this brings DXF
up to the same standard, plus a final ellipsis-truncation backstop PDF
doesn't need (DXF text has no wrapping story — a single TEXT entity, no
per-line layout)."""
import os
import tempfile

import ezdxf

import export_dxf


def test_fit_room_label_dxf_returns_name_unchanged_when_it_already_fits():
    name, height = export_dxf._fit_room_label_dxf("BOH", "BOH", max_w_ft=20, start_height=2.0)
    assert name == "BOH"
    assert height == 2.0


def test_fit_room_label_dxf_falls_back_to_short_label_for_known_room_types():
    """The real defect this guards: 'Back-of-House (Electrical / Server / "
    "Store)' at a shrunk floor-size single line still doesn't fit a small
    BOH room's real width — must fall back to the short label, not
    overflow."""
    name, height = export_dxf._fit_room_label_dxf(
        "Back-of-House (Electrical / Server / Store)", "BOH", max_w_ft=8, start_height=1.5
    )
    assert name == "BOH"


def test_fit_room_label_dxf_truncates_with_ellipsis_as_a_last_resort():
    """No short-label entry exists for AUDITORIUM — an architect's own long
    rename must never silently overflow; truncate with an ellipsis instead."""
    long_name = "IMAX Dolby Atmos Premium Grand Experience Theatre One"
    name, height = export_dxf._fit_room_label_dxf(long_name, "AUDITORIUM_1", max_w_ft=15, start_height=2.0)
    assert name != long_name
    assert name.endswith("…")
    assert len(name) < len(long_name)
    # The fitted result must actually respect the width budget at the
    # returned height — not just be shorter than the original.
    assert len(name) * height * export_dxf._TEXT_CHAR_WIDTH_RATIO <= 15 + 1e-6


def test_fit_room_label_dxf_never_returns_empty_string():
    """Even a pathological max_w_ft doesn't collapse a label to nothing —
    always leaves at least a few characters plus the ellipsis."""
    name, height = export_dxf._fit_room_label_dxf("Screen 1 (Auditorium)", "AUDITORIUM_1", max_w_ft=1, start_height=2.0)
    assert len(name) >= 3


def test_export_layout_to_dxf_keeps_long_custom_names_within_room_width():
    """Integration check: a genuinely long, architect-renamed auditorium
    name on a small (24ft-wide) screen must produce DXF text that — even
    accounting for the width heuristic's approximation — never claims a
    footprint wildly larger than the room itself. Regression target for the
    fixed 1.5ft-height/-5-unit-offset behavior this replaces, which had no
    such guarantee at all."""
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    rooms = [{
        "room_id": "r1", "room_type": "AUDITORIUM_1",
        "display_name": "IMAX Dolby Atmos Premium Grand Experience Theatre One",
        "area_sqft": 960, "geometry_points_ft": [[0, 0], [24, 0], [24, 40], [0, 40]],
        "width_ft": 24, "depth_ft": 40, "origin_ft": [0, 0],
        "label_point_ft": [12, 20], "doors": [], "seat_estimate": {"seat_count": 35},
    }]
    with tempfile.TemporaryDirectory() as d:
        out_path = os.path.join(d, "test.dxf")
        export_dxf.export_layout_to_dxf(
            {"property_name": "Test", "project_code": "1", "city": "X", "state": "Y"},
            boundary, [], rooms, out_path, also_dwg=False,
        )
        doc = ezdxf.readfile(out_path)
        msp = doc.modelspace()
        room_label = next(e for e in msp.query("TEXT") if e.dxf.text.startswith("IMAX"))
        estimated_width = len(room_label.dxf.text) * room_label.dxf.height * export_dxf._TEXT_CHAR_WIDTH_RATIO
        assert estimated_width <= 24 * 0.92 + 1e-6, (
            f"label {room_label.dxf.text!r} at height {room_label.dxf.height} estimates to "
            f"{estimated_width:.1f}ft wide — wider than the 24ft room it's labeling"
        )
