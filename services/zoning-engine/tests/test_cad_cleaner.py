"""End-to-end coverage for the Clean CAD stage (cad_cleaner.py): given a
messy synthetic file with a boundary, a column, a duct/shaft, an internal
partition wall, furniture, and geometry entirely outside the boundary, the
cleaner must (1) find a room by its printed label, (2) build a region from a
directly-selected closed shape, (3) keep only COLUMN/DUCT obstacles plus the
outline when partitioning, and (4) export a DXF containing exactly that —
nothing from the dropped classifications or the outside-boundary geometry."""
import ezdxf

import cad_cleaner
import cad_extraction


def _build_messy_dxf(path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()

    # The room boundary a user would select — 40x30ft, on a plain layer with
    # no boundary-hint naming, since selection here is by direct click/label,
    # not by cad_extraction's own automatic boundary-ranking heuristic.
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 30), (0, 30)], close=True, dxfattribs={"layer": "0"})
    msp.add_text("Screen 1", dxfattribs={"layer": "0", "height": 1.0}).set_placement((20, 15))

    # Kept: a structural column and a duct/shaft, both small and inside the boundary.
    msp.add_lwpolyline([(5, 5), (7, 5), (7, 7), (5, 7)], close=True, dxfattribs={"layer": "COLUMN"})
    msp.add_lwpolyline([(30, 20), (33, 20), (33, 23), (30, 23)], close=True, dxfattribs={"layer": "SHAFT"})

    # Dropped: an internal partition wall and a piece of furniture, both inside the boundary.
    msp.add_lwpolyline([(15, 10), (25, 10), (25, 11), (15, 11)], close=True, dxfattribs={"layer": "A-WALL-PRTN"})
    msp.add_lwpolyline([(10, 20), (13, 20), (13, 22), (10, 22)], close=True, dxfattribs={"layer": "FURN-CHAIR"})

    # Entirely outside the selected boundary — must never appear in the clean output.
    msp.add_lwpolyline([(100, 100), (110, 100), (110, 108), (100, 108)], close=True, dxfattribs={"layer": "COLUMN"})

    doc.saveas(path)


def _boundary_handle(full_raw_geometry):
    shapes = full_raw_geometry["closed_shapes"]
    return max(shapes, key=lambda s: s["area_sqft"])["handle"]


def test_search_labels_finds_the_room_and_its_enclosing_shape(tmp_path):
    dxf_path = str(tmp_path / "messy.dxf")
    _build_messy_dxf(dxf_path)
    geometry = cad_extraction.extract(dxf_path)

    matches = cad_cleaner.search_labels(geometry["full_raw_geometry"], "screen")
    assert len(matches) == 1
    assert matches[0]["text"] == "Screen 1"
    assert matches[0]["shape_handle"] == _boundary_handle(geometry["full_raw_geometry"])


def test_partition_kept_keeps_only_column_and_duct(tmp_path):
    dxf_path = str(tmp_path / "messy.dxf")
    _build_messy_dxf(dxf_path)
    geometry = cad_extraction.extract(dxf_path)
    full_raw = geometry["full_raw_geometry"]
    handle = _boundary_handle(full_raw)

    regions = cad_cleaner.build_clean_regions(full_raw, [handle])
    assert len(regions) == 1
    split = cad_cleaner.partition_kept(regions[0])

    kept_classes = sorted(o["classification"] for o in split["kept"])
    dropped_classes = sorted(o["classification"] for o in split["dropped"])
    assert kept_classes == ["COLUMN", "DUCT"]
    assert dropped_classes == ["FURNITURE", "WALL"]


def test_export_clean_cad_writes_only_kept_geometry(tmp_path):
    dxf_path = str(tmp_path / "messy.dxf")
    _build_messy_dxf(dxf_path)
    geometry = cad_extraction.extract(dxf_path)
    full_raw = geometry["full_raw_geometry"]
    handle = _boundary_handle(full_raw)

    regions = cad_cleaner.build_clean_regions(full_raw, [handle])
    out_path = str(tmp_path / "clean.dxf")
    result = cad_cleaner.export_clean_cad(regions, out_path, also_dwg=False)
    assert result["dxf_path"] == out_path

    clean_doc = ezdxf.readfile(out_path)
    clean_msp = clean_doc.modelspace()
    layers_used = sorted({e.dxf.layer for e in clean_msp})
    assert layers_used == ["COLUMN", "DUCT", "OUTLINE"]
    assert len(list(clean_msp)) == 3  # exactly one entity per kept layer — wall/furniture/outside-boundary geometry all absent


