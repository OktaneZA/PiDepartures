"""Tests for src/trains.py — TEST-02.

All tests use mock SOAP XML responses; no network calls are made.
"""

import os
import sys
import pytest

# Add src/ to path
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import trains


# ---------------------------------------------------------------------------
# Fixture: minimal SOAP XML response builder
# ---------------------------------------------------------------------------

_SOAP_WRAPPER = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepBoardWithDetailsResponse>
      <GetStationBoardResult>
        <lt4:locationName>London Paddington</lt4:locationName>
        {services_block}
      </GetStationBoardResult>
    </GetDepBoardWithDetailsResponse>
  </soap:Body>
</soap:Envelope>"""

_TRAIN_SERVICE_WRAPPER = "<lt7:trainServices><lt7:service>{}</lt7:service></lt7:trainServices>"

_SERVICE_TEMPLATE = """\
<lt4:std>{std}</lt4:std>
<lt4:etd>{etd}</lt4:etd>
<lt4:operator>{operator}</lt4:operator>
{platform_block}
<lt5:destination><lt4:location><lt4:locationName>{dest}</lt4:locationName></lt4:location></lt5:destination>
{calling_block}"""

_CALLING_BLOCK = """\
<lt7:subsequentCallingPoints>
  <lt7:callingPointList>
    <lt7:callingPoint>
      <lt7:locationName>{name}</lt7:locationName>
      <lt7:st>{st}</lt7:st>
      <lt7:et>On time</lt7:et>
    </lt7:callingPoint>
  </lt7:callingPointList>
