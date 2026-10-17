import discord

from ui.utils import format_number, get_banner_file
from data_loader import CARDS_BY_ID, STARTER_PACK
from database import register_user, claim_daily, claim_birthday, get_inventory


class UserHomeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @classmethod
    async def send_menu(cls, interaction: discord.Interaction):
        """Encapsulates all logic for building and sending the main gacha menu."""
        view = cls(interaction.user.id)
        embed = await view.build_embed(interaction)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @staticmethod
    async def build_embed(interaction: discord.Interaction) -> discord.Embed:
        """Handles user setup/rewards and constructs the standardized Main Menu embed."""
        is_new_user = await register_user(interaction.user.id)
        daily = await claim_daily(interaction.user.id)
        birthday = await claim_birthday(interaction.user.id)
        inventory = await get_inventory(interaction.user.id)

        daily_status = ""
        if daily:
            if daily.claimed:
                daily_status = (
                    f"\n\n**Daily Reward Claimed!**\n"
                    f"+{daily.scout_coins:,} 🪙   +{daily.practice_balls:,} 🏐\n"
                    f"📅 Days Played: {daily.total_logins}\n"
                    f"⏳ Reset: <t:{daily.next_reset}:R>"
                )
            else:
                daily_status = (
                    f"\n\n**Daily Already Claimed**\n"
                    f"📅 Days Played: {daily.total_logins}\n"
                    f"⏳ Reset: <t:{daily.next_reset}:R>"
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

            title = "Today's Birthday" if len(birthday.birthdays_today) == 1 else "Today's Birthdays"

            embed.add_field(
                name=title,
                value=(
                    f"{names_list}\n"
                    f"+{birthday.scout_coins:,} 🪙   +{birthday.practice_balls:,} 🏐{bonus_text}"
                ),
                inline=False
            )

        if birthday and birthday.birthdays_tomorrow:
            names_str = "\n".join([f"• {name}" for name in birthday.birthdays_tomorrow])
            title = "Tomorrow's Birthday" if len(birthday.birthdays_tomorrow) == 1 else "Tomorrow's Birthdays"
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
                    f"+{STARTER_PACK['scout_coins']:,} 🪙   +{STARTER_PACK['practice_balls']:,} 🏐\n\n"
                    f"**Starter Team**\n"
                    f"{team_lines}"
                ),
                inline=False
            )

        embed.add_field(
            name="Inventory",
            value=(
                f"🪙 Scout Coins: **{format_number(inventory.scout_coins)}**\n"
                f"🏐 Practice Balls: **{format_number(inventory.practice_balls)}**\n"
                f"🥤 Sports Drinks: **{format_number(inventory.sports_drinks)}**\n"
                f"🎟️ Drink Vouchers: **{format_number(inventory.drink_vouchers)}**"
            ),
            inline=False
        )

        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        return embed

    # --- ROW 0: Management ---
    @discord.ui.button(label="Scout", style=discord.ButtonStyle.primary, emoji="🔍", row=0)
    async def scout_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.scout import ScoutScreenView
        embed = await ScoutScreenView.build_embed(interaction.user.id)
        banner_file = get_banner_file("scout")

        attachments = [banner_file] if banner_file else []

        await interaction.response.edit_message(
            embed=embed,
            view=ScoutScreenView(interaction.user.id),
            attachments=attachments
        )

    @discord.ui.button(label="Train", style=discord.ButtonStyle.primary, emoji="🏋️", row=0)
    async def train_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.train import TrainScreenView
        view, content, embed, attachments = await TrainScreenView.create(interaction.user.id)
        await interaction.response.edit_message(content=content, embed=embed, view=view, attachments=attachments)

    @discord.ui.button(label="Team", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def teams_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from ui.team import TeamScreenView
        view, content, embed, attachments = await TeamScreenView.create(interaction.user.id)
        await interaction.response.edit_message(content=content, embed=embed, view=view, attachments=attachments)

    # --- ROW 1: Active Game Modes ---
    @discord.ui.button(label="Match", style=discord.ButtonStyle.success, emoji="⚔️", row=1)
    async def match_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Match simulation starting...", ephemeral=True)

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
        view, content, embed, attachments = await TripScreenView.create(interaction.user.id)
        await interaction.response.edit_message(content=content, embed=embed, view=view, attachments=attachments)

    @discord.ui.button(label="Collection", style=discord.ButtonStyle.secondary, emoji="🎴", row=2)
    async def collection_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Collection view coming soon!", ephemeral=True)

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    async def help_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_message("Help & Guides coming soon!", ephemeral=True)