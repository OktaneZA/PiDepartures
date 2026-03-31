#!/usr/bin/env bash
# Train Departure Display (.NET) — Installer
# Run on the Raspberry Pi as root: sudo bash install-dotnet.sh
# Installs .NET 8 SDK, builds the project, and configures the systemd service.

set -euo pipefail

REPO_URL="https://github.com/OktaneZA/PiDepartures.git"
INSTALL_DIR="/opt/train-display"
DOTNET_DIR="${INSTALL_DIR}/dotnet"
PUBLISH_DIR="${INSTALL_DIR}/dotnet-publish"
CONFIG_DIR="/etc/train-display"
CONFIG_FILE="${CONFIG_DIR}/config"
SERVICE_NAME="train-display"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOGFILE="/var/log/train-display-install.log"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ ! -f /proc/device-tree/model ]] || ! grep -qi "raspberry" /proc/device-tree/model; then
    error "This installer must run on a Raspberry Pi."
fi
echo -e "${GREEN}[INFO]${NC} Detected: $(cat /proc/device-tree/model)"

if [[ $EUID -ne 0 ]]; then
    error "Please run as root: sudo bash install-dotnet.sh"
fi

# ---------------------------------------------------------------------------
# Interactive configuration (before tee redirect)
# ---------------------------------------------------------------------------
DESTINATION_STATION=""
PLATFORM_FILTER=""
PORTAL_ENABLED="true"
PORTAL_PASSWORD=""
PORTAL_PORT=$(shuf -i 8000-9999 -n 1)

echo ""
echo -e "${GREEN}[INFO]${NC} === Configuration ==="
echo "  (.NET version — all other settings can be changed via the web portal)"
echo ""

# API key (hidden input)
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
    echo -e "${YELLOW}[WARN]${NC} CRS code must be exactly 3 uppercase letters. Try again."
done

# Optional: destination filter
read -r -p "Filter by destination CRS (press Enter to skip): " DESTINATION_STATION
DESTINATION_STATION="${DESTINATION_STATION^^}"
if [[ -n "${DESTINATION_STATION}" ]] && ! [[ "${DESTINATION_STATION}" =~ ^[A-Z]{3}$ ]]; then
    echo -e "${YELLOW}[WARN]${NC} Invalid destination CRS — ignoring"
    DESTINATION_STATION=""
fi

# ---------------------------------------------------------------------------
# Start logging
# ---------------------------------------------------------------------------
exec > >(tee -a "${LOGFILE}") 2>&1
info "Logging to ${LOGFILE}"

trap 'echo -e "${RED}[ERROR]${NC} Install failed at line ${LINENO} (exit code $?). Full log: ${LOGFILE}" >&2' ERR

# ---------------------------------------------------------------------------
# Enable SPI
# ---------------------------------------------------------------------------
if ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    info "Enabling SPI interface..."
    raspi-config nonint do_spi 0
else
    info "SPI already enabled"
fi

# ---------------------------------------------------------------------------
# Install .NET 8 SDK
# ---------------------------------------------------------------------------
if ! command -v dotnet &>/dev/null || ! dotnet --list-sdks 2>/dev/null | grep -q "^8\."; then
    info "Installing .NET 8 SDK (this may take a few minutes)..."
    curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
    chmod +x /tmp/dotnet-install.sh
    /tmp/dotnet-install.sh --channel 8.0 --install-dir /usr/share/dotnet
    ln -sf /usr/share/dotnet/dotnet /usr/local/bin/dotnet
    rm /tmp/dotnet-install.sh
    info ".NET $(dotnet --version) installed"
else
    info ".NET $(dotnet --version) already installed"
fi

# ---------------------------------------------------------------------------
# Clone or update repo
# ---------------------------------------------------------------------------
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing installation..."
    git -C "${INSTALL_DIR}" pull --ff-only || error "git pull failed"
else
    info "Cloning repository to ${INSTALL_DIR}..."
    git clone "${REPO_URL}" "${INSTALL_DIR}" || error "git clone failed"
fi

