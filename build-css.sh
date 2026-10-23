#!/usr/bin/env bash
# Compile Tailwind once into static/css/tailwind.css (committed, so the Pi needs no build step).
# Usage: ./build-css.sh [--watch]
set -euo pipefail
cd "$(dirname "$0")"

VERSION="v3.4.17"
BIN="bin/tailwindcss-${VERSION}"

if [ ! -x "$BIN" ]; then
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)             ASSET="tailwindcss-macos-arm64" ;;
        Darwin-x86_64)            ASSET="tailwindcss-macos-x64" ;;
        Linux-aarch64|Linux-arm64) ASSET="tailwindcss-linux-arm64" ;;
        Linux-x86_64)             ASSET="tailwindcss-linux-x64" ;;
        *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
    esac
    mkdir -p bin
    echo "Downloading Tailwind CLI ${VERSION} (${ASSET})..."
    curl -fsSL -o "$BIN" "https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/${ASSET}"
    chmod +x "$BIN"
fi

exec "$BIN" -c tailwind.config.js -i static/css/tailwind.src.css -o static/css/tailwind.css --minify "$@"
