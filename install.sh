#!/bin/sh
set -e

REPO="qaclan/agent"
INSTALL_DIR="/usr/local/bin"
BINARY_NAME="qaclan"
PLAYWRIGHT_VERSION="1.58.0"

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
# Hard prerequisites: Node.js (with npm) and Python 3 (with pip). The qaclan
# binary no longer bundles a Playwright runtime — it shells out to system
# Node for JS/TS scripts and system Python for Python scripts.
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    error "Node.js (with npm) is required. Install Node.js 18+ from https://nodejs.org or your distro package manager, then re-run."
fi
if ! command -v python3 >/dev/null 2>&1; then
    error "Python 3 is required. Install python3 + pip from your distro package manager, then re-run."
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
    error "pip is required for python3. Install it (e.g. 'sudo apt-get install python3-pip') and re-run."
fi

# Install npm Playwright + @playwright/test + tsx at the pinned version.
info "Installing Playwright ${PLAYWRIGHT_VERSION} (npm: playwright + @playwright/test + tsx)..."
npm install -g \
    "playwright@${PLAYWRIGHT_VERSION}" \
    "@playwright/test@${PLAYWRIGHT_VERSION}" \
    tsx \
    || error "npm install failed. Run manually: npm install -g playwright@${PLAYWRIGHT_VERSION} @playwright/test@${PLAYWRIGHT_VERSION} tsx"

# Resolve a runner for the playwright CLI: prefer the bin on PATH, fall back
# to `npx playwright` (works even when the global npm bin dir isn't on PATH,
# which is common under sudo + nvm).
if command -v playwright >/dev/null 2>&1; then
    PW_RUN="playwright"
elif command -v npx >/dev/null 2>&1; then
    PW_RUN="npx --no-install playwright"
    warn "playwright bin not on PATH; using 'npx playwright' instead."
else
    error "Neither 'playwright' nor 'npx' is available. Check your Node.js install."
fi

# Install pip Playwright at the pinned version. --break-system-packages handles
# PEP 668 distros (Debian 12+, Ubuntu 24.04+); fall back to plain --user on
# older pip that doesn't recognize the flag.
info "Installing Playwright ${PLAYWRIGHT_VERSION} (pip)..."
if ! python3 -m pip install --user --break-system-packages "playwright==${PLAYWRIGHT_VERSION}" 2>/dev/null; then
    python3 -m pip install --user "playwright==${PLAYWRIGHT_VERSION}" \
        || error "pip install failed. Run manually: pip install --user playwright==${PLAYWRIGHT_VERSION}"
fi
info "Playwright (npm + pip) and tsx installed."

# Install all browsers + system dependencies. One install via the npm
# Playwright populates ~/.cache/ms-playwright; Python's pip-installed
# Playwright reads from the same cache, so no second download.
info "Installing all Playwright browsers (chromium, firefox, webkit) and system dependencies..."

if [ "$OS" = "linux" ]; then
    # sudo strips PATH; pass it through so $PW_RUN (which may be `npx ...`)
    # can locate node/npx/playwright via nvm or other PATH setups.
    if sudo env "PATH=$PATH" $PW_RUN install --with-deps chromium firefox webkit; then
        info "Browsers + system dependencies installed."
    else
        warn "Could not auto-install system libs (unsupported distro?). Falling back to browser-only install."
        $PW_RUN install chromium firefox webkit || \
            error "Failed to install browsers. Run manually: npx playwright install chromium firefox webkit"
        warn "If a browser fails to launch, install the libs reported in the error via your package manager."
    fi
else
    $PW_RUN install chromium firefox webkit || \
        error "Failed to install browsers. Run manually: npx playwright install chromium firefox webkit"
    info "Browsers installed."
fi

# Verify
if command -v qaclan >/dev/null 2>&1; then
    info "qaclan installed successfully!"
    echo ""
    echo "  Prerequisites: Node.js 18+ and Python 3.8+ (verified above)."
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
