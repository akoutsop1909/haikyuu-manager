"""Translator Cog - Japanese-to-English Twitter/X Translator.

Monitors Japanese Twitter unfurls in the source channel, runs text and
multimodal image OCR through Gemini API, and posts formatted English
embeds to the destination channel with offline catch-up support.
"""

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
import asyncio
from collections import OrderedDict
import io
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands, tasks
from google import genai
from google.genai import errors, types
from PIL import Image

logger = logging.getLogger(__name__)

# Path setup relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompt.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip() if PROMPT_PATH.exists() else ""

# Prevents circular import errors at runtime while giving PyCharm complete type inference
if TYPE_CHECKING:
    from bot import CrowBot

# ==============================================================================
# 2. UTILITY & HELPER FUNCTIONS
# ==============================================================================
def create_image_part(data: bytes) -> types.Part | None:
    """Fast-paths JPEG, PNG, and WebP bytes directly to Gemini, with Pillow fallback for other formats."""
    try:
        # 1. FAST PATH: Pass supported native formats directly to Gemini without Pillow
        if data.startswith(b'\xff\xd8\xff'):
            return types.Part.from_bytes(data=data, mime_type="image/jpeg")
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return types.Part.from_bytes(data=data, mime_type="image/png")
        if len(data) >= 12 and data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            return types.Part.from_bytes(data=data, mime_type="image/webp")

        # 2. SLOW PATH: Fallback for unsupported formats (GIF, BMP, TIFF) using Pillow
        with Image.open(io.BytesIO(data)) as img:
            rgb_img = img.convert("RGB")
            buffer = io.BytesIO()
            rgb_img.save(buffer, format="PNG")

        return types.Part.from_bytes(
            data=buffer.getvalue(),
            mime_type="image/png"
        )
    except Exception as e:
        logger.warning(f"Failed to convert image bytes to Gemini Part: {e}")
        return None

def extract_twitter_url(message: discord.Message) -> str | None:
    """Extracts a Twitter/X post URL from a message and converts it to a standard x.com format."""
    text_to_search = ""

    if message.embeds and message.embeds[0].url:
        text_to_search += message.embeds[0].url + " "
    if message.content:
        text_to_search += message.content

    # Capture username and tweet ID in regex groups
    pattern = r"https?://(?:www\.)?(?:twitter|x)\.com/([^/]+)/status/(\d+)"
    if match := re.search(pattern, text_to_search):
        username, status_id = match.group(1), match.group(2)
        return f"https://x.com/{username}/status/{status_id}"

    return None

def safe_truncate(text: str, max_chars: int = 3500) -> str:
    """Truncates text for Discord embeds without breaking Markdown bold tags or word boundaries."""
    if not text or len(text) <= max_chars:
        return text or ""

    footer = "\n\n*(...read full post on Twitter/X)*"
    # Reserve extra space for potential closing bold tags (** = 2 chars)
    target_len = max_chars - len(footer) - 2
    truncated = text[:target_len]

    last_newline = truncated.rfind("\n")
    last_space = truncated.rfind(" ")

    # Prefer snapping to a paragraph break, then to a word boundary
    if last_newline != -1 and last_newline > target_len - 200:
        truncated = truncated[:last_newline]
    elif last_space != -1 and last_space > target_len - 200:
        truncated = truncated[:last_space]

    truncated = truncated.strip()

    # Balance unclosed bold tags (**) to prevent leaking style into footer
    if truncated.count("**") % 2 != 0:
        truncated += "**"

    return truncated + footer

