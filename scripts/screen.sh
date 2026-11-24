#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Interactive screen for the container: video + (by default) mouse/touch control.
#
#   scripts/screen.sh [serial] [--watch] [-- extra scrcpy args]
#
# --watch keeps the window read-only. Use it when you drive the device through
# `droidkit touch ...` instead: scrcpy's own input lands as an injected event
# (deviceId = -1), while the uinput injector produces a real touchscreen device.
set -euo pipefail

SERIAL="${1:-127.0.0.1:5564}"
shift || true
WATCH=0
if [ "${1:-}" = "--watch" ]; then WATCH=1; shift; fi

find_scrcpy() {
    if [ -n "${SCRCPY:-}" ] && [ -x "$SCRCPY" ]; then echo "$SCRCPY"; return; fi
    for c in "$HOME"/.local/opt/scrcpy-*/scrcpy; do
        [ -x "$c" ] && { echo "$c"; return; }
    done
    command -v scrcpy && return
    cat >&2 <<'EOF'
scrcpy not found. Install one of:
  - apt install scrcpy                     (needs root)
  - scripts/get-scrcpy.sh                  (static build into ~/.local/opt)
EOF
    exit 1
}

SCRCPY_BIN="$(find_scrcpy)"
ARGS=(--serial "$SERIAL" --max-size 1080 --max-fps 60 --no-audio --window-title "droidkit:$SERIAL")
if [ "$WATCH" = "1" ]; then
    ARGS+=(--no-control)          # read-only window; drive it with `droidkit touch`
else
    ARGS+=(--stay-awake)
fi

exec "$SCRCPY_BIN" "${ARGS[@]}" "$@"
