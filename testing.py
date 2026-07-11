from openai import OpenAI
import requests
import json
import os
from PIL import Image

def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
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

def get_quote():
    api_url = 'https://api.api-ninjas.com/v1/jokes'
    response = requests.get(api_url, headers={'X-Api-Key': os.environ["API_NINJAS_KEY"]})
    data = json.loads(response.text)
    return data[0]["joke"]

quote = get_quote()
print(quote)
response = client.images.generate(
  prompt="You are a cartoonist for a newspaper. Create a pencil drawing to accompany the quote of the day: " + quote,
  model="dall-e-3",
  n=1,
  size="1024x1024",
  style="natural"
)

# Extract the URL of the generated image
image_url = response.data[0].url
image_response = requests.get(image_url)

# Save the image to a file
if image_response.status_code == 200:
    with open('generated_image.png', 'wb') as f:
        f.write(image_response.content)
    print("Image downloaded and saved as 'generated_image.png'")
else:
    print("Failed to download the image")