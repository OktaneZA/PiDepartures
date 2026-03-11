#!/usr/bin/env bash
# Train Departure Display — Updater
# Run on the Pi as root: sudo bash /opt/train-display/update.sh

set -euo pipefail

INSTALL_DIR="/opt/train-display"
SERVICE_NAME="train-display"

info() { echo "[INFO] $*"; }

info "Pulling latest code..."
git -C "${INSTALL_DIR}" pull --ff-only

info "Updating Python dependencies..."
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

info "Restarting service..."
systemctl restart "${SERVICE_NAME}"

info "Done. Logs: journalctl -u ${SERVICE_NAME} -f"
