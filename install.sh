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

# Install Playwright browsers (needed for recording and running web tests)
info "Installing Playwright browsers..."
if command -v qaclan >/dev/null 2>&1; then
    # The binary bundles the Playwright driver — use it to install browsers
    PLAYWRIGHT_BROWSERS_PATH="${HOME}/.qaclan/browsers" "${INSTALL_DIR}/${BINARY_NAME}" _pw-install 2>/dev/null || true
fi

# If the binary doesn't support _pw-install yet, try using the npx/pip fallback
if [ ! -d "${HOME}/.qaclan/browsers" ] || [ -z "$(ls -A "${HOME}/.qaclan/browsers" 2>/dev/null)" ]; then
    if command -v npx >/dev/null 2>&1; then
        PLAYWRIGHT_BROWSERS_PATH="${HOME}/.qaclan/browsers" npx playwright install chromium 2>/dev/null || true
    elif command -v pip3 >/dev/null 2>&1; then
        pip3 install playwright -q 2>/dev/null && PLAYWRIGHT_BROWSERS_PATH="${HOME}/.qaclan/browsers" playwright install chromium 2>/dev/null || true
    fi
fi

if [ -d "${HOME}/.qaclan/browsers" ] && [ -n "$(ls -A "${HOME}/.qaclan/browsers" 2>/dev/null)" ]; then
    info "Playwright browsers installed."
else
    warn "Could not auto-install Playwright browsers."
    warn "Recording/running web tests requires Chromium. Install manually:"
    warn "  npx playwright install chromium"
    warn "  OR: pip3 install playwright && playwright install chromium"
fi

# Verify
if command -v qaclan >/dev/null 2>&1; then
    info "qaclan installed successfully!"
    echo ""
    echo "  Get started:"
    echo "    qaclan login          # Authenticate with your API key"
    echo "    qaclan serve          # Launch the web UI"
    echo "    qaclan --help         # See all commands"
    echo ""
else
    warn "Installed to ${INSTALL_DIR}/${BINARY_NAME} but it's not in your PATH."
    warn "Add ${INSTALL_DIR} to your PATH, or run directly: ${INSTALL_DIR}/${BINARY_NAME}"
fi
