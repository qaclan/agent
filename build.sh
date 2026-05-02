#!/bin/bash
set -e

# Detect platform for artifact naming
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux*)  OS_NAME="linux" ;;
    Darwin*) OS_NAME="macos" ;;
    *)       OS_NAME="$(echo "$OS" | tr '[:upper:]' '[:lower:]')" ;;
esac

case "$ARCH" in
    x86_64|amd64)  ARCH_NAME="amd64" ;;
    aarch64|arm64) ARCH_NAME="arm64" ;;
    *)             ARCH_NAME="$ARCH" ;;
esac

OUTPUT_NAME="qaclan-${OS_NAME}-${ARCH_NAME}"

# Bake version into cli/_version.py before compile.
# Priority: $QACLAN_VERSION env > exact tag > git describe > placeholder.
if [[ -n "$QACLAN_VERSION" ]]; then
    VERSION="$QACLAN_VERSION"
elif VERSION="$(git describe --tags --exact-match 2>/dev/null)"; then
    VERSION="${VERSION#v}"
elif VERSION="$(git describe --tags --always --dirty 2>/dev/null)"; then
    VERSION="${VERSION#v}"
else
    VERSION="0.0.0+dev"
fi
echo "Baking version: $VERSION"
printf '__version__ = "%s"\n' "$VERSION" > cli/_version.py

# Suggest ccache for faster rebuilds
if ! command -v ccache &>/dev/null; then
    echo "Tip: install ccache for much faster rebuilds (sudo apt install ccache)"
fi

# Dev mode: --standalone (fast, produces a directory)
# Release mode (default): --onefile (slower, produces single binary)
ONEFILE_FLAG="--onefile"
if [[ "$1" == "--dev" ]]; then
    ONEFILE_FLAG="--standalone"
    echo "Building ${OUTPUT_NAME} (dev — standalone dir)..."
else
    echo "Building ${OUTPUT_NAME} (release — onefile)..."
fi

JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

python -m nuitka $ONEFILE_FLAG \
  --output-filename="$OUTPUT_NAME" \
  --output-dir=dist \
  --jobs="$JOBS" \
  --lto=yes \
  --assume-yes-for-downloads \
  --nofollow-import-to=tkinter,unittest,test,setuptools,pip,distutils,pydoc,doctest,xmlrpc,lib2to3,ensurepip,idlelib,turtle,playwright,pygments,markdown_it,mdurl,IPython,docutils,babel,asyncio,_codecs_cn,_codecs_hk,_codecs_iso2022,_codecs_jp,_codecs_kr,_codecs_tw,_multibytecodec \
  --noinclude-data-files='playwright/**' \
  --noinclude-data-files='pygments/**' \
  --include-package=rich \
  --include-data-dir=web/static=web/static \
  --include-data-dir=cli/runtime_assets=cli/runtime_assets \
  qaclan.py

echo "Built: dist/${OUTPUT_NAME}"
