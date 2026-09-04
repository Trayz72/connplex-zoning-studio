"""Bounded backtracking retry for greedy placement loops.

A real, standard constraint-satisfaction technique (chronological
backtracking with a bounded depth and a bounded total-attempt budget) —
not a full branch-and-bound solve (see placement/solver.py for that, an
opt-in, slower, exact/near-exact alternative). This module exists for the
DEFAULT, always-on auto-layout path, which needs to stay fast: a plain
greedy forward search can commit to a choice for slot N that's
individually valid but leaves too little usable room for slot N+1, even
though a different valid choice for slot N would have left more — this
lets the search notice that and try an alternative, instead of giving up
the instant the greedy forward pass gets stuck.
"""


def search_with_backtracking(num_slots, candidates_for_slot, try_candidate,
                              max_backtrack=2, max_total_attempts=60):
    """Depth-first slot-filling with bounded backtracking.

    candidates_for_slot(depth, committed) -> an ordered list of opaque
    candidates for the depth'th slot (best first), computed FRESH against
    whatever's actually been committed so far — so a later slot's
    candidates correctly reflect an earlier slot's choice, including after
    a backtrack changes that choice.

    try_candidate(candidate) -> a result object on success, or None if this
    specific candidate doesn't actually pan out (try the next one in the
    list for this slot).

    Returns the list of committed results, one per successfully filled
    slot, in order — shorter than num_slots only when genuinely nothing
    more fits even after backtracking (never fabricates a slot that
    doesn't really fit, same "never invent a placement" convention every
    other placement function in this codebase already follows).
    """
    committed = []
    frames = []  # parallel to committed: (candidates_list, next_index_already_tried) for that depth
    attempts = 0

    depth = 0
    candidates = candidates_for_slot(depth, committed)
    idx = 0
    # The deepest committed state reached across every branch explored —
    # if backtracking ultimately fails to find something that fills MORE
    # slots, real, already-valid progress must be kept, not discarded just
    # because the search happened to be mid-backtrack when it gave up.
    best_committed = []

    while depth < num_slots:
        if len(committed) > len(best_committed):
            best_committed = list(committed)

        if idx >= len(candidates):
            # Exhausted every candidate at this depth — backtrack up to
            # max_backtrack levels looking for one with an untried
            # candidate left.
            if not frames:
                break
            popped = 0
            found = False
            while frames and popped < max_backtrack:
                depth -= 1
                committed.pop()
                candidates, idx = frames.pop()
                popped += 1
                if idx < len(candidates):
                    found = True
                    break
            if not found:
                break
            continue

        if attempts >= max_total_attempts:
            break
        attempts += 1
        result = try_candidate(candidates[idx])
        idx += 1
        if result is None:
            continue

        frames.append((candidates, idx))  # remember where this depth left off, for a future backtrack
        committed.append(result)
        depth += 1
        candidates = candidates_for_slot(depth, committed)
        idx = 0

    if len(committed) > len(best_committed):
        best_committed = list(committed)
    return best_committed
