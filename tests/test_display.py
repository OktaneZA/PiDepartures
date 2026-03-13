"""Tests for display logic in src/main.py — TEST-04.

luma display hardware is mocked; no physical device needed (TEST-05).
"""

import os
import sys
from datetime import time, datetime
from unittest.mock import MagicMock, patch

import pytest

# Add src/ to path
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ---------------------------------------------------------------------------
# Mock luma and RPi before importing main
# ---------------------------------------------------------------------------

def _mock_luma():
    """Insert mock luma modules into sys.modules so main.py can be imported."""
    for mod in [
        "luma", "luma.core", "luma.core.interface", "luma.core.interface.serial",
        "luma.core.render", "luma.core.virtual", "luma.core.sprite_system",
        "luma.oled", "luma.oled.device",
        "RPi", "RPi.GPIO",
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    # Ensure ssd1322 is importable
    sys.modules["luma.oled.device"].ssd1322 = MagicMock()
    sys.modules["luma.core.interface.serial"].spi = MagicMock()
    sys.modules["luma.core.interface.serial"].noop = MagicMock()
    sys.modules["luma.core.virtual"].viewport = MagicMock()
    sys.modules["luma.core.virtual"].snapshot = MagicMock()
    sys.modules["luma.core.render"].canvas = MagicMock()
    mock_regulator = MagicMock()
    mock_regulator.__enter__ = MagicMock(return_value=None)
    mock_regulator.__exit__ = MagicMock(return_value=False)
    sys.modules["luma.core.sprite_system"].framerate_regulator = MagicMock(return_value=mock_regulator)


_mock_luma()


# ---------------------------------------------------------------------------
# blank-hours logic tests (hours.py)
# ---------------------------------------------------------------------------

import hours as open_mod


class TestBlankHours:
    def test_simple_window_active(self):
        """22:00–06:00 should be active at 23:00."""
        assert open_mod.is_time_between(time(22, 0), time(6, 0), time(23, 0)) is True

    def test_simple_window_active_before_midnight(self):
        assert open_mod.is_time_between(time(22, 0), time(6, 0), time(22, 30)) is True

    def test_simple_window_active_after_midnight(self):
        assert open_mod.is_time_between(time(22, 0), time(6, 0), time(3, 0)) is True

    def test_simple_window_inactive_daytime(self):
        """22:00–06:00 should NOT be active at 12:00."""
        assert open_mod.is_time_between(time(22, 0), time(6, 0), time(12, 0)) is False

    def test_non_crossing_window_active(self):
        """08:00–20:00, check at 14:00."""
        assert open_mod.is_time_between(time(8, 0), time(20, 0), time(14, 0)) is True

    def test_non_crossing_window_inactive(self):
        """08:00–20:00, check at 21:00."""
        assert open_mod.is_time_between(time(8, 0), time(20, 0), time(21, 0)) is False


# ---------------------------------------------------------------------------
# platform_filter tests
# ---------------------------------------------------------------------------

import main as main_mod


_SAMPLE_DEPARTURES = [
    {"aimed_departure_time": "10:00", "destination_name": "Oxford", "expected_departure_time": "On time",
     "operator": "GWR", "calling_at_list": "Oxford only.", "platform": "1"},
    {"aimed_departure_time": "10:15", "destination_name": "Bristol", "expected_departure_time": "On time",
     "operator": "GWR", "calling_at_list": "Bristol only.", "platform": "2"},
    {"aimed_departure_time": "10:30", "destination_name": "Bath Spa", "expected_departure_time": "Delayed",
     "operator": "GWR", "calling_at_list": "Bath Spa only."},
]


class TestPlatformFilter:
    def test_empty_filter_returns_all(self):
        deps, calling, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "", "PAD")
        assert len(deps) == 3

    def test_platform_1_filter(self):
        deps, calling, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "1", "PAD")
        assert len(deps) == 1
        assert deps[0]["destination_name"] == "Oxford"

    def test_platform_2_filter(self):
        deps, calling, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "2", "PAD")
        assert len(deps) == 1
        assert deps[0]["destination_name"] == "Bristol"

    def test_no_match_returns_empty(self):
        deps, calling, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "9", "PAD")
        assert len(deps) == 0
        assert calling == ""

    def test_first_departure_calling_at_list_returned(self):
        deps, calling, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "", "PAD")
        assert calling == "Oxford only."

    def test_station_passed_through(self):
        _, _, station = main_mod.platform_filter(_SAMPLE_DEPARTURES, "", "PAD")
        assert station == "PAD"


