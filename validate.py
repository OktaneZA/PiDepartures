"""Post-install API connectivity validator.

Reads /etc/train-display/config, verifies API connectivity, and prints
a structured pass/fail report. Run on the Pi after installation.

Requirements: VAL-01 – VAL-10
"""

import os
import re
import sys

CONFIG_FILE = "/etc/train-display/config"
_CRS_RE = re.compile(r"^[A-Z]{3}$")

PASS = "[ PASS ]"
FAIL = "[ FAIL ]"


def _check(label: str, ok: bool, reason: str = "") -> bool:
    """Print a pass/fail line and return ok."""
    if ok:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}: {reason}")
    return ok


def load_config_file(path: str) -> dict:
    """Parse a KEY=value config file into a dict (handles quotes, ignores comments)."""
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                cfg[key.strip()] = value
    return cfg


def main() -> int:
    """Run all 5 validation checks. Returns 0 on full pass, 1 on any failure."""
    all_ok = True

    # Check 1: config file exists and is readable (VAL-03)
    config_readable = os.path.isfile(CONFIG_FILE) and os.access(CONFIG_FILE, os.R_OK)
    all_ok &= _check("Config file exists and is readable", config_readable, CONFIG_FILE)
    if not config_readable:
        print("\nCannot continue without config file.")
        return 1

    cfg = load_config_file(CONFIG_FILE)

    # Check 2: API_KEY is set (VAL-04) — print "set" never the value (SEC-01)
    api_key = cfg.get("API_KEY", "")
    api_key_set = bool(api_key)
    all_ok &= _check("API_KEY is set", api_key_set, "API_KEY is empty or missing")

    # Check 3: DEPARTURE_STATION is valid CRS (VAL-05)
    station = cfg.get("DEPARTURE_STATION", "").strip().upper()
    station_valid = bool(station) and bool(_CRS_RE.match(station))
    all_ok &= _check(
        f"DEPARTURE_STATION is valid CRS ({station!r})",
        station_valid,
        f"Got {station!r} — must be 3 uppercase letters",
    )

    if not api_key_set or not station_valid:
        print("\nCannot make API call without valid API_KEY and DEPARTURE_STATION.")
        return 1

    # Check 4: live HTTPS call returns HTTP 200 with XML (VAL-06)
    try:
        import requests

        destination = cfg.get("DESTINATION_STATION", "").strip()
        rows = "3"

        api_request = (
            '<x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/"'
            ' xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/"'
            ' xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">'
            "<x:Header>"
            f"<typ4:AccessToken><typ4:TokenValue>{api_key}</typ4:TokenValue></typ4:AccessToken>"
            "</x:Header>"
            "<x:Body>"
            "<ldb:GetDepBoardWithDetailsRequest>"
            f"<ldb:numRows>{rows}</ldb:numRows>"
            f"<ldb:crs>{station}</ldb:crs>"
            "<ldb:timeOffset>0</ldb:timeOffset>"
            f"<ldb:filterCrs>{destination}</ldb:filterCrs>"
            "<ldb:filterType>to</ldb:filterType>"
            "<ldb:timeWindow>120</ldb:timeWindow>"
            "</ldb:GetDepBoardWithDetailsRequest>"
            "</x:Body>"
            "</x:Envelope>"
        )

        resp = requests.post(
            "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
            data=api_request,
            headers={"Content-Type": "text/xml"},
            timeout=15,
            verify=True,
        )

        http_ok = resp.status_code == 200 and "soap:Envelope" in resp.text
        all_ok &= _check(
            f"Live HTTPS call to OpenLDBWS returned valid XML (HTTP {resp.status_code})",
            http_ok,
            f"HTTP {resp.status_code}" if resp.status_code != 200 else "Response missing soap:Envelope",
        )

        if not http_ok:
            return 1

        # Check 5: at least one departure parsed (VAL-07)
        src_path = os.path.join(os.path.dirname(__file__), "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from trains import ProcessDepartures

        journey_cfg = {
            "departureStation": station,
            "destinationStation": destination,
            "timeOffset": "0",
            "individualStationDepartureTime": False,
        }
        departures, station_name = ProcessDepartures(journey_cfg, resp.text)

        has_departures = departures is not None and len(departures) > 0
        all_ok &= _check(
            "At least one departure parsed from response",
            has_departures,
            f"No departures found for {station} (could be out of hours or no services)",
        )

        # VAL-08: print next departure on success
        if has_departures:
            first = departures[0]
            platform = first.get("platform", "TBC")
            print(
                f"\nNext departure from {station_name}:\n"
                f"  {first['aimed_departure_time']}  {first['destination_name']}  "
                f"Plat {platform}  [{first['expected_departure_time']}]"
            )

    except Exception as exc:
        all_ok &= _check("Live HTTPS call to OpenLDBWS", False, str(exc))

    return 0 if all_ok else 1  # VAL-10


if __name__ == "__main__":
    sys.exit(main())
