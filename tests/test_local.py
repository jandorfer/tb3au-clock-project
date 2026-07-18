"""pytest wrapper around the local (no-hardware) test harness.

Importing `run_local_test` injects the fake waveshare/openai/paho modules and
imports the real `tb3au` / `tb3au_mqtt`, so these tests exercise the actual
render and MQTT-dispatch logic against an in-memory display.

Run from the repo root:
    pytest
    pytest tests/test_local.py
"""

import json
import os
import sys

# Make the repo root importable (the harness does this too, but be explicit so
# `import run_local_test` always resolves regardless of pytest's import mode).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_local_test as harness  # noqa: E402

EXPECTED_SIZE = (400, 300)


# --- render functions -------------------------------------------------------


def test_render_text():
    harness.tb3au.render_text("Hello from pytest")
    img = harness.last_image()
    assert img is not None
    assert img.size == EXPECTED_SIZE
    assert harness.black_pixels(img) > 0


def test_render_markdown():
    harness.tb3au.render_text(
        "# Title\n**bold** word\n- a\n- b", markdown=True
    )
    img = harness.last_image()
    assert img is not None
    assert img.size == EXPECTED_SIZE
    assert harness.black_pixels(img) > 0


def test_render_image():
    harness.tb3au.render_image(harness.TEST_B64, "base64")
    img = harness.last_image()
    assert img is not None
    assert harness.black_pixels(img) > 0


def test_render_both():
    harness.tb3au.render_both("Caption", harness.TEST_B64, "base64")
    img = harness.last_image()
    assert img is not None
    assert harness.black_pixels(img) > 0


def test_render_clear_is_white():
    harness.tb3au.render_clear()
    img = harness.last_image()
    assert img is not None
    assert harness.black_pixels(img) == 0


# --- mqtt dispatch ----------------------------------------------------------


def test_dispatch_text_echo():
    r = harness.tb3au_mqtt.handle_payload(b'{"mode":"text","text":"hi"}')
    assert r == {"mode": "text", "text": "hi"}


def test_dispatch_image_echo():
    r = harness.tb3au_mqtt.handle_payload(
        b'{"mode":"image","image":"%s","image_type":"base64"}' % harness.TEST_B64.encode()
    )
    assert r == {"mode": "image", "text": ""}


def test_dispatch_image_missing_field_errors():
    r = harness.tb3au_mqtt.handle_payload(b'{"mode":"image"}')
    assert isinstance(r, dict) and "error" in r


def test_dispatch_unknown_mode_errors():
    r = harness.tb3au_mqtt.handle_payload(b'{"mode":"bogus"}')
    assert isinstance(r, dict) and "error" in r


def test_dispatch_non_json_ignored():
    assert harness.tb3au_mqtt.handle_payload(b"not json") is None


def test_dispatch_joke_without_key_errors():
    r = harness.tb3au_mqtt.handle_payload(b'{"mode":"joke"}')
    assert isinstance(r, dict) and "error" in r


def test_dispatch_joke_echo_includes_quote():
    tb = harness.tb3au
    saved = (tb.get_quote, tb.download_image, tb.img_convert)
    tb.get_quote = lambda: "Why did the chicken cross the road? To get to the other side!"
    tb.download_image = lambda q: None
    from PIL import Image as _PILImage

    tb.img_convert = lambda p: _PILImage.new("1", (300, 300), 255)
    try:
        r = harness.tb3au_mqtt.handle_payload(b'{"mode":"joke"}')
    finally:
        tb.get_quote, tb.download_image, tb.img_convert = saved
    assert r == {
        "mode": "joke",
        "text": "Why did the chicken cross the road? To get to the other side!",
    }


def test_on_message_publishes_state():
    class Msg:
        topic = harness.tb3au_mqtt.TOPIC_SET
        payload = b'{"mode":"text","text":"via on_message"}'

    class Client:
        published = []

        def publish(self, topic, payload, qos=None, retain=None):
            Client.published.append((topic, payload))

    Client.published.clear()
    harness.tb3au_mqtt.on_message(Client(), None, Msg())
    assert any(t == harness.tb3au_mqtt.TOPIC_STATE for t, _ in Client.published)
    state = json.loads(Client.published[0][1])
    assert state.get("status") == "ok"