def test_build_clean_regions_supports_multiple_disconnected_shapes(tmp_path):
    dxf_path = str(tmp_path / "messy.dxf")
    _build_messy_dxf(dxf_path)
    geometry = cad_extraction.extract(dxf_path)
    full_raw = geometry["full_raw_geometry"]

    room_handle = _boundary_handle(full_raw)
    outside_handle = next(
        s["handle"] for s in full_raw["closed_shapes"]
        if s["handle"] != room_handle and s["layer"] == "COLUMN" and s["area_sqft"] > 50
    )

    regions = cad_cleaner.build_clean_regions(full_raw, [room_handle, outside_handle])
    assert len(regions) == 2
    assert {r["boundary"]["source_handle"] for r in regions} == {room_handle, outside_handle}


def test_search_labels_stays_fast_on_a_large_number_of_shapes():
    """Real-file regression: search_labels used to rebuild a Shapely polygon
    from scratch for every closed shape, for every matching text (no cache,
    no spatial index) — measured at 45.7s for just 52 real matches against a
    real 21,894-closed-shape file (Keshav Landmark). Fixed with the same
    STRtree query-then-verify pattern used throughout cad_extraction.py.
    This synthetic file is smaller than that real one but still large enough
    that the old O(matches x shapes) behavior would be clearly, unmissably
    slow — a wide time budget (5s) so this stays robust across machines
    while still catching a regression back to the naive approach."""
    import time

    closed_shapes = []
    texts = []
    for i in range(3000):
        x, y = (i % 100) * 10.0, (i // 100) * 10.0
        closed_shapes.append({
            "handle": f"shape-{i}", "layer": "0", "dxftype": "LWPOLYLINE", "source": "explicit",
            "area_sqft": 4.0, "points_ft": [[x, y], [x + 2, y], [x + 2, y + 2], [x, y + 2]],
        })
        if i % 20 == 0:
            texts.append({"text": f"Toilet {i}", "position_ft": [x + 1, y + 1]})

    full_raw = {"closed_shapes": closed_shapes, "texts": texts}

    t0 = time.time()
    matches = cad_cleaner.search_labels(full_raw, "toilet")
    elapsed = time.time() - t0

    assert len(matches) == len(texts)
    assert all(m["shape_handle"] is not None for m in matches)
    assert elapsed < 5.0, f"search_labels took {elapsed:.1f}s — regressed back to O(matches x shapes)?"


def test_a_small_cleaned_room_is_auto_detected_on_re_extraction(tmp_path):
    """Real-world edge case: cad_extraction's default 150 sqft boundary-area
    floor exists to reject furniture-scale junk in an arbitrary raw upload —
    but a Clean CAD output's OUTLINE layer was already deliberately chosen
    by the user, not a heuristic guess, so that risk doesn't apply. Without
    MIN_CLEAN_BOUNDARY_AREA_SQFT, re-extracting the clean file for a real
    small room (this exact case: a 51.5 sqft toilet) produced region_count
    == 0 — 'no candidate boundary was found automatically' — even though the
    outline was right there. Confirms both halves: the default threshold
    really would miss it, and main.py's override threshold finds it."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (8, 0), (8, 5), (0, 5)], close=True, dxfattribs={"layer": "0"})  # 40 sqft
    msp.add_lwpolyline([(1, 1), (2, 1), (2, 2), (1, 2)], close=True, dxfattribs={"layer": "COLUMN"})
    dxf_path = str(tmp_path / "small_room.dxf")
    doc.saveas(dxf_path)

    raw_geometry = cad_extraction.extract(dxf_path)["full_raw_geometry"]
    boundary_handle = next(s["handle"] for s in raw_geometry["closed_shapes"] if s["area_sqft"] == 40.0)
    regions = cad_cleaner.build_clean_regions(raw_geometry, [boundary_handle])

    clean_path = str(tmp_path / "clean_small_room.dxf")
    cad_cleaner.export_clean_cad(regions, clean_path, also_dwg=False)

    assert cad_extraction.extract(clean_path)["region_count"] == 0, (
        "sanity check: the default threshold really does miss a real but small room"
    )
    reextracted = cad_extraction.extract(clean_path, min_boundary_area_sqft=cad_cleaner.MIN_CLEAN_BOUNDARY_AREA_SQFT)
    assert reextracted["region_count"] == 1
    assert reextracted["regions"][0]["boundary"]["area_sqft"] == 40.0
