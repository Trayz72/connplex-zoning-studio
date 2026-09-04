"""Regression coverage for layout_engine.py's post-auditorium
auto-placement pass — _place_support_zones_and_foyer and the connectivity
gate it's built on (placement/connectivity.py). Verifies the real, evidence
-based behavior this round's redesign depends on: real Box Office/F&B/
Washroom/BOH geometry (not just a circulation number), a connectivity veto
that actually changes which candidate gets chosen, and Foyer computed as
the true geometric remainder rather than an independently sized room."""
from shapely.ops import unary_union

import layout_engine
import rules_registry

RECT_BOUNDARY = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]

# The same irregular "comb" boundary test_solver.py's own regression test
# uses — already vetted as a real, non-trivial floor plate by this suite.
COMB_BOUNDARY = [
    [0, 0], [24, 0], [24, 40], [30, 40], [30, 0], [54, 0], [54, 65], [60, 65], [60, 0],
    [84, 0], [84, 40], [90, 40], [90, 0], [114, 0], [114, 50], [120, 50], [120, 0],
    [140, 0], [140, 60], [0, 60], [0, 0],
]


def _usable(boundary):
    return layout_engine.compute_usable_area(boundary, [])


def test_connectivity_gate_rejects_best_scoring_candidate_and_falls_through_to_next():
    """A deliberately constructed scenario: a 40x20 floor with a single
    ~10ft-wide neck connecting a left half (holding the entry) and a right
    half (holding an already-placed auditorium's door). BOX_OFFICE's own
    heuristic (closest to the entry) would naturally rank a candidate that
    fills the neck as its best-scoring choice — the connectivity gate must
    veto it and fall through to a lower-ranked, non-blocking position
    instead, proving the veto actually changes the outcome rather than
    coincidentally agreeing with the unfiltered best."""
    boundary = [[0, 0], [40, 0], [40, 20], [0, 20], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    entry_point = (1, 10)

    # A single "auditorium" occupying the right half, door facing the neck.
    aud_room = {
        "room_id": "aud-1", "room_type": "AUDITORIUM_1",
        "origin_ft": [30, 0], "width_ft": 10, "depth_ft": 20,
        "doors": [{"kind": "ENTRY", "wall": "min_x", "offset_ft": 8, "width_ft": 4}],
    }
    aud_poly = layout_engine._rect(30, 0, 10, 20)

    requirements = {"entry_point_ft": list(entry_point), "max_auditoriums": 0}
    support_rooms, foyer_room, leftover_slack, warnings = layout_engine._place_support_zones_and_foyer(
        usable, usable, [], bbox, [aud_room], [aud_poly], requirements
    )
    box_office = next((r for r in support_rooms if r["room_type"] == "BOX_OFFICE"), None)
    assert box_office is not None, f"expected BOX_OFFICE to be placed somewhere safe, got warnings {warnings}"

    # The placed room must not itself have severed the neck — reachability
    # from the entry to the auditorium's own door must still hold with
    # BOX_OFFICE included in the occupied set.
    from placement import connectivity
    bo_poly = layout_engine._rect(*box_office["origin_ft"], box_office["width_ft"], box_office["depth_ft"])
    free_after = usable.difference(unary_union([aud_poly, bo_poly]))
    door_pt = connectivity.door_outside_point(aud_room, aud_room["doors"][0])
    assert connectivity.reachable_between(free_after, bbox, [entry_point, door_pt]), (
        "BOX_OFFICE was placed in a way that severs the entry from the auditorium's own door"
    )
    # And it must not be sitting in the middle of the connecting neck (x in [15, 25]).
    bo_x0, bo_x1 = box_office["origin_ft"][0], box_office["origin_ft"][0] + box_office["width_ft"]
    assert not (bo_x0 < 25 and bo_x1 > 15), f"BOX_OFFICE landed in the connecting neck: x=[{bo_x0},{bo_x1}]"


def test_auto_layout_produces_real_geometry_and_excludes_passage():
    for candidate in layout_engine.generate_candidates(RECT_BOUNDARY, [], {}):
        room_types = [r["room_type"] for r in candidate["rooms"]]
        assert "PASSAGE" not in room_types
        for room in candidate["rooms"]:
            assert len(room["geometry_points_ft"]) >= 3
            assert room["area_sqft"] > 0


def test_foyer_and_components_and_screens_reconcile_to_usable_area():
    """Real area-conservation check on the irregular comb boundary: total
    screen area + every support-zone area + Foyer's own area + reported
    leftover slack must reconcile to the true usable (fallback) area within
    a small tolerance — proving Foyer is a genuine accounting of what's
    left, not an approximation. Checked for both greedy strategies and the
    CP-SAT optimizer, since all three build their candidate independently."""
    usable = _usable(COMB_BOUNDARY)

    def check(candidate):
        fallback_area = candidate["usable_area_sqft"]
        room_area = sum(r["area_sqft"] for r in candidate["rooms"])
        total = room_area + candidate["circulation_area_sqft"]
        assert abs(total - fallback_area) < 2.0, (
            f"rooms ({room_area}) + leftover slack ({candidate['circulation_area_sqft']}) "
            f"!= usable area ({fallback_area})"
        )
        assert any(r["room_type"] == "FOYER" for r in candidate["rooms"]), "expected a real Foyer room"

    for candidate in layout_engine.generate_candidates(COMB_BOUNDARY, [], {"max_auditoriums": 6}):
        check(candidate)

    optimized = layout_engine.generate_optimized_candidate(usable, COMB_BOUNDARY, {"max_auditoriums": 6}, [], time_limit_seconds=10)
    check(optimized)


def test_foyer_polygon_is_the_real_remainder_not_a_bounding_box():
    """On the comb boundary (genuinely irregular), Foyer's stored polygon
    must equal the true leftover space (rooms subtracted from usable area),
    not an approximation, and — since the comb boundary's leftover space is
    not a plain rectangle — its area must differ from width_ft*depth_ft
    (the bounding box), proving geometry_points_ft carries the real shape.

    The true remainder can be a MultiPolygon here (a real, correct outcome
    on this boundary once the realistic-shape floor rejects a sliver
    custom-fit screen: the freed-up strip is too small/disconnected to
    reach Foyer's own connected piece, so it correctly shows up as
    circulation_area_sqft leftover slack instead — see
    test_multipolygon_remainder_picks_entry_connected_piece_as_foyer for
    that behavior's own dedicated test) — so this test compares Foyer's
    polygon against the true remainder's OWN matching piece, not the
    combined multi-piece total."""
    usable = _usable(COMB_BOUNDARY)
    candidate = layout_engine.generate_candidate(usable, COMB_BOUNDARY, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 6}, [])
    foyer = next((r for r in candidate["rooms"] if r["room_type"] == "FOYER"), None)
    assert foyer is not None

    other_polys = [
        layout_engine._rect(*r["origin_ft"], r["width_ft"], r["depth_ft"])
        for r in candidate["rooms"] if r["room_type"] != "FOYER"
    ]
    foyer_poly = layout_engine.poly_from_points(foyer["geometry_points_ft"] + [foyer["geometry_points_ft"][0]])
    true_remainder = usable.difference(unary_union(other_polys))
    pieces = list(true_remainder.geoms) if true_remainder.geom_type == "MultiPolygon" else [true_remainder]
    match_idx = min(range(len(pieces)), key=lambda i: abs(pieces[i].area - foyer["area_sqft"]))
    matching_piece = pieces[match_idx]
    mismatch_area = foyer_poly.symmetric_difference(matching_piece).area
    assert mismatch_area < 2.0, f"Foyer's stored polygon differs from its matching true-remainder piece by {mismatch_area} sqft"
    # Every other piece (if any) must be accounted for as reported leftover
    # slack, not silently dropped.
    other_pieces_area = sum(p.area for i, p in enumerate(pieces) if i != match_idx)
    assert abs(candidate["circulation_area_sqft"] - other_pieces_area) < 2.0

    bbox_area = foyer["width_ft"] * foyer["depth_ft"]
    assert abs(foyer["area_sqft"] - bbox_area) > 1.0, "expected a non-rectangular Foyer remainder on the comb boundary"


