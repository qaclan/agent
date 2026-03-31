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

# ── Install Playwright ────────────────────────────────────────────────
info "Installing Playwright..."

# Step 1: Ensure Node.js + npm are available
if ! command -v npm >/dev/null 2>&1; then
    info "Node.js not found. Installing Node.js..."
    case "$OS" in
        macos)
            if command -v brew >/dev/null 2>&1; then
                brew install node
            else
                error "Homebrew is required to install Node.js on macOS. Install it from https://brew.sh then re-run this script."
            fi
            ;;
        linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update -qq && sudo apt-get install -y -qq nodejs npm
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y nodejs npm
            elif command -v yum >/dev/null 2>&1; then
                sudo yum install -y nodejs npm
            elif command -v apk >/dev/null 2>&1; then
                sudo apk add --quiet nodejs npm
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -Sy --noconfirm nodejs npm
            else
                error "Could not detect a supported package manager (apt, dnf, yum, apk, pacman). Install Node.js manually and re-run this script."
            fi
            ;;
    esac

    if ! command -v npm >/dev/null 2>&1; then
        error "Node.js installation failed. Install Node.js manually and re-run this script."
    fi
    info "Node.js installed."
fi

# Step 2: Install Playwright globally via npm
info "Installing Playwright via npm..."
npm install -g playwright || error "Failed to install Playwright. Run manually: npm install -g playwright"

if ! command -v playwright >/dev/null 2>&1; then
    error "Playwright installed but not found in PATH. Check your npm global bin path (npm bin -g)."
fi
info "Playwright installed."

# Step 3: Install Chromium system dependencies + browser
info "Installing Chromium browser..."

# Install system deps separately (--with-deps can fail due to apt issues)
case "$OS" in
    linux)
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y -qq libnss3 libatk1.0-0 libatk-bridge2.0-0 \
                libcups2 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
                libpango-1.0-0 libcairo2 libasound2 libxshmfence1 2>/dev/null || true
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y nss atk at-spi2-atk cups-libs libXcomposite \
                libXdamage libXrandr mesa-libgbm pango cairo alsa-lib 2>/dev/null || true
        elif command -v yum >/dev/null 2>&1; then
            sudo yum install -y nss atk at-spi2-atk cups-libs libXcomposite \
                libXdamage libXrandr mesa-libgbm pango cairo alsa-lib 2>/dev/null || true
        elif command -v apk >/dev/null 2>&1; then
            sudo apk add --quiet nss cups-libs libxcomposite libxdamage \
                libxrandr mesa-gbm pango cairo alsa-lib 2>/dev/null || true
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -Sy --noconfirm nss cups libxcomposite libxdamage \
                libxrandr mesa pango cairo alsa-lib 2>/dev/null || true
        fi
        ;;
esac

# Download the browser (without --with-deps to avoid apt-get update failures)
PLAYWRIGHT_BROWSERS_PATH="${HOME}/.qaclan/browsers" playwright install chromium || \
    error "Failed to install Chromium. Run manually: playwright install chromium"
info "Chromium browser installed."

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
