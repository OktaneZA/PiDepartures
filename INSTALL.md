# Installation Guide

## Prerequisites

- Raspberry Pi Zero W (or Zero 2W, 3B, 3B+, 4)
- SSD1322 256×64 OLED display (7-pin SPI, e.g. DIYTZT 3.12" module)
- SD card ≥ 8 GB with Raspberry Pi OS Lite **(Bookworm)**; 32-bit for Zero W, 32 or 64-bit for Zero 2W
- National Rail OpenLDBWS API key — [register here](https://realtime.nationalrail.co.uk/OpenLDBWSRegistration) (allow 2–4 weeks)

---

## GPIO Wiring (Pi Zero W / Zero 2W)

**Orientation:** Pin 1 is at the corner of the GPIO header closest to the **SD card slot**. Hold the Pi with the SD card on the left and the USB/HDMI ports on the right — Pin 1 is top-left.

```
  ◄── SD card                                          USB / HDMI ──►

  Pin 1  [ 3V3 ●]── VCC    [  5V  ]  Pin 2
  Pin 3  [ SDA  ]          [  5V  ]  Pin 4
  Pin 5  [ SCL  ]          [ GND ●]── GND          Pin 6
  Pin 7  [GPIO4 ]          [ TXD  ]  Pin 8
  Pin 9  [ GND  ]          [ RXD  ]  Pin 10
  Pin 11 [GPIO17]          [GPIO18]  Pin 12
  Pin 13 [GPIO27]          [ GND  ]  Pin 14
  Pin 15 [GPIO22]          [GPIO23]  Pin 16
  Pin 17 [ 3V3  ]          [GPIO24●]── DC          Pin 18
  Pin 19 [GPIO10●]── DIN   [ GND  ]  Pin 20
  Pin 21 [ GPIO9]          [GPIO25●]── RST         Pin 22
  Pin 23 [GPIO11●]── CLK   [ GPIO8●]── CS         Pin 24
  Pin 25 [ GND  ]          [ GPIO7 ]  Pin 26

  ● = wire to OLED
```

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

Flash **Raspberry Pi OS Lite (Bookworm)** to an SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Choose 32-bit for the Zero W; either 32 or 64-bit works on the Zero 2W. Set your username/password and configure Wi-Fi in the imager before flashing.

> Bookworm is required for Raspberry Pi Connect support.

### 2. Boot and connect via Raspberry Pi Connect

[Raspberry Pi Connect](https://connect.raspberrypi.com) provides browser-based remote shell access — no SSH client or IP address needed. All ongoing management of the Pi (starting/stopping the service, viewing logs, reconfiguring) is done through Pi Connect.

1. Insert SD card and power on — wait ~60 seconds to boot
2. On first boot, connect a keyboard and monitor (or use SSH once) and run:
   ```bash
   sudo apt update && sudo apt install -y rpi-connect-lite
   rpi-connect signin
   ```
3. Follow the link in the terminal to authorise the device at [connect.raspberrypi.com](https://connect.raspberrypi.com)
4. Open your browser → [connect.raspberrypi.com](https://connect.raspberrypi.com) → your device → **Remote shell**

> **Note:** Screen sharing requires a Pi 4 or newer with a desktop environment. The Zero 2W supports remote shell only.

### 3. Download and run installer

**Important:** Do not pipe directly from curl — download the script first so stdin works correctly for the interactive prompts:

```bash
curl -fsSL https://raw.githubusercontent.com/OktaneZA/PiDepartures/master/install.sh -o /tmp/install.sh
sudo bash /tmp/install.sh
```

The installer will:
- Check prerequisites and enable SPI
- Clone the repo to `/opt/train-display/`
- Create a Python venv and install dependencies
- Create the `train-display` system user
- Prompt for your API key (hidden input), departure station, and options
- Write `/etc/train-display/config` (permissions 640)
- Install and **enable** the systemd service (does **not** auto-start)
- Run the connectivity validator

### 4. Start the service

Once the installer completes and validation passes, start the service:

```bash
sudo systemctl start train-display
```

The service will now start automatically on every boot.

### 5. Verify

```bash
# Check service is running
sudo systemctl status train-display

# Stream live logs
journalctl -u train-display -f

# Run connectivity validator
sudo /opt/train-display/.venv/bin/python /opt/train-display/validate.py
```

---

## Day-to-day Management

Connect to your Pi at [connect.raspberrypi.com](https://connect.raspberrypi.com) → Remote shell, then:

```bash
# View live logs
journalctl -u train-display -f

# Restart after config changes
sudo systemctl restart train-display

# Stop / Start
sudo systemctl stop train-display
sudo systemctl start train-display
```

---

## Reconfiguration

All settings (station, filters, display options, portal password) are managed through the **web portal**. Open `http://<pi-ip>:<PORTAL_PORT>` in a browser — the URL is printed at the end of installation.

To change the API key or departure station (the two values set during install), re-run the installer:

```bash
sudo bash /opt/train-display/install.sh
```

---

## Updating

```bash
sudo bash /opt/train-display/update.sh
```

---

## Web Portal

The web portal lets you change settings via a browser without needing Pi Connect.

To enable it, edit the config:

```bash
sudo nano /etc/train-display/config
```

Set `PORTAL_ENABLED=true`, then restart:

```bash
sudo systemctl restart train-display
```

The portal runs on the port shown in `PORTAL_PORT` in the config file. Access it at `http://<pi-ip>:<port>`.

---

## Weekly Reboot Timer

To enable a weekly scheduled reboot (default: Sunday 03:00):

```bash
sudo cp /opt/train-display/systemd/train-display-reboot.timer /etc/systemd/system/
sudo cp /opt/train-display/systemd/train-display-reboot.target.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now train-display-reboot.timer
```

To change the schedule:

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
| Pi not appearing in Connect | Ensure `rpi-connect-lite` is installed and `rpi-connect signin` has been run |
| Connect signin link expired | Run `rpi-connect signin` again to generate a new link |
| CRS prompt loops — not accepting input | Download the installer first: `curl ... -o /tmp/install.sh && sudo bash /tmp/install.sh` |
