import base64
import io
import json
import os
import re
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

# Display orientation correction (degrees). The panel's native buffer is
# landscape (400x300). If the panel is physically mounted rotated from that,
# set this to 0/90/180/270 to compensate. The user's panel is mounted 180
# degrees from native, so every render is flipped before being sent to the
# driver.
DISPLAY_ROTATION = 180

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


def display_image(epd, img=None):
    """Send the canvas to the panel, applying the mount-orientation rotation."""
    if img is None:
        img = image
    if DISPLAY_ROTATION:
        img = img.rotate(DISPLAY_ROTATION)
    epd.display(epd.getbuffer(img))


# ---------------------------------------------------------------------------
# Markdown + auto-fit text rendering
# ---------------------------------------------------------------------------

# Bundled TrueType family (Liberation Sans/Mono, SIL-licensed) in ./fonts so
# we control typography and get REAL bold/italic. Text is rendered to a
# grayscale canvas with these fonts (anti-aliased) and thresholded to the 1-bit
# panel, replacing the old ImageDraw.text + faux-bold path.
_FONT_DIR = os.path.join(_BASE, "fonts")
REGULAR_TTF = os.path.join(_FONT_DIR, "LiberationSans-Regular.ttf")
BOLD_TTF = os.path.join(_FONT_DIR, "LiberationSans-Bold.ttf")
ITALIC_TTF = os.path.join(_FONT_DIR, "LiberationSans-Italic.ttf")
BOLDITALIC_TTF = os.path.join(_FONT_DIR, "LiberationSans-BoldItalic.ttf")
MONO_TTF = os.path.join(_FONT_DIR, "LiberationMono-Regular.ttf")

# Largest auto-fit base size. Keeps short text readable instead of ballooning
# to fill the whole 400x300 panel.
MAX_BASE = 40

_FONT_CACHE = {}


def _load_font(path, size):
    key = (path, int(size))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, int(size))
    return _FONT_CACHE[key]


def _ttf_path(style):
    if "code" in style:
        return MONO_TTF
    if "bold" in style and "italic" in style:
        return BOLDITALIC_TTF
    if "bold" in style:
        return BOLD_TTF
    if "italic" in style:
        return ITALIC_TTF
    return REGULAR_TTF


def _ttf(style, size):
    return _load_font(_ttf_path(style), size)


def _font(size, mono=False):
    """Fallback font used only for width measurement during layout."""
    return _load_font(MONO_TTF if mono else REGULAR_TTF, size)


def _text_width(font, text):
    if not text:
        return 0
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


_INLINE_RE = re.compile(r"(\*\*.+?\*\*|\*[^*]+\*|`[^`]+`)")


def _parse_inline(text):
    """Split text into (text, style-set) runs for **bold**, *italic*, `code`."""
    segs = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            segs.append((text[pos:m.start()], set()))
        tok = m.group(0)
        if tok.startswith("**") and tok.endswith("**"):
            segs.append((tok[2:-2], {"bold"}))
        elif tok.startswith("`") and tok.endswith("`"):
            segs.append((tok[1:-1], {"code"}))
        else:
            segs.append((tok[1:-1], {"italic"}))
        pos = m.end()
    if pos < len(text):
        segs.append((text[pos:], set()))
    return segs


def _wrap_inline(segs, size, max_w, mono=False):
    """Wrap inline runs into lines that fit max_w (list of word-runs)."""
    font = _font(size, mono)
    space_w = _text_width(font, " ")
    words = []
    for text, style in segs:
        for w in text.split(" "):
            if w:
                words.append((w, set(style)))
    lines = []
    cur = []
    cur_w = 0
    for w, style in words:
        ww = _text_width(font, w)
        if cur and cur_w + space_w + ww > max_w:
            lines.append(cur)
            cur = [(w, style)]
            cur_w = ww
        else:
            cur.append((w, style))
            cur_w += (space_w if cur_w else 0) + ww
    if cur:
        lines.append(cur)
    return lines


