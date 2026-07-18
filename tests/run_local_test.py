"""Local, hardware-free test harness for tb3au / tb3au_mqtt.

Waveshare ships no emulator, so this module injects fake `waveshare_epd`,
`openai`, and `paho.mqtt` modules BEFORE importing the real code. The actual
render and MQTT-dispatch logic then runs against an in-memory "display" whose
final PIL image we capture, assert on, and (optionally) save as PNGs.

Importing this module sets up the fakes and imports the real `tb3au` /
`tb3au_mqtt`, so it is safe to use from both the CLI and pytest.

CLI usage:
    .venv/Scripts/python.exe tests/run_local_test.py            # full checks
    .venv/Scripts/python.exe tests/run_local_test.py --save-only # render PNGs only

Requires only Pillow + requests (already in requirements.txt). No broker, no
API keys, no e-paper hardware.
"""

import argparse
import base64
import io
import json
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# ---------------------------------------------------------------------------
# 1. Inject fakes into sys.modules so `import tb3au` / `import tb3au_mqtt`
#    succeed without hardware / network / extra packages.
# ---------------------------------------------------------------------------

# --- fake waveshare_epd.epd4in2_V2 (records the last displayed image) ---
fake_epd_pkg = types.ModuleType("waveshare_epd")
sys.modules["waveshare_epd"] = fake_epd_pkg

fake_epd2 = types.ModuleType("waveshare_epd.epd4in2_V2")


class FakeEPD:
    """Records the last displayed image instead of driving SPI/GPIO."""

    width = 400
    height = 300
    _last = None

    def __init__(self):
        pass

    def init(self):
        pass

    def Clear(self):
        FakeEPD._last = None

    def getbuffer(self, image):
        return image

    def display(self, buf):
        FakeEPD._last = buf.copy() if hasattr(buf, "copy") else buf

    def sleep(self):
        pass

    class epdconfig:
        @staticmethod
        def module_exit():
            pass


fake_epd2.EPD = FakeEPD
sys.modules["waveshare_epd.epd4in2_V2"] = fake_epd2

# --- fake openai (only used lazily for joke mode; not exercised here) ---
if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *a, **k):
            pass

    fake_openai.OpenAI = _OpenAI
    sys.modules["openai"] = fake_openai

# --- fake paho.mqtt.client (lets us import + drive tb3au_mqtt) ---
fake_paho = types.ModuleType("paho")
sys.modules["paho"] = fake_paho
fake_paho_mqtt = types.ModuleType("paho.mqtt")
sys.modules["paho.mqtt"] = fake_paho_mqtt
fake_paho_client = types.ModuleType("paho.mqtt.client")
sys.modules["paho.mqtt.client"] = fake_paho_client


class _FakeMqttClient:
    def __init__(self, *a, **k):
        pass

    def username_pw_set(self, *a, **k):
        pass

    def will_set(self, *a, **k):
        pass

    def subscribe(self, *a, **k):
        pass

    def publish(self, *a, **k):
        pass

    def reconnect_delay_set(self, *a, **k):
        pass

    def connect(self, *a, **k):
        pass

    def loop_forever(self, *a, **k):
        pass

    def disconnect(self, *a, **k):
        pass


fake_paho_client.Client = _FakeMqttClient
fake_paho_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)

# ---------------------------------------------------------------------------
# 2. Import the real code (now that fakes are in place).
# ---------------------------------------------------------------------------
from PIL import Image, ImageDraw
from PIL import ImageFont as _ImageFont

import tb3au
import tb3au_mqtt


# The real SDK ships Font.ttc inside the (gitignored) submodule, which is
# absent locally. Point tb3au.ImageFont at a stub so draw.text works, WITHOUT
# mutating PIL's real module (which would break ImageFont.load_default).
class _FontStub:
    @staticmethod
    def truetype(*a, **k):
        return _ImageFont.load_default()


tb3au.ImageFont = _FontStub

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 3. Helpers (shared by the CLI runner and pytest).
# ---------------------------------------------------------------------------


def last_image():
    return FakeEPD._last


def save_last(name):
    img = last_image()
    if img is not None:
        img.convert("RGB").save(os.path.join(OUT_DIR, name + ".png"))
    return img


def black_pixels(img):
    return sum(1 for p in img.getdata() if p == 0)


def make_test_image_b64():
    buf = io.BytesIO()
    img = Image.new("RGB", (120, 120), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 100, 100], outline=(0, 0, 0), width=6)
    d.text((30, 50), "IMG", fill=(0, 0, 0))
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


TEST_B64 = make_test_image_b64()

# Sample texts used by the render cases.
SAMPLE_TEXT = "Hello from the local test harness"
SAMPLE_CAPTION = "Caption text"


# ---------------------------------------------------------------------------
# 4. CLI runner.
# ---------------------------------------------------------------------------


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + extra) if extra else ""))
    return cond


