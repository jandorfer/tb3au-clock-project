#!/bin/sh
# Daily joke for the tb3au e-ink clock (invoked by cron; see README §5).
#
# The e-paper is owned SOLELY by the MQTT daemon (tb3au_mqtt.py). The cron
# must NOT render directly: two processes sharing the SPI/GPIO lines breaks
# the long-running daemon (its hardware handle is clobbered when the other
# process exits and releases the GPIO). So the cron simply asks the daemon to
# render the joke over MQTT -- exactly the way Home Assistant drives it.
#
# Portable: resolves the repo root from this script's own location, so the
# cron entry can point at any path the repo is cloned to.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
python3 - <<'PY'
import os, json, paho.mqtt.client as mqtt

def _load_dotenv(path=".env"):
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass

_load_dotenv()
broker = os.environ.get("MQTT_BROKER", "192.168.1.215")
port = int(os.environ.get("MQTT_PORT", "1883"))
user = os.environ.get("MQTT_USER", "")
password = os.environ.get("MQTT_PASSWORD", "")

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
if user:
    c.username_pw_set(user, password)
c.connect(broker, port, 10)
c.publish("tb3au/display/set", json.dumps({"mode": "joke"}), qos=1, retain=False)
c.disconnect()
print("cron: published daily-joke request via MQTT")
PY
