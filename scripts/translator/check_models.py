"""Utility script to list reachable Gemini text/chat models for your API key."""

import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise SystemExit("Error: GEMINI_API_KEY must be set in .env")

client = genai.Client(api_key=GEMINI_API_KEY)

SKIP_KEYWORDS = ("image", "nano-banana", "audio", "omni", "tts", "transcribe", "embedding", "veo", "imagen", "lyria", "deep-research")

try:
    models = list(client.models.list())
except Exception as e:
    print(f"Failed to fetch models: {e}")
    sys.exit(1)

candidates = [
    m.name.removeprefix("models/")
    for m in models
    if "generateContent" in (m.supported_actions or [])
    and not any(w in m.name.lower() for w in SKIP_KEYWORDS)
]

available = []
for name in candidates:
    try:
        client.models.count_tokens(model=name, contents="test")
        available.append(name)
    except errors.APIError:
        pass

print("\nAvailable models:")
for name in available:
    print(f"- {name}")