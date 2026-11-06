"""Integration test script for Crow Bot translation pipeline.

Loads text and image fixtures from the assets/ directory, executes the Gemini
multimodal API translation engine, and passes the output through the post-processor
and truncation helpers to verify Discord embed readiness.
"""

import asyncio
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from google import genai

# Add project root to sys.path so Python can find bot.py when running from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env variables into environment memory
load_dotenv()

from cogs.translator import create_image_part, enhance_tweet_formatting, safe_truncate, Translator

# Paths to test fixtures in assets/
ASSETS_DIR = PROJECT_ROOT / "assets" / "translator"
SAMPLE_TEXT_PATH = ASSETS_DIR / "sample_tweet.txt"
SAMPLE_IMAGE_PATH = ASSETS_DIR / "sample_tweet_image.jpg"

def get_test_translator() -> Translator:
    """Instantiates a lightweight Translator cog instance for standalone API testing."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY environment variable is not set.")
        sys.exit(1)

    # Bypass full discord.py Bot dependency for testing
    translator = Translator.__new__(Translator)
    translator.gemini = genai.Client(api_key=gemini_key)
    translator.gemini_semaphore = asyncio.Semaphore(2)
    return translator

async def main():
    print("==================================================")
    print("🚀 RUNNING TRANSLATION & RESILIENCY TEST")
    print("==================================================")

    # 1. Load sample text fixture
    sample_text = ""
    if SAMPLE_TEXT_PATH.exists():
        try:
            sample_text = SAMPLE_TEXT_PATH.read_text(encoding="utf-8").strip()
            print(f"📄 Loaded text fixture from: {SAMPLE_TEXT_PATH.name}")
        except Exception as e:
            print(f"❌ Error: Text fixture exists but could not be read ({SAMPLE_TEXT_PATH.name}): {e}")
            sys.exit(1)
    else:
        print(f"⚠️ Text fixture not found at '{SAMPLE_TEXT_PATH.name}'. Running without text...")

    # 2. Load sample image fixture
    image_part = None
    if SAMPLE_IMAGE_PATH.exists():
        try:
            image_bytes = SAMPLE_IMAGE_PATH.read_bytes()
            image_part = create_image_part(image_bytes)
            print(f"📷 Loaded image fixture from: {SAMPLE_IMAGE_PATH.name}")
        except Exception as e:
            print(f"❌ Error: Image fixture exists but failed to decode ({SAMPLE_IMAGE_PATH.name}): {e}")
            sys.exit(1)
    else:
        print(f"⚠️ Image fixture not found at '{SAMPLE_IMAGE_PATH.name}'. Running without image...")

    # 3. Guard Check: Stop execution if both fixtures are missing
    if not sample_text and not image_part:
        print("❌ Error: Neither text nor image fixture could be loaded. Aborting test.")
        sys.exit(1)

    print("\n⏳ Calling translate_with_gemini()...\n")
    translator = get_test_translator()

    translated_text = await translator.translate_with_gemini(text=sample_text, image_part=image_part)
    translated_text = enhance_tweet_formatting(translated_text)
    translated_text = safe_truncate(translated_text, max_chars=3500)

    print("\n==================================================")
    print("📥 FINAL DISCORD-READY EMBED TEXT:")
    print("==================================================")
    if translated_text:
        print(translated_text)
    else:
        print("❌ Translation returned an empty string (API failed or quota exhausted).")
    print("==================================================")

def setup_test_logging() -> None:
    """Configures lightweight console logging to stdout for test execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True  # Guarantees fresh configuration even if imports touched logging
    )

if __name__ == "__main__":
    setup_test_logging()
    asyncio.run(main())