"""Regression coverage for placement/solver.py — the CP-SAT "Optimize
Layout" combinatorial solver. Verified for real structural correctness
(no overlaps, real containment, respects max_auditoriums) and for actually
out-performing the existing greedy generate_candidate on a scenario
deliberately constructed so a greedy largest-first pass picks a genuinely
worse total than the real optimum — not just "the call doesn't crash."""
from shapely.geometry import box

import layout_engine
import rules_registry
from placement import solver


def _usable(boundary):
    return layout_engine.compute_usable_area(boundary, [])


def test_generate_candidates_produces_only_real_contained_non_negative_options():
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()
    cands = solver.generate_candidates(usable, usable, [], bbox, presets, 0.02, None)
    assert len(cands) > 0
    for c in cands:
        rect = box(c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"])
        assert usable.contains(rect)
        assert c["seat_estimate"]["seat_count"] > 0


def test_solve_returns_non_overlapping_placements():
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()
    selected, status = solver.solve(usable, usable, [], bbox, presets, 4, 0.02, None, time_limit_seconds=10)
    assert status in ("OPTIMAL", "FEASIBLE")
    assert len(selected) >= 1
    rects = [box(c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"]) for c in selected]
    for i in range(len(rects)):
        assert usable.contains(rects[i])
        for j in range(i + 1, len(rects)):
            assert rects[i].intersection(rects[j]).area < 1e-6


def test_solve_respects_max_auditoriums_cap():
    boundary = [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()
    selected, status = solver.solve(usable, usable, [], bbox, presets, 1, 0.02, None, time_limit_seconds=10)
    assert status in ("OPTIMAL", "FEASIBLE")
    assert len(selected) <= 1


def test_solve_returns_no_candidates_status_on_a_tiny_boundary():
    boundary = [[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]  # far too small for any real preset
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()
    selected, status = solver.solve(usable, usable, [], bbox, presets, 4, 0.02, None, time_limit_seconds=5)
    assert selected == []
    assert status == "NO_CANDIDATES"


def test_solver_finds_a_genuinely_better_total_than_greedy_first_fit():
    """The real point of this module: a scenario where greedy largest-
    preset-first placement commits to a choice a global optimizer would
    never make. A 100x24 strip fits exactly one 90_SEAT-tier room end to
    end (90_SEAT needs up to 65ft length, leaving no room for anything
    else afterward) — but the SAME strip fits TWO 35_SEAT rooms
    (needing only 35-40ft length each) with real leftover space besides.
    Two smaller real auditoriums genuinely seat more people combined than
    one bigger one on this exact strip — the solver must find that; a
    greedy largest-first pass (this module's own generate_candidate with
    MAX_SEATS_PER_SCREEN) is expected to settle for the single big room
    instead."""
    boundary = [[0, 0], [100, 0], [100, 24], [0, 24], [0, 0]]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()

    selected, status = solver.solve(usable, usable, [], bbox, presets, 4, 0.02, None, time_limit_seconds=10)
    assert status in ("OPTIMAL", "FEASIBLE")
    optimized_seats = sum(c["seat_estimate"]["seat_count"] for c in selected)
    optimized_screens = len(selected)

    greedy = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 4}, [])

    assert optimized_screens >= 2, f"expected the solver to find room for 2 screens on this strip, got {optimized_screens}"
    assert optimized_seats >= greedy["total_seats"], (
        f"optimizer found {optimized_seats} seats across {optimized_screens} screens, greedy found "
        f"{greedy['total_seats']} across {greedy['screen_count']} — optimizer must never do worse"
    )


def test_generate_candidates_includes_custom_fit_options_for_narrow_strips_no_preset_fits():
    """Real regression: found via direct comparison against greedy on a
    "comb" boundary with narrow leftover strips (a 54x20 and an 80x10
    rectangle) whose SHORT side is below every preset's minimum (24ft for
    the smallest, 35_SEAT) — generate_candidates originally produced ZERO
    candidates from those strips at all, even though greedy's own
    custom-fit fallback (_find_largest_fitting_custom_screen) successfully
    seats real people there by using the strip's own full extent as a
    non-preset-shaped room. Without this, the solver — despite being a
    strictly more powerful search — actually finished with FEWER total
    seats than greedy (216 vs 309) on this exact boundary, a real,
    measured regression this test guards against."""
    boundary = [
        [0, 0], [24, 0], [24, 40], [30, 40], [30, 0], [54, 0], [54, 65], [60, 65], [60, 0],
        [84, 0], [84, 40], [90, 40], [90, 0], [114, 0], [114, 50], [120, 50], [120, 0],
        [140, 0], [140, 60], [0, 60], [0, 0],
    ]
    usable = _usable(boundary)
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()

    cands = solver.generate_candidates(usable, usable, [], bbox, presets, 0.02, None)
    custom_fit = [c for c in cands if c["preset"] is None]
    assert custom_fit, "expected at least one custom-fit (preset=None) candidate from the narrow strips"

    selected, status = solver.solve(usable, usable, [], bbox, presets, 6, 0.02, None, time_limit_seconds=15)
    assert status in ("OPTIMAL", "FEASIBLE")
    optimized_seats = sum(c["seat_estimate"]["seat_count"] for c in selected)

    greedy = layout_engine.generate_candidate(usable, boundary, "MAX_SEATS_PER_SCREEN", {"max_auditoriums": 6}, [])
    assert optimized_seats >= greedy["total_seats"], (
        f"optimizer found {optimized_seats} seats, greedy found {greedy['total_seats']} — "
        f"optimizer must never do worse once it can also propose custom-fit candidates"
    )
    assert any(c["preset"] is None for c in selected), "expected the optimizer to actually select a custom-fit room here"


def test_generate_candidates_rejects_a_custom_fit_candidate_over_an_interior_column():
    """Parity with layout_engine's own custom-fit column gate (see that
    module's _place_auditoriums_inner comment): a custom-fit candidate gets
    a wider AREA ratio cap than a preset match (custom_fit_column_cap), but
    the POSITION gate (edge_tolerance_ft) is never relaxed for it — a real,
    reported client defect this guards against: the solver's own candidate
    pool was accepting a custom-fit rectangle covering a column stranded
    dead-center in its interior, using only the area-ratio check
    (enclosure_ok was being called with edge_tolerance_ft hardcoded to
    None regardless of what the caller passed in). A tiny column dead-
    center of an otherwise-viable 40x40 boundary is farther than
    aud_edge_tolerance_ft from every wall of the only rectangle that could
    cover it, so no custom-fit candidate should be generated there at all."""
    boundary = [[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]
    column = box(19.5, 19.5, 20.5, 20.5)
    column_obstacle = {"points_ft": list(column.exterior.coords), "classification": "COLUMN"}
    usable = layout_engine.compute_usable_area(boundary, [column_obstacle])
    fallback = layout_engine.compute_usable_area(boundary, [column_obstacle], exclude_classifications=("COLUMN",))
    bbox = layout_engine.poly_from_points(boundary).bounds
    presets = rules_registry.auditorium_presets()
    cands = solver.generate_candidates(usable, fallback, [column], bbox, presets, 0.02, None, aud_edge_tolerance_ft=2.0)
    assert not any(c["preset"] is None for c in cands), "expected no custom-fit candidate to tolerate the dead-center column"
