"""Configuration loading for train-display.

Based on https://github.com/chrisys/train-departure-display
Adapted for native systemd deployment: uppercase env var names (per systemd EnvironmentFile
convention), config file permission check, logging instead of print.

Environment variables are injected by systemd from /etc/train-display/config.

Requirements: ARCH-06, SEC-01, SEC-08, SEC-10
"""

import logging
import os
import re
import stat

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = "/etc/train-display/config"

_HOURS_PATTERN = re.compile(r"^((2[0-3]|[0-1]?[0-9])-(2[0-3]|[0-1]?[0-9]))$")
_CRS_PATTERN = re.compile(r"^[A-Z]{3}$")


def _validate_platform_regex(raw: str) -> str:
    """Validate that a platform filter string is a compilable regex.

    REQUIREMENTS.md specifies PLATFORM_FILTER as a regex (e.g. '^[12]$').
    Returns the raw string unchanged if valid, or '' if None/blank/invalid.

    Args:
        raw: Raw PLATFORM_FILTER value from config.

    Returns:
        Validated regex string, or '' if absent or invalid.
    """
    if not raw:
        return ""
    try:
        re.compile(raw)
        return raw
    except re.error:
        logger.warning("PLATFORM_FILTER '%s' is not a valid regex — ignoring", raw)
        return ""


def _check_config_permissions() -> None:
    """Warn if the config file is world-readable (SEC-10)."""
    try:
        st = os.stat(CONFIG_FILE_PATH)
        if st.st_mode & stat.S_IROTH:
            logger.warning(
                "Config file %s is world-readable — run: chmod o-r %s",
                CONFIG_FILE_PATH,
                CONFIG_FILE_PATH,
            )
    except OSError:
        pass  # File absent in DEBUG/headless mode — not a fault


def load_config() -> dict:
    """Load and return the runtime configuration from environment variables.

    systemd injects /etc/train-display/config as an EnvironmentFile before
    the process starts, so all values are available via os.environ / os.getenv.

    Returns:
        Config dict with keys: journey, api, and top-level display settings.

    Raises:
        ValueError: if required fields are missing or values are invalid (ARCH-06).
    """
    _check_config_permissions()

    data: dict = {"journey": {}, "api": {}}

    # Display settings
    data["targetFPS"] = int(os.getenv("TARGET_FPS") or 20)  # P-01: 20fps is appropriate for Pi Zero W
    data["refreshTime"] = int(os.getenv("REFRESH_TIME") or 120)
    data["fpsTime"] = int(os.getenv("FPS_TIME") or 10)
    data["screenRotation"] = int(os.getenv("SCREEN_ROTATION") or 2)
    data["screenBlankHours"] = os.getenv("SCREEN_BLANK_HOURS") or ""
    data["hoursPattern"] = _HOURS_PATTERN

    data["headless"] = os.getenv("DEBUG", "").upper() == "TRUE"  # DEBUG=true skips hardware

    data["dualScreen"] = os.getenv("DUAL_SCREEN", "").upper() == "TRUE"

    data["firstDepartureBold"] = os.getenv("FIRST_DEPARTURE_BOLD", "true").upper() != "FALSE"

    data["showDepartureNumbers"] = os.getenv("SHOW_DEPARTURE_NUMBERS", "").upper() == "TRUE"

    # Journey settings
    departure_station = (os.getenv("DEPARTURE_STATION") or "").strip().upper()
    if not departure_station:
        raise ValueError(
            "DEPARTURE_STATION is required but not set. "
            "Set it in /etc/train-display/config"
        )
    # Q-10: validate CRS format
    if not _CRS_PATTERN.match(departure_station):
        raise ValueError(
            f"DEPARTURE_STATION '{departure_station}' must be a 3-letter CRS code (e.g. PAD, WAT)"
        )
    data["journey"]["departureStation"] = departure_station

    destination = (os.getenv("DESTINATION_STATION") or "").strip().upper()
    if destination in ("NULL", "UNDEFINED", ""):
        destination = ""
    if destination and not _CRS_PATTERN.match(destination):
        logger.warning("DESTINATION_STATION '%s' is not a valid CRS code — ignoring", destination)
        destination = ""
    data["journey"]["destinationStation"] = destination

    data["journey"]["individualStationDepartureTime"] = (
        os.getenv("INDIVIDUAL_STATION_DEPARTURE_TIME", "").upper() == "TRUE"
    )
    data["journey"]["outOfHoursName"] = (
        os.getenv("OUT_OF_HOURS_NAME") or data["journey"]["departureStation"]
    )
    data["journey"]["stationAbbr"] = {"International": "Intl."}
    data["journey"]["timeOffset"] = os.getenv("TIME_OFFSET") or "0"
    # INST-10: PLATFORM_FILTER is a regex per REQUIREMENTS.md (e.g. '^[12]$')
    data["journey"]["screen1Platform"] = _validate_platform_regex(os.getenv("PLATFORM_FILTER", ""))
    data["journey"]["screen2Platform"] = _validate_platform_regex(os.getenv("SCREEN2_PLATFORM", ""))

    # API settings — SEC-01: never log the key value
    api_key = os.getenv("API_KEY") or None
    if not api_key:
        raise ValueError(
            "API_KEY is required but not set. "
            "Set it in /etc/train-display/config"
        )
    data["api"]["apiKey"] = api_key
    data["api"]["operatingHours"] = os.getenv("OPERATING_HOURS") or ""

    logger.info(
        "Config loaded: station=%s destination=%s dualScreen=%s",
        data["journey"]["departureStation"],
        data["journey"]["destinationStation"] or "(none)",
        data["dualScreen"],
    )
    return data
