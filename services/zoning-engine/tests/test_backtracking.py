"""Regression coverage for placement/backtracking.py's generic bounded
backtracking search — verified against a small, hand-constructed puzzle
where a plain greedy-first-choice forward search provably gets stuck and
only backtracking finds the real, existing full solution. This is the
same shape of failure the real auto-layout hits (an early choice that's
individually valid but forecloses a later slot)."""
from placement.backtracking import search_with_backtracking


def test_backtracking_finds_a_solution_a_greedy_first_choice_would_miss():
    """3 slots, values drawn from {1, 2, 3}, each slot's real (must not
    repeat) value. Deliberately rigged so slot 0's PREFERRED (first-listed)
    candidate (1) leads to a dead end at slot 2, but its second choice (2)
    leads to a real, complete solution (2, 1, 3). A greedy-only search
    (no backtracking) commits to 1 and never recovers."""
    def candidates_for_slot(depth, committed):
        if depth == 0:
            return [1, 2]  # 1 preferred first, but is the wrong choice
        if depth == 1:
            return [v for v in (1, 2) if v not in committed]
        if depth == 2:
            # Only reachable with a real solution when slot 0 chose 2 (so
            # slot 1 is forced to 1, leaving 3 available here). If slot 0
            # chose 1, slot 1 is forced to 2, and nothing is left here.
            remaining = [v for v in (1, 2, 3) if v not in committed]
            return remaining if committed == [2, 1] else []
        return []

    def try_candidate(candidate):
        return candidate  # every offered candidate is real; the puzzle is in which ones exist at all

    result = search_with_backtracking(3, candidates_for_slot, try_candidate, max_backtrack=2)
    assert result == [2, 1, 3]


def test_zero_backtrack_budget_gets_stuck_on_the_same_puzzle():
    """Same puzzle, but with backtracking disabled (max_backtrack=0) — a
    plain greedy forward search commits to slot 0 = 1, fails at slot 2, and
    has no budget to reconsider slot 0. Confirms the test above is real
    evidence backtracking did the work, not a puzzle that happens to
    resolve on its own."""
    def candidates_for_slot(depth, committed):
        if depth == 0:
            return [1, 2]
        if depth == 1:
            return [v for v in (1, 2) if v not in committed]
        if depth == 2:
            remaining = [v for v in (1, 2, 3) if v not in committed]
            return remaining if committed == [2, 1] else []
        return []

    def try_candidate(candidate):
        return candidate

    result = search_with_backtracking(3, candidates_for_slot, try_candidate, max_backtrack=0)
    assert result == [1, 2]  # stuck after 2 slots, never reaches the real 3-slot solution


def test_try_candidate_rejection_is_treated_like_no_candidate_and_moves_on():
    """try_candidate returning None (a candidate that looked fine but
    didn't actually pan out) must be handled like "not a real option" —
    the search moves to the next candidate in the list, not crash or stop."""
    def candidates_for_slot(depth, committed):
        return [10, 20, 30] if depth == 0 else []

    def try_candidate(candidate):
        return None if candidate == 10 else candidate

    result = search_with_backtracking(1, candidates_for_slot, try_candidate)
    assert result == [20]


def test_returns_partial_result_when_genuinely_nothing_more_fits():
    """Never fabricates a slot that doesn't fit — if a slot's candidate
    list is empty and there's nothing to backtrack to, the search returns
    whatever it filled so far, not an error or a padded/fake result."""
    def candidates_for_slot(depth, committed):
        return [1] if depth == 0 else []

    def try_candidate(candidate):
        return candidate

    result = search_with_backtracking(5, candidates_for_slot, try_candidate)
    assert result == [1]


def test_attempt_budget_bounds_total_work():
    """A pathological candidate list that never succeeds must not spin
    forever — the total-attempt budget caps real work done."""
    calls = {"n": 0}

    def candidates_for_slot(depth, committed):
        return list(range(1000))  # huge, all doomed to fail

    def try_candidate(candidate):
        calls["n"] += 1
        return None

    result = search_with_backtracking(1, candidates_for_slot, try_candidate, max_total_attempts=25)
    assert result == []
    assert calls["n"] <= 25
