#!/usr/bin/env bash
set -euo pipefail

# Headful Chromium (plan 018 C2) needs an X display and a container has none.
# Xvfb ships with `patchright install --with-deps chromium`, but nothing
# starts it. Runs once per container start, so uvicorn's --reload children
# inherit both DISPLAY and a live server.
if [ -n "${DISPLAY:-}" ]; then
    display_num="${DISPLAY#:}"
    display_num="${display_num%%.*}"
    if [ ! -e "/tmp/.X${display_num}-lock" ]; then
        Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp &
    fi
fi

exec "$@"
