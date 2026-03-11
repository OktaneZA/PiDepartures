# Pi Train Departure Display — Requirements

## Overview

A self-hosted UK National Rail departure board that runs **natively on a Raspberry Pi Zero W** without Docker, Balena, or any cloud management platform. The Pi calls the National Rail OpenLDBWS API directly, renders live departures on a 256×64 SSD1322 SPI OLED display, and starts automatically on boot.

This project is derived from [chrisys/train-departure-display](https://github.com/chrisys/train-departure-display) with the following key changes:
- Removed Balena/Docker dependency — runs directly on Raspberry Pi OS
- Configuration via `/etc/train-display/config` instead of Balena environment variables
- Bash installer (`install.sh`) that guides setup interactively, including API key input
- systemd service for process management, autostart, and crash recovery
- Scheduled weekly reboot via systemd timer
- Hardened error handling, exponential back-off, and stale-data display on connectivity loss

---

## 1. Hardware Requirements

| Component | Requirement |
|---|---|
| **Primary device** | Raspberry Pi Zero W |
| **Also supported** | Raspberry Pi Zero 2W, Pi 3B, Pi 3B+, Pi 4 |
| **Display** | SSD1322 256×64 OLED, SPI interface (e.g. DIYTZT 3.12" 256×64 module) |
| **Display interface** | 7-pin SPI: VCC, GND, DIN (MOSI), CLK (SCLK), CS (CE0), DC, RST |
| **Storage** | SD card ≥ 8 GB |
| **OS** | Raspberry Pi OS Lite (32-bit, Bullseye or Bookworm) |
| **Network** | Wi-Fi or Ethernet (required for API access) |

### SSD1322 GPIO Wiring (Pi Zero W)

| OLED Pin | GPIO Pin | Physical Pin | Notes |
|---|---|---|---|
| VCC | 3.3V | Pin 1 | 3.3V power |
| GND | GND | Pin 6 | Ground |
| DIN | GPIO 10 (MOSI) | Pin 19 | SPI data |
| CLK | GPIO 11 (SCLK) | Pin 23 | SPI clock |
| CS | GPIO 8 (CE0) | Pin 24 | Chip select (screen 1) |
| DC | GPIO 24 | Pin 18 | Data/command select |
| RST | GPIO 25 | Pin 22 | Reset |
| CS2 | GPIO 7 (CE1) | Pin 26 | Chip select (screen 2, dual-screen mode only) |

---

## 2. Software Stack

| Component | Version / Package |
|---|---|
| **Python** | 3.9+ (system Python on Pi OS) |
| **luma.oled** | ≥ 3.13.0 — OLED display driver |
| **luma.core** | ≥ 2.4.2 — display rendering framework |
| **Pillow** | ≥ 10.3.0 — image/font rendering |
| **requests** | ≥ 2.31.0 — HTTP client for API calls |
| **xmltodict** | ≥ 0.13.0 — SOAP XML parsing |
| **RPi.GPIO** | ≥ 0.7.1 — GPIO control |
| **spidev** | ≥ 3.6 — SPI interface |
| **urllib3** | ≥ 2.2.0 — HTTP connection pooling |
| **systemd** | system package — service management |
| **git** | system package — source deployment |

**Dev-only dependencies** (`requirements-dev.txt`):
- `pytest >= 8.0`
- `pytest-mock >= 3.12`

---

## 3. Data Source — National Rail OpenLDBWS

| Item | Detail |
|---|---|
| **API** | National Rail Enquiries — Live Departure Boards Web Service (OpenLDBWS) |
| **Endpoint** | `https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx` |
| **Protocol** | SOAP 1.1 / XML over HTTPS |
| **Authentication** | API key in SOAP header (`<AccessToken><TokenValue>…</TokenValue></AccessToken>`) |
| **Registration** | https://realtime.nationalrail.co.uk/OpenLDBWSRegistration — allow 2–4 weeks |
| **Data returned** | Departures within 120-minute window: scheduled/actual time, platform, destination, operator, calling points, status |
| **Polling interval** | 120 seconds (configurable via `REFRESH_TIME`) |

---

## 4. Configuration

Configuration is stored in `/etc/train-display/config`, owned by `root:train-display`, permissions `640`. The file uses `KEY=value` shell syntax and is loaded as an `EnvironmentFile` by systemd.

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | Yes | — | National Rail OpenLDBWS API key |
| `DEPARTURE_STATION` | Yes | — | 3-letter CRS code of departure station (e.g. `PAD`, `WAT`, `MAN`) |
| `DESTINATION_STATION` | No | — | Filter departures to this destination CRS code |
| `PLATFORM_FILTER` | No | — | Regex to show only matching platform numbers (e.g. `^[12]$`) |
| `REFRESH_TIME` | No | `120` | Seconds between API polls |
| `SCREEN_ROTATION` | No | `2` | Display rotation: 0, 1, 2, or 3 |
| `SCREEN_BLANK_HOURS` | No | — | Blank display during these hours, format `HH-HH` (e.g. `22-06`) |
| `DUAL_SCREEN` | No | `false` | Drive a second SSD1322 on CE1 (GPIO 7) |
| `SCREEN2_PLATFORM` | No | — | Platform filter for second screen (requires `DUAL_SCREEN=true`) |
| `SHOW_DEPARTURE_NUMBERS` | No | `false` | Show departure index numbers (1, 2, 3) |
| `FIRST_DEPARTURE_BOLD` | No | `true` | Render first departure row in bold |
| `DEBUG` | No | `false` | Run without display hardware (log-only mode) |

---

## 5. Display Behaviour

| ID | Requirement |
|---|---|
| DISP-01 | Show up to 3 next departures on the 256×64 OLED canvas |
| DISP-02 | Each row: scheduled departure time, destination, platform number, service status |
| DISP-03 | Calling stations for the first departure scroll horizontally in a continuous animation |
| DISP-04 | Dot-matrix font aesthetic matching original project fonts |
| DISP-05 | Display blanks automatically during `SCREEN_BLANK_HOURS`; a minimal clock may be shown |
| DISP-06 | Attribution/loading screen displayed on startup while initial data is fetched |
| DISP-07 | First departure rendered in bold when `FIRST_DEPARTURE_BOLD=true` |
| DISP-08 | Dual screen mode: second SSD1322 shows departures filtered by `SCREEN2_PLATFORM` |

---

## 6. Installer (`install.sh`)

A bash script run **directly on the Pi** as root. The installer is idempotent — re-running it updates configuration and restarts the service.

| ID | Requirement |
|---|---|
| INST-01 | Validates it is running on a Raspberry Pi; exits with a clear message if not |
| INST-02 | Checks prerequisites: Python 3.9+, pip3, git; installs missing packages via `apt` |
| INST-03 | Enables SPI interface via `raspi-config nonint do_spi 0` if not already enabled |
| INST-04 | Clones the repo to `/opt/train-display/` or does `git pull` if already present |
| INST-05 | Creates a Python venv at `/opt/train-display/.venv` and installs `requirements.txt` |
| INST-06 | Creates `train-display` system user and group (no login shell, no home directory) if absent |
| INST-07 | Adds `train-display` user to `gpio` and `spi` groups for hardware access |
| INST-08 | Prompts interactively for `API_KEY` using `read -s` (hidden input, not echoed) |
| INST-09 | Prompts for `DEPARTURE_STATION` with CRS code hint and format validation (3 uppercase letters) |
| INST-10 | Optionally prompts for `DESTINATION_STATION`, `PLATFORM_FILTER`, `SCREEN_BLANK_HOURS` |
| INST-11 | Asks whether to enable weekly reboot timer and (if yes) what time (default: Sun 03:00) |
| INST-12 | Writes `/etc/train-display/config` with permissions `640`, owner `root:train-display` |
| INST-13 | Installs and enables `train-display.service` and (if chosen) `train-display-reboot.timer` |
| INST-14 | Starts the service and reports status |
| INST-15 | Offers to run `validate.py` at the end to confirm API connectivity |
| INST-16 | Prints a post-install summary: station, service status, log command |

---

## 7. systemd Service

**File:** `/etc/systemd/system/train-display.service`

```ini
[Unit]
Description=Train Departure Display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=train-display
Group=train-display
EnvironmentFile=/etc/train-display/config
ExecStart=/opt/train-display/.venv/bin/python /opt/train-display/src/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Key behaviours:
- `After=network-online.target` — waits for network connectivity before first API call (BOOT-02)
- `Restart=on-failure` — automatically restarts on crash (BOOT-01)
- Unprivileged `train-display` user in `gpio`/`spi` groups — no root required (SEC-03, SEC-04)

---

## 8. Boot & Scheduled Restart

**Auto-start on boot:**

| ID | Requirement |
|---|---|
| BOOT-01 | Service enabled at install via `systemctl enable train-display` — starts after every reboot |
| BOOT-02 | Unit declares `After=network-online.target` so it waits for network before starting |
| BOOT-03 | If network is unavailable, app retries silently and shows loading screen (no crash) |

**Scheduled weekly reboot:**

| ID | Requirement |
|---|---|
| REBOOT-01 | `train-display-reboot.timer` triggers a full system reboot every 7 days |
| REBOOT-02 | Default schedule: Sunday at 03:00 local time (configurable during install) |
| REBOOT-03 | Timer installed and enabled by `install.sh` alongside the main service |
| REBOOT-04 | Reboot performed via `systemctl reboot` (clean shutdown sequence) |
| REBOOT-05 | Timer and schedule documented in `INSTALL.md` with instructions to change or disable |

---

## 9. Update Mechanism

- `update.sh` performs: `git -C /opt/train-display pull && pip install -r requirements.txt && systemctl restart train-display`
- No OTA — manual pull on the Pi is the supported update path
- Re-running `install.sh` is the supported reconfiguration path

---

## 10. Security Requirements

| ID | Requirement |
|---|---|
| SEC-01 | `API_KEY` never written to logs, tracebacks, or stdout under any circumstances |
| SEC-02 | Config file permissions `640`, owned `root:train-display` |
| SEC-03 | Service runs as unprivileged `train-display` user, not root |
| SEC-04 | `train-display` user added to `gpio` and `spi` groups for hardware access |
| SEC-05 | API key collected in installer with `read -s` — not exposed in shell history |
| SEC-06 | HTTPS enforced for OpenLDBWS endpoint; no HTTP fallback |
| SEC-07 | `requests` SSL verification always enabled (`verify=True`) |
| SEC-08 | No hardcoded credentials, station codes, or tokens in source |
| SEC-09 | No use of `eval`, `os.system`, or `subprocess` with config-derived values |
| SEC-10 | Startup checks config file permissions; logs a warning if world-readable |
| SEC-11 | Python dependency versions pinned in `requirements.txt` |

---

## 11. Architectural Resilience

| ID | Requirement |
|---|---|
| ARCH-01 | API call wrapped in try/except with exponential back-off: 2s → 4s → 8s → … → 120s cap |
| ARCH-02 | On API failure, display continues showing last known departures with a "No signal" indicator |
| ARCH-03 | After 3 consecutive API failures, display shows a dedicated connectivity warning screen |
| ARCH-04 | Network unavailable at startup: retry loop with loading screen — no unhandled exception |
| ARCH-05 | SPI/display initialisation failure: log clear error and exit with code 1 (no infinite loop) |
| ARCH-06 | Config validation runs at startup before any I/O; missing required fields exit with a clear message |
| ARCH-07 | Data shared between API-fetch thread and render thread protected by a `threading.Lock` |
| ARCH-08 | SIGTERM handler set at startup; graceful shutdown completes current render cycle before exit |
| ARCH-09 | Bitmap text cache bounded to a maximum of 256 entries (LRU eviction) to protect Pi Zero RAM |
| ARCH-10 | All caught exceptions logged with: station code, attempt number, error type — never the API key |

---

## 12. Python Test Suite

| ID | Requirement |
|---|---|
| TEST-01 | `tests/` directory at project root; all tests runnable with `pytest` |
| TEST-02 | `tests/test_trains.py`: mock SOAP XML responses; verify correct parsing of on-time, delayed, cancelled, and empty-service responses |
| TEST-03 | `tests/test_config.py`: missing required fields raise `ValueError`; defaults applied correctly; CRS validation; blank-hours parsing |
| TEST-04 | `tests/test_display.py`: calling-point scroll offset logic; bold/normal row selection; blank-hours active/inactive check |
| TEST-05 | All tests runnable without physical display hardware — luma device mocked via `pytest-mock` |
| TEST-06 | `requirements-dev.txt` lists `pytest` and `pytest-mock` as dev-only dependencies |
| TEST-07 | `pytest --tb=short -q` exits non-zero on any failure (CI-friendly) |

---

## 13. API Validation Tool (`validate.py`)

A standalone script run on the Pi after install to confirm end-to-end connectivity.

| ID | Requirement |
|---|---|
| VAL-01 | Runnable as `python /opt/train-display/validate.py` or `.venv/bin/python validate.py` |
| VAL-02 | Reads config from `/etc/train-display/config` (same path as the service) |
| VAL-03 | Check 1: config file exists and is readable |
| VAL-04 | Check 2: `API_KEY` is set (prints `API_KEY: set` — never the value) |
| VAL-05 | Check 3: `DEPARTURE_STATION` is set and matches CRS format |
| VAL-06 | Check 4: live HTTPS call to OpenLDBWS returns HTTP 200 with valid XML |
| VAL-07 | Check 5: at least one departure parsed from response |
| VAL-08 | Prints next departure (time, destination, platform) on success |
| VAL-09 | Each check prints `[ PASS ]` or `[ FAIL ] <reason>` |
| VAL-10 | Exits code 0 if all checks pass; non-zero if any fail |

---

## 14. Project Documentation Files

| File | Purpose |
|---|---|
| `CLAUDE.md` | AI assistant instructions: project conventions, test/validate commands, Do Not rules |
| `REQUIREMENTS.md` | This document — canonical requirements reference |
| `INSTALL.md` | Human-readable installer and wiring guide |
| `README.md` | Overview, quick-start, hardware photo, licence |

---

## 15. Out of Scope

- Journey planning, ticket purchasing, arrivals boards
- iOS, macOS, or Windows support
- Web dashboard or remote configuration UI
- OTA (over-the-air) updates
- National Rail Darwin push feed (polling only in this version)
- Any cloud service dependency (Balena, AWS, GCP, etc.)
