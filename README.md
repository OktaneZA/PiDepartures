# Pi Train Departure Display

Live UK National Rail departure board on a Raspberry Pi Zero W with a 256×64 SSD1322 SPI OLED.

Based on [chrisys/train-departure-display](https://github.com/chrisys/train-departure-display), redeployed for native Raspberry Pi OS with systemd (no Docker, no Balena).

## Quick Start

1. Register for a free [National Rail OpenLDBWS API key](https://realtime.nationalrail.co.uk/OpenLDBWSRegistration) (allow 2–4 weeks)
2. Wire up the SSD1322 display (see [INSTALL.md](INSTALL.md))
3. Flash Raspberry Pi OS Lite to an SD card and boot your Pi
4. Clone this repo and run the installer:

```bash
git clone https://github.com/YOUR_ORG/PiDepartures.git /opt/train-display
sudo bash /opt/train-display/install.sh
```

5. Check the logs:

```bash
journalctl -u train-display -f
```

## Hardware

| Component | Detail |
|---|---|
| Pi | Raspberry Pi Zero W (or Zero 2W, 3B, 3B+, 4) |
| Display | SSD1322 256×64 OLED, 7-pin SPI |
| OS | Raspberry Pi OS Lite (Bullseye or Bookworm, 32-bit) |

See [INSTALL.md](INSTALL.md) for GPIO wiring.

## Configuration

Configuration lives in `/etc/train-display/config` (written by the installer).

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | Yes | — | National Rail API key |
| `DEPARTURE_STATION` | Yes | — | 3-letter CRS code (e.g. `PAD`) |
| `DESTINATION_STATION` | No | — | Filter by destination CRS |
| `PLATFORM_FILTER` | No | — | Regex for platform (e.g. `^[12]$`) |
| `REFRESH_TIME` | No | `120` | Seconds between API polls |
| `SCREEN_ROTATION` | No | `2` | Display rotation (0–3) |
| `SCREEN_BLANK_HOURS` | No | — | Blank display hours `HH-HH` (e.g. `22-06`) |
| `DUAL_SCREEN` | No | `false` | Second SSD1322 on CE1 |

To reconfigure: `sudo bash /opt/train-display/install.sh`

## Updating

```bash
sudo bash /opt/train-display/update.sh
```

## Running Tests (dev machine)

```bash
pip install -r requirements-dev.txt
pytest --tb=short -q
```

## Licence

MIT — see original project for attribution.