# ---------------------------------------------------------------------------
# Build and publish
# ---------------------------------------------------------------------------
info "Building .NET project (this may take several minutes on a Pi Zero)..."

ARCH=$(uname -m)
if [[ "${ARCH}" == "aarch64" ]]; then
    RID="linux-arm64"
else
    RID="linux-arm"
fi

dotnet publish "${DOTNET_DIR}/src/PiDepartures/PiDepartures.csproj" \
    -c Release \
    -r "${RID}" \
    --self-contained \
    -o "${PUBLISH_DIR}" \
    -p:PublishSingleFile=true \
    -p:PublishTrimmed=false \
    2>&1 || error "dotnet publish failed"

info "Published to ${PUBLISH_DIR} (runtime: ${RID})"

# ---------------------------------------------------------------------------
# Create system user
# ---------------------------------------------------------------------------
if ! id -u train-display &>/dev/null; then
    info "Creating train-display system user..."
    useradd --system --no-create-home --shell /usr/sbin/nologin train-display
fi
usermod -aG gpio,spi train-display
info "train-display user in gpio and spi groups"

# ---------------------------------------------------------------------------
# Write config file
# ---------------------------------------------------------------------------
info "Writing config to ${CONFIG_FILE}..."
mkdir -p "${CONFIG_DIR}"

cat > "${CONFIG_FILE}" <<EOF
# Train Departure Display — configuration
# Managed by installer / web portal — edit with care.

API_KEY=${API_KEY}
DEPARTURE_STATION=${DEPARTURE_STATION}
EOF

[[ -n "${DESTINATION_STATION}" ]] && echo "DESTINATION_STATION=${DESTINATION_STATION}" >> "${CONFIG_FILE}"
[[ -n "${PLATFORM_FILTER}" ]]     && echo "PLATFORM_FILTER=${PLATFORM_FILTER}"         >> "${CONFIG_FILE}"

cat >> "${CONFIG_FILE}" <<EOF

REFRESH_TIME=120
SCREEN_ROTATION=2
FIRST_DEPARTURE_BOLD=true
SHOW_DEPARTURE_NUMBERS=false
DUAL_SCREEN=false

PORTAL_ENABLED=${PORTAL_ENABLED}
PORTAL_PORT=${PORTAL_PORT}
EOF

chown root:train-display "${CONFIG_FILE}"
chmod 640 "${CONFIG_FILE}"
info "Config written (permissions 640, owner root:train-display)"

# ---------------------------------------------------------------------------
# Install systemd service
# ---------------------------------------------------------------------------
info "Installing systemd service..."
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Train Departure Display (.NET)
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=train-display
Group=train-display
EnvironmentFile=${CONFIG_FILE}
ExecStart=${PUBLISH_DIR}/PiDepartures
WorkingDirectory=${PUBLISH_DIR}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${CONFIG_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
info "Service enabled (will start on boot)"

# ---------------------------------------------------------------------------
# Post-install summary
# ---------------------------------------------------------------------------
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
info "=== Installation Complete (.NET) ==="
echo "  Station:      ${DEPARTURE_STATION}"
[[ -n "${DESTINATION_STATION}" ]] && echo "  Destination:  ${DESTINATION_STATION}"
echo "  Runtime:      .NET $(dotnet --version) (${RID})"
echo "  Service:      ${SERVICE_NAME} (enabled on boot, not yet started)"
echo ""
echo "  Web portal:   http://${PI_IP:-<pi-ip>}:${PORTAL_PORT}"
echo "                (local access only — no password set)"
echo ""
echo "  Manage via:   https://connect.raspberrypi.com  (Raspberry Pi Connect)"
echo ""
echo "  Start:        sudo systemctl start ${SERVICE_NAME}"
echo "  Stop:         sudo systemctl stop ${SERVICE_NAME}"
echo "  Logs:         journalctl -u ${SERVICE_NAME} -f"
echo "  Install log:  ${LOGFILE}"
echo "  Reconfigure:  sudo bash ${INSTALL_DIR}/dotnet/install-dotnet.sh"
echo ""
