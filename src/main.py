"""Train Departure Display — entry point.

Based on https://github.com/chrisys/train-departure-display
Adapted for native systemd deployment:
  - logging module throughout (no print in production paths)
  - Background fetch thread + render thread separated (ARCH-07)
  - threading.Lock protects shared departure state (ARCH-07)
  - SIGTERM / SIGINT handled gracefully via threading.Event (ARCH-08)
  - Exponential back-off on API failures (ARCH-01)
  - Display shows stale data + "No signal" indicator on failure (ARCH-02)
  - After 3 consecutive failures shows connectivity warning screen (ARCH-03)
  - Viewport rebuilt only on data change, not every frame (P-05)
  - OrderedDict LRU cache for O(1) eviction (P-02)

Requirements: ARCH-01–ARCH-10, SEC-01–SEC-11, DISP-01–DISP-08
"""

import logging
import os
import re
import signal
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont

from config import load_config
from hours import isRun
from trains import loadDeparturesForStation, backoff_delay

# ---------------------------------------------------------------------------
# Logging setup — before any imports that might log
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "").upper() == "TRUE" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state (protected by _lock) — ARCH-07
# Render thread reads; fetch thread writes.
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_departures = None          # list of departure dicts, or None
_station_name = ""          # resolved station name
_fetch_error_count = 0      # consecutive failure counter
_display_epoch = 0          # incremented by fetch thread on every state change;
                            # render thread uses this to detect when to rebuild viewport
_shutdown_event = threading.Event()  # ARCH-08

# ---------------------------------------------------------------------------
# Bitmap render cache — bounded LRU via OrderedDict for O(1) eviction (ARCH-09, P-02)
# ---------------------------------------------------------------------------
_BITMAP_CACHE_MAX = 256
_bitmapCache: OrderedDict = OrderedDict()


