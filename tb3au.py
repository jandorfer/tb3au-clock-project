import base64

import requests
import json
import sys, os
_BASE = os.path.dirname(os.path.abspath(__file__))
_EPAPER = os.path.join(_BASE, "e-Paper", "RaspberryPi_JetsonNano", "python")
picdir = os.path.join(_EPAPER, "pic")
libdir = os.path.join(_EPAPER, "lib")  # SDK is a git submodule checked out at ./e-Paper
if os.path.exists(libdir): sys.path.append(libdir)
from waveshare_epd import epd4in2_V2
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

def _load_dotenv(path=os.path.join(_BASE, ".env")):
    """Minimal .env loader (no external dependency)."""
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

# Fail fast with a clear message if required secrets are missing.
for _var in ("OPENAI_API_KEY", "API_NINJAS_KEY"):
    if not os.environ.get(_var):
        raise RuntimeError(f"Missing required environment variable: {_var} (set it in .env)")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

black = 0
white = 1

IMG_PATH = os.path.join(_BASE, "generated_image.png")

def get_quote():
    api_url = 'https://api.api-ninjas.com/v1/jokes'
    response = requests.get(api_url, headers={'X-Api-Key': os.environ["API_NINJAS_KEY"]})
    response.raise_for_status()
    data = json.loads(response.text)
    return data[0]["joke"]

def clear_display(epd):
    global image, draw
    epd.Clear()
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    epd.display(epd.getbuffer(image))

def download_image():
    img = client.images.generate(
        prompt="You are a cartoonist for a newspaper. Create a funny pencil drawing to accompany the quote of the day: " + quote,
        model="gpt-image-1",
        n=1,
        size="1024x1024",
        quality="medium"
    )
    image_bytes = base64.b64decode(img.data[0].b64_json)
    with open(IMG_PATH, 'wb') as f:
        f.write(image_bytes)
    print("Image downloaded and saved as 'generated_image.png'")

def img_convert(img_file):
    img = Image.open(img_file)
    img = img.resize((300, 300), Image.LANCZOS)
    img = img.rotate(90)
    img = img.convert('1') # convert to black & white
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
    except Exception:
        pass

try:
    epd = epd4in2_V2.EPD()
    epd.init()
    font15 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 15)

    # Fetch the joke + image BEFORE touching the screen, so a failure
    # leaves the previous content instead of a blank panel.
    quote = get_quote()
    print(quote)
    download_image()
    img = img_convert(IMG_PATH)

    clear_display(epd)
    image.paste(img, (0,100))
    lines = break_string_into_array(quote, 44)
    offset = 0
    for line in lines:
        draw.text((5, offset), line, font = font15, fill = black)
        offset = offset + 18

    epd.display(epd.getbuffer(image))
    epd.sleep()

except KeyboardInterrupt:
    print("ctrl + c:")
    epd4in2_V2.epdconfig.module_exit()
    sys.exit()

except Exception as e:
    print("Update failed:", e)
    try:
        show_error(epd, "Update failed: " + str(e))
    except Exception:
        pass