def enhance_tweet_formatting(text: str) -> str:
    """Sanitizes Gemini translation outputs into clean Discord Markdown."""
    if not text:
        return ""

    # Strip accidental code blocks, signatures, and trailing URLs
    text = re.sub(r"^```(?:markdown)?\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```$", "", text)
    text = re.sub(r"(?i)\*?\*?haikyu!!\s+fly\s+high.*?\b\w+\s+on\s+x\*?\*?", "", text)
    text = re.sub(r"\s*https?://\S+\s*$", "", text)

    # Strip blockquotes and lone structural artifacts
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[*•\->]\s*$", "", text, flags=re.MULTILINE).strip()

    # 1. First, separate the main tweet body from the image OCR block
    match = re.search(r"(🖼️\s*\*\*Text from Image:?\*\*:?)", text, re.IGNORECASE)

    if match:
        found_header = match.group(1)
        tweet_body, _, image_text = text.partition(found_header)
        tweet_body = tweet_body.strip()
        image_text = image_text.strip()
    else:
        tweet_body = text
        image_text = ""

    # 2. Convert the last arrow into 🔥 ONLY within the tweet body
    last_arrow_idx = tweet_body.rfind("➡️")
    if last_arrow_idx != -1:
        tweet_body = tweet_body[:last_arrow_idx] + "🔥" + tweet_body[last_arrow_idx + 2:]

    # 3. Re-assemble the body and the image text block
    if image_text:
        text = f"{tweet_body}\n\n> 🖼️ **Text from Image**\n{image_text}"
    else:
        text = tweet_body

    return re.sub(r"\n{3,}", "\n\n", text).strip()

# ==============================================================================
# 3. CLIENT DEFINITION
# ==============================================================================
class Translator(commands.Cog):
    def __init__(self, bot: "CrowBot"):
        self.bot = bot

        # Load and validate environment variables
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        jp_env = os.getenv("JP_CHANNEL_ID", "0")
        en_env = os.getenv("EN_CHANNEL_ID", "0")

        self.jp_channel_id = int(jp_env) if jp_env.isdigit() else 0
        self.en_channel_id = int(en_env) if en_env.isdigit() else 0

        if not self.gemini_key or self.jp_channel_id == 0 or self.en_channel_id == 0 or not SYSTEM_PROMPT:
            logger.critical("Translator cog missing required configuration in .env or prompt.txt!")
            raise SystemExit(1)

        # State tracking
        self.processing_messages = set()  # Tracks message IDs currently undergoing translation
        self.processed_messages = OrderedDict()  # In-memory cache to prevent re-translating edited/unfurled messages

        # Unbound attributes (initialized in async context)
        self.gemini = None
        self.gemini_semaphore = None

    @property
    def jp_channel(self) -> discord.TextChannel | None:
        """Returns the cached Japanese channel object, or None if unavailable."""
        return self.bot.get_channel(self.jp_channel_id)

    @property
    def en_channel(self) -> discord.TextChannel | None:
        """Returns the cached English channel object, or None if unavailable."""
        return self.bot.get_channel(self.en_channel_id)

    async def cog_load(self) -> None:
        """Async setup hook for the cog running on the active event loop."""
        self.gemini = genai.Client(api_key=self.gemini_key)
        self.gemini_semaphore = asyncio.Semaphore(2)

        self.periodic_catch_up.start()

    async def cog_unload(self) -> None:
        """Stops active background tasks when the cog is unloaded."""
        self.periodic_catch_up.cancel()

