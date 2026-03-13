# Pi Train Departure Display

Live UK National Rail departure board on a Raspberry Pi Zero W with a 256×64 SSD1322 SPI OLED.

Based on [chrisys/train-departure-display](https://github.com/chrisys/train-departure-display), redeployed for native Raspberry Pi OS with systemd (no Docker, no Balena).

---

## Before You Start

- Register for a free [National Rail OpenLDBWS API key](https://realtime.nationalrail.co.uk/OpenLDBWSRegistration) — allow **2–4 weeks** for approval
- You will also need your station's **3-letter CRS code** (e.g. `WAT` for London Waterloo, `PAD` for Paddington) — look yours up at [nationalrail.co.uk](https://www.nationalrail.co.uk)

---

## Hardware

| Component | Detail |
|---|---|
| Pi | Raspberry Pi Zero W (or Zero 2W, 3B, 3B+, 4) |
| Display | SSD1322 256×64 OLED, 7-pin SPI (e.g. DIYTZT 3.12" module) |
| OS | Raspberry Pi OS Lite (Bullseye or Bookworm, 32-bit) |

### GPIO Wiring

| OLED Pin | Function | GPIO | Physical Pin |
|---|---|---|---|
| VCC | 3.3V power | 3.3V | Pin 1 |
| GND | Ground | GND | Pin 6 |
| DIN | SPI data (MOSI) | GPIO 10 | Pin 19 |
| CLK | SPI clock (SCLK) | GPIO 11 | Pin 23 |
| CS | Chip select | GPIO 8 (CE0) | Pin 24 |
| DC | Data/command | GPIO 24 | Pin 18 |
| RST | Reset | GPIO 25 | Pin 22 |

---

## Installation

### Step 1 — Flash the SD card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer
2. Choose **Raspberry Pi OS Lite (32-bit)**
3. Click the **gear icon** before flashing:
   - Enable SSH
   - Set username/password
   - Configure your Wi-Fi (SSID + password)
4. Flash to SD card, insert into Pi, power on

### Step 2 — SSH into the Pi

Wait ~60 seconds after power-on, then:

```bash
ssh pi@raspberrypi.local
```

> If `raspberrypi.local` doesn't resolve, find the IP from your router's device list and use that instead.

### Step 3 — Create a GitHub personal access token

The repo is private, so the Pi needs credentials to clone it.

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Give it a name (e.g. `pi-departures`), set expiry, tick **repo** scope
4. Copy the token — you'll use it as the password in Step 4

### Step 4 — Clone and run the installer

```bash
git clone https://github.com/OktaneZA/PiDepartures.git /tmp/train-display
# When prompted: username = OktaneZA, password = your token from Step 3
sudo bash /tmp/train-display/install.sh
```

The installer will prompt you for:
- **API key** — your National Rail OpenLDBWS key (hidden input)
- **Departure station** — 3-letter CRS code (e.g. `WAT`)
- **Destination station** — optional, filters departures to one destination
- **Platform filter** — optional regex (e.g. `^[12]$` for platforms 1 and 2)
- **Screen blank hours** — optional, format `HH-HH` (e.g. `22-06` to blank overnight)
- **Weekly reboot** — optional scheduled reboot (default Sunday 03:00)

### Step 5 — Verify it's working

```bash
# Check service is running
sudo systemctl status train-display

# Stream live logs
journalctl -u train-display -f

# Test API connectivity end-to-end
sudo /opt/train-display/.venv/bin/python /opt/train-display/validate.py
```

The validator runs 5 checks and prints the next departure if everything is working.

---

## Configuration

Config lives in `/etc/train-display/config` (written by the installer). To change any setting, re-run the installer:

```bash
sudo bash /opt/train-display/install.sh
```

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
| `FIRST_DEPARTURE_BOLD` | No | `true` | Render first departure in bold |
| `SHOW_DEPARTURE_NUMBERS` | No | `false` | Show departure index (1, 2, 3) |

---

## Updating

```bash
sudo bash /opt/train-display/update.sh
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Display blank on boot | Check SPI wiring, especially DC (Pin 18) and CS (Pin 24) |
| `Failed to connect to SPI` | `sudo raspi-config` → Interface Options → SPI → Enable |
| `API_KEY is required` | Edit `/etc/train-display/config` and set `API_KEY=...` |
| No departures shown | Run `validate.py` to check API connectivity |
| Service not starting | `journalctl -u train-display -n 50` for full error log |
| `raspberrypi.local` not found | Use the Pi's IP address directly instead |

---

## Running Tests (dev machine)

```bash
pip install -r requirements-dev.txt
pytest --tb=short -q
# On Windows: python -m pytest --tb=short -q
```

To test against the real API on your dev machine:

```bash
cp config.local.example config.local
# edit config.local — add your API_KEY and DEPARTURE_STATION
TRAIN_DISPLAY_CONFIG=config.local python validate.py
```

---

## Licence

MIT — see original project for attribution.
