"""Utility script to query and list available Gemini text/multimodal models.

Run this script to verify your API key and check which models support the
`generateContent` endpoint used by the bot.
"""

import os
import sys
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise SystemExit("Error: GEMINI_API_KEY must be set in .env")

client = genai.Client(api_key=GEMINI_API_KEY)

try:
    # Filter for models that support content generation (text/multimodal)
    gen_models = [
        m.name.replace("models/", "")
        for m in client.models.list()
        if "generateContent" in m.supported_actions
    ]

    formatted_list = "\n  • ".join(gen_models)

    print("\nAvailable Gemini Generation Models:")
    print("-" * 40)
    print(f"  • {formatted_list}")
    print("-" * 40 + "\n")

except Exception as e:
    print(f"Failed to fetch models: {e}")
    sys.exit(1)