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
echo "  - qaclan data directory: ${DATA_DIR}"
echo "  - Playwright (global npm package)"
echo "  - Playwright browsers (~/.cache/ms-playwright)"
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

# ── Remove Playwright browsers ───────────────────────────────────────
PW_CACHE="${HOME}/.cache/ms-playwright"
if [ -d "${PW_CACHE}" ]; then
    info "Removing Playwright browsers (${PW_CACHE})..."
    rm -rf "${PW_CACHE}"
    info "Playwright browsers removed."
else
    warn "Playwright browser cache not found at ${PW_CACHE}, skipping."
fi

# ── Uninstall Playwright npm package ─────────────────────────────────
if command -v npm >/dev/null 2>&1; then
    if npm list -g playwright >/dev/null 2>&1; then
        info "Uninstalling Playwright (npm global)..."
        npm uninstall -g playwright
        info "Playwright uninstalled."
    else
        warn "Playwright npm package not found globally, skipping."
    fi
else
    warn "npm not found, skipping Playwright package removal."
fi

echo ""
info "qaclan has been fully uninstalled."
