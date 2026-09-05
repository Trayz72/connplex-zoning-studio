"""OR-Tools CP-SAT-based exact/near-exact auditorium placement —
"Optimize Layout": a genuinely different, stronger technique than any
greedy heuristic (even the backtracking-aware one in
placement/backtracking.py). Poses placement as a real combinatorial
optimization — Maximum Weight Independent Set over a real candidate pool —
and lets a proven solver find the best (or best-found-within-a-time-limit)
answer, instead of any hand-tuned heuristic ordering.

Deliberately NOT wired into the fast, always-on auto-layout path
(layout_engine.generate_candidate) — CP-SAT can take real time (bounded by
TIME_LIMIT_SECONDS) on a hard instance, so this is exposed as an explicit,
opt-in "Run Optimizer" action instead (see main.py's
POST .../zoning-runs/optimize).

Candidate generation is real but deliberately bounded, not exhaustive
continuous positioning (which would make the model intractably large for
no real benefit): every auditorium preset, tried at each of a bounded set
of real maximal free rectangles (placement.free_rectangles — already a
much richer position source than a fixed grid step), anchored at 2 of that
rectangle's corners per orientation. That's real, substantial diversity —
many different real free rectangles, not one guess — without the
candidate pool blowing up into the tens of thousands.
"""
import rules_registry
import seat_engine
from placement import free_rectangles, column_enclosure

TIME_LIMIT_SECONDS = 30.0  # a real, observed case: under real server load (not an isolated script run),
# the same 8-worker parallel search found a genuinely worse packing within 20s than it found in
# isolation on identical input — CP-SAT's within-time-limit quality is inherently sensitive to
# available CPU, not just wall-clock time. More headroom trades a few extra seconds of "Optimize
# Layout" wait for a materially more reliable result instead of a load-dependent coin flip.
MAX_FREE_RECTS = 60


