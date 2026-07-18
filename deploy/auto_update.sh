#!/bin/bash
# Auto-update hook for the tb3au Pi.
#
# Pulls code + SDK from GitHub, then ONLY reinstalls dependencies / reinstalls
# the systemd unit / restarts the daemon when something that affects the
# running service actually changed. Safe to run frequently (every 15 min from
# cron) — a no-op pull costs nothing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "[$(date -Is)] auto_update: pull"
git pull --ff-only origin main

# Files changed by this pull (empty when already up to date).
CHANGED="$(git diff --name-only ORIG_HEAD HEAD 2>/dev/null || true)"
echo "[$(date -Is)] changed: ${CHANGED:-<none>}"

git submodule update --init

RESTART=0

if echo "$CHANGED" | grep -qE 'requirements.*\.txt'; then
  echo "[$(date -Is)] requirements changed -> pip install -r requirements.txt"
  python3 -m pip install -r requirements.txt
  RESTART=1
fi

if echo "$CHANGED" | grep -qE 'deploy/tb3au-mqtt\.service'; then
  echo "[$(date -Is)] unit file changed -> reinstall + daemon-reload"
  sudo cp deploy/tb3au-mqtt.service /etc/systemd/system/
  sudo systemctl daemon-reload
  RESTART=1
fi

if echo "$CHANGED" | grep -qE 'tb3au\.py|tb3au_mqtt\.py|^e-Paper'; then
  echo "[$(date -Is)] app/sdk changed -> daemon restart needed"
  RESTART=1
fi

if [ "$RESTART" -eq 1 ]; then
  echo "[$(date -Is)] restarting tb3au-mqtt.service"
  sudo systemctl restart tb3au-mqtt.service
fi

echo "[$(date -Is)] auto_update: done"