</lt7:subsequentCallingPoints>"""


def _build_xml(std="10:00", etd="On time", operator="GWR", dest="Bristol Temple Meads",
               platform=None, calling_name="Reading", calling_st="10:25"):
    platform_block = f"<lt4:platform>{platform}</lt4:platform>" if platform else ""
    calling_block = _CALLING_BLOCK.format(name=calling_name, st=calling_st)
    service = _SERVICE_TEMPLATE.format(
        std=std, etd=etd, operator=operator, dest=dest,
        platform_block=platform_block, calling_block=calling_block,
    )
    services = _TRAIN_SERVICE_WRAPPER.format(service)
    return _SOAP_WRAPPER.format(services_block=services)


_JOURNEY_CONFIG = {
    "departureStation": "PAD",
    "destinationStation": "",
    "timeOffset": "0",
    "individualStationDepartureTime": False,
}

_EMPTY_SERVICES_XML = _SOAP_WRAPPER.format(services_block="")


# ---------------------------------------------------------------------------
# ProcessDepartures tests
# ---------------------------------------------------------------------------

class TestOnTime:
    def test_returns_departure_list(self):
        xml = _build_xml()
        deps, station = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps is not None
        assert len(deps) == 1

    def test_station_name_parsed(self):
        xml = _build_xml()
        _, station = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert station == "London Paddington"

    def test_scheduled_time(self):
        xml = _build_xml(std="08:45")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["aimed_departure_time"] == "08:45"

    def test_status_on_time(self):
        xml = _build_xml(etd="On time")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["expected_departure_time"] == "On time"

    def test_destination_name(self):
        xml = _build_xml(dest="Oxford")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["destination_name"] == "Oxford"

    def test_operator(self):
        xml = _build_xml(operator="Chiltern Railways")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["operator"] == "Chiltern Railways"

    def test_calling_at_list_contains_station(self):
        xml = _build_xml(calling_name="Didcot Parkway")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert "Didcot Parkway" in deps[0]["calling_at_list"]

    def test_platform_parsed(self):
        xml = _build_xml(platform="3")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["platform"] == "3"

    def test_no_platform_key_absent(self):
        xml = _build_xml(platform=None)
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert "platform" not in deps[0]


class TestDelayed:
    def test_status_delayed(self):
        xml = _build_xml(etd="Delayed")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["expected_departure_time"] == "Delayed"


class TestCancelled:
    def test_status_cancelled(self):
        xml = _build_xml(etd="Cancelled")
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, xml)
        assert deps[0]["expected_departure_time"] == "Cancelled"


class TestEmptyServices:
    def test_no_services_returns_none(self):
        deps, station = trains.ProcessDepartures(_JOURNEY_CONFIG, _EMPTY_SERVICES_XML)
        assert deps is None
        assert station == "London Paddington"


class TestMalformedXML:
    def test_invalid_xml_raises_value_error(self):
        with pytest.raises(ValueError, match="parse"):
            trains.ProcessDepartures(_JOURNEY_CONFIG, "<<NOT XML>>")

    def test_missing_body_raises_value_error(self):
        with pytest.raises(ValueError):
            trains.ProcessDepartures(
                _JOURNEY_CONFIG,
                '<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body/></soap:Envelope>',
            )


class TestMalformedService:
    """C-04 / A-02: a malformed individual service must not discard the whole batch."""

    _TWO_SERVICE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepBoardWithDetailsResponse>
      <GetStationBoardResult>
        <lt4:locationName>London Paddington</lt4:locationName>
        <lt7:trainServices>
          <lt7:service>
            <lt4:std>10:00</lt4:std>
            <lt4:etd>On time</lt4:etd>
            <lt4:operator>GWR</lt4:operator>
            <lt5:destination><lt4:location><lt4:locationName>Oxford</lt4:locationName></lt4:location></lt5:destination>
          </lt7:service>
          <lt7:service>
            <lt4:etd>On time</lt4:etd>
            <lt4:operator>GWR</lt4:operator>
            <lt5:destination><lt4:location><lt4:locationName>Bristol</lt4:locationName></lt4:location></lt5:destination>
          </lt7:service>
        </lt7:trainServices>
      </GetStationBoardResult>
    </GetDepBoardWithDetailsResponse>
  </soap:Body>
</soap:Envelope>"""

    def test_valid_service_returned_when_sibling_is_malformed(self):
        """One service missing lt4:std should be skipped; the valid service is returned."""
        deps, station = trains.ProcessDepartures(_JOURNEY_CONFIG, self._TWO_SERVICE_XML)
        assert deps is not None
        assert len(deps) == 1
        assert deps[0]["destination_name"] == "Oxford"

    def test_malformed_service_does_not_raise(self):
        """Processing a batch with one malformed service must not raise."""
        try:
            trains.ProcessDepartures(_JOURNEY_CONFIG, self._TWO_SERVICE_XML)
        except Exception as exc:
            pytest.fail(f"ProcessDepartures raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestRemoveBrackets:
    def test_removes_bracket_suffix(self):
        assert trains.removeBrackets("Reading (Berks)") == "Reading"

    def test_no_brackets_unchanged(self):
        assert trains.removeBrackets("Oxford") == "Oxford"


class TestIsTime:
    def test_valid_time(self):
        assert trains.isTime("08:45") is True

    def test_invalid(self):
        assert trains.isTime("On time") is False


class TestBackoffDelay:
    def test_first_failure(self):
        assert trains.backoff_delay(1) == 2.0

    def test_second_failure(self):
        assert trains.backoff_delay(2) == 4.0

    def test_caps_at_120(self):
        assert trains.backoff_delay(100) == 120.0


class TestPrepareServiceMessage:
    def test_a_service(self):
        assert trains.prepareServiceMessage("GWR") == "A GWR Service"

    def test_an_service_elizabeth(self):
        assert trains.prepareServiceMessage("Elizabeth Line") == "An Elizabeth Line Service"


class TestArrivalOrderMidnight:
    """T-04: ArrivalOrder midnight-crossover sorting."""

    def _make_service(self, std: str) -> dict:
        return {"lt4:std": std}

    def test_midnight_crossover_00_sorts_after_23(self):
        """00:15 departure must sort after 23:45 departure."""
        services = [self._make_service("00:15"), self._make_service("23:45")]
        result = trains.ArrivalOrder(services)
        assert result[0]["lt4:std"] == "23:45"
        assert result[1]["lt4:std"] == "00:15"

    def test_01_sorts_after_23(self):
        services = [self._make_service("01:00"), self._make_service("22:30")]
        result = trains.ArrivalOrder(services)
        assert result[0]["lt4:std"] == "22:30"
        assert result[1]["lt4:std"] == "01:00"

    def test_normal_order_preserved(self):
        services = [self._make_service("10:30"), self._make_service("08:00")]
        result = trains.ArrivalOrder(services)
        assert result[0]["lt4:std"] == "08:00"
        assert result[1]["lt4:std"] == "10:30"

    def test_02_treated_as_daytime(self):
        """02:00 is the boundary — should NOT be shifted (STDHour < 2 is False for 2)."""
        services = [self._make_service("02:00"), self._make_service("01:00")]
        result = trains.ArrivalOrder(services)
        # 01:00 gets +24 → sorts after 02:00
        assert result[0]["lt4:std"] == "02:00"
        assert result[1]["lt4:std"] == "01:00"


class TestPrepareLocationNameFallback:
    """T-06: prepareLocationName handles missing et/at gracefully (C-04 fix)."""

    def test_uses_et_when_present(self):
        location = {"lt7:locationName": "Reading", "lt7:st": "10:00", "lt7:et": "10:05"}
        result = trains.prepareLocationName(location, show_departure_time=True)
        assert "10:05" in result
        assert "Reading" in result

    def test_falls_back_to_at_when_no_et(self):
        location = {"lt7:locationName": "Didcot", "lt7:st": "10:20", "lt7:at": "10:22"}
        result = trains.prepareLocationName(location, show_departure_time=True)
        assert "10:22" in result

    def test_falls_back_to_st_when_neither_et_nor_at(self):
        """C-04: neither et nor at present — must not raise KeyError."""
        location = {"lt7:locationName": "Oxford", "lt7:st": "10:40"}
        result = trains.prepareLocationName(location, show_departure_time=True)
        assert "10:40" in result
        assert "Oxford" in result

    def test_no_time_when_show_departure_time_false(self):
        location = {"lt7:locationName": "Bath Spa", "lt7:st": "11:00", "lt7:et": "On time"}
        result = trains.prepareLocationName(location, show_departure_time=False)
        assert result == "Bath Spa"
        assert "11:00" not in result


class TestMultiDestination:
    """T-02: split-train multi-destination parsing."""

    _MULTI_DEST_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepBoardWithDetailsResponse>
      <GetStationBoardResult>
        <lt4:locationName>London Paddington</lt4:locationName>
        <lt7:trainServices>
          <lt7:service>
            <lt4:std>09:00</lt4:std>
            <lt4:etd>On time</lt4:etd>
            <lt4:operator>GWR</lt4:operator>
            <lt5:destination>
              <lt4:location><lt4:locationName>Penzance</lt4:locationName></lt4:location>
              <lt4:location><lt4:locationName>Plymouth</lt4:locationName></lt4:location>
            </lt5:destination>
          </lt7:service>
        </lt7:trainServices>
      </GetStationBoardResult>
    </GetDepBoardWithDetailsResponse>
  </soap:Body>
</soap:Envelope>"""

    def test_multi_destination_joined_with_ampersand(self):
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, self._MULTI_DEST_XML)
        assert deps is not None
        assert "Penzance" in deps[0]["destination_name"]
        assert "Plymouth" in deps[0]["destination_name"]
        assert "&" in deps[0]["destination_name"]


class TestMultiSectionCallingPoints:
    """T-03: split-train multi-section calling-point parsing."""

    _SPLIT_TRAIN_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepBoardWithDetailsResponse>
      <GetStationBoardResult>
        <lt4:locationName>London Paddington</lt4:locationName>
        <lt7:trainServices>
          <lt7:service>
            <lt4:std>09:00</lt4:std>
            <lt4:etd>On time</lt4:etd>
            <lt4:operator>GWR</lt4:operator>
            <lt5:destination>
              <lt4:location><lt4:locationName>Penzance</lt4:locationName></lt4:location>
            </lt5:destination>
            <lt7:subsequentCallingPoints>
              <lt7:callingPointList>
                <lt7:callingPoint>
                  <lt7:locationName>Reading</lt7:locationName>
                  <lt7:st>09:25</lt7:st>
                  <lt7:et>On time</lt7:et>
                </lt7:callingPoint>
              </lt7:callingPointList>
              <lt7:callingPointList>
                <lt7:callingPoint>
                  <lt7:locationName>Plymouth</lt7:locationName>
                  <lt7:st>11:30</lt7:st>
                  <lt7:et>On time</lt7:et>
                </lt7:callingPoint>
              </lt7:callingPointList>
            </lt7:subsequentCallingPoints>
          </lt7:service>
        </lt7:trainServices>
      </GetStationBoardResult>
    </GetDepBoardWithDetailsResponse>
  </soap:Body>
</soap:Envelope>"""

    def test_split_calling_points_contain_both_portions(self):
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, self._SPLIT_TRAIN_XML)
        assert deps is not None
        calling = deps[0]["calling_at_list"]
        assert "Reading" in calling
        assert "Plymouth" in calling

    def test_split_calling_points_contain_portion_separator(self):
        deps, _ = trains.ProcessDepartures(_JOURNEY_CONFIG, self._SPLIT_TRAIN_XML)
        calling = deps[0]["calling_at_list"]
        assert "with a portion going to" in calling
