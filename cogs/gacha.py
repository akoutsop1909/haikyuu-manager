import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from ui.gacha import UserHomeView

logger = logging.getLogger(__name__)

class Gacha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Load and validate environment variables
        self.gacha_channel_id = int(os.getenv("GACHA_CHANNEL_ID", 0))

        if self.gacha_channel_id == 0:
            logger.critical("Gacha cog missing required channel IDs in .env!")
            raise SystemExit(1)

        # State tracking
        self.has_run_startup = False  # Prevents duplicate catch-up execution on gateway reconnects

    @property
    def gacha_channel(self) -> discord.TextChannel | None:
        """Returns the cached gacha channel object, or None if unavailable."""
        return self.bot.get_channel(self.gacha_channel_id)

    async def cog_load(self) -> None:
        """Async setup hook to launch channel validation on startup."""
        asyncio.create_task(self.initialize_gacha())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Routes slash commands to their designated channels."""
        # 0. Prevent execution before initialize_gacha finishes running
        if not self.bot.is_ready() or not self.has_run_startup:
            await interaction.response.send_message(
                "⏳ Bot is currently starting up! Please try again in a few seconds.",
                ephemeral=True
            )
            return False

        # 1. Player Gacha Commands routing (e.g., /register, /play)
        if self.gacha_channel_id and interaction.channel_id != self.gacha_channel_id:
            await interaction.response.send_message(
                f"❌ Gacha commands can only be used in <#{self.gacha_channel_id}>!",
                ephemeral=True
            )
            return False

        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Silences CheckFailure log spam when routing checks reject execution."""
        if isinstance(error, app_commands.CheckFailure):
            # The error response was already handled inside interaction_check
            return

        # Log unexpected command execution errors normally
        logger.error(f"Unhandled app command error in {interaction.command.name}: {error}", exc_info=True)

    @app_commands.command(name="play", description="Play Haikyuu!! gacha game: Reach the Top!!")
    async def play(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await UserHomeView.send_menu(interaction)

    async def initialize_gacha(self):
        """Validates channel existence and permissions once the bot is ready."""
        await self.bot.wait_until_ready()

        if self.has_run_startup:
            logger.info("Reconnected to Discord gateway.")
            return

        # 2. Check channel existence
        if not self.gacha_channel:
            logger.critical("Invalid channel configuration or Gacha channels inaccessible.")
            await self.bot.close()
            raise SystemExit(1)

        # 3. Check permissions
        gacha_perms = self.gacha_channel.permissions_for(self.gacha_channel.guild.me)

        # Gacha channel needs view, send, and embed permissions
        if not (gacha_perms.view_channel and gacha_perms.send_messages and gacha_perms.embed_links):
            logger.critical(f"Missing View/Send/Embed permissions in Gacha channel ({self.gacha_channel_id})")
            await self.bot.close()
            raise SystemExit(1)

        self.has_run_startup = True

async def setup(bot):
    await bot.add_cog(Gacha(bot))