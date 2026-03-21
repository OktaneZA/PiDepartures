"""Configuration loading for train-display.

Based on https://github.com/chrisys/train-departure-display
Adapted for native systemd deployment: uppercase env var names (per systemd EnvironmentFile
convention), config file permission check, logging instead of print.

Environment variables are injected by systemd from /etc/train-display/config.

Requirements: ARCH-06, SEC-01, SEC-08, SEC-10
"""

import base64
import hashlib
import logging
import os
import re
import secrets
import stat
import tempfile

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = "/etc/train-display/config"

_HOURS_PATTERN = re.compile(r"^((2[0-3]|[0-1]?[0-9])-(2[0-3]|[0-1]?[0-9]))$")
_CRS_PATTERN = re.compile(r"^[A-Z]{3}$")


def hash_password(plaintext: str) -> str:
    """Hash *plaintext* with PBKDF2-HMAC-SHA256 and a random 16-byte salt. (SEC-08)

    Returns a string of the form: ``pbkdf2:sha256:260000:<salt_hex>:<base64_hash>``
    Never logs input value. (SEC-01)
    """
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), bytes.fromhex(salt), 260_000)
    return f"pbkdf2:sha256:260000:{salt}:{base64.b64encode(dk).decode('ascii')}"


def verify_password(plaintext: str, stored: str) -> bool:
    """Return True if *plaintext* matches *stored* PBKDF2 hash. (SEC-08)

    Handles legacy plaintext passwords for migration from older installs.
    Never logs either argument. (SEC-01)
    """
    if not stored:
        return False
    if not stored.startswith("pbkdf2:"):
        return secrets.compare_digest(plaintext, stored)
    try:
        _, method, iterations_str, salt_hex, hash_b64 = stored.split(":")
        if method != "sha256":
            logger.warning("verify_password: unsupported hash method %r", method)
            return False
        dk_stored = base64.b64decode(hash_b64)
        dk_attempt = hashlib.pbkdf2_hmac(
            method, plaintext.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations_str)
        )
        return secrets.compare_digest(dk_attempt, dk_stored)
    except Exception:  # noqa: BLE001 — malformed hash must not crash
        logger.warning("verify_password: malformed stored hash (not logging value)")
        return False


def load_raw_config(path: str = CONFIG_FILE_PATH) -> dict:
    """Parse the KEY=VALUE config file into a flat dict.

    Ignores blank lines and comments. Strips quotes from values.
    """
    cfg: dict = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


def save_raw_config(data: dict, path: str = CONFIG_FILE_PATH) -> None:
    """Atomically write a flat KEY=VALUE config file to *path*. (CFG-05)

    Writes to a .tmp file first, then uses os.replace() for atomicity.
    """
    dir_path = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# Train Departure Display — configuration\n")
            f.write("# Managed by install.sh / web portal — edit with care.\n\n")
            for key, value in data.items():
                f.write(f"{key}={value}\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info("Config saved to %s", path)


def validate_portal_config(data: dict) -> list:
    """Validate a flat portal config dict. Returns list of error strings."""
    errors = []

    station = data.get("DEPARTURE_STATION", "").strip().upper()
    if not station:
        errors.append("DEPARTURE_STATION is required")
    elif not _CRS_PATTERN.match(station):
        errors.append("DEPARTURE_STATION must be a 3-letter CRS code (e.g. PAD, WAT)")

    dest = data.get("DESTINATION_STATION", "").strip().upper()
    if dest and not _CRS_PATTERN.match(dest):
        errors.append("DESTINATION_STATION must be a 3-letter CRS code or blank")

    blank_hours = data.get("SCREEN_BLANK_HOURS", "").strip()
    if blank_hours and not _HOURS_PATTERN.match(blank_hours):
        errors.append("SCREEN_BLANK_HOURS must be in HH-HH format (e.g. 22-06)")

    try:
        refresh = int(data.get("REFRESH_TIME", "120"))
        if not (30 <= refresh <= 3600):
            errors.append("REFRESH_TIME must be between 30 and 3600 seconds")
    except ValueError:
        errors.append("REFRESH_TIME must be an integer")

    rotation = data.get("SCREEN_ROTATION", "2")
    if rotation not in ("0", "1", "2", "3"):
        errors.append("SCREEN_ROTATION must be 0, 1, 2, or 3")

    try:
        port = int(data.get("PORTAL_PORT", "8080"))
        if not (1 <= port <= 65535):
            errors.append("PORTAL_PORT must be between 1 and 65535")
    except ValueError:
        errors.append("PORTAL_PORT must be an integer")

    if not data.get("API_KEY", "").strip():
        errors.append("API_KEY is required")

    return errors


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
    data["portalPort"] = int(os.getenv("PORTAL_PORT") or 8080)

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
