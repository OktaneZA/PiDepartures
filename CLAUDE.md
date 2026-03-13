# Pi Train Departure Display — Claude Instructions

## What This Project Is

A Raspberry Pi departure board that displays live UK National Rail departures on a 256×64 SSD1322 SPI OLED. Runs natively on Raspberry Pi OS — no Docker, no Balena, no cloud dependency.

Derived from [chrisys/train-departure-display](https://github.com/chrisys/train-departure-display) with native systemd deployment replacing the Balena container model.

## Repository Structure

```
/
├── CLAUDE.md                   ← You are here
├── REQUIREMENTS.md             ← Canonical requirements (read before coding)
├── INSTALL.md                  ← Human installer guide and wiring reference
├── README.md                   ← Project overview and quick-start
│
├── src/
│   ├── main.py                 ← Entry point: display loop, threading, SIGTERM handler
│   ├── trains.py               ← National Rail OpenLDBWS SOAP client
│   ├── config.py               ← Config loading, validation, defaults
│   ├── hours.py                ← Blank-hours logic (is_time_between, isRun)
│   └── fonts/                  ← Dot-matrix bitmap fonts (.ttf)
│
├── tests/
│   ├── test_trains.py          ← Unit tests: SOAP parsing, departure models
│   ├── test_config.py          ← Unit tests: validation, defaults, CRS format
│   └── test_display.py         ← Unit tests: scroll logic, blank-hours, row selection
│
├── systemd/
│   ├── train-display.service   ← systemd service unit
│   └── train-display-reboot.timer  ← Weekly reboot timer
│
├── validate.py                 ← Post-install API connectivity checker
├── install.sh                  ← Installer (runs on Pi as root)
├── update.sh                   ← Update script (git pull + restart)
├── requirements.txt            ← Pinned runtime dependencies
└── requirements-dev.txt        ← Dev-only: pytest, pytest-mock
```

## Requirements First

**Read `REQUIREMENTS.md` before making any changes.** All functional behaviour, acceptance criteria, and requirement IDs (e.g. `ARCH-01`, `SEC-06`, `DISP-03`) are defined there. Code should be traceable to a requirement ID in comments where non-obvious.

## Python Conventions

- Python 3.9+ compatible — no walrus operator in 3.8-incompatible ways, no 3.10+ match statements
- Type hints on all public functions and class methods
- Docstrings on all public functions (one-line for simple, multi-line for complex)
- `logging` module for all output — never `print()` in production code
- Log levels: `DEBUG` for render cycle detail, `INFO` for API calls and state changes, `WARNING` for recoverable errors, `ERROR` for failures
- Line length: 100 characters max

## Error Handling Conventions

- API calls: `try/except requests.RequestException` — always catch, log with context, never let propagate to render loop
- XML parsing: wrap `xmltodict.parse()` in try/except — malformed XML is a `SECRV-03` requirement
- Display init: if SPI/luma raises on init, log and `sys.exit(1)` — do not mask hardware failures
- Never catch bare `except Exception` without re-logging with full context
- Exponential back-off for API retries: start 2s, double each failure, cap at 120s (ARCH-01)

## Threading Model

- **Two threads**: main render thread + background API-fetch thread
- **Shared state**: `_departures` list and `_fetch_error_count` protected by `threading.Lock`
- Render thread **never** writes to shared state; fetch thread **never** calls display functions
- SIGTERM sets a `_shutdown_event` (`threading.Event`) — both threads check and exit cleanly (ARCH-08)

## Security — Do Not

- **NEVER** log or print the `API_KEY` value — not in errors, not in debug, not in tracebacks
- **NEVER** use `verify=False` on any `requests` call (SEC-07)
- **NEVER** use `eval()`, `exec()`, `os.system()`, or `subprocess` with config-derived strings (SEC-09)
- **NEVER** run the service as root (SEC-03)
- **NEVER** hardcode a station code, API key, or credential in source (SEC-08)
- **NEVER** downgrade HTTP for the OpenLDBWS endpoint (SEC-06)

## How to Run Tests

```bash
# From project root on any machine (no Pi hardware needed)
pip install -r requirements-dev.txt
pytest --tb=short -q
```

All tests mock luma display hardware and RPi.GPIO — safe to run on Linux/macOS/Windows.

## How to Run the Validator (on Pi after install)

```bash
sudo /opt/train-display/.venv/bin/python /opt/train-display/validate.py
```

Or if running from the repo directory with venv active:
```bash
python validate.py
```

Expected output: 5 checks, all `[ PASS ]`, followed by the next departure.

## How to Install / Reconfigure

```bash
# On the Pi, as root:
curl -fsSL https://raw.githubusercontent.com/OktaneZA/PiDepartures/main/install.sh | sudo bash
# Or after cloning:
sudo bash install.sh
```

## How to Update

```bash
sudo bash /opt/train-display/update.sh
```

## How to View Logs

```bash
journalctl -u train-display -f
```

## Current Status

| Component | Status |
|---|---|
| REQUIREMENTS.md | Complete |
| src/config.py | Complete |
| src/trains.py | Complete |
| src/hours.py | Complete |
| src/main.py | Complete |
| tests/ | Complete — 100 tests passing (TEST-08 pending DISP-09 implementation) |
| validate.py | Complete |
| install.sh | In progress |
| systemd units | In progress |
