#!/bin/sh
set -e

REPO="qaclan/agent"
INSTALL_DIR="/usr/local/bin"
BINARY_NAME="qaclan"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}>>>${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}>>>${NC} %s\n" "$1"; }
error() { printf "${RED}>>>${NC} %s\n" "$1"; exit 1; }

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)  OS="linux" ;;
    Darwin*) OS="macos" ;;
    *)       error "Unsupported OS: $OS" ;;
esac

# Detect architecture
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *)             error "Unsupported architecture: $ARCH" ;;
esac

info "Detected platform: ${OS}-${ARCH}"

# Get latest release tag from GitHub API
info "Fetching latest release..."
LATEST_URL="https://api.github.com/repos/${REPO}/releases/latest"

if command -v curl >/dev/null 2>&1; then
    RELEASE_JSON=$(curl -fsSL "$LATEST_URL")
elif command -v wget >/dev/null 2>&1; then
    RELEASE_JSON=$(wget -qO- "$LATEST_URL")
else
    error "curl or wget is required"
fi

# Parse tag name and download URL
TAG=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"//;s/".*//')
ASSET_NAME="qaclan-${OS}-${ARCH}"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET_NAME}"

if [ -z "$TAG" ]; then
    error "Could not determine latest release. Check https://github.com/${REPO}/releases"
fi

info "Installing qaclan ${TAG} (${OS}-${ARCH})..."

# Download to temp file
TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl -fSL --progress-bar "$DOWNLOAD_URL" -o "$TMP_FILE"
elif command -v wget >/dev/null 2>&1; then
    wget --show-progress -qO "$TMP_FILE" "$DOWNLOAD_URL"
fi

chmod +x "$TMP_FILE"

# Install — use sudo if needed
if [ -w "$INSTALL_DIR" ]; then
    mv "$TMP_FILE" "${INSTALL_DIR}/${BINARY_NAME}"
else
    info "Writing to ${INSTALL_DIR} requires sudo..."
    sudo mv "$TMP_FILE" "${INSTALL_DIR}/${BINARY_NAME}"
    sudo chmod +x "${INSTALL_DIR}/${BINARY_NAME}"
fi

# ── Provision isolated runtime ────────────────────────────────────────
# qaclan provisions an isolated runtime under ~/.qaclan/runtime/ (Node deps +
# Python venv + Chromium). Hard prerequisites: Node.js (with npm) + Python 3.
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    error "Node.js (with npm) is required. Install Node.js 18+ from https://nodejs.org or your distro package manager, then re-run."
fi
if ! command -v python3 >/dev/null 2>&1; then
    error "Python 3 is required. Install python3 + venv from your distro package manager, then re-run."
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
    error "python3 venv module missing. Install it (e.g. 'sudo apt-get install python3-venv') and re-run."
fi

# Linux system libs needed by Chromium (the runtime's bundled Chromium still
# needs these shared libs from the host). On non-apt distros, surface a
# warning and let the user install equivalents.
if [ "$OS" = "linux" ]; then
    info "Installing Linux libs required by Chromium (sudo)..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq || true
        sudo apt-get install -y --no-install-recommends \
            libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
            libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
            libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
            2>/dev/null || warn "apt-get install of Chromium libs failed (unsupported distro?). Browser may not launch."
    else
        warn "Non-apt distro: install Chromium runtime libs manually if browser fails to launch."
    fi
fi

# Hand off to binary: provision ~/.qaclan/runtime/ (npm install + venv + Chromium).
info "Initializing qaclan runtime (npm install + venv + Chromium)..."
qaclan setup --runtime-only \
    || error "Runtime setup failed. Re-run manually: qaclan setup --runtime-only"

# Verify
if command -v qaclan >/dev/null 2>&1; then
    info "qaclan installed successfully!"
    echo ""
    echo "  Prerequisites: Node.js 18+ and Python 3.9+ (verified above)."
    echo ""
    echo "  Get started:"
    echo "    qaclan login --key <your_auth_key>   # Authenticate (key from qaclan.com Settings)"
    echo "    qaclan serve                         # Launch the web UI"
    echo "    qaclan --help                        # See all commands"
    echo ""
else
    warn "Installed to ${INSTALL_DIR}/${BINARY_NAME} but it's not in your PATH."
    warn "Add ${INSTALL_DIR} to your PATH, or run directly: ${INSTALL_DIR}/${BINARY_NAME}"
fi
