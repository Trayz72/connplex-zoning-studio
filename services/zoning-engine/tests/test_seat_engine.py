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