def _rects_overlap(a, b):
    """Plain axis-aligned rectangle overlap test — real, cheap arithmetic,
    not a shapely call. Every candidate here is already known to be a
    simple (x, y, w, h) box, so this is both correct and, at the O(n^2)
    pairwise scale the solver's constraint-building needs, dramatically
    cheaper than a geometry-library intersection test per pair."""
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def generate_candidates(usable_poly, fallback_poly, column_polys, bbox, presets,
                         aud_column_cap, screen_width_ft=None, max_free_rects=MAX_FREE_RECTS,
                         max_dim_ft=80.0, aud_edge_tolerance_ft=None):
    """Every (preset, free-rectangle, orientation, corner) combination that
    actually fits, PLUS one custom-fit candidate per free rectangle (its own
    full extent, capped at max_dim_ft) — real parity with the greedy path's
    own fallback (_find_largest_fitting_custom_screen /
    _fill_remaining_auditoriums_with_backtracking in layout_engine.py).
    Without this, a free rectangle whose short side is narrower than every
    preset's minimum (a real case: a narrow leftover strip) contributed
    ZERO candidates here even though greedy could and did seat real people
    there by using the strip as-is — found by direct comparison against
    greedy on a boundary with such strips, where the solver otherwise
    finished with fewer total seats than greedy despite being a strictly
    more powerful search.

    A custom-fit candidate's short side is preferred to clear
    min_short_side_ft (the smallest configured preset's own width_min_ft)
    — a strip narrower than that produces an architecturally unusual
    "screen" (a real, measured case: 70.8x13.8ft) no human would draw by
    choice. But since each free rectangle here is independent and already
    at its own maximal size (not a range to shrink within, the way
    greedy's preset ladder can retry a smaller footprint), a rectangle
    whose short side never clears the floor would otherwise contribute
    ZERO candidates forever — a real, measured case on a real uploaded
    file with a dense, irregular confirmed column layout, where an entire
    wing of a 7,000+ sqft floor plate produced no candidate at all this
    way. So a below-floor rectangle still gets its own full-extent
    candidate (same SOP-adjustment trade layout_engine._place_auditoriums_inner's
    own two-tier backtracking retry makes) — real usable area is never
    silently contributed zero candidates just because it's narrower than
    ideal; every custom-fit room still carries its "review before
    finalizing" note regardless of which path produced it (see
    _build_auditorium_room).

    Returns a list of dicts: {x, y, w, h, preset,
    used_fallback, seat_config, seat_estimate} — preset is None for a
    custom-fit candidate, the same convention _build_auditorium_room
    already understands for greedy's custom-fit rooms."""
    candidates = []
    seen = set()
    min_preset_area_sqft = min((p["min_area_sqft"] for p in presets), default=0)
    # Same relaxation layout_engine._place_auditoriums_inner's greedy custom-
    # fit backtracking uses (see that module's own comment for the full
    # reasoning and the real, measured case it fixes): a custom-fit room
    # already carries its own "review before finalizing" note, so it can
    # tolerate a bit more real structural column presence — and skip the
    # preset-only interior-position gate entirely — without the solver's
    # own candidate pool becoming a worse choice than greedy's.
    custom_fit_column_cap = 0.05

    for poly, used_fallback in ((usable_poly, False), (fallback_poly, True)):
        if poly is None or (used_fallback and poly is usable_poly):
            continue
        rects = free_rectangles.free_rectangles_ft(poly, bbox, cell_ft=1.0, max_candidates=max_free_rects)
        for rx, ry, rw, rh in rects:
            cw, ch = min(rw, max_dim_ft), min(rh, max_dim_ft)
            if cw * ch >= min_preset_area_sqft:
                for ax, ay in ((rx, ry), (rx + rw - cw, ry + rh - ch)):
                    key = (round(ax, 2), round(ay, 2), round(cw, 2), round(ch, 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    enclosed_ratio = column_enclosure.enclosed_ratio(ax, ay, cw, ch, column_polys) if used_fallback else 0.0
                    if used_fallback and not column_enclosure.enclosure_ok(ax, ay, cw, ch, column_polys, custom_fit_column_cap, None):
                        continue
                    enclosed_area = enclosed_ratio * cw * ch
                    seat_config, seat_est = seat_engine.best_seat_estimate(
                        None, cw, ch, enclosed_area, screen_width_ft
                    )
                    if seat_est["seat_count"] > 0:
                        candidates.append({
                            "x": ax, "y": ay, "w": cw, "h": ch,
                            "preset": None, "used_fallback": used_fallback,
                            "seat_config": seat_config, "seat_estimate": seat_est,
                        })
            for preset in presets:
                w_max = preset.get("width_max_ft", preset["width_min_ft"])
                h_max = preset.get("length_max_ft", preset["length_min_ft"])
                footprints = {(w_max, h_max), (preset["width_min_ft"], preset["length_min_ft"])}
                for pw, ph in footprints:
                    for ow, oh in {(pw, ph), (ph, pw)}:
                        if ow > rw + 1e-6 or oh > rh + 1e-6:
                            continue
                        # Anchor at 2 diagonal corners of the free rectangle
                        # — real, bounded diversity per rectangle without
                        # scanning every possible interior position.
                        for ax, ay in ((rx, ry), (rx + rw - ow, ry + rh - oh)):
                            key = (round(ax, 2), round(ay, 2), round(ow, 2), round(oh, 2))
                            if key in seen:
                                continue
                            seen.add(key)
                            enclosed_ratio = column_enclosure.enclosed_ratio(ax, ay, ow, oh, column_polys) if used_fallback else 0.0
                            if used_fallback and not column_enclosure.enclosure_ok(ax, ay, ow, oh, column_polys, aud_column_cap, aud_edge_tolerance_ft):
                                continue
                            enclosed_area = enclosed_ratio * ow * oh
                            seat_config, seat_est = seat_engine.best_seat_estimate(
                                preset, ow, oh, enclosed_area, screen_width_ft
                            )
                            if seat_est["seat_count"] <= 0:
                                continue
                            candidates.append({
                                "x": ax, "y": ay, "w": ow, "h": oh,
                                "preset": preset, "used_fallback": used_fallback,
                                "seat_config": seat_config, "seat_estimate": seat_est,
                            })
    return candidates


def solve(usable_poly, fallback_poly, column_polys, bbox, presets, max_auditoriums,
          aud_column_cap, screen_width_ft=None, time_limit_seconds=TIME_LIMIT_SECONDS,
          aud_edge_tolerance_ft=None):
    """Maximum Weight Independent Set over the real candidate pool
    (generate_candidates): one boolean decision variable per candidate, a
    "not both" constraint for every pair whose rectangles actually
    overlap, objective = maximize total seats. CP-SAT always returns its
    best-found incumbent even if the time limit hits before proving
    optimality — this degrades gracefully to "the best found in
    time_limit_seconds," never hangs.

    Returns (selected_candidates, status_name). selected_candidates is the
    subset of generate_candidates' own dicts CP-SAT chose — the caller
    (layout_engine.generate_optimized_candidate) turns each into a real
    room dict the same way every other placement path in this codebase
    does."""
    from ortools.sat.python import cp_model

    candidates = generate_candidates(usable_poly, fallback_poly, column_polys, bbox, presets,
                                      aud_column_cap, screen_width_ft, aud_edge_tolerance_ft=aud_edge_tolerance_ft)
    if not candidates:
        return [], "NO_CANDIDATES"

    model = cp_model.CpModel()
    x_vars = [model.NewBoolVar(f"c{i}") for i in range(len(candidates))]

    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if _rects_overlap(candidates[i], candidates[j]):
                model.Add(x_vars[i] + x_vars[j] <= 1)

    if max_auditoriums:
        model.Add(sum(x_vars) <= max_auditoriums)

    model.Maximize(sum(
        x_vars[i] * candidates[i]["seat_estimate"]["seat_count"] for i in range(len(candidates))
    ))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], solver.StatusName(status)

    selected = [candidates[i] for i in range(len(candidates)) if solver.Value(x_vars[i])]
    return selected, solver.StatusName(status)
