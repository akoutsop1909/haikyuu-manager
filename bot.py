"""Crow Bot - Main Entry Point."""

# ==============================================================================
# 1. SETUP, CONFIGURATION & CLIENT DEFINITION
# ==============================================================================
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import ssl
import time

import aiohttp
from better_profanity import profanity
import certifi
import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import init_db_pool

# A. Logging Infrastructure
logger = logging.getLogger(__name__)

def setup_production_logging() -> None:
    """Configures application-wide logging to file and stdout streams."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    log_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        logs_dir / "crow_bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler],
        force=True  # Overrides any early logging initializations from third-party libraries
    )

    # Silence noisy third-party library loggers
    for lib in ("aiohttp", "discord", "discord.client", "discord.gateway", "httpx"):
        logging.getLogger(lib).setLevel(logging.ERROR)

# B. Path Setup & Environment Validation
PROJECT_ROOT = Path(__file__).resolve().parent
COGS_DIR = PROJECT_ROOT / "cogs"

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN must be set in .env")
    raise SystemExit(1)

# C. Discord Client Definition & Instantiation
class CrowBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        # Load profanity filter dictionary on startup
        profanity.load_censor_words()

        # Initialize PostgreSQL Connection Pool
        await init_db_pool()

        # Create or recreate session if closed or missing on reconnect retry
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
                timeout=aiohttp.ClientTimeout(total=15, connect=5)
            )

        # Load cogs safely (skip if already loaded on previous attempt)
        for file in COGS_DIR.glob("*.py"):
            # Skip private module helpers (e.g., __init__.py, _utils.py)
            if file.name.startswith("_"):
                continue

            extension = f"cogs.{file.stem}"
            if extension not in self.extensions:
                try:
                    await self.load_extension(extension)
                    logger.debug(f"Loaded cog extension: {extension}")
                except Exception as e:
                    logger.error(f"Failed to load cog extension {extension}: {e}", exc_info=True)
                    await self.close()
                    raise SystemExit(1)

        # Sync slash commands to Discord
        await self.tree.sync()

    async def close(self):
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            await asyncio.sleep(0.25)  # Yields to event loop so underlying SSL transports close cleanly
            logger.info("Closed aiohttp ClientSession.")

        await super().close()

intents = discord.Intents.default()
intents.message_content = True
bot = CrowBot(command_prefix="!", intents=intents)

# ==============================================================================
# 2. DISCORD EVENTS & BOT STARTUP
# ==============================================================================
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}!")

def main():
    setup_production_logging()

    max_retries = 5
    base_delay = 5  # seconds

    for attempt in range(1, max_retries + 1):
        try:
            bot.run(DISCORD_TOKEN, log_handler=None)
            break  # Clean exit if the bot shuts down normally
        except (discord.errors.HTTPException, aiohttp.ClientError, Exception) as e:
            logger.error(f"Connection lost or gateway error (Attempt {attempt}/{max_retries}): {e}")

            if attempt < max_retries:
                retry_delay = base_delay * attempt  # Incremental backoff (5s, 10s, 15s...)
                logger.info(f"Retrying connection in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.critical("Maximum reconnection attempts reached. Shutting down.")

if __name__ == "__main__":
    main()