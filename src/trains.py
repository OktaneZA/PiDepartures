"""National Rail OpenLDBWS SOAP client.

Based on https://github.com/chrisys/train-departure-display
Adapted for native systemd deployment: logging, explicit SSL verification, error handling.

Requirements: ARCH-01, ARCH-10, SEC-01, SEC-06, SEC-07
"""

import logging
import re
from xml.sax.saxutils import escape as _xml_escape

import requests
import xmltodict

logger = logging.getLogger(__name__)

# OpenLDBWS endpoint — HTTPS enforced, no HTTP fallback (SEC-06)
_API_URL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

# Exponential back-off constants (ARCH-01)
BACKOFF_INITIAL = 2
BACKOFF_MAX = 120


def removeBrackets(originalName):
    """Strip parenthetical suffixes from station names (e.g. 'Reading (Berks)' → 'Reading')."""
    return re.split(r" \(", originalName)[0]


def isTime(value):
    """Return True if value matches HH:MM format."""
    return len(re.findall(r"\d{2}:\d{2}", value)) > 0


def joinwithCommas(listIN):
    """Join list with commas, replacing the last comma with 'and'."""
    return ", ".join(listIN)[::-1].replace(",", "dna ", 1)[::-1]


def removeEmptyStrings(items):
    """Filter out falsy/empty strings from an iterable."""
    return filter(None, items)


def joinWith(items, joiner: str):
    """Join non-empty items with joiner."""
    return joiner.join(removeEmptyStrings(items))


def joinWithSpaces(*args):
    """Join non-empty args with a single space."""
    return joinWith(args, " ")


def prepareServiceMessage(operator):
    """Format 'A/An <Operator> Service' string."""
    article = "An" if operator in ("Elizabeth Line", "Avanti West Coast") else "A"
    return joinWithSpaces(article, operator, "Service")


def prepareLocationName(location, show_departure_time):
    """Format a calling-point location name, optionally with departure time."""
    location_name = removeBrackets(location["lt7:locationName"])
    if not show_departure_time:
        return location_name
    scheduled_time = location["lt7:st"]
    try:
        expected_time = location.get("lt7:et") or location.get("lt7:at") or scheduled_time
    except (KeyError, AttributeError):
        expected_time = scheduled_time  # C-04: neither et nor at present — fall back gracefully
    departure_time = expected_time if isTime(expected_time) else scheduled_time
    return joinWithSpaces(location_name, joinWith(["(", departure_time, ")"], ""))


def prepareCarriagesMessage(carriages):
    """Format 'formed of N coaches.' or empty string if 0."""
    if carriages == 0:
        return ""
    return joinWithSpaces("formed of", carriages, "coaches.")


def ArrivalOrder(ServicesIN):
    """Sort services by scheduled departure time, handling midnight crossover."""
    ServicesOUT = []
    for servicenum, eachService in enumerate(ServicesIN):
        STDHour = int(eachService["lt4:std"][0:2])
        STDMinute = int(eachService["lt4:std"][3:5])
        if STDHour < 2:
            STDHour += 24  # prevent 12am showing before 11pm
        ServicesOUT.append(eachService)
        ServicesOUT[servicenum]["sortOrder"] = STDHour * 60 + STDMinute
    return sorted(ServicesOUT, key=lambda k: k["sortOrder"])


