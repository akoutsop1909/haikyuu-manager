import discord

from database import boost_admin_account, grant_all_cards, user_exists, delete_user, ADMIN_PACK
from ui.utils import format_number


def format_pack_resources() -> str:
    """Helper to return formatted resource reward lines."""
    return (
        f"🪙 Scout Coins: **{format_number(ADMIN_PACK['scout_coins'])}**\n"
        f"🏐 Practice Balls: **{format_number(ADMIN_PACK['practice_balls'])}**\n"
        f"🥤 Sports Drinks: **{format_number(ADMIN_PACK['sports_drinks'])}**\n"
        f"🎟️ Drink Vouchers: **{format_number(ADMIN_PACK['drink_vouchers'])}**"
    )


class AdminHomeView(discord.ui.View):
    def __init__(self, user_id: int, has_account: bool = True):
        super().__init__(timeout=180)
        self.user_id = user_id

        # Disable the delete button if no account exists
        if not has_account:
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.label == "Delete My Account":
                    child.disabled = True
                    child.style = discord.ButtonStyle.secondary

    @classmethod
    async def create(cls, user_id: int):
        """Asynchronously initialize the view with correct account status."""
        exists = await user_exists(user_id)
        return cls(user_id, has_account=exists)

    @classmethod
    async def send_panel(cls, interaction: discord.Interaction):
        """Encapsulates all logic for building and sending the admin control panel."""
        view = await cls.create(interaction.user.id)
        embed = view.build_embed(interaction)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @staticmethod
    def build_embed(interaction: discord.Interaction) -> discord.Embed:
        embed = discord.Embed(
            title="🛠️ Admin Control Panel",
            description=f"Manage administrative options for **{interaction.user.display_name}**.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Warning",
            value="Deleting your account is permanent. Your inventory, teams, and cards will be removed.",
            inline=False
        )
        return embed

    @discord.ui.button(label="Boost Account", style=discord.ButtonStyle.success, emoji="⚡", row=0)
    async def create_admin_account(self, interaction: discord.Interaction, _button: discord.ui.Button):
        is_new = await boost_admin_account(interaction.user.id)

        if is_new:
            status_text = "Created New Admin Account"
            desc = "🎁 **Starter Pack & Starter Team 1** granted!\n\n**Admin Pack Items:**\n" + format_pack_resources()
        else:
            status_text = "Boosted Existing Account"
            desc = format_pack_resources()

        embed = discord.Embed(
            title=f"✅ {status_text}",
            description=desc,
            color=discord.Color.green()
        )

        # Refresh the view so the delete button becomes enabled
        new_view = await AdminHomeView.create(interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="Unlock All Cards", style=discord.ButtonStyle.primary, emoji="🎴", row=0)
    async def unlock_all_cards(self, interaction: discord.Interaction, _button: discord.ui.Button):
        result = await grant_all_cards(interaction.user.id)

        if result["is_new"]:
            status_prefix = "Created Admin Account & "
            desc = "🎁 **Starter Pack & Starter Team 1** granted!\n\n**Admin Pack Items:**\n" + format_pack_resources() + "\n\n"
        else:
            status_prefix = ""
            desc = ""

        desc += f"🎴 **+{result['granted_cards_count']}** new card(s) unlocked!"

        embed = discord.Embed(
            title=f"✅ {status_prefix}All Cards Unlocked",
            description=desc,
            color=discord.Color.blue()
        )

        # Refresh the view here as well
        new_view = await AdminHomeView.create(interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="Delete My Account", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_account(self, interaction: discord.Interaction, _button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠️ Confirm Account Deletion",
            description="Are you sure you want to permanently delete your account? This action **cannot** be undone.",
            color=discord.Color.dark_red()
        )
        await interaction.response.edit_message(embed=embed, view=AdminConfirmDeleteView(self.user_id))


class AdminConfirmDeleteView(discord.ui.View):
    """Confirmation view to prevent accidental account deletions."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="Yes, Delete My Account", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_delete(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await delete_user(interaction.user.id)

        embed = discord.Embed(
            title="🗑️ Account Deleted",
            description=(
                "Your account, inventory, and cards have been successfully removed.\n\n"
                "🛠️ **Admin Options:** Use the buttons below to create or boost a new account."
            ),
            color=discord.Color.red()
        )

        new_view = await AdminHomeView.create(self.user_id)
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, _button: discord.ui.Button):
        embed = AdminHomeView.build_embed(interaction)
        new_view = await AdminHomeView.create(self.user_id)
        await interaction.response.edit_message(embed=embed, view=new_view)