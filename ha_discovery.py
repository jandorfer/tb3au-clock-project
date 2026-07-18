"""Home Assistant MQTT Discovery for the tb3au e-ink clock.

Builds and publishes MQTT discovery config messages so Home Assistant creates a
proper *device* (with entities) automatically -- no manual YAML needed.

The daemon (tb3au_mqtt.py) calls ``publish_discovery()`` on connect, and again
whenever Home Assistant announces itself online (``homeassistant/status`` ->
``"online"``), so the device is (re)created after an HA restart too.

Schema reference: https://www.home-assistant.io/docs/mqtt/discovery/
"""

import json

# Discovery prefix used by Home Assistant (change here only if you also changed
# it in HA's MQTT options).
DISCOVERY_PREFIX = "homeassistant"

# Local topics (must match tb3au_mqtt.py).
TOPIC_STATUS = "tb3au/status"
TOPIC_STATE = "tb3au/display/state"
TOPIC_SET = "tb3au/display/set"

DEVICE = {
    "identifiers": ["tb3au-epd"],
    "name": "E-ink Clock",
    "manufacturer": "tb3au",
    "model": 'Waveshare 4.2" e-Paper (400x300)',
    "sw_version": "1.0",
}

ORIGIN = {
    "name": "tb3au-clock",
    "sw": "1.0",
    "url": "https://github.com/jandorfer/tb3au-clock-project",
}

AVAILABILITY = [
    {
        "topic": TOPIC_STATUS,
        "payload_available": "online",
        "payload_not_available": "offline",
    }
]


def _configs():
    """Yield (component, object_id, config_dict) tuples for each entity."""
    # Connection state (online/offline) from the LWT/availability topic.
    yield (
        "binary_sensor",
        "tb3au_epd_connection",
        {
            "name": "Connection",
            "unique_id": "tb3au_epd_connection",
            "device_class": "connectivity",
            "state_topic": TOPIC_STATUS,
            "payload_on": "online",
            "payload_off": "offline",
            "availability": AVAILABILITY,
            "device": DEVICE,
            "qos": 1,
        },
    )
    # Last rendered text (the daemon echoes state to tb3au/display/state).
    yield (
        "sensor",
        "tb3au_epd_last_shown",
        {
            "name": "Last Shown",
            "unique_id": "tb3au_epd_last_shown",
            "state_topic": TOPIC_STATE,
            "value_template": (
                "{% if value_json.mode == 'joke' %}(joke) {{ value_json.text }}"
                "{% elif value_json.mode == 'clear' %}(cleared)"
                "{% elif value_json.text %}{{ value_json.text }}"
                "{% else %}(image){% endif %}"
            ),
            "json_attributes_topic": TOPIC_STATE,
            "availability": AVAILABILITY,
            "device": DEVICE,
            "icon": "mdi:book-open-page-variant",
            "qos": 1,
        },
    )
    # Free-text message push (HA text box -> {"mode":"text","text":"..."}).
    yield (
        "text",
        "tb3au_epd_message",
        {
            "name": "Display Message",
            "unique_id": "tb3au_epd_message",
            "command_topic": TOPIC_SET,
            "command_template": '{"mode":"text","text":"{{ value }}"}',
            "state_topic": TOPIC_STATE,
            "value_template": "{{ value_json.text if value_json.text else '' }}",
            "mode": "text",
            "min": 1,
            "max": 200,
            "availability": AVAILABILITY,
            "device": DEVICE,
            "icon": "mdi:message-text-outline",
            "qos": 1,
        },
    )
    # Preset: re-run the daily joke.
    yield (
        "button",
        "tb3au_epd_joke",
        {
            "name": "Show Joke",
            "unique_id": "tb3au_epd_joke",
            "command_topic": TOPIC_SET,
            "payload_press": '{"mode":"joke"}',
            "availability": AVAILABILITY,
            "device": DEVICE,
            "icon": "mdi:emoticon-happy",
            "entity_category": "action",
            "qos": 1,
            "retain": False,
        },
    )
    # Preset: blank the panel.
    yield (
        "button",
        "tb3au_epd_clear",
        {
            "name": "Clear Screen",
            "unique_id": "tb3au_epd_clear",
            "command_topic": TOPIC_SET,
            "payload_press": '{"mode":"clear"}',
            "availability": AVAILABILITY,
            "device": DEVICE,
            "icon": "mdi:delete",
            "entity_category": "action",
            "qos": 1,
            "retain": False,
        },
    )


def publish_discovery(client):
    """Publish all discovery configs (retained) so HA creates the device."""
    for component, object_id, config in _configs():
        topic = "%s/%s/%s/config" % (DISCOVERY_PREFIX, component, object_id)
        client.publish(topic, json.dumps(config), qos=1, retain=True)
