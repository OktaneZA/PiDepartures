# Installation Guide

## Prerequisites

- Raspberry Pi Zero W (or Zero 2W, 3B, 3B+, 4)
- SSD1322 256×64 OLED display (7-pin SPI, e.g. DIYTZT 3.12" module)
- SD card ≥ 8 GB with Raspberry Pi OS Lite (Bullseye or Bookworm, 32-bit)
- National Rail OpenLDBWS API key — [register here](https://realtime.nationalrail.co.uk/OpenLDBWSRegistration) (allow 2–4 weeks)

---

## GPIO Wiring (Pi Zero W)

| OLED Pin | Function | GPIO | Physical Pin |
|---|---|---|---|
| VCC | 3.3V power | 3.3V | Pin 1 |
| GND | Ground | GND | Pin 6 |
| DIN | SPI MOSI (data) | GPIO 10 | Pin 19 |
| CLK | SPI SCLK (clock) | GPIO 11 | Pin 23 |
| CS | Chip select screen 1 | GPIO 8 (CE0) | Pin 24 |
| DC | Data/command select | GPIO 24 | Pin 18 |
| RST | Reset | GPIO 25 | Pin 22 |
| CS2 | Chip select screen 2 (dual only) | GPIO 7 (CE1) | Pin 26 |

---

## Installation Steps

### 1. Flash OS

Flash Raspberry Pi OS Lite (32-bit) to an SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Enable SSH and configure Wi-Fi in the imager before flashing.

### 2. Boot and connect

Insert SD card, power on, wait ~60 seconds, then SSH in:

```bash
ssh pi@raspberrypi.local
```

### 3. Clone and run installer

```bash
git clone https://github.com/YOUR_ORG/PiDepartures.git /tmp/train-display
sudo bash /tmp/train-display/install.sh
```

The installer will:
- Check prerequisites and enable SPI
- Clone the repo to `/opt/train-display/`
- Create a Python venv and install dependencies
- Create the `train-display` system user
- Prompt for your API key (hidden input), departure station, and options
- Write `/etc/train-display/config` (permissions 640)
- Install and start the systemd service
- Optionally run the connectivity validator

### 4. Verify

```bash
# Check service status
sudo systemctl status train-display

# Stream logs
journalctl -u train-display -f

# Run connectivity validator manually
sudo /opt/train-display/.venv/bin/python /opt/train-display/validate.py
```

---

## Reconfiguration

Re-run the installer — it's idempotent:

```bash
sudo bash /opt/train-display/install.sh
```

---

## Updating

```bash
sudo bash /opt/train-display/update.sh
```

---

## Weekly Reboot Timer

During install you can enable a weekly reboot timer (default: Sunday 03:00). To change schedule:

```bash
sudo systemctl edit train-display-reboot.timer
```

Add an override:
```ini
[Timer]
OnCalendar=
OnCalendar=Mon *-*-* 04:00:00
```

To disable:
```bash
sudo systemctl disable --now train-display-reboot.timer
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Display blank on boot | Check SPI wiring, especially DC and CS pins |
| `Failed to connect to SPI` | Run `sudo raspi-config` → Interface Options → SPI → Enable |
| `API_KEY is required` | Edit `/etc/train-display/config` and set `API_KEY=...` |
| No departures shown | Run `validate.py` to check API connectivity |
| Service not starting | `journalctl -u train-display -n 50` for full error log |
