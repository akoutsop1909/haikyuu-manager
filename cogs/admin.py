import asyncio
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

from ui.admin import AdminHomeView

logger = logging.getLogger(__name__)

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.admin_channel_id = int(os.getenv("ADMIN_CHANNEL_ID", 0))

        if self.admin_channel_id == 0:
            logger.critical("Admin cog missing ADMIN_CHANNEL_ID in .env!")
            raise SystemExit(1)

        # State tracking
        self.has_run_startup = False  # Prevents duplicate catch-up execution on gateway reconnects

    @property
    def admin_channel(self) -> discord.TextChannel | None:
        return self.bot.get_channel(self.admin_channel_id)

    async def cog_load(self) -> None:
        asyncio.create_task(self.initialize_admin())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Enforces admin permissions and limits commands to the designated admin channel."""
        # Prevent execution before initialize_admin finishes running
        if not self.bot.is_ready() or not self.has_run_startup:
            await interaction.response.send_message(
                "⏳ Bot is currently starting up! Please try again in a few seconds.",
                ephemeral=True
            )
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ You do not have permission to use admin commands.",
                ephemeral=True
            )
            return False

        if self.admin_channel_id and interaction.channel_id != self.admin_channel_id:
            await interaction.response.send_message(
                f"🔒 Admin commands can only be used in <#{self.admin_channel_id}>!",
                ephemeral=True
            )
            return False

        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Silences CheckFailure errors raised by interaction_check."""
        if isinstance(error, app_commands.CheckFailure):
            return
        logger.error(f"Unhandled error in admin command {interaction.command.name}: {error}", exc_info=True)

    @app_commands.command(name="admin", description="Debug tools for server administrators.")
    @app_commands.default_permissions(administrator=True)
    async def admin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await AdminHomeView.send_panel(interaction)

    async def initialize_admin(self):
        await self.bot.wait_until_ready()

        if self.has_run_startup:
            return

        if not self.admin_channel:
            logger.critical(f"Invalid channel configuration or Admin channel ({self.admin_channel_id}) inaccessible.")
            await self.bot.close()
            raise SystemExit(1)

        perms = self.admin_channel.permissions_for(self.admin_channel.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            logger.critical(f"Missing permissions in Admin channel ({self.admin_channel_id})")
            await self.bot.close()
            raise SystemExit(1)

        self.has_run_startup = True

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))