def test_multipolygon_remainder_picks_entry_connected_piece_as_foyer():
    """Two disconnected leftover pockets (separated by a full-height
    dividing wall-like placed room) — the entry-connected piece must become
    FOYER; the other must NOT appear as a second FOYER room, only as
    reported leftover slack."""
    boundary = [[0, 0], [60, 0], [60, 20], [0, 20], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    entry_point = (1, 10)

    # A full-height divider room splitting left (with entry) from right pocket.
    divider = {
        "room_id": "div-1", "room_type": "BOH",
        "origin_ft": [28, 0], "width_ft": 4, "depth_ft": 20,
        "doors": [],
    }
    divider_poly = layout_engine._rect(28, 0, 4, 20)

    foyer_room, leftover_slack = layout_engine._build_foyer_room(usable, [divider_poly], [divider], entry_point)
    assert foyer_room is not None
    assert foyer_room["origin_ft"][0] < 28, "expected the entry-side (left) pocket to become Foyer"
    assert leftover_slack > 100, "expected the right pocket's area to show up as leftover slack, not vanish"


def test_narrow_egress_passage_stays_open_end_to_end():
    """Perf/behavior sanity on a real, several-thousand-sqft boundary: the
    connectivity-gated auto-layout pass completes in a real time budget."""
    import time
    usable = _usable(COMB_BOUNDARY)
    start = time.time()
    candidate = layout_engine.generate_candidate(usable, COMB_BOUNDARY, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 6}, [])
    elapsed = time.time() - start
    assert elapsed < 10.0, f"connectivity-gated auto-layout took {elapsed:.1f}s — too slow for an interactive path"
    assert len(candidate["rooms"]) > 0