def run_checks(save_only=False):
    """Run the render + dispatch checks.

    With save_only=True, only render the four sample cases and write PNGs,
    returning None (no assertions / no exit code semantics).
    """
    if save_only:
        tb3au.render_text(SAMPLE_TEXT)
        save_last("text")
        tb3au.render_image(TEST_B64, "base64")
        save_last("image")
        tb3au.render_both(SAMPLE_CAPTION, TEST_B64, "base64")
        save_last("both")
        tb3au.render_clear()
        save_last("clear")
        print("Saved render samples to: %s" % OUT_DIR)
        return None

    print("\n== render functions ==")
    results = []

    tb3au.render_text(SAMPLE_TEXT)
    img = save_last("text")
    results.append(check("render_text produces an image", img is not None))
    results.append(
        check(
            "render_text image is 300x400",
            img is not None and img.size == (300, 400),
            str(img.size) if img else "None",
        )
    )
    results.append(
        check(
            "render_text has black pixels",
            img is not None and black_pixels(img) > 0,
            "black=%d" % (black_pixels(img) if img else 0),
        )
    )

    tb3au.render_image(TEST_B64, "base64")
    img = save_last("image")
    results.append(check("render_image produces an image", img is not None))
    results.append(
        check(
            "render_image has black pixels",
            img is not None and black_pixels(img) > 0,
            "black=%d" % (black_pixels(img) if img else 0),
        )
    )

    tb3au.render_both(SAMPLE_CAPTION, TEST_B64, "base64")
    img = save_last("both")
    results.append(check("render_both produces an image", img is not None))
    results.append(
        check(
            "render_both has black pixels",
            img is not None and black_pixels(img) > 0,
            "black=%d" % (black_pixels(img) if img else 0),
        )
    )

    tb3au.render_clear()
    img = save_last("clear")
    results.append(check("render_clear produces an image", img is not None))
    results.append(
        check(
            "render_clear is all white (no black pixels)",
            img is not None and black_pixels(img) == 0,
            "black=%d" % (black_pixels(img) if img else -1),
        )
    )

    print("\n== mqtt dispatch ==")

    r = tb3au_mqtt.handle_payload(json.dumps({"mode": "text", "text": "hi"}).encode())
    results.append(check("dispatch text -> echo", r == {"mode": "text", "text": "hi"}, str(r)))

    r = tb3au_mqtt.handle_payload(
        json.dumps({"mode": "image", "image": TEST_B64, "image_type": "base64"}).encode()
    )
    results.append(check("dispatch image -> echo", r == {"mode": "image", "text": ""}, str(r)))

    r = tb3au_mqtt.handle_payload(json.dumps({"mode": "image"}).encode())
    results.append(
        check(
            "dispatch image without 'image' -> error", isinstance(r, dict) and "error" in r, str(r)
        )
    )

    r = tb3au_mqtt.handle_payload(json.dumps({"mode": "bogus"}).encode())
    results.append(
        check("dispatch unknown mode -> error", isinstance(r, dict) and "error" in r, str(r))
    )

    r = tb3au_mqtt.handle_payload(b"this is not json")
    results.append(check("dispatch non-JSON -> ignored (None)", r is None, str(r)))

    # joke mode with no API key -> render fails gracefully (error dict, no crash)
    r = tb3au_mqtt.handle_payload(json.dumps({"mode": "joke"}).encode())
    results.append(
        check(
            "dispatch joke without key -> error (no crash)",
            isinstance(r, dict) and "error" in r,
            str(r),
        )
    )

    # on_message should publish a retained state echo
    class FakeMsg:
        payload = json.dumps({"mode": "text", "text": "via on_message"}).encode()

    class FakeClient:
        published = []

        def publish(self, topic, payload, qos=None, retain=None):
            FakeClient.published.append((topic, payload))

    FakeClient.published.clear()
    tb3au_mqtt.on_message(FakeClient(), None, FakeMsg())
    results.append(
        check(
            "on_message publishes state to tb3au/display/state",
            any(t == tb3au_mqtt.TOPIC_STATE for t, _ in FakeClient.published),
            str([t for t, _ in FakeClient.published]),
        )
    )
    if FakeClient.published:
        state = json.loads(FakeClient.published[0][1])
        results.append(
            check("on_message state has status=ok", state.get("status") == "ok", str(state))
        )

    passed = sum(1 for c in results if c)
    total = len(results)
    print("\n%d/%d checks passed." % (passed, total))
    print("PNGs written to: %s" % OUT_DIR)
    return passed, total


def main():
    parser = argparse.ArgumentParser(description="Local (no-hardware) test harness.")
    parser.add_argument(
        "--save-only", action="store_true", help="Only render sample PNGs; skip assertions."
    )
    args = parser.parse_args()

    if args.save_only:
        run_checks(save_only=True)
        return

    result = run_checks(save_only=False)
    if result is None:
        return
    passed, total = result
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