# ==============================================================================
# 4. GEMINI TRANSLATION & OCR ENGINE
# ==============================================================================
    async def translate_with_gemini(self, text: str = "", image_part: types.Part | None = None) -> str:
        """Translates Japanese tweet text and performs image OCR via Gemini API with fallbacks."""
        if not text and not image_part:
            return ""

        max_retries = 3
        models_to_try = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]

        for model_name in models_to_try:
            logger.info(f"Attempting translation with model: {model_name}")
            for attempt in range(1, max_retries + 1):
                try:
                    contents = []

                    if text:
                        contents.append(text)

                    if image_part:
                        contents.append(image_part)
                        # If there's no tweet body text, prompt Gemini to perform OCR on the image
                        if not text:
                            contents.append(
                                "Extract and translate all Japanese text visible in this image according to the system instructions."
                            )

                    # Rate-limit concurrent requests and enforce a 30s timeout on API calls
                    async with self.gemini_semaphore:
                        response = await self.gemini.aio.models.generate_content(
                            model=model_name,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_PROMPT,  # Direct instruction channel
                                temperature=0.2,
                                http_options=types.HttpOptions(timeout=30000),  # Prevents hanging indefinitely
                                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                    disable=True  # Explicitly disables SDK's default AFC routine to suppress AsyncModels warnings
                                )
                            ),
                        )

                    if response and response.text:
                        return response.text.strip()

                # API Hang / Latency -> Abandon model immediately to preserve daily quota
                except asyncio.TimeoutError:
                    logger.warning(f"Gemini API timed out after 30s on {model_name}.")
                    break

                except errors.APIError as e:
                    status_code = getattr(e, "code", None) or getattr(e, "status_code", None)
                    error_msg = getattr(e, "message", None) or str(e)

                    if status_code in (400, 404):
                        logger.warning(f"Model {model_name} unavailable or invalid (HTTP {status_code}).")
                        break

                    # Rate Limit / Quota Exhaustion (HTTP 429) -> Abandon model immediately
                    if status_code == 429:
                        logger.warning(f"Quota/Rate limit reached for {model_name} (HTTP 429).")
                        break

                    # Transient Server Errors -> Retry with exponential backoff
                    if status_code in (408, 500, 502, 503, 504, 509):
                        if attempt < max_retries:
                            wait_time = attempt * 5
                            logger.warning(
                                f"Transient API Error {status_code} on {model_name}. Retrying in {wait_time}s... (Attempt {attempt}/{max_retries})"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"All {max_retries} attempts failed on {model_name} (HTTP {status_code}).")
                            break

                    # Unrecoverable Client Error (400, 403, 404, etc.)
                    logger.error(f"Unrecoverable API Error on {model_name} (HTTP {status_code}): {error_msg}")
                    break

                # Catch-all for non-API errors (e.g. local network drops or timeout errors)
                except Exception as e:
                    logger.error(f"Unexpected error calling Gemini API on {model_name}: {e}")
                    continue

        return ""

