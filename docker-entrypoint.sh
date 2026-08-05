#!/usr/bin/env bash
set -euo pipefail

# Headful Chromium (plan 018 C2) needs an X display and a container has none.
# Xvfb ships with `patchright install --with-deps chromium`, but nothing
# starts it. Runs once per container start, so uvicorn's --reload children
# inherit both DISPLAY and a live server.
if [ -n "${DISPLAY:-}" ]; then
    display_num="${DISPLAY#:}"
    display_num="${display_num%%.*}"
    # `docker compose stop` kills Xvfb but leaves /tmp intact, so on the next
    # `start` the lock file is present with no server behind it and the guard
    # below would skip the launch forever -- every headful render then fails
    # with "Missing X server or $DISPLAY" until the container is recreated
    # (hit for real on 2026-08-05 after the plan 019 backfill restart).
    # The lock file holds the server's pid; if that process is gone the lock
    # is stale and must be cleared or Xvfb refuses to bind the display.
    if [ -e "/tmp/.X${display_num}-lock" ]; then
        xvfb_pid="$(tr -d ' ' < "/tmp/.X${display_num}-lock" 2>/dev/null || true)"
        if [ -z "$xvfb_pid" ] || ! kill -0 "$xvfb_pid" 2>/dev/null; then
            rm -f "/tmp/.X${display_num}-lock" "/tmp/.X11-unix/X${display_num}"
        fi
    fi
    if [ ! -e "/tmp/.X${display_num}-lock" ]; then
        Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp &
    fi
fi

exec "$@"
