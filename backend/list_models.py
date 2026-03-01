import httpx
from dotenv import load_dotenv
import os

load_dotenv()
key = os.environ["GOOGLE_CLOUD_API_KEY"]

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
r = httpx.get(url)
print(r.status_code)
for m in r.json().get("models", []):
    print(m["name"])