_BLOCK_START_RE = re.compile(r"^\s*(#{1,3}\s|[-*]\s|> \s|```|-{3,}|\*{3,})")


def _parse_markdown(text):
    """Parse a small markdown subset into typed blocks."""
    lines = text.split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped == "":
            i += 1
            continue
        if stripped in ("---", "***"):
            blocks.append(("rule", None))
            i += 1
            continue
        if stripped.startswith("```"):
            code = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            blocks.append(("code", "\n".join(code)))
            continue
        if stripped.startswith("# "):
            blocks.append(("heading", (1, stripped[2:].strip())))
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(("heading", (2, stripped[3:].strip())))
            i += 1
            continue
        if stripped.startswith("### "):
            blocks.append(("heading", (3, stripped[4:].strip())))
            i += 1
            continue
        if stripped.startswith("> "):
            q = []
            while i < n and lines[i].strip().startswith("> "):
                q.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(("quote", " ".join(q)))
            continue
        if re.match(r"^[-*]\s", stripped):
            items = []
            while i < n and re.match(r"^[-*]\s", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s", "", lines[i].strip()))
                i += 1
            blocks.append(("list", items))
            continue
        para = [stripped]
        i += 1
        while i < n and lines[i].strip() != "" and not _BLOCK_START_RE.match(lines[i]):
            para.append(lines[i].strip())
            i += 1
        blocks.append(("paragraph", " ".join(para)))
    return blocks


_HEADING_SCALE = {1: 2.0, 2: 1.5, 3: 1.25}


def _line_width(words, size, mono=False):
    font = _font(size, mono)
    return sum(_text_width(font, w) + _text_width(font, " ") for w, _ in words)


def _build_layout(blocks, base, avail_w, margin):
    """Return (ops, total_height, max_width). ops are draw descriptors with
    relative y; final drawing offsets by a centered start_y."""
    ops = []
    y = 0
    max_w = 0
    for block in blocks:
        kind = block[0]
        if kind == "rule":
            y += 4
            ops.append(("rule", y, 6))
            y += 6
            continue
        if kind == "heading":
            lvl, txt = block[1]
            size = int(base * _HEADING_SCALE.get(lvl, 1.25))
            for wl in _wrap_inline(_parse_inline(txt), size, avail_w - margin):
                ops.append(("line", y, margin, wl, size, False))
                y += size + 6
                max_w = max(max_w, _line_width(wl, size))
            continue
        if kind == "paragraph":
            size = base
            for wl in _wrap_inline(_parse_inline(block[1]), size, avail_w - margin):
                ops.append(("line", y, margin, wl, size, False))
                y += size + 6
                max_w = max(max_w, _line_width(wl, size))
            continue
        if kind == "list":
            size = base
            bullet_indent = margin + max(10, size)
            for item in block[1]:
                wrapped = _wrap_inline(_parse_inline(item), size, avail_w - bullet_indent)
                first = True
                for wl in wrapped:
                    indent = bullet_indent if not first else margin
                    if first:
                        wl = [("\u2022 ", set())] + wl
                    ops.append(("line", y, indent, wl, size, False))
                    y += size + 6
                    max_w = max(max_w, _line_width(wl, size) + indent)
                    first = False
            continue
        if kind == "quote":
            size = base
            qindent = margin + 8
            wrapped = _wrap_inline(_parse_inline(block[1]), size, avail_w - qindent)
            block_h = 0
            qlines = []
            for wl in wrapped:
                qlines.append(("line", y, qindent, wl, size, False))
                y += size + 6
                block_h += size + 6
                max_w = max(max_w, _line_width(wl, size) + qindent)
            ops.append(("bar", y - block_h, block_h))
            ops.extend(qlines)
            continue
        if kind == "code":
            size = base
            pad = 4
            inner_w = avail_w - margin - pad
            wrapped = _wrap_inline(_parse_inline(block[1]), size, inner_w, mono=True)
            block_h = 0
            clines = []
            for wl in wrapped:
                clines.append(("line", y, margin + pad, wl, size, True))
                y += size + 4
                block_h += size + 4
                max_w = max(max_w, _line_width(wl, size, mono=True) + margin + pad)
            ops.append(("box", y - block_h - pad, block_h + 2 * pad))
            ops.extend(clines)
            continue
    return ops, y, max_w


def _fit_base_size(blocks, W, H, margin):
    avail_w = W - 2 * margin
    avail_h = H - 2 * margin
    lo, hi, best = 8, MAX_BASE, 8
    while lo <= hi:
        mid = (lo + hi) // 2
        _, th, mw = _build_layout(blocks, mid, avail_w, margin)
        if th <= avail_h and mw <= avail_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _draw_words(draw, x, y, words, size):
    fx = x
    for w, style in words:
        f = _ttf(style, size)
        draw.text((fx, y), w, font=f, fill=0)
        fx += _text_width(f, w) + _text_width(f, " ")


def _render_markdown(text, markdown, image):
    W, H = image.size
    margin = 6
    avail_w = W - 2 * margin
    if text and text.strip():
        blocks = _parse_markdown(text) if markdown else [("paragraph", text)]
    else:
        blocks = [("paragraph", " ")]
    base = _fit_base_size(blocks, W, H, margin)
    ops, total_h, _ = _build_layout(blocks, base, avail_w, margin)
    start_y = margin + max(0, (H - 2 * margin - total_h) // 2)

    # Render text onto a grayscale canvas (anti-aliased with real TTF weights),
    # then threshold it to a 1-bit mask and composite onto the panel buffer.
    gray = Image.new("L", (W, H), 255)
    gdraw = ImageDraw.Draw(gray)
    draw = ImageDraw.Draw(image)
    for op in ops:
        if op[0] == "line":
            _, y, indent, words, size, mono = op
            _draw_words(gdraw, indent, start_y + y, words, size)
        elif op[0] == "rule":
            _, y, h = op
            draw.line((margin, start_y + y, W - margin, start_y + y), fill=black, width=2)
        elif op[0] == "bar":
            _, y0, h = op
            draw.line((margin + 2, start_y + y0, margin + 2, start_y + y0 + h), fill=black, width=3)
        elif op[0] == "box":
            _, y0, h = op
            draw.rectangle(
                (margin, start_y + y0, W - margin, start_y + y0 + h),
                outline=black,
                width=1,
            )
    mask = gray.point(lambda p: 255 if p < 128 else 0)
    image.paste(black, mask=mask)
    return image


def clear_display(epd):
    global image, draw
    epd.Clear()
    # Build the buffer in the panel's native landscape size (400x300). Creating
    # it as (height, width) made the driver transpose the buffer, which rotated
    # every render 90 degrees.
    image = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(image)
    display_image(epd)


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
    # Panel is landscape (400x300); fit the cartoon into the top band.
    img = img.convert("RGB")
    img.thumbnail((400, 200), Image.LANCZOS)
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
        display_image(epd)
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
        # Landscape panel: cartoon across the top, joke text underneath.
        ix = (image.width - img.width) // 2
        image.paste(img, (ix, 0))
        lines = break_string_into_array(quote, 44)
        offset = img.height + 8
        for line in lines:
            draw.text((5, offset), line, font=font15, fill=black)
            offset = offset + 18
        display_image(epd)
        return quote
    except Exception as e:
        print("Joke render failed:", e)
        show_error(epd, "Update failed: " + str(e))
        return False
    finally:
        epd.sleep()


def render_text(text, layout=None, markdown=False):
    init_display()
    try:
        clear_display(epd)
        _render_markdown(text or "", markdown, image)
        display_image(epd)
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
        display_image(epd)
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
        img = _fit_image(img, image.width, image.height)
        # Landscape panel: image across the top, text underneath.
        ix = (image.width - img.width) // 2
        image.paste(img, (ix, 0))
        lines = break_string_into_array(text or "", 44)
        offset = img.height + 8
        for line in lines:
            draw.text((5, offset), line, font=font15, fill=black)
            offset = offset + 18
        display_image(epd)
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
