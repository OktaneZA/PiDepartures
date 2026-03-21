"""Tests for src/config.py — TEST-03."""

import os
import sys
import pytest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import config as cfg_mod


def _load(env_overrides: dict):
    """Helper: patch os.environ and call load_config()."""
    import sys

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


# ---------------------------------------------------------------------------
# hash_password / verify_password (SEC-08)
# ---------------------------------------------------------------------------

class TestHashVerifyPassword:
    def test_hash_returns_pbkdf2_format(self):
        h = cfg_mod.hash_password("secret")
        assert h.startswith("pbkdf2:sha256:260000:")
        assert len(h.split(":")) == 5

    def test_hash_is_not_plaintext(self):
        assert "secret" not in cfg_mod.hash_password("secret")

    def test_two_hashes_of_same_password_differ(self):
        """Different salts produce different hashes."""
        assert cfg_mod.hash_password("secret") != cfg_mod.hash_password("secret")

    def test_verify_correct_password_returns_true(self):
        h = cfg_mod.hash_password("correct")
        assert cfg_mod.verify_password("correct", h) is True

    def test_verify_wrong_password_returns_false(self):
        h = cfg_mod.hash_password("correct")
        assert cfg_mod.verify_password("wrong", h) is False

    def test_verify_empty_stored_returns_false(self):
        assert cfg_mod.verify_password("anything", "") is False

    def test_verify_legacy_plaintext_falls_back_to_compare(self):
        assert cfg_mod.verify_password("admin", "admin") is True

    def test_verify_legacy_wrong_plaintext_returns_false(self):
        assert cfg_mod.verify_password("wrong", "admin") is False

    def test_verify_malformed_hash_returns_false(self):
        assert cfg_mod.verify_password("x", "pbkdf2:broken") is False


# ---------------------------------------------------------------------------
# load_raw_config / save_raw_config
# ---------------------------------------------------------------------------

class TestRawConfig:
    def test_load_parses_key_value(self, tmp_path):
        f = tmp_path / "config"
        f.write_text("API_KEY=mykey\nDEPARTURE_STATION=PAD\n")
        result = cfg_mod.load_raw_config(str(f))
        assert result["API_KEY"] == "mykey"
        assert result["DEPARTURE_STATION"] == "PAD"

    def test_load_ignores_comments_and_blank_lines(self, tmp_path):
        f = tmp_path / "config"
        f.write_text("# comment\n\nAPI_KEY=abc\n")
        result = cfg_mod.load_raw_config(str(f))
        assert list(result.keys()) == ["API_KEY"]

    def test_load_strips_double_quotes(self, tmp_path):
        f = tmp_path / "config"
        f.write_text('API_KEY="quoted"\n')
        assert cfg_mod.load_raw_config(str(f))["API_KEY"] == "quoted"

    def test_load_strips_single_quotes(self, tmp_path):
        f = tmp_path / "config"
        f.write_text("API_KEY='quoted'\n")
        assert cfg_mod.load_raw_config(str(f))["API_KEY"] == "quoted"

    def test_save_writes_key_value_file(self, tmp_path):
        f = tmp_path / "config"
        cfg_mod.save_raw_config({"API_KEY": "abc", "DEPARTURE_STATION": "PAD"}, str(f))
        text = f.read_text()
        assert "API_KEY=abc" in text
        assert "DEPARTURE_STATION=PAD" in text

    def test_save_is_atomic_via_replace(self, tmp_path):
        """No .tmp file should remain after save."""
        f = tmp_path / "config"
        cfg_mod.save_raw_config({"API_KEY": "abc"}, str(f))
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_then_load_roundtrip(self, tmp_path):
        f = tmp_path / "config"
        original = {"API_KEY": "mykey", "DEPARTURE_STATION": "WAT", "REFRESH_TIME": "60"}
        cfg_mod.save_raw_config(original, str(f))
        loaded = cfg_mod.load_raw_config(str(f))
        assert loaded["API_KEY"] == "mykey"
        assert loaded["DEPARTURE_STATION"] == "WAT"
        assert loaded["REFRESH_TIME"] == "60"


# ---------------------------------------------------------------------------
# validate_portal_config
# ---------------------------------------------------------------------------

class TestValidatePortalConfig:
    def _valid(self, **overrides):
        base = {
            "API_KEY": "test-key",
            "DEPARTURE_STATION": "PAD",
            "REFRESH_TIME": "120",
            "SCREEN_ROTATION": "2",
            "PORTAL_PORT": "8080",
        }
        base.update(overrides)
        return base

    def test_valid_config_no_errors(self):
        assert cfg_mod.validate_portal_config(self._valid()) == []

    def test_missing_departure_station(self):
        errors = cfg_mod.validate_portal_config(self._valid(DEPARTURE_STATION=""))
        assert any("DEPARTURE_STATION" in e for e in errors)

    def test_invalid_departure_station_crs(self):
        errors = cfg_mod.validate_portal_config(self._valid(DEPARTURE_STATION="LONDON"))
        assert any("CRS" in e for e in errors)

    def test_invalid_destination_crs(self):
        errors = cfg_mod.validate_portal_config(self._valid(DESTINATION_STATION="TOOSHORT"))
        assert any("DESTINATION_STATION" in e for e in errors)

    def test_valid_destination_crs(self):
        assert cfg_mod.validate_portal_config(self._valid(DESTINATION_STATION="EUS")) == []

    def test_missing_api_key(self):
        errors = cfg_mod.validate_portal_config(self._valid(API_KEY=""))
        assert any("API_KEY" in e for e in errors)

    def test_invalid_refresh_time_non_integer(self):
        errors = cfg_mod.validate_portal_config(self._valid(REFRESH_TIME="abc"))
        assert any("REFRESH_TIME" in e for e in errors)

    def test_refresh_time_below_minimum(self):
        errors = cfg_mod.validate_portal_config(self._valid(REFRESH_TIME="5"))
        assert any("REFRESH_TIME" in e for e in errors)

    def test_invalid_screen_rotation(self):
        errors = cfg_mod.validate_portal_config(self._valid(SCREEN_ROTATION="5"))
        assert any("SCREEN_ROTATION" in e for e in errors)

    def test_valid_screen_rotations(self):
        for r in ("0", "1", "2", "3"):
            assert cfg_mod.validate_portal_config(self._valid(SCREEN_ROTATION=r)) == []

    def test_invalid_portal_port_non_integer(self):
        errors = cfg_mod.validate_portal_config(self._valid(PORTAL_PORT="abc"))
        assert any("PORTAL_PORT" in e for e in errors)

    def test_portal_port_out_of_range(self):
        errors = cfg_mod.validate_portal_config(self._valid(PORTAL_PORT="99999"))
        assert any("PORTAL_PORT" in e for e in errors)

    def test_invalid_blank_hours_format(self):
        errors = cfg_mod.validate_portal_config(self._valid(SCREEN_BLANK_HOURS="badformat"))
        assert any("SCREEN_BLANK_HOURS" in e for e in errors)

    def test_valid_blank_hours(self):
        assert cfg_mod.validate_portal_config(self._valid(SCREEN_BLANK_HOURS="22-06")) == []

    def test_blank_blank_hours_no_error(self):
        assert cfg_mod.validate_portal_config(self._valid(SCREEN_BLANK_HOURS="")) == []
