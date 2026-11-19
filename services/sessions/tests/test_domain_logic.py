"""Session validation, quality filter and statistics: pure functions over dictionaries."""

from datetime import date

import domain_logic as logic

VALID = {
    "spot_id": 1,
    "date": "2026-11-01",
    "duration_mins": 60,
    "wave_or_wind_rating": 4,
    "gear_used": "Shortboard",
    "notes": "Fun",
}


def test_a_complete_session_is_valid():
    assert logic.validate_session_data(VALID) == {}


def test_a_date_object_is_accepted_as_well_as_a_string():
    assert logic.validate_session_data({**VALID, "date": date(2026, 11, 1)}) == {}


def test_spot_duration_and_rating_are_checked():
    errors = logic.validate_session_data({
        **VALID, "spot_id": 0, "duration_mins": "soon", "wave_or_wind_rating": 6,
    })
    assert set(errors) == {"spot_id", "duration_mins", "wave_or_wind_rating"}

    zero = logic.validate_session_data({**VALID, "duration_mins": 0})
    assert zero["duration_mins"] == "Duration must be greater than zero minutes."


def test_rating_must_be_present_and_in_range():
    errors = logic.validate_session_data({**VALID, "wave_or_wind_rating": None})
    assert "from 1 to 5" in errors["wave_or_wind_rating"]


def test_date_must_be_present_well_formed_real_and_not_in_the_future():
    assert logic.validate_session_data({**VALID, "date": ""})["date"].startswith("Date is required")
    assert logic.validate_session_data({**VALID, "date": None})["date"].startswith("Date is required")
    assert "YYYY-MM-DD" in logic.validate_session_data({**VALID, "date": "01/11/2026"})["date"]
    assert "real calendar date" in logic.validate_session_data({**VALID, "date": "2026-13-01"})["date"]
    assert "future" in logic.validate_session_data({**VALID, "date": "2999-01-01"})["date"]


def test_gear_and_notes_have_length_limits():
    errors = logic.validate_session_data({
        **VALID,
        "gear_used": "g" * (logic.MAX_GEAR_LENGTH + 1),
        "notes": "n" * (logic.MAX_NOTES_LENGTH + 1),
    })
    assert "gear_used" in errors and "notes" in errors


def test_calculate_stats_for_no_sessions_has_no_averages():
    assert logic.calculate_spot_stats([]) == {
        "session_count": 0,
        "total_duration_mins": 0,
        "average_duration_mins": None,
        "average_rating": None,
    }


def test_calculate_stats_totals_and_rounds_and_tolerates_form_strings():
    rows = [
        {"duration_mins": 30, "wave_or_wind_rating": 4},
        {"duration_mins": "60", "wave_or_wind_rating": "5"},
        {"duration_mins": 0, "wave_or_wind_rating": None},
    ]
    stats = logic.calculate_spot_stats(rows)
    assert stats["session_count"] == 3
    assert stats["total_duration_mins"] == 90, "zero and missing durations add nothing"
    assert stats["average_duration_mins"] == 30.0
    assert stats["average_rating"] == 4.5, "only rated sessions count towards the rating"


def test_calculate_stats_has_no_rating_average_when_nothing_is_rated():
    stats = logic.calculate_spot_stats([{"duration_mins": 10, "wave_or_wind_rating": None}])
    assert stats["average_rating"] is None


def test_filter_keeps_sessions_at_or_above_the_minimum_in_order():
    rows = [
        {"id": 1, "wave_or_wind_rating": 5},
        {"id": 2, "wave_or_wind_rating": 3},
        {"id": 3, "wave_or_wind_rating": None},
        {"id": 4, "wave_or_wind_rating": "4"},
    ]
    assert [r["id"] for r in logic.filter_ideal_sessions(rows)] == [1, 4]
    assert [r["id"] for r in logic.filter_ideal_sessions(rows, min_rating=5)] == [1]


def test_distribution_counts_each_rating_and_ignores_out_of_range():
    rows = [{"wave_or_wind_rating": r} for r in (1, 5, 5, 3, 0, 9, None)]
    assert logic.rating_distribution(rows) == {1: 1, 2: 0, 3: 1, 4: 0, 5: 2}
