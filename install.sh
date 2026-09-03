#!/usr/bin/env bash
# Sets up idea-bank-v2: venv + deps, CLI on PATH, and the new (v2) systemd
# user units. Never touches ~/ideas/ or the old idea-triage / idea-horizon-review
# units -- those are left exactly as they are.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
LOCAL_BIN="$HOME/.local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "==> project dir: $PROJECT_DIR"

echo "==> creating venv (if needed)"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

echo "==> installing dependencies"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"

echo "==> linking CLI onto PATH"
mkdir -p "$LOCAL_BIN"
ln -sf "$PROJECT_DIR/cli/idea" "$LOCAL_BIN/idea"
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo "    NOTE: $LOCAL_BIN is not on your PATH. Add it in ~/.zshrc, e.g.:"
    echo "          export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo "==> installing systemd user units (idea-bank-v2-*, new names only)"
mkdir -p "$SYSTEMD_USER_DIR"
cp "$PROJECT_DIR"/systemd/idea-bank-v2-*.service "$SYSTEMD_USER_DIR/"
cp "$PROJECT_DIR"/systemd/idea-bank-v2-*.timer "$SYSTEMD_USER_DIR/"

systemctl --user daemon-reload

echo "==> enabling + starting the local server (idea-bank-v2-server.service)"
systemctl --user enable --now idea-bank-v2-server.service

echo "==> enabling the triage and horizon-review timers"
systemctl --user enable --now idea-bank-v2-triage.timer
systemctl --user enable --now idea-bank-v2-horizon-review.timer

echo ""
echo "==> done."
echo "    GUI:        http://127.0.0.1:8420/"
echo "    Capture:    idea \"some text\""
echo "    Migrate:    $VENV_DIR/bin/python $PROJECT_DIR/scripts/migrate.py"
echo ""
echo "    The old ~/ideas/ system (inbox.md, expire.sh, idea-triage.timer,"
echo "    idea-horizon-review.timer) was NOT touched and is untouched by this script."
