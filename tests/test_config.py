"""Tests for src/config.py — TEST-03."""

import os
import pytest


def _load(env_overrides: dict):
    """Helper: patch os.environ and call load_config()."""
    import importlib
    import sys

    # Ensure clean import
    if "config" in sys.modules:
        del sys.modules["config"]

    src_path = os.path.join(os.path.dirname(__file__), "..", "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    base_env = {
        "API_KEY": "test-key-12345",
        "DEPARTURE_STATION": "PAD",
    }
    base_env.update(env_overrides)

    # Patch only the keys we care about; don't pollute real env
    old = {k: os.environ.get(k) for k in base_env}
    for k, v in base_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import config as cfg_mod
        return cfg_mod.load_config()
    finally:
        for k, old_v in old.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


class TestRequiredFields:
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="API_KEY"):
            _load({"API_KEY": ""})

    def test_missing_departure_station_raises(self):
        with pytest.raises(ValueError, match="DEPARTURE_STATION"):
            _load({"DEPARTURE_STATION": ""})

    def test_valid_minimal_config(self):
        cfg = _load({})
        assert cfg["journey"]["departureStation"] == "PAD"
        assert cfg["api"]["apiKey"] == "test-key-12345"


class TestDefaults:
    def test_refresh_time_default(self):
        cfg = _load({})
        assert cfg["refreshTime"] == 120

    def test_screen_rotation_default(self):
        cfg = _load({})
        assert cfg["screenRotation"] == 2

    def test_dual_screen_default_false(self):
        cfg = _load({})
        assert cfg["dualScreen"] is False

    def test_first_departure_bold_default_true(self):
        cfg = _load({})
        assert cfg["firstDepartureBold"] is True

    def test_show_departure_numbers_default_false(self):
        cfg = _load({})
        assert cfg["showDepartureNumbers"] is False

    def test_destination_station_default_empty(self):
        cfg = _load({})
        assert cfg["journey"]["destinationStation"] == ""


class TestCRSValidation:
    def test_valid_crs_uppercase(self):
        cfg = _load({"DEPARTURE_STATION": "WAT"})
        assert cfg["journey"]["departureStation"] == "WAT"

    def test_destination_station_valid(self):
        cfg = _load({"DESTINATION_STATION": "EUS"})
        assert cfg["journey"]["destinationStation"] == "EUS"

    def test_destination_null_string_becomes_empty(self):
        cfg = _load({"DESTINATION_STATION": "null"})
        assert cfg["journey"]["destinationStation"] == ""

    def test_destination_undefined_string_becomes_empty(self):
        cfg = _load({"DESTINATION_STATION": "undefined"})
        assert cfg["journey"]["destinationStation"] == ""


class TestBooleanParsing:
    def test_dual_screen_true(self):
        cfg = _load({"DUAL_SCREEN": "TRUE"})
        assert cfg["dualScreen"] is True

    def test_first_departure_bold_false(self):
        cfg = _load({"FIRST_DEPARTURE_BOLD": "FALSE"})
        assert cfg["firstDepartureBold"] is False

    def test_show_departure_numbers_true(self):
        cfg = _load({"SHOW_DEPARTURE_NUMBERS": "TRUE"})
        assert cfg["showDepartureNumbers"] is True


class TestCRSFormatValidation:
    """Q-10: CRS format validated in load_config, not just validate.py."""

    def test_invalid_crs_too_long_raises(self):
        with pytest.raises(ValueError, match="CRS"):
            _load({"DEPARTURE_STATION": "LONDON"})

    def test_invalid_crs_too_short_raises(self):
        with pytest.raises(ValueError, match="CRS"):
            _load({"DEPARTURE_STATION": "PA"})

    def test_invalid_crs_digits_raises(self):
        with pytest.raises(ValueError, match="CRS"):
            _load({"DEPARTURE_STATION": "P4D"})

    def test_valid_crs_passes(self):
        cfg = _load({"DEPARTURE_STATION": "EUS"})
        assert cfg["journey"]["departureStation"] == "EUS"


class TestPlatformParsing:
    """INST-10: PLATFORM_FILTER is a regex per REQUIREMENTS.md."""

    def test_valid_regex_stored_as_is(self):
        cfg = _load({"PLATFORM_FILTER": "^[12]$"})
        assert cfg["journey"]["screen1Platform"] == "^[12]$"

    def test_simple_number_is_valid_regex(self):
        cfg = _load({"PLATFORM_FILTER": "3"})
        assert cfg["journey"]["screen1Platform"] == "3"

    def test_blank_platform_filter_is_empty(self):
        cfg = _load({"PLATFORM_FILTER": ""})
        assert cfg["journey"]["screen1Platform"] == ""

    def test_invalid_regex_becomes_empty(self):
        cfg = _load({"PLATFORM_FILTER": "[unclosed"})
        assert cfg["journey"]["screen1Platform"] == ""


class TestBlankHoursParsing:
    """T-09: SCREEN_BLANK_HOURS config parsing (required by TEST-03)."""

    def test_valid_blank_hours_stored(self):
        cfg = _load({"SCREEN_BLANK_HOURS": "22-06"})
        assert cfg["screenBlankHours"] == "22-06"

    def test_blank_hours_pattern_matches_valid(self):
        cfg = _load({"SCREEN_BLANK_HOURS": "22-06"})
        assert cfg["hoursPattern"].match("22-06") is not None

    def test_blank_hours_pattern_rejects_invalid(self):
        cfg = _load({"SCREEN_BLANK_HOURS": "25-06"})  # 25 is invalid hour
        # Pattern itself rejects 25; value stored as-is but pattern won't match
        assert cfg["hoursPattern"].match(cfg["screenBlankHours"]) is None

    def test_blank_hours_absent_is_empty_string(self):
        cfg = _load({"SCREEN_BLANK_HOURS": ""})
        assert cfg["screenBlankHours"] == ""

    def test_single_digit_hours_valid(self):
        cfg = _load({"SCREEN_BLANK_HOURS": "8-20"})
        assert cfg["hoursPattern"].match("8-20") is not None
