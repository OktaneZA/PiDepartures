"""Display preview — renders a sample departure board to preview.png.

Uses only PIL (no luma, no hardware). Produces a 256x64 image (the exact
OLED canvas size) scaled up 4x for readability.

Optionally fetches live data if config.local exists:
    TRAIN_DISPLAY_CONFIG=config.local python scripts/preview.py

Otherwise uses built-in sample departures.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

WIDTH, HEIGHT = 256, 64
SCALE = 4  # scale up for readability


def make_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(_SRC, "fonts", name)
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)


def _paste_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                x: int, y: int, right_align_width: int = 0) -> None:
    """Draw text at (x, y), or right-aligned within right_align_width if given."""
    _, _, w, _ = font.getbbox(text)
    if right_align_width:
        x = right_align_width - w
    draw.text((x, y), text, font=font, fill=255)


def _load_live_departures():
    """Try to fetch live data via config.local. Returns (departures, station) or None."""
    config_path = os.environ.get("TRAIN_DISPLAY_CONFIG")
    if not config_path or not os.path.isfile(config_path):
        return None

    # Parse config file
    cfg = {}
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")

    api_key = cfg.get("API_KEY", "")
    station = cfg.get("DEPARTURE_STATION", "")
    if not api_key or not station:
        print("config.local missing API_KEY or DEPARTURE_STATION — using sample data")
        return None

    print(f"Fetching live departures for {station}...")
    try:
        from trains import loadDeparturesForStation
        journey = {
            "departureStation": station,
            "destinationStation": cfg.get("DESTINATION_STATION", ""),
            "timeOffset": "0",
            "individualStationDepartureTime": False,
        }
        deps, station_name = loadDeparturesForStation(journey, api_key, "10")
        if deps:
            print(f"Got {len(deps)} departures from {station_name}")
            return deps, station_name
        print("No departures returned — using sample data")
    except Exception as exc:
        print(f"Live fetch failed ({exc}) — using sample data")
    return None


_SAMPLE_DEPARTURES = [
    {
        "aimed_departure_time": "10:24",
        "destination_name": "London Waterloo",
        "expected_departure_time": "On time",
        "platform": "3",
        "calling_at_list": (
            "Woking, Wimbledon, Clapham Junction, London Waterloo only."
            "  --  A South Western Railway Service."
        ),
    },
    {
        "aimed_departure_time": "10:35",
        "destination_name": "Basingstoke",
        "expected_departure_time": "10:37",
        "platform": "1",
        "calling_at_list": "Basingstoke only.  --  A South Western Railway Service.",
    },
    {
        "aimed_departure_time": "10:51",
        "destination_name": "London Waterloo",
        "expected_departure_time": "Delayed",
        "platform": "4",
        "calling_at_list": (
            "Woking, Wimbledon, Clapham Junction, London Waterloo only."
            "  --  A South Western Railway Service."
        ),
    },
]


def render(departures: list, station_name: str = "Sample Station") -> Image.Image:
    font = make_font("Dot Matrix Regular.ttf", 10)
    font_bold = make_font("Dot Matrix Bold.ttf", 10)
    font_large = make_font("Dot Matrix Bold.ttf", 20)

    img = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)

    if not departures:
        _paste_text(draw, "Welcome to", font_bold, 60, 0)
        _paste_text(draw, station_name, font_bold, 60, 12)
        _paste_text(draw, ".  .  .", font_bold, 0, 24)
        return img

    d = departures[0]
    # Row 1: time + destination (bold) + status right-aligned
    row1 = f"{d['aimed_departure_time']}  {d['destination_name']}"
    exp = d["expected_departure_time"]
    status = "On time" if exp == "On time" else ("Cancelled" if exp == "Cancelled"
             else ("Delayed" if exp == "Delayed" else f"Exp {exp}"))
    _paste_text(draw, row1, font_bold, 0, 0)
    _paste_text(draw, status, font, 0, 0, right_align_width=WIDTH)
    if "platform" in d:
        plat_label = f"Plat {d['platform']}"
        _, _, pw, _ = font.getbbox(plat_label)
        _, _, sw, _ = font.getbbox(status)
        _paste_text(draw, plat_label, font, WIDTH - sw - pw - 4, 0)

    # Row 2: calling at (truncated — no scroll in static preview)
    calling = d.get("calling_at_list", "")
    max_chars = 45
    calling_display = (calling[:max_chars] + "…") if len(calling) > max_chars else calling
    _paste_text(draw, "Calling at: ", font, 0, 12)
    _, _, cw, _ = font.getbbox("Calling at: ")
    _paste_text(draw, calling_display, font, cw, 12)

    # Rows 3 & 4: next 2 departures
    for i, dep in enumerate(departures[1:3]):
        y = 24 + i * 12
        row = f"{dep['aimed_departure_time']}  {dep['destination_name']}"
        exp2 = dep["expected_departure_time"]
        status2 = ("On time" if exp2 == "On time" else
                   ("Cancelled" if exp2 == "Cancelled" else
                   ("Delayed" if exp2 == "Delayed" else f"Exp {exp2}")))
        _paste_text(draw, row, font, 0, y)
        _paste_text(draw, status2, font, 0, y, right_align_width=WIDTH)

    # Bottom row: clock
    from datetime import datetime
    t = datetime.now().strftime("%H:%M")
    _, _, tw, _ = font_large.getbbox(t)
    _paste_text(draw, t, font_large, (WIDTH - tw) // 2, 50)

    return img


def main():
    result = _load_live_departures()
    if result:
        departures, station_name = result
    else:
        departures, station_name = _SAMPLE_DEPARTURES, "Sample Station"

    img = render(departures, station_name)

    # Scale up for readability and save
    out = img.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.NEAREST)
    out_path = os.path.join(_ROOT, "preview.png")
    out.save(out_path)
    print(f"Saved {out_path}  ({WIDTH}x{HEIGHT} scaled to {WIDTH*SCALE}x{HEIGHT*SCALE})")
    print("Open preview.png to see what the display would show.")


if __name__ == "__main__":
    main()
