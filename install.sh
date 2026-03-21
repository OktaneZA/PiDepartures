#!/usr/bin/env bash
# Train Departure Display — Installer
# Run on the Raspberry Pi as root: sudo bash install.sh
# Idempotent: safe to re-run to update config or restart the service.
#
# Requirements: INST-01 – INST-16

set -euo pipefail

REPO_URL="https://github.com/OktaneZA/PiDepartures.git"
INSTALL_DIR="/opt/train-display"
CONFIG_DIR="/etc/train-display"
CONFIG_FILE="${CONFIG_DIR}/config"
SERVICE_NAME="train-display"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}-reboot.timer"
TIMER_UNIT="/etc/systemd/system/${SERVICE_NAME}-reboot.target.service"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
confirm() { read -r -p "$1 [y/N] " ans; [[ "${ans,,}" == "y" ]]; }

# ---------------------------------------------------------------------------
# INST-01: Must run on a Raspberry Pi
# ---------------------------------------------------------------------------
if [[ ! -f /proc/device-tree/model ]] || ! grep -qi "raspberry" /proc/device-tree/model; then
    error "This installer must run on a Raspberry Pi."
fi
info "Detected: $(cat /proc/device-tree/model)"

# Must be root
if [[ $EUID -ne 0 ]]; then
    error "Please run as root: sudo bash install.sh"
fi

# ---------------------------------------------------------------------------
# INST-02: Check/install prerequisites
# ---------------------------------------------------------------------------
info "Checking prerequisites..."
apt-get update -qq

for pkg in python3 python3-pip python3-venv git; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        info "Installing $pkg..."
        apt-get install -y -qq "$pkg"
    fi
done

# Verify Python >= 3.9
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)'; then
    info "Python ${PYTHON_VERSION} OK"
else
    error "Python 3.9+ required, found ${PYTHON_VERSION}"
fi

# ---------------------------------------------------------------------------
# INST-03: Enable SPI
# ---------------------------------------------------------------------------
if ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    info "Enabling SPI interface..."
    raspi-config nonint do_spi 0
else
    info "SPI already enabled"
fi

# ---------------------------------------------------------------------------
# INST-04: Clone or update repo
# ---------------------------------------------------------------------------
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing installation..."
    git -C "${INSTALL_DIR}" pull --ff-only
else
    info "Cloning repository to ${INSTALL_DIR}..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

# ---------------------------------------------------------------------------
# INST-05: Create venv and install dependencies
# ---------------------------------------------------------------------------
info "Setting up Python virtual environment..."
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"
info "Python dependencies installed"

# ---------------------------------------------------------------------------
# INST-06 / INST-07: Create system user
# ---------------------------------------------------------------------------
if ! id -u train-display &>/dev/null; then
    info "Creating train-display system user..."
    useradd --system --no-create-home --shell /usr/sbin/nologin train-display
fi
usermod -aG gpio,spi train-display
info "train-display user in gpio and spi groups"

# ---------------------------------------------------------------------------
# INST-08 – INST-12: Interactive configuration
# ---------------------------------------------------------------------------
info ""
info "=== Configuration ==="

# API key (hidden input — SEC-05)
echo -n "Enter your National Rail OpenLDBWS API key: "
read -rs API_KEY
echo
[[ -z "${API_KEY}" ]] && error "API_KEY cannot be empty"

# Departure station
while true; do
    read -r -p "Enter departure station CRS code (e.g. PAD, WAT, MAN): " DEPARTURE_STATION
    DEPARTURE_STATION="${DEPARTURE_STATION^^}"
    if [[ "${DEPARTURE_STATION}" =~ ^[A-Z]{3}$ ]]; then
        break
    fi
    warn "CRS code must be exactly 3 uppercase letters. Try again."
done

# Optional: destination filter
read -r -p "Filter by destination CRS (leave blank for none): " DESTINATION_STATION
DESTINATION_STATION="${DESTINATION_STATION^^}"
if [[ -n "${DESTINATION_STATION}" ]] && ! [[ "${DESTINATION_STATION}" =~ ^[A-Z]{3}$ ]]; then
    warn "Invalid destination CRS — ignoring"
    DESTINATION_STATION=""
fi

# Optional: platform filter
read -r -p "Platform filter regex (e.g. ^[12]$, leave blank for none): " PLATFORM_FILTER

# Optional: screen blank hours
read -r -p "Blank screen hours HH-HH (e.g. 22-06, leave blank to disable): " SCREEN_BLANK_HOURS
if [[ -n "${SCREEN_BLANK_HOURS}" ]] && ! [[ "${SCREEN_BLANK_HOURS}" =~ ^[0-9]{1,2}-[0-9]{1,2}$ ]]; then
    warn "Invalid blank-hours format — ignoring"
    SCREEN_BLANK_HOURS=""
fi

# Optional: portal password (leave blank for local-only access)
echo ""
echo "  Web portal runs on port 8080 and lets you change settings via a browser."
echo "  Leave password blank to allow access from localhost only (recommended for LAN use)."
echo "  Set a password to enable remote access via HTTP Basic Auth."
echo -n "  Portal password (leave blank for local-only): "
read -rs PORTAL_PASSWORD
echo
PORTAL_PORT=$(shuf -i 8000-9999 -n 1)
if [[ -n "${PORTAL_PASSWORD}" ]]; then
    read -r -p "  Portal port [${PORTAL_PORT}]: " PORTAL_PORT_INPUT
    [[ -n "${PORTAL_PORT_INPUT}" ]] && PORTAL_PORT="${PORTAL_PORT_INPUT}"
