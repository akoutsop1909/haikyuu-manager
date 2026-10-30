import asyncio
import discord

from ui.utils import lock_view_ui, format_inventory_lines
from engine.data_loader import CARDS_BY_ID, STARTER_PACK, ITEM_METADATA
from database import register_user, claim_daily, claim_birthday, get_inventory

# Load item metadata shortcuts
COIN_EMOJI = ITEM_METADATA["coins"]["emoji"]
BALL_EMOJI = ITEM_METADATA["balls"]["emoji"]

class UserHomeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @classmethod
    async def send_menu(cls, interaction: discord.Interaction):
        view = cls(interaction.user.id)
        embed = await view.build_embed(interaction)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def build_embed(self, interaction: discord.Interaction) -> discord.Embed:
        is_new_user, daily, birthday, inventory = await asyncio.gather(
            register_user(self.user_id),
            claim_daily(self.user_id),
            claim_birthday(self.user_id),
            get_inventory(self.user_id)
        )
        if is_new_user:
            welcome_text = (
                f"Welcome to the club, **{interaction.user.display_name}**! "
                f"Time to raise a powerhouse team and make it to the Nationals."
            )
        else:
            welcome_text = (
                f"Welcome back to the gym, **{interaction.user.display_name}**! "
                f"The team is counting on you today."
            )

        if daily.claimed:
            header = "**Daily Reward Claimed!**"
            rewards = f"+{daily.scout_coins:,} {COIN_EMOJI}   +{daily.practice_balls:,} {BALL_EMOJI}\n"
        else:
            header = "**Daily Already Claimed**"
            rewards = ""

        daily_status = (
            f"\n\n{header}\n"
            f"{rewards}"
            f"📅 Days Played: {daily.total_logins}\n"
            f"⏳ Reset: <t:{daily.next_reset}:R>"
        )

        embed = discord.Embed(
            title="🏐 Reach the Top!!",
            description=f"{welcome_text}{daily_status}",
            color=discord.Color.orange()
        )

        if birthday and birthday.claimed and birthday.birthdays_today:
            names_list = "\n".join([f"• {name}" for name in birthday.birthdays_today])

            if birthday.bonus_names:
                owned_str = ", ".join(birthday.bonus_names)
                bonus_text = f"\n*(Includes Owner Bonus for {owned_str}!)*"
            else:
                bonus_text = ""

            title = self._get_birthday_title(birthday.birthdays_today, "Today")

            embed.add_field(
                name=title,
                value=(
                    f"{names_list}\n"
                    f"+{birthday.scout_coins:,} {COIN_EMOJI}   +{birthday.practice_balls:,} {BALL_EMOJI}{bonus_text}"
                ),
                inline=False
            )

        if birthday and birthday.birthdays_tomorrow:
            names_str = "\n".join([f"• {name}" for name in birthday.birthdays_tomorrow])
            title = self._get_birthday_title(birthday.birthdays_tomorrow, "Tomorrow")
            embed.add_field(
                name=title,
                value=names_str,
                inline=False
            )

        if is_new_user:
            team_lines = "\n".join([
                f"• **[{CARDS_BY_ID[c]['position']}]** {CARDS_BY_ID[c]['name']}"
                for c in STARTER_PACK["cards"] if c in CARDS_BY_ID
            ])

            embed.add_field(
                name="Starter Pack Received",
                value=(
                    f"+{STARTER_PACK['scout_coins']:,} {COIN_EMOJI}   +{STARTER_PACK['practice_balls']:,} {BALL_EMOJI}\n\n"
                    f"**Starter Team**\n"
                    f"{team_lines}"
                ),
                inline=False
            )

        embed.add_field(
            name="Inventory",
            value=format_inventory_lines(inventory),
            inline=False
        )

        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        return embed

    # --- ROW 0: Management ---
    @discord.ui.button(label="Scout", style=discord.ButtonStyle.primary, emoji="🔍", row=0)
    async def scout_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.scout import ScoutScreenView
        await self._navigate_to_screen(interaction, ScoutScreenView.create)

    @discord.ui.button(label="Train", style=discord.ButtonStyle.primary, emoji="🏋️", row=0)
    async def train_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.train import TrainScreenView
        await self._navigate_to_screen(interaction, TrainScreenView.create)

    @discord.ui.button(label="Team", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def team_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.team import TeamScreenView
        await self._navigate_to_screen(interaction, TeamScreenView.create)

    # --- ROW 1: Active Game Modes ---
    @discord.ui.button(label="Match", style=discord.ButtonStyle.success, emoji="⚔️", row=1)
    async def match_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.match import MatchScreenView
        await self._navigate_to_screen(interaction, MatchScreenView.create)

    @discord.ui.button(label="TOTC", style=discord.ButtonStyle.success, emoji="👑", row=1)
    async def totc_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Top of the Court view coming soon!", ephemeral=True)

    @discord.ui.button(label="Tourneys", style=discord.ButtonStyle.success, emoji="🏆", row=1)
    async def tourneys_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Tournaments view coming soon!", ephemeral=True)

    # --- ROW 2: Event & Utilities ---
    @discord.ui.button(label="Trip", style=discord.ButtonStyle.secondary, emoji="🚌", row=2)
    async def trip_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.trip import TripScreenView
        await self._navigate_to_screen(interaction, TripScreenView.create)

    @discord.ui.button(label="Collection", style=discord.ButtonStyle.secondary, emoji="🎴", row=2)
    async def collection_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Collection view coming soon!", ephemeral=True)

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    async def help_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Help & Guides coming soon!", ephemeral=True)

    @staticmethod
    def _get_birthday_title(names: list, day_label: str) -> str:
        suffix = "Birthday" if len(names) == 1 else "Birthdays"
        return f"{day_label}'s {suffix}"

    async def _navigate_to_screen(self, interaction: discord.Interaction, view_factory):
        """Helper to eliminate repetition across screen navigation buttons."""
        await lock_view_ui(self, interaction)
        view, content, embed, attachments = await view_factory(interaction.user.id)
        await interaction.edit_original_response(content=content, embed=embed, view=view, attachments=attachments)