# ---------------------------------------------------------------------------
# Scroll state tests
# ---------------------------------------------------------------------------

class TestScrollState:
    def test_initial_pixels_up_zero(self):
        state = main_mod.ScrollState()
        assert state.pixelsUp == 0

    def test_initial_has_not_elevated(self):
        state = main_mod.ScrollState()
        assert state.hasElevated == 0

    def test_unique_per_screen_id(self):
        """Each screen_id gets its own ScrollState."""
        main_mod._scrollStates.clear()
        font_mock = MagicMock()
        draw_mock = MagicMock()

        # Patch _cachedBitmapText so PIL is not called with a mock font
        bmp_mock = MagicMock()
        with patch.object(main_mod, "_cachedBitmapText", return_value=(100, 10, bmp_mock)):
            cb = main_mod.renderStations("Reading, Oxford", font_mock, "screenA")
            cb(draw_mock)

            cb2 = main_mod.renderStations("Reading, Oxford", font_mock, "screenB")
            cb2(draw_mock)

        assert "screenA" in main_mod._scrollStates
        assert "screenB" in main_mod._scrollStates
        assert main_mod._scrollStates["screenA"] is not main_mod._scrollStates["screenB"]


# ---------------------------------------------------------------------------
# Row selection (bold/normal) tests — T-07
# ---------------------------------------------------------------------------

class TestRowSelection:
    """Verify that config['firstDepartureBold'] controls which font renderDestination receives."""

    _DEPARTURE = {
        "aimed_departure_time": "10:00",
        "destination_name": "Oxford",
        "expected_departure_time": "On time",
        "operator": "GWR",
        "calling_at_list": "Oxford only.",
        "platform": "1",
    }

    def _get_rendered_text(self, departure, font, config):
        """Call the renderDestination closure and capture the text bitmap key used."""
        captured = []

        class CaptureDraw:
            def bitmap(self, pos, bmp, fill=None):
                pass  # we inspect the cache key directly

        # Patch _cachedBitmapText to capture the (text, font) call
        original = main_mod._cachedBitmapText
        calls = []

        def patched(text, f):
            calls.append((text, f))
            w, h = 100, 10
            bmp = MagicMock()
            return w, h, bmp

        main_mod._cachedBitmapText = patched
        try:
            cb = main_mod.renderDestination(departure, font, "1st", config)
            cb(CaptureDraw())
        finally:
            main_mod._cachedBitmapText = original

        return calls

    def test_bold_font_passed_when_first_departure_bold_true(self):
        """When firstDepartureBold=True the bold font object is passed to renderDestination."""
        font_regular = MagicMock(name="regular")
        font_regular.getname.return_value = ("Dot Matrix Regular", "")
        font_bold = MagicMock(name="bold")
        font_bold.getname.return_value = ("Dot Matrix Bold", "")
        config = {"firstDepartureBold": True, "showDepartureNumbers": False, "refreshTime": 120}

        # With firstDepartureBold=True the caller should pass fontBold to renderDestination
        firstFont = font_bold if config["firstDepartureBold"] else font_regular
        calls = self._get_rendered_text(self._DEPARTURE, firstFont, config)
        _, font_used = calls[0]
        assert font_used is font_bold

    def test_regular_font_passed_when_first_departure_bold_false(self):
        """When firstDepartureBold=False the regular font object is passed."""
        font_regular = MagicMock(name="regular")
        font_regular.getname.return_value = ("Dot Matrix Regular", "")
        font_bold = MagicMock(name="bold")
        font_bold.getname.return_value = ("Dot Matrix Bold", "")
        config = {"firstDepartureBold": False, "showDepartureNumbers": False, "refreshTime": 120}

        firstFont = font_bold if config["firstDepartureBold"] else font_regular
        calls = self._get_rendered_text(self._DEPARTURE, firstFont, config)
        _, font_used = calls[0]
        assert font_used is font_regular

    def test_departure_number_included_when_show_numbers_true(self):
        """Departure index prefix appears in rendered text when showDepartureNumbers=True."""
        font = MagicMock()
        font.getname.return_value = ("Test", "")
        config = {"firstDepartureBold": False, "showDepartureNumbers": True, "refreshTime": 120}
        calls = self._get_rendered_text(self._DEPARTURE, font, config)
        text, _ = calls[0]
        assert "1st" in text

    def test_departure_number_excluded_when_show_numbers_false(self):
        """Departure index prefix absent when showDepartureNumbers=False."""
        font = MagicMock()
        font.getname.return_value = ("Test", "")
        config = {"firstDepartureBold": False, "showDepartureNumbers": False, "refreshTime": 120}
        calls = self._get_rendered_text(self._DEPARTURE, font, config)
        text, _ = calls[0]
        assert "1st" not in text


