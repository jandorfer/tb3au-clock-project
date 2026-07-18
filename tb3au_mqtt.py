"""MQTT daemon for the tb3au e-ink clock.

Listens on an MQTT topic for render commands from Home Assistant and draws
text / images onto the Waveshare 4.2" e-Paper display. Intended to run as a
systemd service alongside the daily cron job.

See MQTT_DESIGN.md for the topic/payload schema.
"""

import json
import os
import sys
import time

import paho.mqtt.client as mqtt

from tb3au import (
    render_both,
    render_clear,
    render_image,
    render_joke,
    render_text,
)
from ha_discovery import publish_discovery

TOPIC_SET = os.environ.get("TB3AU_TOPIC_SET", "tb3au/display/set")
TOPIC_STATE = os.environ.get("TB3AU_TOPIC_STATE", "tb3au/display/state")
TOPIC_STATUS = os.environ.get("TB3AU_TOPIC_STATUS", "tb3au/status")

BROKER = os.environ.get("MQTT_BROKER", "core-mosquitto")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
USERNAME = os.environ.get("MQTT_USER", "")
PASSWORD = os.environ.get("MQTT_PASSWORD", "")
CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "tb3au-epd")


def on_connect(client, userdata, flags, reason_code, properties):
    print("Connected to MQTT broker (rc=%s); subscribing to %s" % (reason_code, TOPIC_SET))
    client.subscribe(TOPIC_SET, qos=1)
    client.subscribe("homeassistant/status", qos=1)
    # Announce availability (retained).
    client.publish(TOPIC_STATUS, "online", qos=1, retain=True)
    # Advertise the Home Assistant device via MQTT discovery (retained).
    publish_discovery(client)


def on_disconnect(client, userdata, flags, reason_code, properties):
    print("MQTT disconnected (rc=%s)" % reason_code)


def handle_payload(payload):
    """Dispatch a decoded payload to a render function.

    Returns a dict describing the outcome (echo or error), or None if the
    payload should be silently ignored.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        print("Ignoring non-JSON payload")
        return None

    if not isinstance(data, dict):
        print("Ignoring non-object payload")
        return None

    mode = data.get("mode", "text")
    text = data.get("text", "")
    image = data.get("image")
    image_type = data.get("image_type", "base64")

    if mode == "clear":
        ok = render_clear()
    elif mode == "joke":
        ok = render_joke()
        if ok:
            text = ok
    elif mode == "text":
        ok = render_text(text)
    elif mode == "image":
        if not image:
            return {"error": "image mode requires 'image' field"}
        ok = render_image(image, image_type)
    elif mode == "both":
        if not image:
            return {"error": "both mode requires 'image' field"}
        ok = render_both(text, image, image_type)
    else:
        return {"error": "unknown mode: %s" % mode}

    if not ok:
        return {"error": "render failed"}
    return {"mode": mode, "text": text}


def on_message(client, userdata, msg):
    # Re-advertise the HA device when Home Assistant (re)starts.
    if getattr(msg, "topic", None) == "homeassistant/status":
        try:
            payload = getattr(msg, "payload", b"") or b""
            if payload.decode("utf-8", "replace").strip().lower() == "online":
                publish_discovery(client)
        except Exception:  # nosec B110 - best-effort re-advertise
            pass
        return
    result = handle_payload(msg.payload)
    state = {"ts": int(time.time())}
    if result is None:
        state.update({"status": "ignored"})
    elif "error" in result:
        state.update({"status": "error", "error": result["error"]})
    else:
        state.update({"status": "ok", "mode": result.get("mode"), "text": result.get("text")})

    try:
        client.publish(TOPIC_STATE, json.dumps(state), qos=1, retain=True)
    except Exception as e:
        print("Failed to publish state:", e)


def main():
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=CLIENT_ID,
    )
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)
    # Last-will: broker marks the panel offline if we drop unexpectedly.
    client.will_set(TOPIC_STATUS, "offline", qos=1, retain=True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try:
            print("Connecting to %s:%s ..." % (BROKER, PORT))
            client.connect(BROKER, PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            print("Interrupted, exiting")
            try:
                client.publish(TOPIC_STATUS, "offline", qos=1, retain=True)
                client.disconnect()
            except Exception:  # nosec B110 - ensure we still exit on Ctrl-C
                pass
            sys.exit(0)
        except Exception as e:
            print("Connection error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
