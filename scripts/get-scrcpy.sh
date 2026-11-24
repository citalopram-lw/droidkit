#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Fetch a static scrcpy build into ~/.local/opt (no root needed).
set -euo pipefail
VER="${1:-3.3.4}"
URL="https://github.com/Genymobile/scrcpy/releases/download/v${VER}/scrcpy-linux-x86_64-v${VER}.tar.gz"
MIRROR="${SCRCPY_MIRROR:-https://gh-proxy.com/}"
DEST="$HOME/.local/opt"
mkdir -p "$DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "fetching $URL"
curl -fSL -o "$tmp/scrcpy.tar.gz" "${MIRROR}${URL}" || curl -fSL -o "$tmp/scrcpy.tar.gz" "$URL"
tar xzf "$tmp/scrcpy.tar.gz" -C "$DEST"
echo "installed: $(ls -d "$DEST"/scrcpy-linux-*/ | tail -1)"
