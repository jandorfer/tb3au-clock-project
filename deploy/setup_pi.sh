#!/bin/bash
# Provision the tb3au e-ink clock on a Raspberry Pi.
#
# Run from anywhere; the script locates the repo root from its own path.
# Requires: git, Python 3.9+, passwordless sudo (see PI_ACCESS.md),
# and SPI/GPIO enabled (sudo raspi-config -> Interface Options).
#
# This is idempotent: re-running it is safe.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Repo root: $REPO_ROOT"

echo "==> Initialising Waveshare SDK submodule"
git submodule update --init

echo "==> Installing Python dependencies"
python3 -m pip install -r requirements.txt

echo "==> Installing systemd unit (tb3au-mqtt.service)"
sudo cp deploy/tb3au-mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tb3au-mqtt.service

echo "==> Making tb3au.sh executable"
chmod +x tb3au.sh

echo "==> Installing cron jobs"
# Strip any prior tb3au entries (daily + auto-update) so we never duplicate,
# then install the canonical pair idempotently.
CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
NEW_CRON="$(printf '%s\n' "$CURRENT_CRON" | grep -vE 'tb3au\.sh|git pull --ff-only origin main|deploy/auto_update\.sh' || true)"
{
  printf '%s\n' "$NEW_CRON"
  echo "# tb3au clock"
  echo "0 0 * * * $REPO_ROOT/tb3au.sh"
  echo "*/15 * * * * $REPO_ROOT/deploy/auto_update.sh >> $REPO_ROOT/git_pull.log 2>&1"
} | crontab -
echo "    cron jobs installed/updated"

echo
echo "==> DONE. Next steps:"
echo "    1. Create .env from the template and fill in secrets:"
echo "         cp .env.example .env"
echo "       then edit OPENAI_API_KEY, API_NINJAS_KEY, and MQTT_* in $REPO_ROOT/.env"
echo "       (on this Pi you can also edit it directly over VNC - see PI_ACCESS.md)."
echo "    2. Restart the daemon so it picks up .env:"
echo "         sudo systemctl restart tb3au-mqtt.service"
echo "    3. Verify: journalctl -u tb3au-mqtt.service -f"
echo "    See PI_SETUP.md for the full walkthrough and MQTT broker setup in HA."