# ==============================================================================
# 5. MAIN MESSAGE PROCESSING LOGIC
# ==============================================================================
    async def process_and_send_message(self, message: discord.Message) -> None:
        """Parses, translates, and posts a Japanese Twitter update to the English channel."""
        # Skip if currently translating OR already finished
        if message.id in self.processing_messages or message.id in self.processed_messages:
            return

        extracted_text = ""
        extracted_img_url = None
        image_part = None

        try:
            self.processing_messages.add(message.id)
            # 1. Parse text and image from Embeds
            if message.embeds:
                for embed in message.embeds:
                    if embed.description:
                        extracted_text += embed.description + "\n"
                    if embed.image and embed.image.url and not extracted_img_url:
                        extracted_img_url = embed.image.url

            # 2. Fallback to standard message content ONLY if embeds yielded no description
            if not extracted_text and message.content:
                extracted_text += re.sub(r"https?://\S+", "", message.content).strip() + "\n"

            extracted_text = extracted_text.strip()

            # Direct Guard: If there is neither text nor an image URL, don't attempt anything
            if not extracted_text and not extracted_img_url:
                return

            # 3. Fetch image directly into PIL format for Gemini (with up to 3 retry attempts)
            if extracted_img_url:
                image_data = None
                max_retries = 3
                timeout = aiohttp.ClientTimeout(connect=3, total=8)

                # Step A: Retry network download using the persistent global session
                for attempt in range(1, max_retries + 1):
                    wait_time = attempt * 2

                    try:
                        async with self.bot.http_session.get(extracted_img_url, timeout=timeout) as resp:
                            # Immediate exit for unrecoverable 4xx client errors
                            if 400 <= resp.status < 500:
                                logger.error(
                                    f"Permanent HTTP {resp.status} client error fetching image. Skipping retries.")
                                break

                            # If status is not OK (e.g. 5xx server errors), trigger retry
                            if not resp.ok:
                                if attempt < max_retries:
                                    logger.warning(
                                        f"Image fetch returned HTTP {resp.status}. Retrying in {wait_time}s... (Attempt {attempt}/{max_retries})"
                                    )
                                    await asyncio.sleep(wait_time)
                                    continue
                                else:
                                    logger.error(
                                        f"All {max_retries} attempts failed fetching image (HTTP {resp.status}).")
                                    break

                            # Status is OK (200-299): Read the raw payload
                            image_data = await resp.read()
                            break  # Download succeeded!

                    # Retry expected network, timeout, or streaming payload exceptions
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        if attempt < max_retries:
                            logger.warning(
                                f"Network error fetching image ({e}). Retrying in {wait_time}s... (Attempt {attempt}/{max_retries})"
                            )
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(
                                f"All {max_retries} attempts failed fetching image due to network errors ({e}).")
                            break

                    except Exception as e:
                        logger.error(f"Unexpected error fetching image: {e}")
                        break  # Don't retry unknown non-network errors

                # Step B: Process image once if download succeeded
                if image_data:
                    image_part = await asyncio.to_thread(create_image_part, image_data)

            # Guard check: Only abort if we have NO text and NO image
            if not extracted_text and not image_part:
                logger.error("No text found and image unavailable. Skipping processing.")
                return

            # 4. Single Gemini call for both Text Translation and Multimodal Image OCR/Translation
            translated_text = await self.translate_with_gemini(text=extracted_text, image_part=image_part)
            if not translated_text:
                logger.warning("Translation failed, skipped, or quota exhausted. Skipping Discord post.")
                return

            translated_text = enhance_tweet_formatting(translated_text)
            translated_text = safe_truncate(translated_text, max_chars=3500)

            # 5. Send translated post to EN channel
            notification_text = (
                "🏐 Hey Haikyu!! Fly High fans! A new update from the official JP "
                "Twitter/X account has just dropped. Check out the fresh translation 👇"
            )

            # Use extracted URL or fall back to profile page
            exact_post_url = extract_twitter_url(message) or "https://x.com/haikyu_haifura"

            # --- CREATE EMBED ---
            en_embed = discord.Embed(
                title="@haikyu_haifura",
                url=exact_post_url,
                description=translated_text,
                color=discord.Color(0xFF6600),  # Official Karasuno Orange
            )

            # --- RE-ATTACH AUTHOR, TIMESTAMP & FOOTER ---
            author_icon = None
            timestamp = message.created_at

            if message.embeds:
                jp_embed = message.embeds[0]
                if jp_embed.author:
                    author_icon = jp_embed.author.icon_url
                if jp_embed.timestamp:
                    timestamp = jp_embed.timestamp

            en_embed.set_author(
                name="ハイキュー!!FLY HIGH【公式】",
                icon_url=author_icon,
                url=None  # Disables link on the author line
            )
            en_embed.timestamp = timestamp
            en_embed.set_footer(text="Powered by Crow Bot")

            # --- IMAGE RE-ATTACH ---
            if extracted_img_url:
                en_embed.set_image(url=extracted_img_url)

            # Send both notification text and embed card
            await self.en_channel.send(content=notification_text, embed=en_embed)
            logger.info("Successfully processed post with Gemini and posted to EN channel!")

            # Record & refresh cache
            self.processed_messages[message.id] = True
            self.processed_messages.move_to_end(message.id)

            # Evict oldest entry when capacity is reached
            if len(self.processed_messages) > 1000:
                self.processed_messages.popitem(last=False)

        finally:
            self.processing_messages.discard(message.id)

