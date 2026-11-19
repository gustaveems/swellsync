"""Spot validation, the pure part of the spots domain (no Flask, no database)."""

import domain_logic as logic

VALID = {"name": "Thurso East", "location": "Caithness", "ideal_wind_dir": "S", "ideal_swell_ft": 6}


def test_a_complete_spot_is_valid():
    assert logic.validate_spot_data(VALID) == {}


def test_name_and_location_are_required_and_limited():
    errors = logic.validate_spot_data({"name": "   ", "location": ""})
    assert errors["name"] == "Name is required."
    assert errors["location"] == "Location is required."

    too_long = {**VALID, "name": "x" * (logic.MAX_NAME_LENGTH + 1),
                "location": "y" * (logic.MAX_LOCATION_LENGTH + 1)}
    errors = logic.validate_spot_data(too_long)
    assert "100 characters" in errors["name"]
    assert "150 characters" in errors["location"]


def test_wind_direction_has_a_length_limit():
    errors = logic.validate_spot_data({**VALID, "ideal_wind_dir": "w" * (logic.MAX_WIND_DIR_LENGTH + 1)})
    assert "ideal_wind_dir" in errors


def test_swell_may_be_blank_but_must_be_a_non_negative_number():
    assert logic.validate_spot_data({**VALID, "ideal_swell_ft": None}) == {}
    assert logic.validate_spot_data({**VALID, "ideal_swell_ft": "   "}) == {}
    assert logic.validate_spot_data({**VALID, "ideal_swell_ft": "4.5"}) == {}
    assert "number" in logic.validate_spot_data({**VALID, "ideal_swell_ft": "tall"})["ideal_swell_ft"]
    assert "negative" in logic.validate_spot_data({**VALID, "ideal_swell_ft": -1})["ideal_swell_ft"]


def test_to_int_accepts_integral_values_and_rejects_the_rest():
    assert logic._to_int(7) == 7
    assert logic._to_int(3.0) == 3
    assert logic._to_int(" 12 ") == 12
    assert logic._to_int(3.5) is None
    assert logic._to_int(True) is None, "a boolean is not a duration"
    assert logic._to_int("twelve") is None
    assert logic._to_int(None) is None


def test_to_float_accepts_numbers_and_rejects_the_rest():
    assert logic._to_float(2) == 2.0
    assert logic._to_float(" 4.5 ") == 4.5
    assert logic._to_float(".5") == 0.5
    assert logic._to_float("   ") is None
    assert logic._to_float(False) is None
    assert logic._to_float("4.5m") is None


def test_text_or_empty_strips_and_stringifies():
    assert logic._text_or_empty(None) == ""
    assert logic._text_or_empty("  Mavericks ") == "Mavericks"
    assert logic._text_or_empty(42) == "42"
