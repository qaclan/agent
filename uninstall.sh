#!/bin/sh
set -e

INSTALL_DIR="/usr/local/bin"
BINARY_NAME="qaclan"
DATA_DIR="${HOME}/.qaclan"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}>>>${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}>>>${NC} %s\n" "$1"; }
error() { printf "${RED}>>>${NC} %s\n" "$1"; exit 1; }

echo ""
echo "This will remove:"
echo "  - qaclan binary from ${INSTALL_DIR}/${BINARY_NAME}"
echo "  - qaclan data directory: ${DATA_DIR} (includes isolated runtime: node_modules, venv, Chromium)"
echo ""
printf "Continue? [y/N] "
read -r REPLY
case "$REPLY" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
esac

# ── Remove qaclan binary ─────────────────────────────────────────────
if [ -f "${INSTALL_DIR}/${BINARY_NAME}" ]; then
    info "Removing qaclan binary..."
    if [ -w "${INSTALL_DIR}/${BINARY_NAME}" ]; then
        rm -f "${INSTALL_DIR}/${BINARY_NAME}"
    else
        sudo rm -f "${INSTALL_DIR}/${BINARY_NAME}"
    fi
    info "Binary removed."
else
    warn "qaclan binary not found at ${INSTALL_DIR}/${BINARY_NAME}, skipping."
fi

# ── Remove qaclan data directory ─────────────────────────────────────
if [ -d "${DATA_DIR}" ]; then
    info "Removing qaclan data directory (${DATA_DIR})..."
    rm -rf "${DATA_DIR}"
    info "Data directory removed."
else
    warn "Data directory ${DATA_DIR} not found, skipping."
fi

echo ""
info "qaclan has been fully uninstalled."
