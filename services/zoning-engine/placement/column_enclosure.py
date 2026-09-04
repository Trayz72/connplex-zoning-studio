"""Shared column-enclosure gate for a placed rectangle — how much of a
confirmed structural COLUMN a room's footprint is allowed to cover before
the placement engine rejects that position.

A single leaf module (no imports of layout_engine/solver) so both the
greedy path (layout_engine.py) and the CP-SAT path (placement/solver.py)
share one implementation instead of two that can drift — this consolidates
what was previously layout_engine._column_enclosure_ok's inline ratio math
and solver._column_enclosed_ratio into one place, and adds a genuinely new
second gate: position, not just area.

Area-ratio alone (enclosed_ratio / enclosure_ok's max_ratio arg) says
nothing about WHERE inside the room a column falls — a column dead-center
in a seating field and a column clipping a back corner can have the same
area ratio but are not remotely equivalent in how much they actually
disrupt the room. has_interior_column_violation adds a real position test:
a column is only tolerable when it sits within edge_tolerance_ft of one of
the room's own four walls (near enough to be absorbed into wall
furring/an aisle); farther in than that, it's rejected outright regardless
of how small its area share is. Auditoriums use both gates
(edge_tolerance_ft set); support zones keep the old ratio-only behavior
(edge_tolerance_ft=None) since their much larger cap already reflects that
a foyer/F&B/BOH room can legitimately wrap a whole column or core.
"""
from shapely.geometry import box

# Below this, a rejected-as-interior overlap is floating-point/rasterization
# noise, not a real violation.
_MIN_VIOLATION_AREA_SQFT = 1e-6


def enclosed_ratio(x, y, w, h, column_polys) -> float:
    """Fraction of the rect's own area covered by column_polys, 0..1."""
    if not column_polys or w <= 0 or h <= 0:
        return 0.0
    rect = box(x, y, x + w, y + h)
    if rect.area <= 0:
        return 0.0
    return sum(rect.intersection(cp).area for cp in column_polys) / rect.area


def has_interior_column_violation(x, y, w, h, column_polys, edge_tolerance_ft) -> bool:
    """True iff some part of a column inside this rect lies farther than
    edge_tolerance_ft from every one of the rect's own four walls — i.e.
    stranded in the room's interior rather than near an edge."""
    if not column_polys or edge_tolerance_ft is None or w <= 0 or h <= 0:
        return False
    rect = box(x, y, x + w, y + h)
    # Mitred (square-cornered) negative buffer, so a column near a true
    # corner isn't misread as "near an edge" through a rounded-corner gap.
    core = rect.buffer(-edge_tolerance_ft, join_style=2)
    if core.is_empty:
        # Room too small to have an interior beyond the tolerance band —
        # every point is already within tolerance of some wall.
        return False
    for cp in column_polys:
        if core.intersection(cp).area > _MIN_VIOLATION_AREA_SQFT:
            return True
    return False


def enclosure_ok(x, y, w, h, column_polys, max_ratio, edge_tolerance_ft=None) -> bool:
    """The real gate a caller should use: the existing area-ratio cap AND
    (only when edge_tolerance_ft is given) the interior-position gate.
    edge_tolerance_ft=None reproduces the historical ratio-only behavior
    exactly — this is how support-zone column tolerance stays untouched."""
    if enclosed_ratio(x, y, w, h, column_polys) > max_ratio:
        return False
    if has_interior_column_violation(x, y, w, h, column_polys, edge_tolerance_ft):
        return False
    return True