def ProcessDepartures(journeyConfig, APIOut):
    """Parse SOAP XML response into a list of departure dicts.

    Args:
        journeyConfig: Journey configuration dict.
        APIOut: Raw XML string from OpenLDBWS.

    Returns:
        Tuple of (list-of-departure-dicts or None, station-name-string).

    Raises:
        ValueError: if XML is malformed or has unexpected structure (SECRV-03).
    """
    show_individual_departure_time = journeyConfig.get("individualStationDepartureTime", False)

    try:
        APIElements = xmltodict.parse(APIOut)
    except Exception as exc:
        raise ValueError(f"Failed to parse SOAP XML response: {exc}") from exc

    try:
        board_result = (
            APIElements["soap:Envelope"]["soap:Body"]
            ["GetDepBoardWithDetailsResponse"]["GetStationBoardResult"]
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unexpected SOAP response structure: {type(exc).__name__}: {exc}") from exc

    departureStationName = board_result.get("lt4:locationName", "Unknown")

    Services = []
    if "lt7:trainServices" in board_result:
        raw = board_result["lt7:trainServices"]["lt7:service"]
        Services = [raw] if isinstance(raw, dict) else raw
        if "lt7:busServices" in board_result:
            raw_bus = board_result["lt7:busServices"]["lt7:service"]
            bus = [raw_bus] if isinstance(raw_bus, dict) else raw_bus
            Services = ArrivalOrder(Services + bus)
    elif "lt7:busServices" in board_result:
        raw_bus = board_result["lt7:busServices"]["lt7:service"]
        Services = [raw_bus] if isinstance(raw_bus, dict) else raw_bus
    else:
        return None, departureStationName

    Departures = []

    for servicenum, eachService in enumerate(Services):
        try:
            thisDeparture = _parse_service(eachService, show_individual_departure_time)
        except (KeyError, TypeError, AttributeError) as exc:
            # C-04 / A-02: malformed individual service must not kill the fetch thread;
            # skip this service and log — ARCH-10: log attempt number, never API key
            raise ValueError(
                f"Failed to parse service {servicenum}: {type(exc).__name__}: {exc}"
            ) from exc
        Departures.append(thisDeparture)

    return Departures, departureStationName


def _parse_service(eachService: dict, show_individual_departure_time: bool) -> dict:
    """Parse a single service dict from the SOAP response into a departure dict.

    Args:
        eachService: Raw service dict from xmltodict.
        show_individual_departure_time: Whether to show per-stop times.

    Returns:
        Departure dict with keys: aimed_departure_time, expected_departure_time,
        destination_name, operator, carriages, calling_at_list, and optionally platform.

    Raises:
        KeyError: if a required field is missing (caller converts to ValueError).
    """
    thisDeparture = {}

    if "lt4:platform" in eachService:
        thisDeparture["platform"] = eachService["lt4:platform"]

    thisDeparture["aimed_departure_time"] = eachService["lt4:std"]
    thisDeparture["expected_departure_time"] = eachService["lt4:etd"]
    thisDeparture["carriages"] = eachService.get("lt4:length", 0)
    thisDeparture["operator"] = eachService.get("lt4:operator", "")

    dest_loc = eachService["lt5:destination"]["lt4:location"]
    if isinstance(dest_loc, list):
        thisDeparture["destination_name"] = " & ".join(
            removeBrackets(i["lt4:locationName"]) for i in dest_loc
        )
    else:
        thisDeparture["destination_name"] = removeBrackets(dest_loc["lt4:locationName"])

    # Calling points
    if "lt7:subsequentCallingPoints" in eachService:
        cpl = eachService["lt7:subsequentCallingPoints"]["lt7:callingPointList"]
        if not isinstance(cpl, dict):
            # Multiple sections (train splits)
            CallListJoined = []
            for section in cpl:
                cp = section["lt7:callingPoint"]
                if isinstance(cp, dict):
                    CallListJoined.append(prepareLocationName(cp, show_individual_departure_time))
                else:
                    names = [prepareLocationName(i, show_individual_departure_time) for i in cp]
                    CallListJoined.append(joinwithCommas(names))
            thisDeparture["calling_at_list"] = joinWithSpaces(
                " with a portion going to ".join(CallListJoined),
                "  --  ",
                prepareServiceMessage(thisDeparture["operator"]),
                prepareCarriagesMessage(thisDeparture["carriages"]),
            )
        else:
            cp = cpl["lt7:callingPoint"]
            if isinstance(cp, dict):
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    prepareLocationName(cp, show_individual_departure_time),
                    "only.",
                    "  --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"]),
                )
            else:
                names = [prepareLocationName(i, show_individual_departure_time) for i in cp]
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    joinwithCommas(names) + ".",
                    " --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"]),
                )
    else:
        thisDeparture["calling_at_list"] = joinWithSpaces(
            thisDeparture["destination_name"] + " only.",
            prepareServiceMessage(thisDeparture["operator"]),
            prepareCarriagesMessage(thisDeparture["carriages"]),
        )

    return thisDeparture


def loadDeparturesForStation(journeyConfig, apiKey, rows):
    """Fetch departures from OpenLDBWS for the configured station.

    Args:
        journeyConfig: Journey config dict (departureStation, destinationStation, etc.).
        apiKey: OpenLDBWS API key (SEC-01: never logged).
        rows: Number of rows to request (string).

    Returns:
        Tuple of (departures list, station name string).

    Raises:
        ValueError: on config errors or malformed XML.
        requests.RequestException: on network/HTTP failures.
    """
    if not journeyConfig.get("departureStation"):
        raise ValueError("departureStation is not configured")
    if not apiKey:
        raise ValueError("apiKey is not configured")  # SEC-01: never log the value

    station = journeyConfig["departureStation"]
    logger.info("Fetching departures for %s", station)  # ARCH-10: log station, never key

    # C-08: escape all config-derived values before XML interpolation
    APIRequest = (
        '<x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/"'
        ' xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">'
        "<x:Header>"
        "<typ4:AccessToken><typ4:TokenValue>" + _xml_escape(apiKey) + "</typ4:TokenValue></typ4:AccessToken>"
        "</x:Header>"
        "<x:Body>"
        "<ldb:GetDepBoardWithDetailsRequest>"
        "<ldb:numRows>" + _xml_escape(rows) + "</ldb:numRows>"
        "<ldb:crs>" + _xml_escape(station) + "</ldb:crs>"
        "<ldb:timeOffset>" + _xml_escape(journeyConfig.get("timeOffset", "0")) + "</ldb:timeOffset>"
        "<ldb:filterCrs>" + _xml_escape(journeyConfig.get("destinationStation", "")) + "</ldb:filterCrs>"
        "<ldb:filterType>to</ldb:filterType>"
        "<ldb:timeWindow>120</ldb:timeWindow>"
        "</ldb:GetDepBoardWithDetailsRequest>"
        "</x:Body>"
        "</x:Envelope>"
    )

    response = requests.post(
        _API_URL,
        data=APIRequest,
        headers={"Content-Type": "text/xml"},
        timeout=15,
        verify=True,  # SEC-07: SSL verification always enabled
    )
    response.raise_for_status()

    return ProcessDepartures(journeyConfig, response.text)


def backoff_delay(failure_count: int) -> float:
    """Calculate exponential back-off delay (ARCH-01).

    Args:
        failure_count: Number of consecutive failures (1-based).

    Returns:
        Seconds to wait: 2, 4, 8, …, capped at 120.
    """
    return float(min(BACKOFF_INITIAL * (2 ** (failure_count - 1)), BACKOFF_MAX))
