import base64
import io
import json
import os
import sys

import requests

_BASE = os.path.dirname(os.path.abspath(__file__))
_EPAPER = os.path.join(_BASE, "e-Paper", "RaspberryPi_JetsonNano", "python")
picdir = os.path.join(_EPAPER, "pic")
libdir = os.path.join(_EPAPER, "lib")  # SDK is a git submodule checked out at ./e-Paper
if os.path.exists(libdir):
    sys.path.append(libdir)

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd4in2_V2


def _load_dotenv(path=None):
    """Minimal .env loader (no external dependency)."""
    if path is None:
        path = os.path.join(_BASE, ".env")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

black = 0
white = 1

IMG_PATH = os.path.join(_BASE, "generated_image.png")

# Module-level display state (mirrors the original globals so render helpers
# and show_error() can share the active canvas).
epd = None
font15 = None
image = None
draw = None

# Lazily-created OpenAI client (only needed for joke mode).
_client = None


def get_openai_client():
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY (set it in .env)")
        _client = OpenAI(api_key=api_key)
    return _client


def init_display():
    """Initialise the e-paper panel and the shared module state."""
    global epd, font15, image, draw
    epd = epd4in2_V2.EPD()
    epd.init()
    font15 = ImageFont.truetype(os.path.join(picdir, "Font.ttc"), 15)
    image = None
    draw = None
    return epd, font15


def clear_display(epd):
    global image, draw
    epd.Clear()
    image = Image.new("1", (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    epd.display(epd.getbuffer(image))


def get_quote():
    api_key = os.environ.get("API_NINJAS_KEY")
    if not api_key:
        raise RuntimeError("Missing API_NINJAS_KEY (set it in .env)")
    api_url = "https://api.api-ninjas.com/v1/jokes"
    response = requests.get(api_url, headers={"X-Api-Key": api_key}, timeout=15)
    response.raise_for_status()
    data = json.loads(response.text)
    return data[0]["joke"]


def download_image(quote):
    prompt = (
        "You are a cartoonist for a newspaper. Create a funny pencil drawing "
        "to accompany the quote of the day: " + quote
    )
    img = get_openai_client().images.generate(
        prompt=prompt,
        model="gpt-image-1",
        n=1,
        size="1024x1024",
        quality="medium",
    )
    image_bytes = base64.b64decode(img.data[0].b64_json)
    with open(IMG_PATH, "wb") as f:
        f.write(image_bytes)
    print("Image downloaded and saved as 'generated_image.png'")


def img_convert(img_file):
    img = Image.open(img_file)
    img = img.resize((300, 300), Image.LANCZOS)
    img = img.rotate(90)
    img = img.convert("1")  # convert to black & white
    return img


def break_string_into_array(string, max_length):
    words = string.split()
    result = []
    current_substring = ""

    for word in words:
        if len(current_substring) + len(word) + 1 <= max_length:
            current_substring += word + " "
        else:
            result.append(current_substring.strip())
            current_substring = word + " "

    if current_substring:
        result.append(current_substring.strip())

    return result


def show_error(epd, message):
    """Render an error message on the panel instead of leaving it blank."""
    try:
        clear_display(epd)
        lines = break_string_into_array(message, 40)
        offset = 0
        for line in lines[:15]:
            draw.text((5, offset), line, font=font15, fill=black)
            offset += 18
        epd.display(epd.getbuffer(image))
        epd.sleep()
    except Exception:  # nosec B110 - best-effort; never crash the error display
        pass


def _decode_image(data, image_type):
    """Return a PIL Image from a base64 string or a URL."""
    if image_type == "url":
        r = requests.get(data, timeout=15)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))
    raw = base64.b64decode(data)
    return Image.open(io.BytesIO(raw))


def _fit_image(img, max_w, max_h):
    """Scale to fit within (max_w, max_h), then convert to 1-bit B/W."""
    img = img.convert("RGB")
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img.convert("1")


# ---------------------------------------------------------------------------
# Public render entry points (shared by the cron job and the MQTT daemon).
# Each returns True on success / False on failure and always sleeps the panel.
# ---------------------------------------------------------------------------


def render_joke():
    init_display()
    try:
        quote = get_quote()
        print(quote)
        download_image(quote)
        img = img_convert(IMG_PATH)
        clear_display(epd)
        image.paste(img, (0, 100))
        lines = break_string_into_array(quote, 44)
        offset = 0
        for line in lines:
            draw.text((5, offset), line, font=font15, fill=black)
            offset = offset + 18
        epd.display(epd.getbuffer(image))
        return True
    except Exception as e:
        print("Joke render failed:", e)
        show_error(epd, "Update failed: " + str(e))
        return False
    finally:
        epd.sleep()


def render_text(text, layout=None):
    init_display()
    try:
        clear_display(epd)
        lines = break_string_into_array(text or "", 44)
        offset = 0
        for line in lines:
            draw.text((5, offset), line, font=font15, fill=black)
            offset = offset + 18
        epd.display(epd.getbuffer(image))
        return True
    except Exception as e:
        print("Text render failed:", e)
        show_error(epd, "Render failed: " + str(e))
        return False
    finally:
        epd.sleep()


def render_image(data, image_type="base64", layout=None):
    init_display()
    try:
        clear_display(epd)
        img = _decode_image(data, image_type)
        img = _fit_image(img, image.width, image.height)
        x = (image.width - img.width) // 2
        y = (image.height - img.height) // 2
        image.paste(img, (x, y))
        epd.display(epd.getbuffer(image))
        return True
    except Exception as e:
        print("Image render failed:", e)
        show_error(epd, "Image failed: " + str(e))
        return False
    finally:
        epd.sleep()


def render_both(text, data, image_type="base64", layout=None):
    init_display()
    try:
        clear_display(epd)
        img = _decode_image(data, image_type)
        img = _fit_image(img, 300, 300)
        img = img.rotate(90)
        image.paste(img, (0, 100))
        lines = break_string_into_array(text or "", 44)
        offset = 0
        for line in lines:
            draw.text((5, offset), line, font=font15, fill=black)
            offset = offset + 18
        epd.display(epd.getbuffer(image))
        return True
    except Exception as e:
        print("Both render failed:", e)
        show_error(epd, "Render failed: " + str(e))
        return False
    finally:
        epd.sleep()


def render_clear():
    init_display()
    try:
        clear_display(epd)
        return True
    except Exception as e:
        print("Clear failed:", e)
        return False
    finally:
        epd.sleep()


def main():
    render_joke()


if __name__ == "__main__":
    main()
