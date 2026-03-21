"""Flask web config portal for train-display.

Serves a dark-themed configuration page on a configurable port (default 8080).
Auth behaviour (SEC-04):
  - Empty PORTAL_PASSWORD: localhost (127.0.0.1 / ::1) allowed without credentials;
    all other origins receive HTTP 403.
  - Non-empty PORTAL_PASSWORD: HTTP Basic Auth required from all origins; password
    verified via PBKDF2-HMAC-SHA256 (verify_password from config module).

API_KEY is masked in the UI and only replaced if a new value is entered. (SEC-01)
"""

import functools
import logging
import threading
from typing import Any

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

import config as cfg_module

logger = logging.getLogger(__name__)

_MASK = "••••••••"


def create_app(
    portal_state: dict[str, Any],
    state_lock: threading.Lock,
    restart_event: threading.Event,
) -> Flask:
    """Create and return the Flask portal app.

    Args:
        portal_state: Shared dict updated by the fetch thread with current departures.
        state_lock: Lock protecting *portal_state*.
        restart_event: Set this to trigger a service restart after config save.
    """
    app = Flask(__name__, template_folder="templates")
    app.secret_key = "train-display-portal"  # sessions not used for auth — no security impact

    # ---------------------------------------------------------------------- #
    # Auth decorator                                                          #
    # ---------------------------------------------------------------------- #

    def _get_portal_password() -> str:
        try:
            return cfg_module.load_raw_config().get("PORTAL_PASSWORD", "")
        except Exception:  # noqa: BLE001
            return ""

    def require_auth(f):  # type: ignore[no-untyped-def]
        @functools.wraps(f)
        def decorated(*args, **kwargs):  # type: ignore[no-untyped-def]
            portal_password = _get_portal_password()

            if not portal_password:
                # SEC-04: no password set — local access only
                if request.remote_addr in ("127.0.0.1", "::1"):
                    return f(*args, **kwargs)
                return Response(
                    "Remote access requires a portal password to be configured.",
                    403,
                )

            # Password is set — require HTTP Basic Auth (SEC-04)
            auth = request.authorization
            if not auth or auth.username != "admin" or not cfg_module.verify_password(
                auth.password or "", portal_password
            ):
                return Response(
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="TrainDisplay"'},
                )
            return f(*args, **kwargs)
        return decorated

    # ---------------------------------------------------------------------- #
    # Routes                                                                  #
    # ---------------------------------------------------------------------- #

    @app.route("/", methods=["GET"])
    @require_auth
    def index() -> str:
        """Show configuration form."""
        try:
            raw = cfg_module.load_raw_config()
        except FileNotFoundError:
            raw = {}

        # Mask API_KEY for display (SEC-01)
        masked = dict(raw)
        if masked.get("API_KEY"):
            masked["API_KEY"] = _MASK

        errors = request.args.get("errors", "")
        saved = request.args.get("saved", "")
        return render_template("index.html", cfg=masked, errors=errors, saved=saved)

    @app.route("/save", methods=["POST"])
    @require_auth
    def save() -> Response:
        """Validate and write config, then trigger service restart."""
        try:
            raw = cfg_module.load_raw_config()
        except FileNotFoundError:
            raw = {}

        form = request.form
        new_cfg: dict[str, Any] = dict(raw)

        # Journey / API settings
        new_cfg["DEPARTURE_STATION"] = form.get("DEPARTURE_STATION", "").strip().upper()
        dest = form.get("DESTINATION_STATION", "").strip().upper()
        if dest:
            new_cfg["DESTINATION_STATION"] = dest
        else:
            new_cfg.pop("DESTINATION_STATION", None)

        platform = form.get("PLATFORM_FILTER", "").strip()
        if platform:
            new_cfg["PLATFORM_FILTER"] = platform
        else:
            new_cfg.pop("PLATFORM_FILTER", None)

        # Display settings
        new_cfg["REFRESH_TIME"] = form.get("REFRESH_TIME", "120").strip()
        new_cfg["SCREEN_ROTATION"] = form.get("SCREEN_ROTATION", "2").strip()
        new_cfg["FIRST_DEPARTURE_BOLD"] = "true" if form.get("FIRST_DEPARTURE_BOLD") == "on" else "false"
        new_cfg["SHOW_DEPARTURE_NUMBERS"] = "true" if form.get("SHOW_DEPARTURE_NUMBERS") == "on" else "false"
        new_cfg["DUAL_SCREEN"] = "true" if form.get("DUAL_SCREEN") == "on" else "false"

        blank_hours = form.get("SCREEN_BLANK_HOURS", "").strip()
        if blank_hours:
            new_cfg["SCREEN_BLANK_HOURS"] = blank_hours
        else:
            new_cfg.pop("SCREEN_BLANK_HOURS", None)

        # Portal settings
        new_cfg["PORTAL_PORT"] = form.get("PORTAL_PORT", "8080").strip()

        # API_KEY: only update if a new value was provided (not the mask) — SEC-01
        api_key = form.get("API_KEY", "").strip()
        if api_key and api_key != _MASK:
            new_cfg["API_KEY"] = api_key

        # Portal password: hash if changed, clear if explicitly blanked — SEC-01, SEC-08
        new_pw = form.get("PORTAL_PASSWORD", "").strip()
        if new_pw and new_pw != _MASK:
            new_cfg["PORTAL_PASSWORD"] = cfg_module.hash_password(new_pw)
        elif not new_pw:
            new_cfg["PORTAL_PASSWORD"] = ""  # cleared = local-only mode

        errors = cfg_module.validate_portal_config(new_cfg)
        if errors:
            return redirect(url_for("index", errors=" | ".join(errors)))

        try:
            cfg_module.save_raw_config(new_cfg)
        except (PermissionError, OSError) as exc:
            return redirect(url_for("index", errors=f"Could not save config: {exc}"))

        logger.info("Config saved via portal; triggering service restart")
        restart_event.set()
        return redirect(url_for("index", saved="1"))

    @app.route("/status", methods=["GET"])
    @require_auth
    def status() -> Response:
        """Return current departure state as JSON."""
        with state_lock:
            state_copy = dict(portal_state)
        return jsonify(state_copy)

    @app.route("/health", methods=["GET"])
    def health() -> Response:
        """Liveness check — no auth required."""
        return jsonify({"ok": True})

    return app
