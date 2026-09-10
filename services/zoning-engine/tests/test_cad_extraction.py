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


def test_a_layer_of_thousands_of_near_zero_area_shapes_is_excluded_as_noise(tmp_path):
    """Real-file regression: a theater plan traced from an imported PDF
    underlay (AutoCAD's PDFIMPORT workflow) put 1,863 closed shapes on one
    layer ("PDF_Geometry"), every one of them under 0.0006 sqft — not real
    architecture, just rasterization/tracing artifacts. Before this fix they
    still consumed the entire full_raw_geometry line budget (crowding out
    the file's real, much sparser wall layer) and inflated
    total_closed_shapes_found by three orders of magnitude, even though none
    of them was ever large enough to become a boundary or obstacle. A real
    building's own real boundary must still be found normally alongside all
    that noise."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    # The real boundary — plausible floor-plate size, wall-hinted layer.
    msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], close=True, dxfattribs={"layer": "WALL"})
    # 600 near-zero-area fragments on one layer, spread out (not stacked —
    # dedup would otherwise collapse near-identical positions) — the
    # traced-PDF signature.
    for i in range(600):
        x = 100 + (i % 30) * 0.5
        y = (i // 30) * 0.5
        msp.add_lwpolyline(
            [(x, y), (x + 0.001, y), (x + 0.001, y + 0.001), (x, y + 0.001)],
            close=True, dxfattribs={"layer": "PDF_Geometry"},
        )
    dxf_path = str(tmp_path / "pdf_traced.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)

    assert result["region_count"] == 1
    assert result["regions"][0]["boundary"]["area_sqft"] == 2400.0
    assert result["total_closed_shapes_found"] == 1  # only the real boundary — noise layer excluded entirely
    assert "PDF_Geometry" in (result["conversion_note"] or "")
    assert all(ln["layer"] != "PDF_Geometry" for ln in result["full_raw_geometry"]["lines"])


def test_a_real_furniture_layer_with_many_small_but_real_shapes_is_not_flagged_as_noise(tmp_path):
    """The two-signal gate matters: a real layer can legitimately have
    hundreds of small shapes (a real "CHAIRS" layer on a real client file
    had 16,135 of them) — that alone must not trip the noise heuristic, only
    "many AND all negligibly tiny" should. Each chair here is a real ~2 sqft
    footprint, comfortably above NOISE_LAYER_MAX_AVG_AREA_SQFT."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], close=True, dxfattribs={"layer": "WALL"})
    for i in range(600):
        x, y = 5 + (i % 20) * 2.0, 5 + (i // 20) * 2.0
        msp.add_lwpolyline([(x, y), (x + 1.5, y), (x + 1.5, y + 1.5), (x, y + 1.5)], close=True, dxfattribs={"layer": "CHAIRS"})
    dxf_path = str(tmp_path / "real_chairs.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)

    assert "CHAIRS" not in (result["conversion_note"] or "")


def test_repeated_block_instances_each_get_a_unique_handle(tmp_path):
    """Real-file regression: a real column/kiosk block referenced by many
    INSERTs (a real client file, "Magnate Plaza Khekra Commercial", had two
    block handles each reused across 1,124 separate closed-shape instances)
    all resolved to the *same* "handle" value — cad_extraction.py walks a
    block's own real entities with a composed transform per INSERT (see
    _resolve_entities) rather than exploding virtual copies, so every
    instance is the same real ezdxf object with the same real dxf.handle.
    _shape_by_handle-style lookups (cad_cleaner.build_clean_regions,
    build_manual_region's existing_source_handle, BoundaryStudio's
    click-a-shape) pick the first match for a handle — with a shared
    handle, clicking instance #9 of 10 would have silently resolved to
    instance #0's geometry instead. Fixed by disambiguating repeat
    occurrences of the same real handle in _resolve_entities itself."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)], close=True, dxfattribs={"layer": "WALL"})

    block = doc.blocks.new(name="COLUMN_BLOCK")
    block.add_lwpolyline([(0, 0), (2, 0), (2, 2), (0, 2)], close=True, dxfattribs={"layer": "COLUMN"})

    positions = [(10, 10), (30, 10), (50, 10), (70, 10), (10, 40), (30, 40), (50, 40), (70, 40)]
    for x, y in positions:
        msp.add_blockref("COLUMN_BLOCK", insert=(x, y))

    dxf_path = str(tmp_path / "repeated_block.dxf")
    doc.saveas(dxf_path)

    result = cad_extraction.extract(dxf_path)
    column_shapes = [s for s in result["full_raw_geometry"]["closed_shapes"] if s["layer"] == "COLUMN"]
    assert len(column_shapes) == len(positions)

    handles = [s["handle"] for s in column_shapes]
    assert len(set(handles)) == len(positions), f"expected {len(positions)} unique handles, got {handles}"

    # Each handle must resolve back to the one real shape actually at that
    # position — not silently the first column instance regardless of which
    # was clicked (the exact failure mode this bug caused in
    # cad_cleaner.build_clean_regions / BoundaryStudio's click-a-shape).
    import cad_cleaner

    def _insert_position(shape):
        # points_ft's Y is negated relative to the raw DXF coordinates the
        # block was inserted at (see _identity_tf) — undo that here so this
        # matches the (x, y) each blockref was actually placed at above.
        xs = [p[0] for p in shape["points_ft"]]
        ys = [p[1] for p in shape["points_ft"]]
        return (min(xs), -max(ys))

    for x, y in positions:
        handle_here = next(s["handle"] for s in column_shapes if _insert_position(s) == (x, y))
        found = cad_cleaner._shape_by_handle(result["full_raw_geometry"], handle_here)
        assert _insert_position(found) == (x, y)


def _build_multi_candidate_dxf(path):
    """Three real, independent boundary-shaped rectangles on a wall-hinted
    layer, sized 2,000 / 7,042 / 20,000 sqft — big enough apart that only one
    can ever be within FORM_MATCH_AREA_TOLERANCE_FRACTION of any single
    target area used below."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 50), (0, 50)], close=True, dxfattribs={"layer": "WALL"})  # 2,000 sqft
    msp.add_lwpolyline([(100, 0), (200, 0), (200, 70.42), (100, 70.42)], close=True, dxfattribs={"layer": "WALL"})  # 7,042 sqft
    msp.add_text("Shop 7", dxfattribs={"layer": "0", "height": 1.0}).set_placement((150, 35))
    msp.add_lwpolyline([(300, 0), (400, 0), (400, 200), (300, 200)], close=True, dxfattribs={"layer": "WALL"})  # 20,000 sqft
    doc.saveas(path)


def test_form_match_ranks_the_carpet_area_candidate_first(tmp_path):
    """The actual "form drives boundary detection" behavior: a salesperson's
    intake carpet-area figure (7,000 sqft) should surface the one real
    candidate that's actually close to it (7,042 sqft, ~0.6% off) ahead of
    a much bigger 20,000 sqft candidate that would otherwise win on size
    alone. Confirms the app finally does what the original spec always
    called for — a form the app uses to look up the right boundary — instead
    of the plain size-first heuristic that shipped without it."""
    dxf_path = str(tmp_path / "multi_candidate.dxf")
    _build_multi_candidate_dxf(dxf_path)

    default_result = cad_extraction.extract(dxf_path)
    assert default_result["regions"][0]["boundary"]["area_sqft"] == 20000.0, (
        "sanity check: without a target area, plain size-first ordering wins as before"
    )
    assert all(r["boundary"]["form_match"] is False for r in default_result["regions"])

    matched_result = cad_extraction.extract(dxf_path, target_area_sqft=7000.0)
    top = matched_result["regions"][0]["boundary"]
    assert top["area_sqft"] == 7042.0
    assert top["form_match"] is True
    assert "7,000 sqft" in top["form_match_note"]
    assert "0.6%" in top["form_match_note"]
    # The other two candidates are still returned, just not first — nothing
    # is filtered out, only re-ranked.
    assert len(matched_result["regions"]) == 3
    assert all(r["boundary"]["form_match"] is False for r in matched_result["regions"] if r is not matched_result["regions"][0])


def test_form_match_does_nothing_when_no_candidate_is_close_enough(tmp_path):
    """A target area with no real match (say, a typo'd carpet area) must
    never force a bad match — ordering falls back to the same plain
    size-first heuristic as if no target had been given at all."""
    dxf_path = str(tmp_path / "multi_candidate.dxf")
    _build_multi_candidate_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path, target_area_sqft=500000.0)
    assert result["regions"][0]["boundary"]["area_sqft"] == 20000.0
    assert all(r["boundary"]["form_match"] is False for r in result["regions"])
    assert all(r["boundary"]["form_match_note"] is None for r in result["regions"])


def test_form_match_note_mentions_a_matching_printed_label(tmp_path):
    """label_hint (the intake form's free-text Floor/Shop No field) is only
    ever an upgrade to the note, never a requirement — this confirms the
    upgrade actually fires when a real printed label inside the matched
    region overlaps a significant word from the hint."""
    dxf_path = str(tmp_path / "multi_candidate.dxf")
    _build_multi_candidate_dxf(dxf_path)

    result = cad_extraction.extract(dxf_path, target_area_sqft=7000.0, label_hint="2nd Floor, Shop 7")
    top = result["regions"][0]["boundary"]
    assert top["area_sqft"] == 7042.0
    assert "matching label" in top["form_match_note"]
