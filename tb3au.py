import base64

import requests
import json
import sys, os, time, traceback
_EPAPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e-Paper", "RaspberryPi_JetsonNano", "python")
picdir = os.path.join(_EPAPER, "pic")
libdir = os.path.join(_EPAPER, "lib")  # SDK is a git submodule checked out at ./e-Paper
if os.path.exists(libdir): sys.path.append(libdir)
from waveshare_epd import epd4in2_V2
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from openai import OpenAI

def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
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

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

black = 0
white = 1

def get_quote():
    api_url = 'https://api.api-ninjas.com/v1/jokes'
    response = requests.get(api_url, headers={'X-Api-Key': os.environ["API_NINJAS_KEY"]})
    data = json.loads(response.text)
    return data[0]["joke"]

def clear_display(epd):
    global image, draw
    epd.Clear()
    image = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(image)
    epd.display(epd.getbuffer(image))

def download_image(text):
    img = client.images.generate(
        prompt="You are a cartoonist for a newspaper. Create a funny pencil drawing to accompany the quote of the day: " + quote,
        model="gpt-image-1",
        n=1,
        size="1024x1024",
        quality="medium"
    )
    image_bytes = base64.b64decode(img.data[0].b64_json)
    with open('generated_image.png', 'wb') as f:
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

try:
    epd = epd4in2_V2.EPD()
    epd.init()
#    epd.Clear()
#    time.sleep(2)

    font15 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 15)
#    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
#    font32 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 32)

    clear_display(epd)

    quote = get_quote()
    print(quote)

    download_image(quote)
    img = img_convert("generated_image.png")
    image.paste(img, (0,100))

    lines = break_string_into_array(quote, 44)
    offset = 0
    for line in lines:
        draw.text((5, offset), line, font = font15, fill = black)
        offset = offset + 18

    epd.display(epd.getbuffer(image))

#    clear_display(epd)
    epd.sleep()

except IOError as e:
    print(e)

except KeyboardInterrupt:
    print("ctrl + c:")
    epd2in13_V2.epdconfig.module_exit()
    exit()