# ==============================================================================
# 6. CATCH-UP TASK
# ==============================================================================
    async def catch_up_missing_translations(self) -> None:
        """Reconciles and translates Japanese posts missed while the bot was offline."""
        logger.debug("Checking for un-translated posts...")

        en_urls = set()
        missing_messages = []

        try:
            # Collect unique post URLs already posted in the EN channel
            async for en_msg in self.en_channel.history(limit=20):
                if url := extract_twitter_url(en_msg):
                    en_urls.add(url)

            async for jp_msg in self.jp_channel.history(limit=10):
                # Skip if already translated OR currently undergoing live translation
                if jp_msg.id in self.processed_messages or jp_msg.id in self.processing_messages:
                    continue

                # Extract the exact URL from the original JP message/embed
                if jp_url := extract_twitter_url(jp_msg):
                    if jp_url in en_urls:
                        self.processed_messages[jp_msg.id] = True
                        self.processed_messages.move_to_end(jp_msg.id)
                    else:
                        missing_messages.append(jp_msg)

        except (discord.HTTPException, aiohttp.ClientError) as e:
            logger.error(f"Failed to fetch channel history during catch-up: {e}")
            return

        missing_messages.reverse()

        if missing_messages:
            logger.info(f"Found {len(missing_messages)} missing post(s). Translating now...")

            # return_exceptions=True ensures that if one message fails catastrophically,
            # the rest of the batch will still finish translating.
            await asyncio.gather(
                *(self.process_and_send_message(msg) for msg in missing_messages),
                return_exceptions=True
            )

            logger.info("Catch-up complete!")
        else:
            logger.debug("All recent posts are already translated!")

# ==============================================================================
# 7. BACKGROUND TASKS & EVENT LISTENERS
# ==============================================================================
    @tasks.loop(minutes=15)
    async def periodic_catch_up(self):
        """Periodically checks for missed translations without locking live event loops."""
        logger.debug("Running scheduled periodic catch-up check...")
        await self.catch_up_missing_translations()

    @periodic_catch_up.before_loop
    async def before_periodic_catch_up(self):
        """Validates configuration and permissions before the loop starts running."""
        await self.bot.wait_until_ready()

        # Abort startup sequence if essential channels are missing
        if not self.jp_channel or not self.en_channel:
            logger.critical("Invalid channel configuration or channels inaccessible.")
            await self.bot.close()
            raise SystemExit(1)

        # --- PERMISSION CHECKS ---
        jp_perms = self.jp_channel.permissions_for(self.jp_channel.guild.me)
        en_perms = self.en_channel.permissions_for(self.en_channel.guild.me)

        # JP Channel needs to view channel & read message history
        if not (jp_perms.view_channel and jp_perms.read_message_history):
            logger.critical(f"Missing View/History permissions in JP channel ({self.jp_channel_id})")
            await self.bot.close()
            raise SystemExit(1)

        # EN Channel needs view, history, send, and embed permissions
        if not (en_perms.view_channel and en_perms.read_message_history and
                en_perms.send_messages and en_perms.embed_links):
            logger.critical(f"Missing Send/Embed permissions in EN channel ({self.en_channel_id})")
            await self.bot.close()
            raise SystemExit(1)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.channel_id != self.jp_channel_id:
            return

        # Early exit if already handled or currently processing
        if payload.message_id in self.processed_messages or payload.message_id in self.processing_messages:
            return

        # Verify that payload.data actually contains a populated embed
        raw_embeds = (payload.data or {}).get("embeds", [])
        if not raw_embeds or not any(e.get("description") or e.get("image") or e.get("url") for e in raw_embeds):
            return

        try:
            # Fetch fresh message directly to avoid stale cache data
            message = await self.jp_channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.HTTPException):
            return

        if message.embeds:
            await self.process_and_send_message(message)

async def setup(bot: "CrowBot"):
    await bot.add_cog(Translator(bot))