fi

# Optional: weekly reboot timer — INST-11
ENABLE_TIMER=false
REBOOT_TIME="Sun 03:00"
if confirm "Enable weekly scheduled reboot?"; then
    ENABLE_TIMER=true
    read -r -p "Reboot schedule (default: Sun *-*-* 03:00:00, press Enter to accept): " REBOOT_INPUT
    [[ -n "${REBOOT_INPUT}" ]] && REBOOT_TIME="${REBOOT_INPUT}"
fi

# ---------------------------------------------------------------------------
# INST-12: Write config file
# ---------------------------------------------------------------------------
info "Writing config to ${CONFIG_FILE}..."
mkdir -p "${CONFIG_DIR}"

cat > "${CONFIG_FILE}" <<EOF
# Train Departure Display — configuration
# Managed by install.sh — edit with care.
# Permissions: 640 (root:train-display read-only for service user)

API_KEY=${API_KEY}
DEPARTURE_STATION=${DEPARTURE_STATION}
EOF

[[ -n "${DESTINATION_STATION}" ]] && echo "DESTINATION_STATION=${DESTINATION_STATION}" >> "${CONFIG_FILE}"
[[ -n "${PLATFORM_FILTER}" ]] && echo "PLATFORM_FILTER=${PLATFORM_FILTER}" >> "${CONFIG_FILE}"
[[ -n "${SCREEN_BLANK_HOURS}" ]] && echo "SCREEN_BLANK_HOURS=${SCREEN_BLANK_HOURS}" >> "${CONFIG_FILE}"

cat >> "${CONFIG_FILE}" <<EOF

REFRESH_TIME=120
SCREEN_ROTATION=2
FIRST_DEPARTURE_BOLD=true
SHOW_DEPARTURE_NUMBERS=false
DUAL_SCREEN=false
PORTAL_PORT=${PORTAL_PORT}
EOF

# Hash and write portal password if set (SEC-08)
if [[ -n "${PORTAL_PASSWORD}" ]]; then
    HASHED_PW=$(python3 -c "
import base64, hashlib, secrets
salt = secrets.token_hex(16)
dk = hashlib.pbkdf2_hmac('sha256', '${PORTAL_PASSWORD}'.encode(), bytes.fromhex(salt), 260000)
print(f'pbkdf2:sha256:260000:{salt}:{base64.b64encode(dk).decode()}')
")
    echo "PORTAL_PASSWORD=${HASHED_PW}" >> "${CONFIG_FILE}"
fi

chown root:train-display "${CONFIG_FILE}"
chmod 640 "${CONFIG_FILE}"  # SEC-02
info "Config written (permissions 640, owner root:train-display)"

# ---------------------------------------------------------------------------
# INST-13: Install systemd units
# ---------------------------------------------------------------------------
info "Installing systemd service..."
cp "${INSTALL_DIR}/systemd/train-display.service" "${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

if [[ "${ENABLE_TIMER}" == "true" ]]; then
    info "Installing weekly reboot timer (${REBOOT_TIME})..."
    # Substitute the reboot time into the timer file
    sed "s|Sun \*-\*-\* 03:00:00|${REBOOT_TIME}|g" \
        "${INSTALL_DIR}/systemd/train-display-reboot.timer" > "${TIMER_FILE}"
    cp "${INSTALL_DIR}/systemd/train-display-reboot.target.service" "${TIMER_UNIT}" 2>/dev/null || true
    systemctl daemon-reload
    systemctl enable train-display-reboot.timer
    systemctl start train-display-reboot.timer
fi

# ---------------------------------------------------------------------------
# INST-14: Start service
# ---------------------------------------------------------------------------
info "Starting ${SERVICE_NAME} service..."
systemctl restart "${SERVICE_NAME}"
sleep 3
systemctl --no-pager status "${SERVICE_NAME}" || true

# ---------------------------------------------------------------------------
# INST-15: Offer to run validator
# ---------------------------------------------------------------------------
if confirm "Run validate.py to confirm API connectivity?"; then
    "${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/validate.py" || true
fi

# ---------------------------------------------------------------------------
# INST-16: Post-install summary
# ---------------------------------------------------------------------------
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
info "=== Installation Complete ==="
echo "  Station:     ${DEPARTURE_STATION}"
[[ -n "${DESTINATION_STATION}" ]] && echo "  Destination: ${DESTINATION_STATION}"
echo "  Service:     ${SERVICE_NAME} (enabled, started)"
echo ""
echo "  Web portal:  http://${PI_IP:-<pi-ip>}:${PORTAL_PORT}"
if [[ -z "${PORTAL_PASSWORD}" ]]; then
    echo "               (local access only — no password set)"
else
    echo "               (password protected — username: admin)"
fi
echo ""
echo "  Logs:        journalctl -u ${SERVICE_NAME} -f"
echo "  Update:      sudo bash ${INSTALL_DIR}/update.sh"
echo "  Reconfigure: sudo bash ${INSTALL_DIR}/install.sh"
