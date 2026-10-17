import discord

from ui.gacha import UserHomeView
from ui.utils import create_card_embed, get_card_image_file, get_banner_file, format_resonance_stars, format_number
from data_loader import SCOUT_CONFIG
from database import get_inventory, perform_scout

# Load scout configurations
COST_PER_PULL = SCOUT_CONFIG["cost_per_pull"]
WEIGHTS = SCOUT_CONFIG["rarity_weights"]
TOTAL_WEIGHT = sum(WEIGHTS.values()) or 1

def attach_scout_status_field(embed: discord.Embed, card_data: dict):
    """Helper to append gacha pull status to a card embed."""
    status = card_data.get("status")
    if status == "NEW":
        embed.add_field(name="Status", value="✨ **NEW PLAYER!**", inline=False)
    elif status == "DUPLICATE":
        res_stars = format_resonance_stars(card_data.get('new_resonance', 0))
        embed.add_field(
            name="Status",
            value=f"🌟 Duplicate (Resonance: {res_stars})",
            inline=False,
        )
    elif status == "OVERFLOW":
        count = card_data.get("vouchers", 1)
        label = "Drink Voucher" if count == 1 else "Drink Vouchers"
        embed.add_field(
            name="Status",
            value=f"🎟️ Max Resonance (+{count} {label})",
            inline=False,
        )

def build_card_result_payload(card_data: dict, scout_coins: int) -> tuple[discord.Embed, list[discord.File]]:
        """Helper to build embed, status field, footer, and image attachment for a pulled card."""
        embed = create_card_embed(card_data, show_level_info=False)
        attach_scout_status_field(embed, card_data)
        embed.set_footer(text=f"Balance: 🪙 {format_number(scout_coins)}")

        image_file = get_card_image_file(card_data)
        attachments = [image_file] if image_file else []

        return embed, attachments

class ScoutSelectMenu(discord.ui.Select):
    def __init__(self, pulled_cards: list, summary_embed: discord.Embed, balance: int):
        self.pulled_cards = pulled_cards
        self.summary_embed = summary_embed
        self.balance = balance

        options = [
            discord.SelectOption(
                label="📋 Show All Results",
                description="View the 10x scout summary list",
                value="summary",
            )
        ]
        for idx, card in enumerate(pulled_cards):
            label = f"{idx + 1}. {card['name']}"
            desc = f"{card['rarity']} | Pos: {card['position']} | {card['school']}"
            options.append(
                discord.SelectOption(label=label, description=desc, value=str(idx))
            )

        super().__init__(
            placeholder="Select a player to view details...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "summary":
            await interaction.response.edit_message(
                embed=self.summary_embed, attachments=[], view=self.view
            )
            return

        selected_idx = int(val)
        card_data = self.pulled_cards[selected_idx]

        embed, attachments = build_card_result_payload(card_data, self.balance)
        await interaction.response.edit_message(embed=embed, attachments=attachments, view=self.view)

class ScoutScreenView(discord.ui.View):

    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.dropdown: ScoutSelectMenu | None = None

    @staticmethod
    async def build_embed(user_id: int) -> discord.Embed:
        inventory = await get_inventory(user_id)

        cost_10x = COST_PER_PULL * 10

        rates_str = " • ".join(
            [f"{rarity}: {weight / TOTAL_WEIGHT * 100:.0f}%" for rarity, weight in WEIGHTS.items()]
        )

        banner_file = get_banner_file("scout")

        embed = discord.Embed(
            title="🔍 Player Scouting",
            description=(
                "Scout elite players across schools to build your dream lineup!\n\n"
                f"• 1x Scout: 🪙 **{COST_PER_PULL:,}**\n"
                f"• 10x Scout: 🪙 **{cost_10x:,}**\n\n"
                f"📊 **Drop Rates:** {rates_str}"
            ),
            color=discord.Color.gold(),
        )
        if banner_file:
            embed.set_image(url=f"attachment://{banner_file.filename}")
        embed.set_footer(text=f"Balance: 🪙 {format_number(inventory.scout_coins)}")
        return embed

    def _cleanup_dropdown(self):
        if self.dropdown:
            self.remove_item(self.dropdown)
            self.dropdown = None

    @discord.ui.button(label="Scout 1", style=discord.ButtonStyle.primary, row=1)
    async def scout_one(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._handle_scout(interaction, count=1)

    @discord.ui.button(label="Scout 10", style=discord.ButtonStyle.success, row=1)
    async def scout_ten(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._handle_scout(interaction, count=10)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button):
        embed = await UserHomeView.build_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=UserHomeView(self.user_id), attachments=[])

    async def _handle_scout(self, interaction: discord.Interaction, count: int):
        cost = count * COST_PER_PULL
        inventory = await get_inventory(interaction.user.id)

        if inventory.scout_coins < cost:
            self._cleanup_dropdown()
            banner_file = get_banner_file("scout_fail")

            embed = discord.Embed(
                title="❌ Scout Failed",
                description=(
                    f"You don't have enough Scout Coins!\n\n"
                    f"• Required: 🪙 **{cost}**\n"
                    f"• Your Balance: 🪙 **{inventory.scout_coins}**"
                ),
                color=discord.Color.gold(),
            )

            if banner_file:
                embed.set_image(url=f"attachment://{banner_file.filename}")

            attachments = [banner_file] if banner_file else []

            await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
            return

        pulled_cards = await perform_scout(interaction.user.id, count)

        # Safety check for unexpected empty results
        if not pulled_cards:
            await interaction.response.send_message(
                "❌ An error occurred while processing your scout. Please try again.",
                ephemeral=True
            )
            return

        new_balance = inventory.scout_coins - cost

        self._cleanup_dropdown()

        if count == 1:
            card_data = pulled_cards[0]
            embed, attachments = build_card_result_payload(card_data, new_balance)

            await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
        else:
            results_formatted = []
            for idx, c in enumerate(pulled_cards, 1):
                status_tag = ""
                if c["status"] == "NEW":
                    status_tag = " `NEW`"
                elif c["status"] == "DUPLICATE":
                    status_tag = f" `R{c['new_resonance']}`"
                elif c["status"] == "OVERFLOW":
                    status_tag = f" `+{c['drink_vouchers']}🎟️`"

                line = f"`{idx:02d}.` **[{c['position']}]** {c['name']} *({c['rarity']})*{status_tag}"
                results_formatted.append(line)

            description_text = "\n".join(results_formatted)

            embed = discord.Embed(
                title="🔍 Scout Results (10x Pull)",
                description=description_text +
                            "\n\n👇 Select a player from the dropdown below to view his details!",
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"Balance: 🪙 {format_number(new_balance)}")

            self.dropdown = ScoutSelectMenu(pulled_cards, summary_embed=embed, balance=new_balance)
            self.add_item(self.dropdown)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])