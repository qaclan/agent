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

echo "Building ${OUTPUT_NAME}..."

python -m nuitka --standalone --onefile \
  --output-filename="$OUTPUT_NAME" \
  --output-dir=dist \
  --include-package=rich._unicode_data \
  --include-data-dir=web/static=web/static \
  qaclan.py

echo "Built: dist/${OUTPUT_NAME}"
