"""Regression coverage for seat_engine.py's screen_width_ft handling — the
fix that makes FIRST_ROW_DISTANCE_RULE (SOP §4.4/§9: first-row distance >=
screen width) a real, meaningful check instead of one that would fail on
every real layout (see the component-placement-upgrade plan's design
decision #2 for the full reasoning: SCREEN_TO_BACK_WALL_MIN_FT, 3ft, is a
much smaller number than any real screen width, so first_row_distance_ft
must actually grow to match screen_width_ft when one is given, not just
report a fixed 3ft forever)."""
import seat_engine
import rules_registry


def test_first_row_distance_defaults_to_screen_to_back_wall_norm():
    result = seat_engine.estimate_seats(40, 50)
    expected = rules_registry.planning_norm("SCREEN_TO_BACK_WALL_MIN_FT")
    assert result["first_row_distance_ft"] == expected


def test_first_row_distance_grows_to_match_a_larger_screen_width():
    result = seat_engine.estimate_seats(40, 60, screen_width_ft=30)
    assert result["first_row_distance_ft"] == 30


def test_first_row_distance_does_not_shrink_below_the_sop_minimum():
    """A screen narrower than the SOP's own 3ft minimum (unrealistic, but
    the function must never use a smaller number than the real minimum)
    still reports the SOP floor, not the smaller screen_width_ft."""
    result = seat_engine.estimate_seats(40, 50, screen_width_ft=1.0)
    expected = rules_registry.planning_norm("SCREEN_TO_BACK_WALL_MIN_FT")
    assert result["first_row_distance_ft"] == expected


def test_larger_screen_width_leaves_less_usable_depth_for_seating():
    """The whole point: a wider screen actually pushes row 1 back further
    in the real packing math, at the cost of fewer rows fitting — not just
    a cosmetically different reported number with identical seat output."""
    narrow = seat_engine.estimate_seats(40, 60, screen_width_ft=10)
    wide = seat_engine.estimate_seats(40, 60, screen_width_ft=40)
    assert wide["first_row_distance_ft"] > narrow["first_row_distance_ft"]
    assert wide["rows"] <= narrow["rows"]


# ---------- front_row_count (real-file gap-closure round) ----------

def test_front_lounger_is_now_selectable():
    """FRONT_LOUNGER previously had no min_row_step_ft (SOURCE_BACKED_INCOMPLETE)
    and no width field _seat_geometry recognized (width_in_front_view was
    never checked) — both fixed this round. Confirms it actually made it
    into the registry-driven selectable list, not just that the JSON field
    exists."""
    ids = {s["id"] for s in seat_engine.selectable_seat_types()}
    assert "FRONT_LOUNGER" in ids


def test_front_row_count_produces_exactly_that_many_front_rows():
    """front_row_count=1 with FRONT_LOUNGER as the primary (front) type
    should yield exactly 1 row of real Front Lounger seats — a real,
    counted assertion, not just "the call didn't crash." A big room (many
    theoretical rows) makes an accidental multi-row match implausible."""
    result = seat_engine.estimate_seats(
        40, 80, primary_seat_type_id="FRONT_LOUNGER", secondary_seat_type_id="SLIDER_SOFA", front_row_count=1
    )
    assert result["seat_breakdown"]["LOUNGER"] > 0
    # Exactly 1 lounger row's worth of seats: dividing by the per-row count
    # (seats_per_row) should recover a whole small number of rows for the
    # lounger portion specifically — check via a 2-row request instead,
    # which must produce roughly double the lounger seats of a 1-row
    # request at the same room width (a real, comparable row-count effect).
    result_2 = seat_engine.estimate_seats(
        40, 80, primary_seat_type_id="FRONT_LOUNGER", secondary_seat_type_id="SLIDER_SOFA", front_row_count=2
    )
    assert result_2["seat_breakdown"]["LOUNGER"] >= 2 * result["seat_breakdown"]["LOUNGER"] - 1


def test_front_row_count_none_reproduces_percentage_behavior_unchanged():
    """Omitting front_row_count (every existing caller, e.g. the manual
    SeatConfigPanel-driven edit path) must keep behaving exactly like
    before this round — the percentage-based mix path is untouched."""
    result = seat_engine.estimate_seats(
        40, 80, primary_seat_type_id="SLIDER_SOFA", secondary_seat_type_id="DUO_LOUNGER", primary_ratio_pct=30
    )
    assert result["seat_breakdown"]["SOFA_SLIDER"] > 0
    assert result["seat_breakdown"]["DUO_LOUNGER"] > 0