def _cachedBitmapText(text: str, font: ImageFont.FreeTypeFont) -> tuple:
    """Return (width, height, bitmap-Image) for text, using an LRU cache (ARCH-09).

    Uses OrderedDict for O(1) move-to-end and eviction instead of O(n) list scan.
    """
    key = text + "".join(font.getname())
    if key in _bitmapCache:
        _bitmapCache.move_to_end(key)  # O(1)
        entry = _bitmapCache[key]
        return entry["w"], entry["h"], entry["bmp"]

    _, _, w, h = font.getbbox(text)
    bmp = Image.new("L", [w, h], color=0)
    ImageDraw.Draw(bmp).text((0, 0), text=text, font=font, fill=255)

    if len(_bitmapCache) >= _BITMAP_CACHE_MAX:
        _bitmapCache.popitem(last=False)  # evict LRU entry — O(1)

    _bitmapCache[key] = {"bmp": bmp, "w": w, "h": h}
    return w, h, bmp


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def makeFont(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font from the fonts/ directory relative to this file."""
    font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fonts", name))
    return ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.BASIC)


# ---------------------------------------------------------------------------
# Scroll state (per screen) — DISP-03
# ---------------------------------------------------------------------------
class ScrollState:
    """Tracks horizontal/vertical scroll position for the calling-points row."""

    def __init__(self):
        self.pixelsLeft = 1
        self.pixelsUp = 0
        self.hasElevated = 0
        self.pauseCount = 0


_scrollStates: dict = {}

# ---------------------------------------------------------------------------
# Render functions (closures returned to luma snapshot callbacks)
# ---------------------------------------------------------------------------

def renderDestination(departure: dict, font: ImageFont.FreeTypeFont, pos: str, config: dict):
    """Return a draw callback that renders departure time + destination."""
    def drawText(draw, *_):
        aimed = departure["aimed_departure_time"]
        dest = departure["destination_name"]
        train = f"{pos}  {aimed}  {dest}" if config["showDepartureNumbers"] else f"{aimed}  {dest}"
        _, _, bitmap = _cachedBitmapText(train, font)
        draw.bitmap((0, 0), bitmap, fill="yellow")
    return drawText


def renderServiceStatus(departure: dict, font: ImageFont.FreeTypeFont):
    """Return a draw callback that renders expected/actual departure status."""
    def drawText(draw, width, *_):
        exp = departure["expected_departure_time"]
        if exp == "On time":
            label = "On time"
        elif exp == "Cancelled":
            label = "Cancelled"
        elif exp == "Delayed":
            label = "Delayed"
        elif isinstance(exp, str):
            label = "On time" if departure["aimed_departure_time"] == exp else "Exp " + exp
        else:
            label = ""
        w, _, bitmap = _cachedBitmapText(label, font)
        draw.bitmap((width - w, 0), bitmap, fill="yellow")
    return drawText


def renderPlatform(departure: dict, font: ImageFont.FreeTypeFont):
    """Return a draw callback that renders platform number."""
    def drawText(draw, *_):
        if "platform" in departure:
            plat = departure["platform"]
            label = "BUS" if plat.lower() == "bus" else "Plat " + plat
            _, _, bitmap = _cachedBitmapText(label, font)
            draw.bitmap((0, 0), bitmap, fill="yellow")
    return drawText


def renderCallingAt(font: ImageFont.FreeTypeFont):
    """Return a draw callback that renders 'Calling at:' label."""
    def drawText(draw, *_):
        _, _, bitmap = _cachedBitmapText("Calling at: ", font)
        draw.bitmap((0, 0), bitmap, fill="yellow")
    return drawText


def renderStations(stations: str, font: ImageFont.FreeTypeFont, screen_id: str = "default"):
    """Return a draw callback that scrolls calling-point text (DISP-03)."""
    def drawText(draw, *_):
        if screen_id not in _scrollStates:
            _scrollStates[screen_id] = ScrollState()
        state = _scrollStates[screen_id]

        txt_width, txt_height, bitmap = _cachedBitmapText(stations, font)

        if state.hasElevated:
            draw.bitmap((state.pixelsLeft - 1, 0), bitmap, fill="yellow")
            if -state.pixelsLeft > txt_width and state.pauseCount < 8:
                state.pauseCount += 1
                state.pixelsLeft = 0
                state.hasElevated = 0
            else:
                state.pauseCount = 0
                state.pixelsLeft -= 1
        else:
            draw.bitmap((0, txt_height - state.pixelsUp), bitmap, fill="yellow")
            if state.pixelsUp == txt_height:
                state.pauseCount += 1
                if state.pauseCount > 20:
                    state.hasElevated = 1
                    state.pixelsUp = 0
            else:
                state.pixelsUp += 1
    return drawText


def renderTime(font_hm: ImageFont.FreeTypeFont, font_s: ImageFont.FreeTypeFont,
               font_date: ImageFont.FreeTypeFont):
    """Return a draw callback that renders time then date, centred as a group (DISP-09)."""
    def drawText(draw, width, *_):
        now = datetime.now()
        rawTime = now.time()
        hour, minute, second = str(rawTime).split(".")[0].split(":")
        w1, clock_h, HMBitmap = _cachedBitmapText(f"{hour}:{minute}", font_hm)
        w2, _, _ = _cachedBitmapText(":00", font_s)
        _, _, SBitmap = _cachedBitmapText(f":{second}", font_s)
        date_str = _ordinal_date(now)
        w_date, date_h, DateBitmap = _cachedBitmapText(date_str, font_date)
        gap = 6  # pixels between time and date
        total_w = w1 + w2 + gap + w_date
        x = int((width - total_w) / 2)
        draw.bitmap((x, 0), HMBitmap, fill="yellow")
        draw.bitmap((x + w1, 5), SBitmap, fill="yellow")
        date_y = (clock_h - date_h) // 2
        draw.bitmap((x + w1 + w2 + gap, date_y), DateBitmap, fill="yellow")
    return drawText


def renderNoSignal(font: ImageFont.FreeTypeFont, error_count: int):
    """Return a draw callback showing a 'No signal' indicator (ARCH-02)."""
    def drawText(draw, width, *_):
        msg = f"No signal ({error_count}x)"
        w, _, bitmap = _cachedBitmapText(msg, font)
        draw.bitmap((width - w, 0), bitmap, fill="yellow")
    return drawText


def renderWelcomeTo(font: ImageFont.FreeTypeFont, xOffset: float):
    """Return a draw callback rendering 'Welcome to'."""
    def drawText(draw, *_):
        draw.text((int(xOffset), 0), text="Welcome to", font=font, fill="yellow")
    return drawText


def renderDepartureStation(station: str, font: ImageFont.FreeTypeFont, xOffset: float):
    """Return a draw callback rendering the station name."""
    def drawText(draw, *_):
        draw.text((int(xOffset), 0), text=station, font=font, fill="yellow")
    return drawText


def renderDots(font: ImageFont.FreeTypeFont):
    """Return a draw callback rendering animated dots."""
    def drawText(draw, *_):
        draw.text((0, 0), text=".  .  .", font=font, fill="yellow")
    return drawText


def renderPoweredBy(font: ImageFont.FreeTypeFont, xOffset: float):
    """Return a draw callback rendering 'Powered by'."""
    def drawText(draw, *_):
        draw.text((int(xOffset), 0), text="Powered by", font=font, fill="yellow")
    return drawText


def renderNRE(font: ImageFont.FreeTypeFont, xOffset: float):
    """Return a draw callback rendering 'National Rail Enquiries'."""
    def drawText(draw, *_):
        draw.text((int(xOffset), 0), text="National Rail Enquiries", font=font, fill="yellow")
    return drawText


def renderName(font: ImageFont.FreeTypeFont, xOffset: float):
    """Return a draw callback rendering the project name."""
    def drawText(draw, *_):
        draw.text((int(xOffset), 0), text="UK Train Departure Display", font=font, fill="yellow")
    return drawText


def renderConnectivityWarning(font: ImageFont.FreeTypeFont, error_count: int):
    """Return a draw callback rendering the connectivity warning message (ARCH-03)."""
    def drawText(draw, *_):
        draw.text((0, 0), text=f"No network ({error_count} attempts)", font=font, fill="yellow")
    return drawText


# ---------------------------------------------------------------------------
# Screen drawing helpers — construct luma viewport + snapshots
# ---------------------------------------------------------------------------

def drawStartup(device, fonts: dict, width: int, height: int):
    """Draw the NRE attribution/loading screen (DISP-06)."""
    from luma.core.render import canvas
    from luma.core.virtual import viewport, snapshot

    fontBold = fonts["bold"]

    virtualViewport = viewport(device, width=width, height=height)

    nameSize = int(fontBold.getlength("UK Train Departure Display"))
    poweredSize = int(fontBold.getlength("Powered by"))
    NRESize = int(fontBold.getlength("National Rail Enquiries"))

    with canvas(device):
        rowOne = snapshot(width, 10, renderName(fontBold, (width - nameSize) / 2), interval=60)
        rowThree = snapshot(width, 10, renderPoweredBy(fontBold, (width - poweredSize) / 2), interval=60)
        rowFour = snapshot(width, 10, renderNRE(fontBold, (width - NRESize) / 2), interval=60)

        for hotspot, xy in list(virtualViewport._hotspots):
            virtualViewport.remove_hotspot(hotspot, xy)

        virtualViewport.add_hotspot(rowOne, (0, 0))
        virtualViewport.add_hotspot(rowThree, (0, 24))
        virtualViewport.add_hotspot(rowFour, (0, 36))

    return virtualViewport


def drawBlankSignage(device, fonts: dict, width: int, height: int,
                     departureStation: str, config: dict):
    """Draw welcome/loading screen when no departures are available (BOOT-03, ARCH-04)."""
    from luma.core.virtual import viewport, snapshot

    fontBold = fonts["bold"]
    fontBoldLarge = fonts["bold_large"]
    fontBoldTall = fonts["bold_tall"]
    refresh = config["refreshTime"]

    welcomeSize = int(fontBold.getlength("Welcome to"))
    stationSize = int(fontBold.getlength(departureStation))

    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo(fontBold, (width - welcomeSize) / 2), interval=refresh)
    rowTwo = snapshot(width, 10,
                      renderDepartureStation(departureStation, fontBold, (width - stationSize) / 2),
                      interval=refresh)
    rowThree = snapshot(width, 10, renderDots(fontBold), interval=refresh)
    rowTime = snapshot(width, 14, renderTime(fontBoldLarge, fontBoldTall, fonts["regular"]), interval=0.1)

    for hotspot, xy in list(virtualViewport._hotspots):
        virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport


def drawConnectivityWarning(device, fonts: dict, width: int, height: int,
                            departureStation: str, error_count: int, config: dict):
    """Draw dedicated connectivity warning screen after 3+ consecutive failures (ARCH-03)."""
    from luma.core.virtual import viewport, snapshot

    font = fonts["regular"]
    fontBold = fonts["bold"]
    fontBoldLarge = fonts["bold_large"]
    fontBoldTall = fonts["bold_tall"]
    refresh = config["refreshTime"]

    stationSize = int(fontBold.getlength(departureStation))

    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

    rowStation = snapshot(width, 10,
                          renderDepartureStation(departureStation, fontBold, (width - stationSize) / 2),
                          interval=refresh)
    rowWarning = snapshot(width, 10, renderConnectivityWarning(font, error_count), interval=5)
    rowTime = snapshot(width, 14, renderTime(fontBoldLarge, fontBoldTall, fonts["regular"]), interval=0.1)

    for hotspot, xy in list(virtualViewport._hotspots):
        virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowStation, (0, 0))
    virtualViewport.add_hotspot(rowWarning, (0, 16))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport


def platform_filter(departureData: list, platform_regex: str, station: str):
    """Filter departures by platform regex (INST-10: PLATFORM_FILTER is a regex).

    Args:
        departureData: Full list of departure dicts.
        platform_regex: Regex string to match against platform field, or '' for all.
        station: Station name for return tuple.

    Returns:
        Tuple of (filtered-departures, first-calling-at-list, station).
    """
    if not platform_regex:
        filtered = departureData
    else:
        pattern = re.compile(platform_regex)
        filtered = [d for d in departureData if pattern.search(d.get("platform", ""))]

    if filtered:
        return filtered, filtered[0].get("calling_at_list", ""), station
    return [], "", station


def drawSignage(device, fonts: dict, width: int, height: int, data: tuple,
                config: dict, screen_id: str, err_count: int = 0):
    """Draw the main departure board.

    Args:
        device: luma OLED device.
        fonts: Dict of font objects.
        width: Viewport width (256).
        height: Viewport height (64).
        data: Tuple of (departures, firstDepartureCallingAt, stationName).
        config: Config dict.
        screen_id: Unique identifier for scroll state ('screen1', 'screen2').
        err_count: Current consecutive fetch error count for ARCH-02 overlay.

    Returns:
        Configured luma viewport.
    """
    from luma.core.virtual import viewport, snapshot

    font = fonts["regular"]
    fontBold = fonts["bold"]
    fontBoldLarge = fonts["bold_large"]
    fontBoldTall = fonts["bold_tall"]
    refresh = config["refreshTime"]

    departures, firstDepartureDestinations, departureStation = data

    if not departures:
        return drawBlankSignage(device, fonts, width, height, departureStation, config)

    virtualViewport = viewport(device, width=width, height=height)

    status_placeholder = "Exp 00:00"
    platform_placeholder = "Plat 888"
    callingAt_label = "Calling at: "

    w_status = int(font.getlength(status_placeholder))
    w_platform = int(font.getlength(platform_placeholder))
    w_calling = int(font.getlength(callingAt_label))
    vp_width = virtualViewport.width

    firstFont = fontBold if config["firstDepartureBold"] else font  # DISP-07

    rowOneA = snapshot(vp_width - w_status - w_platform - 5, 10,
                       renderDestination(departures[0], firstFont, "1st", config), interval=refresh)
    rowOneB = snapshot(w_status, 10, renderServiceStatus(departures[0], font), interval=10)
    rowOneC = snapshot(w_platform, 10, renderPlatform(departures[0], font), interval=refresh)
    rowTwoA = snapshot(w_calling, 10, renderCallingAt(font), interval=refresh)
    rowTwoB = snapshot(vp_width - w_calling, 10,
                       renderStations(firstDepartureDestinations, font, screen_id), interval=0.02)

    for hotspot, xy in list(virtualViewport._hotspots):
        virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOneA, (0, 0))
    virtualViewport.add_hotspot(rowOneB, (vp_width - w_status, 0))
    virtualViewport.add_hotspot(rowOneC, (vp_width - w_status - w_platform, 0))
    virtualViewport.add_hotspot(rowTwoA, (0, 12))
    virtualViewport.add_hotspot(rowTwoB, (w_calling, 12))

    if len(departures) > 1:
        rowThreeA = snapshot(vp_width - w_status - w_platform, 10,
                             renderDestination(departures[1], font, "2nd", config), interval=refresh)
        rowThreeB = snapshot(w_status, 10, renderServiceStatus(departures[1], font), interval=refresh)
        rowThreeC = snapshot(w_platform, 10, renderPlatform(departures[1], font), interval=refresh)
        virtualViewport.add_hotspot(rowThreeA, (0, 24))
        virtualViewport.add_hotspot(rowThreeB, (vp_width - w_status, 24))
        virtualViewport.add_hotspot(rowThreeC, (vp_width - w_status - w_platform, 24))

    if len(departures) > 2:
        rowFourA = snapshot(vp_width - w_status - w_platform, 10,
                            renderDestination(departures[2], font, "3rd", config), interval=10)
        rowFourB = snapshot(w_status, 10, renderServiceStatus(departures[2], font), interval=10)
        rowFourC = snapshot(w_platform, 10, renderPlatform(departures[2], font), interval=refresh)
        virtualViewport.add_hotspot(rowFourA, (0, 36))
        virtualViewport.add_hotspot(rowFourB, (vp_width - w_status, 36))
        virtualViewport.add_hotspot(rowFourC, (vp_width - w_status - w_platform, 36))

    rowTime = snapshot(vp_width, 14, renderTime(fontBoldLarge, fontBoldTall, fonts["regular"]), interval=0.1)
    virtualViewport.add_hotspot(rowTime, (0, 50))

    # ARCH-02: overlay "No signal" indicator when API is failing but stale data is displayed
    if err_count > 0:
        w_ns = int(font.getlength("No signal (99x)"))
        rowNoSignal = snapshot(w_ns, 10, renderNoSignal(font, err_count), interval=5)
        virtualViewport.add_hotspot(rowNoSignal, (0, 12))  # left side of calling-at row

    return virtualViewport


# ---------------------------------------------------------------------------
# Background fetch thread (ARCH-07)
# ---------------------------------------------------------------------------

def _fetch_thread(config: dict) -> None:
    """Background thread: poll the API and update shared departure state.

    Never writes to the display. Reads config but never writes it.
    Uses exponential back-off on consecutive failures (ARCH-01).
    ALL exceptions are caught to prevent the thread from dying silently (A-02).

    Args:
        config: Loaded config dict.
    """
    global _departures, _station_name, _fetch_error_count, _display_epoch

    journey = config["journey"]
    api = config["api"]
    rows = "10"
    attempt = 0

    while not _shutdown_event.is_set():
        attempt += 1
        try:
            departures, station_name = loadDeparturesForStation(journey, api["apiKey"], rows)
            with _lock:  # ARCH-07
                _departures = departures
                _station_name = station_name
                _fetch_error_count = 0
                _display_epoch += 1  # P-05: signal render thread to rebuild viewport
            logger.debug(
                "Fetch OK (attempt %d): %d departures for %s",
                attempt, len(departures or []), station_name,
            )
            attempt = 0  # reset on success

            # Wait for next poll interval, checking shutdown every second
            for _ in range(config["refreshTime"]):
                if _shutdown_event.is_set():
                    break
                time.sleep(1)

        except (requests.RequestException, ValueError) as exc:
            # A-02: expected failures — network errors and XML/parse errors
            with _lock:
                _fetch_error_count += 1
                err_count = _fetch_error_count
                _display_epoch += 1  # trigger viewport rebuild for ARCH-02/03 updates

            log_fn = logger.warning if isinstance(exc, requests.RequestException) else logger.error
            # ARCH-10: log station + attempt + error type — never the API key
            log_fn(
                "Fetch failed for %s (attempt %d, errors %d): %s — retry in %.0fs",
                journey.get("departureStation", "?"),
                attempt,
                err_count,
                type(exc).__name__,
                backoff_delay(err_count),
            )
            _shutdown_event.wait(timeout=backoff_delay(err_count))
        except Exception as exc:
            # A-02: unexpected failure — log full context and re-raise so the thread
            # exits visibly rather than looping silently on an unrecoverable error
            logger.error(
                "Unexpected error in fetch thread (attempt %d): %s",
                attempt, type(exc).__name__, exc_info=True,
            )
            raise


# ---------------------------------------------------------------------------
# Signal handler (ARCH-08)
# ---------------------------------------------------------------------------

def _handle_signal(signum, frame):
    logger.info("Signal %s received — requesting shutdown", signum)
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _get_version() -> str:
    try:
        version_path = os.path.join(os.path.dirname(__file__), "..", "version.txt")
        with open(os.path.abspath(version_path)) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def _ordinal_date(dt: datetime) -> str:
    """Return date string in 'Ddd DDth Month' format e.g. 'Fri 13th March' (DISP-09)."""
    n = dt.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return dt.strftime("%a ") + f"{n}{suffix}" + dt.strftime(" %B")


def _err_band(err_count: int) -> int:
    """Map error count to display band: 0=ok, 1=stale+no-signal-overlay, 2=warning screen."""
    if err_count == 0:
        return 0
    if err_count >= 3:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: initialise display, start fetch thread, run render loop."""
    signal.signal(signal.SIGTERM, _handle_signal)  # ARCH-08
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Starting Train Departure Display v%s", _get_version())

    try:
        config = load_config()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)  # ARCH-06

    # C-07: warn if SCREEN_BLANK_HOURS is set but does not match expected format
    if config["screenBlankHours"] and not config["hoursPattern"].match(config["screenBlankHours"]):
        logger.warning(
            "SCREEN_BLANK_HOURS '%s' is not in HH-HH format — blank-hours feature disabled",
            config["screenBlankHours"],
        )

    # Display init (ARCH-05: hardware failure → exit 1, no infinite loop)
    try:
        if config["headless"]:
            logger.warning("DEBUG mode active — running headless, no display hardware initialised")
            from luma.core.interface.serial import noop
            serial = noop()
        else:
            logger.info("Production mode — initialising SPI display hardware")
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
            from luma.core.interface.serial import spi
            serial = spi(port=0)

        from luma.oled.device import ssd1322
        device = ssd1322(serial, mode="1", rotate=config["screenRotation"])

        device1 = None
        if config["dualScreen"]:
            from luma.core.interface.serial import spi as spi_mod
            serial1 = spi_mod(port=1, gpio_DC=5, gpio_RST=6)
            device1 = ssd1322(serial1, mode="1", rotate=config["screenRotation"])

    except Exception as exc:
        logger.error("Display initialisation failed: %s", exc)
        sys.exit(1)  # ARCH-05

    # Load fonts
    fonts = {
        "regular": makeFont("Dot Matrix Regular.ttf", 10),
        "bold": makeFont("Dot Matrix Bold.ttf", 10),
        "bold_tall": makeFont("Dot Matrix Bold Tall.ttf", 10),
        "bold_large": makeFont("Dot Matrix Bold.ttf", 20),
    }

    WIDTH, HEIGHT = 256, 64

    from luma.core.sprite_system import framerate_regulator
    regulator = framerate_regulator(config["targetFPS"])

    # P-07: start fetch thread BEFORE the startup sleep so the first API call
    # is in-flight during the 5-second attribution screen (ARCH-07)
    fetcher = threading.Thread(target=_fetch_thread, args=(config,), daemon=True, name="fetch")
    fetcher.start()
    logger.info("Fetch thread started")

    # Attribution screen while data loads (DISP-06)
    virtual = drawStartup(device, fonts, WIDTH, HEIGHT)
    virtual.refresh()
    virtual1 = None  # C-01: always initialise before render loop
    if device1:
        virtual1 = drawStartup(device1, fonts, WIDTH, HEIGHT)
        virtual1.refresh()
    if not config["headless"]:
        time.sleep(5)

    # Parse blank hours config
    blankHours = []
    if config["hoursPattern"].match(config["screenBlankHours"]):
        blankHours = [int(x) for x in config["screenBlankHours"].split("-")]

    # -----------------------------------------------------------------------
    # Render loop — never writes to shared state (ARCH-07)
    # P-05: viewport rebuilt only when _display_epoch or error band changes
    # -----------------------------------------------------------------------
    timeFPS = time.time()
    last_epoch = -1      # epoch value when viewport was last built
    last_err_band = -1   # error band when viewport was last built

    while not _shutdown_event.is_set():
        with regulator:
            if len(blankHours) == 2 and isRun(blankHours[0], blankHours[1]):
                # DISP-05: blank display during configured hours
                device.clear()
                if device1:
                    device1.clear()
                _shutdown_event.wait(timeout=10)
                continue

            # FPS logging (debug level only)
            now = time.time()
            if now - timeFPS >= config["fpsTime"]:
                timeFPS = now
                logger.debug("Effective FPS: %.2f", regulator.effective_FPS())

            # Read shared state under lock (ARCH-07)
            with _lock:
                current_departures = _departures
                current_station = _station_name
                err_count = _fetch_error_count
                epoch = _display_epoch

            band = _err_band(err_count)
            need_rebuild = (epoch != last_epoch) or (band != last_err_band)

            if need_rebuild:
                last_epoch = epoch
                last_err_band = band
                station = current_station or config["journey"]["departureStation"]
                station_label = config["journey"].get("outOfHoursName", station)

                if current_departures is None:
                    # ARCH-04: no data yet — show loading screen
                    virtual = drawBlankSignage(device, fonts, WIDTH, HEIGHT, station_label, config)
                    if device1:
                        virtual1 = drawBlankSignage(device1, fonts, WIDTH, HEIGHT, station_label, config)

                elif band == 2:
                    # ARCH-03: 3+ consecutive failures — dedicated connectivity warning screen
                    virtual = drawConnectivityWarning(
                        device, fonts, WIDTH, HEIGHT, station_label, err_count, config
                    )
                    if device1:
                        virtual1 = drawConnectivityWarning(
                            device1, fonts, WIDTH, HEIGHT, station_label, err_count, config
                        )

                else:
                    # Normal or stale-data path — ARCH-02 overlay applied by drawSignage
                    screen1Data = platform_filter(
                        current_departures or [],
                        config["journey"]["screen1Platform"],
                        station,
                    )
                    virtual = drawSignage(
                        device, fonts, WIDTH, HEIGHT, screen1Data, config, "screen1", err_count
                    )
                    if device1:
                        screen2Data = platform_filter(
                            current_departures or [],
                            config["journey"]["screen2Platform"],
                            station,
                        )
                        virtual1 = drawSignage(
                            device1, fonts, WIDTH, HEIGHT, screen2Data, config, "screen2", err_count
                        )

            # C-01: virtual is always set (startup or rebuilt above)
            virtual.refresh()
            if device1 and virtual1:  # C-01: guard — virtual1 is None if device1 was never used
                virtual1.refresh()

    logger.info("Render loop exited — shutting down")
    _shutdown_event.set()  # harmless if already set; ensures fetch thread exits
    fetcher.join(timeout=5)
    logger.info("Goodbye")


if __name__ == "__main__":
    main()
