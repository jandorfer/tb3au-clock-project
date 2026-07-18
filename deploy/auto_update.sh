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

if echo "$CHANGED" | grep -qE 'tb3au\.py|tb3au_mqtt\.py|ha_discovery\.py|^e-Paper'; then
  echo "[$(date -Is)] app/sdk changed -> daemon restart needed"
  RESTART=1
fi

if [ "$RESTART" -eq 1 ]; then
  echo "[$(date -Is)] restarting tb3au-mqtt.service"
  sudo systemctl restart tb3au-mqtt.service
fi

# Only re-assert joke mode when we actually restarted the daemon for a
# code/SDK change (RESTART==1). The retained `mode=joke` message already
# restores the daily joke on every (re)connect, so the routine 15-minute
# auto_update poll must NOT refresh the panel -- forcing a full e-ink refresh
# every 15 minutes is what was re-sticking the panel to black. Re-asserting
# here just clears any stale test render left over from before the deploy.
if [ "$RESTART" -eq 1 ] && [ -f tb3au_mqtt.py ]; then
  PYTHONPATH="$REPO_ROOT" python3 - <<'PYEOF'
import json, time, paho.mqtt.client as mqtt
import tb3au_mqtt as t
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.username_pw_set(t.USERNAME, t.PASSWORD)
try:
    c.connect(t.BROKER, t.PORT, 10)
    c.loop_start()
    c.publish("tb3au/display/set", json.dumps({"mode": "joke"}), qos=1, retain=True)
    time.sleep(2)
    c.loop_stop()
    print("[auto_update] re-asserted joke mode after restart (clears stale test renders)")
except Exception as e:
    print(f"[auto_update] could not re-assert joke mode: {e}")
PYEOF
fi

echo "[$(date -Is)] auto_update: done"