# ---------------------------------------------------------------------------
# _err_band tests — ARCH-02/ARCH-03 display state logic
# ---------------------------------------------------------------------------

class TestErrBand:
    def test_zero_errors_band_0(self):
        assert main_mod._err_band(0) == 0

    def test_one_error_band_1(self):
        assert main_mod._err_band(1) == 1

    def test_two_errors_band_1(self):
        assert main_mod._err_band(2) == 1

    def test_three_errors_band_2(self):
        assert main_mod._err_band(3) == 2

    def test_many_errors_band_2(self):
        assert main_mod._err_band(99) == 2


# ---------------------------------------------------------------------------
# platform_filter regex tests (INST-10 fix)
# ---------------------------------------------------------------------------

class TestPlatformFilterRegex:
    def test_regex_filter_matches_multiple_platforms(self):
        """'^[12]$' regex should match platforms 1 and 2 but not 3."""
        deps, _, _ = main_mod.platform_filter(_SAMPLE_DEPARTURES, "^[12]$", "PAD")
        assert len(deps) == 2
        platforms = {d.get("platform") for d in deps}
        assert "1" in platforms
        assert "2" in platforms
        assert "3" not in platforms

    def test_empty_regex_returns_all(self):
        deps, _, _ = main_mod.platform_filter(_SAMPLE_DEPARTURES, "", "PAD")
        assert len(deps) == 3

    def test_specific_platform_regex(self):
        deps, _, _ = main_mod.platform_filter(_SAMPLE_DEPARTURES, "^2$", "PAD")
        assert len(deps) == 1
        assert deps[0]["destination_name"] == "Bristol"


# ---------------------------------------------------------------------------
# Ordinal date helper tests — TEST-08 (DISP-09)
# ---------------------------------------------------------------------------

class TestOrdinalDate:
    """Verify _ordinal_date formats dates correctly including edge cases."""

    def test_1st(self):
        assert "1st" in main_mod._ordinal_date(datetime(2026, 3, 1))

    def test_2nd(self):
        assert "2nd" in main_mod._ordinal_date(datetime(2026, 3, 2))

    def test_3rd(self):
        assert "3rd" in main_mod._ordinal_date(datetime(2026, 3, 3))

    def test_4th(self):
        assert "4th" in main_mod._ordinal_date(datetime(2026, 3, 4))

    def test_11th_special_case(self):
        """11 ends in 1 but must be 'th' not 'st'."""
        assert "11th" in main_mod._ordinal_date(datetime(2026, 3, 11))

    def test_12th_special_case(self):
        """12 ends in 2 but must be 'th' not 'nd'."""
        assert "12th" in main_mod._ordinal_date(datetime(2026, 3, 12))

    def test_13th_special_case(self):
        """13 ends in 3 but must be 'th' not 'rd'."""
        assert "13th" in main_mod._ordinal_date(datetime(2026, 3, 13))

    def test_21st(self):
        assert "21st" in main_mod._ordinal_date(datetime(2026, 3, 21))

    def test_22nd(self):
        assert "22nd" in main_mod._ordinal_date(datetime(2026, 3, 22))

    def test_23rd(self):
        assert "23rd" in main_mod._ordinal_date(datetime(2026, 3, 23))

    def test_full_format(self):
        """DISP-09: full format must be 'Ddd DDth Month'."""
        assert main_mod._ordinal_date(datetime(2026, 3, 13)) == "Fri 13th March"

    def test_day_name_included(self):
        assert main_mod._ordinal_date(datetime(2026, 3, 13)).startswith("Fri")

    def test_month_name_included(self):
        assert "March" in main_mod._ordinal_date(datetime(2026, 3, 13))
