"""Regression coverage for export_pdf.py's _fit_room_name. It already
shrunk-then-wrapped a long room name to fit a room's on-page width, but the
shrink/wrap loops only stop trying at floor_size — they never guaranteed
the *result* actually fits, so a long custom rename with no good word split
(or no spaces at all) could still return text wider than the room. Found
while bringing export_dxf.py's equivalent (which had no fitting logic at
all) up to standard and auditing export_pdf.py's own version for the same
class of gap."""
from reportlab.pdfgen import canvas
from io import BytesIO

import export_pdf


def _canvas():
    return canvas.Canvas(BytesIO())


def test_fit_room_name_returns_name_unchanged_when_it_already_fits():
    c = _canvas()
    lines, size = export_pdf._fit_room_name(c, "BOH", 100, 20)
    assert lines == ["BOH"]
    assert size == 20


def test_fit_room_name_wraps_a_long_multiword_name_and_it_actually_fits():
    """The real, live case this function exists for: 'FOOD & BEVERAGE /
    CONCESSION' in a narrow room. Every returned line must fit max_w — not
    just be shorter than the original."""
    c = _canvas()
    max_w = 40
    lines, size = export_pdf._fit_room_name(c, "FOOD & BEVERAGE / CONCESSION", max_w, 18)
    assert len(lines) <= 2
    for ln in lines:
        assert c.stringWidth(ln, "Helvetica-Bold", size) <= max_w + 1e-6


def test_fit_room_name_truncates_a_pathological_long_rename_with_no_good_split():
    """An architect's own long custom rename in a small room, with no space
    that produces a fitting 2-line split — must truncate with an ellipsis
    rather than silently returning oversized text (the actual defect: the
    old shrink loop just gave up at floor_size and returned whatever it had,
    even if still too wide)."""
    c = _canvas()
    max_w = 22.08  # a real 24ft-wide room's on-page label budget (24 * 0.92)
    name = "IMAX DOLBY ATMOS PREMIUM GRAND EXPERIENCE THEATRE ONE"
    lines, size = export_pdf._fit_room_name(c, name, max_w, 26)
    assert len(lines) <= 2
    for ln in lines:
        assert c.stringWidth(ln, "Helvetica-Bold", size) <= max_w + 1e-6
    assert any("…" in ln for ln in lines)


def test_fit_room_name_truncates_a_single_word_with_no_spaces():
    """No spaces at all means the wrap-onto-second-line path can't run —
    must still guarantee it fits via truncation, not fall through unfitted."""
    c = _canvas()
    max_w = 22.08
    name = "SUPERCALIFRAGILISTICEXPIALIDOCIOUSSCREEN"
    lines, size = export_pdf._fit_room_name(c, name, max_w, 26)
    assert len(lines) == 1
    assert c.stringWidth(lines[0], "Helvetica-Bold", size) <= max_w + 1e-6
    assert lines[0].endswith("…")


def test_truncate_to_width_never_exceeds_budget_even_for_tiny_max_w():
    c = _canvas()
    result = export_pdf._truncate_to_width(c, "A REASONABLY LONG NAME", "Helvetica-Bold", 10, 5)
    assert c.stringWidth(result, "Helvetica-Bold", 10) <= 5 + 1e-6
