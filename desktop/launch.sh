#!/usr/bin/env bash
# Opens idea-bank-v2 as a chrome-less "app window" (no address bar/tabs)
# instead of a plain browser tab, so the Application-menu icon feels like
# a real desktop app. Starts the local server first if it isn't already
# running, so clicking the icon works even right after login.
set -euo pipefail

URL="http://127.0.0.1:8420/"

if ! systemctl --user is-active --quiet idea-bank-v2-server.service; then
    systemctl --user start idea-bank-v2-server.service
    for _ in $(seq 1 20); do
        curl -sf "$URL" >/dev/null 2>&1 && break
        sleep 0.25
    done
fi

for browser in brave brave-browser chromium chromium-browser google-chrome; do
    if command -v "$browser" >/dev/null 2>&1; then
        exec "$browser" --app="$URL" --new-window
    fi
done

# no Chromium-family browser found (--app is a Chromium-only flag) --
# fall back to a normal tab in whatever the default browser is
exec xdg-open "$URL"
