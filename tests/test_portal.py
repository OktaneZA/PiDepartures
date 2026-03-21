"""Tests for src/portal.py — web configuration portal."""

import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from portal import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(portal_state=None):
    """Create a test Flask app."""
    if portal_state is None:
        portal_state = {"station_name": "London Paddington", "departures": [], "error_count": 0}
    app = create_app(portal_state, threading.Lock(), threading.Event())
    app.config["TESTING"] = True
    return app


def _local(client, method, path, **kwargs):
    """Make a request from localhost."""
    return getattr(client, method)(path, environ_base={"REMOTE_ADDR": "127.0.0.1"}, **kwargs)


def _remote(client, method, path, **kwargs):
    """Make a request from a remote IP."""
    return getattr(client, method)(path, environ_base={"REMOTE_ADDR": "192.168.1.50"}, **kwargs)


_HASHED_PW = "pbkdf2:sha256:260000:aabbccdd:AAAA"
_NO_PW = {"PORTAL_PASSWORD": ""}
_WITH_PW = {"PORTAL_PASSWORD": _HASHED_PW}

_BASIC_ADMIN = {"Authorization": "Basic YWRtaW46cGFzcw=="}  # admin:pass


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    def test_local_ipv4_no_password_allowed(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            with _make_app().test_client() as c:
                assert _local(c, "get", "/").status_code == 200

    def test_local_ipv6_no_password_allowed(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            app = _make_app()
            with app.test_client() as c:
                resp = c.get("/", environ_base={"REMOTE_ADDR": "::1"})
                assert resp.status_code == 200

    def test_remote_no_password_blocked_403(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            with _make_app().test_client() as c:
                assert _remote(c, "get", "/").status_code == 403

    def test_remote_correct_password_allowed(self):
        with patch("config.load_raw_config", return_value=_WITH_PW):
            with patch("config.verify_password", return_value=True):
                with _make_app().test_client() as c:
                    resp = _remote(c, "get", "/", headers=_BASIC_ADMIN)
                    assert resp.status_code == 200

    def test_remote_wrong_password_returns_401(self):
        with patch("config.load_raw_config", return_value=_WITH_PW):
            with patch("config.verify_password", return_value=False):
                with _make_app().test_client() as c:
                    resp = _remote(c, "get", "/", headers=_BASIC_ADMIN)
                    assert resp.status_code == 401

    def test_remote_no_credentials_returns_401(self):
        with patch("config.load_raw_config", return_value=_WITH_PW):
            with _make_app().test_client() as c:
                resp = _remote(c, "get", "/")
                assert resp.status_code == 401

    def test_www_authenticate_header_present_on_401(self):
        with patch("config.load_raw_config", return_value=_WITH_PW):
            with _make_app().test_client() as c:
                resp = _remote(c, "get", "/")
                assert "WWW-Authenticate" in resp.headers

    def test_health_no_auth_required(self):
        """Health endpoint accessible without auth from any origin."""
        with _make_app().test_client() as c:
            resp = _remote(c, "get", "/health")
            assert resp.status_code == 200
            assert resp.get_json()["ok"] is True

    def test_config_load_failure_falls_back_to_local_only(self):
        """If config cannot be read, fail closed — local-only, no fallback password."""
        with patch("config.load_raw_config", side_effect=OSError("disk error")):
            with _make_app().test_client() as c:
                assert _local(c, "get", "/").status_code == 200
                assert _remote(c, "get", "/").status_code == 403


# ---------------------------------------------------------------------------
# /status endpoint
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_returns_portal_state_json(self):
        state = {"station_name": "Paddington", "departures": [{"aimed_departure_time": "12:00"}], "error_count": 2}
        with patch("config.load_raw_config", return_value=_NO_PW):
            with _make_app(portal_state=state).test_client() as c:
                resp = _local(c, "get", "/status")
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["station_name"] == "Paddington"
                assert data["error_count"] == 2
                assert len(data["departures"]) == 1

    def test_status_requires_auth_from_remote(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            with _make_app().test_client() as c:
                assert _remote(c, "get", "/status").status_code == 403


# ---------------------------------------------------------------------------
# /sysinfo endpoint
# ---------------------------------------------------------------------------

class TestSysinfo:
    def test_sysinfo_returns_json_schema(self):
        """Endpoint always returns JSON with ssid and signal_dbm keys."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("builtins.open", side_effect=OSError):
                with _make_app().test_client() as c:
                    resp = c.get("/sysinfo")
                    assert resp.status_code == 200
                    data = resp.get_json()
                    assert "ssid" in data
                    assert "signal_dbm" in data

    def test_sysinfo_null_when_subprocess_unavailable(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("builtins.open", side_effect=OSError):
                with _make_app().test_client() as c:
                    data = c.get("/sysinfo").get_json()
                    assert data["ssid"] is None
                    assert data["signal_dbm"] is None

    def test_sysinfo_parses_ssid_from_iwgetid(self):
        mock_result = MagicMock()
        mock_result.stdout = "HomeNetwork\n"
        with patch("subprocess.run", return_value=mock_result):
            with patch("builtins.open", side_effect=OSError):
                with _make_app().test_client() as c:
                    data = c.get("/sysinfo").get_json()
                    assert data["ssid"] == "HomeNetwork"

    def test_sysinfo_empty_ssid_returns_none(self):
        mock_result = MagicMock()
        mock_result.stdout = "  \n"
        with patch("subprocess.run", return_value=mock_result):
            with patch("builtins.open", side_effect=OSError):
                with _make_app().test_client() as c:
                    data = c.get("/sysinfo").get_json()
                    assert data["ssid"] is None

    def test_sysinfo_no_auth_required(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("builtins.open", side_effect=OSError):
                with _make_app().test_client() as c:
                    resp = _remote(c, "get", "/sysinfo")
                    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /save endpoint
# ---------------------------------------------------------------------------

def _base_form(**overrides):
    form = {
        "DEPARTURE_STATION": "PAD",
        "DESTINATION_STATION": "",
        "PLATFORM_FILTER": "",
        "SCREEN_BLANK_HOURS": "",
        "REFRESH_TIME": "120",
        "SCREEN_ROTATION": "2",
        "PORTAL_PORT": "8080",
        "API_KEY": "••••••••",
        "PORTAL_PASSWORD": "",
    }
    form.update(overrides)
    return form


class TestSave:
    def test_save_preserves_api_key_when_masked(self):
        """Submitting the mask must not overwrite the stored API_KEY."""
        saved = {}
        with patch("config.load_raw_config", return_value={"API_KEY": "real-key", "PORTAL_PASSWORD": ""}):
            with patch("config.save_raw_config", side_effect=lambda d, **_: saved.update(d)):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form())
        assert saved["API_KEY"] == "real-key"

    def test_save_updates_api_key_when_new_value_entered(self):
        saved = {}
        with patch("config.load_raw_config", return_value={"API_KEY": "old-key", "PORTAL_PASSWORD": ""}):
            with patch("config.save_raw_config", side_effect=lambda d, **_: saved.update(d)):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form(API_KEY="new-key-xyz"))
        assert saved["API_KEY"] == "new-key-xyz"

    def test_save_hashes_new_password(self):
        saved = {}
        with patch("config.load_raw_config", return_value=_NO_PW):
            with patch("config.save_raw_config", side_effect=lambda d, **_: saved.update(d)):
                with patch("config.validate_portal_config", return_value=[]):
                    with patch("config.hash_password", return_value=_HASHED_PW) as mock_hash:
                        with _make_app().test_client() as c:
                            _local(c, "post", "/save", data=_base_form(PORTAL_PASSWORD="mysecret"))
        mock_hash.assert_called_once_with("mysecret")
        assert saved["PORTAL_PASSWORD"] == _HASHED_PW

    def test_save_clears_password_when_blank(self):
        """Empty password field should store empty string (local-only mode)."""
        saved = {}
        def capture(data, path=None): saved.update(data)
        # First call: auth check (no password → local access allowed)
        # Second call: save() reads existing config (has a password stored)
        with patch("config.load_raw_config", side_effect=[_NO_PW, {"PORTAL_PASSWORD": _HASHED_PW}]):
            with patch("config.save_raw_config", side_effect=capture):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form(PORTAL_PASSWORD=""))
        assert saved.get("PORTAL_PASSWORD") == ""

    def test_save_does_not_change_password_when_mask_submitted(self):
        """Submitting the mask character should preserve the existing hash."""
        saved = {}
        def capture(data, path=None): saved.update(data)
        with patch("config.load_raw_config", side_effect=[_NO_PW, {"PORTAL_PASSWORD": _HASHED_PW}]):
            with patch("config.save_raw_config", side_effect=capture):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form(PORTAL_PASSWORD="••••••••"))
        assert saved.get("PORTAL_PASSWORD") == _HASHED_PW

    def test_save_sets_restart_event_on_success(self):
        state = {"station_name": "", "departures": [], "error_count": 0}
        lock = threading.Lock()
        restart = threading.Event()
        app = create_app(state, lock, restart)
        app.config["TESTING"] = True
        with patch("config.load_raw_config", return_value=_NO_PW):
            with patch("config.save_raw_config"):
                with patch("config.validate_portal_config", return_value=[]):
                    with app.test_client() as c:
                        _local(c, "post", "/save", data=_base_form())
        assert restart.is_set()

    def test_save_validation_error_redirects_without_saving(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            with patch("config.validate_portal_config", return_value=["DEPARTURE_STATION is required"]):
                with patch("config.save_raw_config") as mock_save:
                    with _make_app().test_client() as c:
                        resp = _local(c, "post", "/save", data=_base_form(DEPARTURE_STATION=""))
        assert resp.status_code in (302, 303)
        mock_save.assert_not_called()

    def test_save_optional_destination_removed_when_blank(self):
        saved = {}
        with patch("config.load_raw_config", return_value={"DESTINATION_STATION": "EUS", "PORTAL_PASSWORD": ""}):
            with patch("config.save_raw_config", side_effect=lambda d, **_: saved.update(d)):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form(DESTINATION_STATION=""))
        assert "DESTINATION_STATION" not in saved

    def test_save_optional_destination_written_when_set(self):
        saved = {}
        with patch("config.load_raw_config", return_value=_NO_PW):
            with patch("config.save_raw_config", side_effect=lambda d, **_: saved.update(d)):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        _local(c, "post", "/save", data=_base_form(DESTINATION_STATION="EUS"))
        assert saved["DESTINATION_STATION"] == "EUS"

    def test_save_permission_error_redirects_with_error_message(self):
        with patch("config.load_raw_config", return_value=_NO_PW):
            with patch("config.save_raw_config", side_effect=PermissionError("read-only")):
                with patch("config.validate_portal_config", return_value=[]):
                    with _make_app().test_client() as c:
                        resp = _local(c, "post", "/save", data=_base_form())
        assert resp.status_code in (302, 303)
        assert b"errors=" in resp.headers["Location"].encode() or "errors" in resp.headers.get("Location", "")
