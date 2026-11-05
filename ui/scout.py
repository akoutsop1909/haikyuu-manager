import discord

from ui.gacha import UserHomeView
from ui.utils import lock_view_ui, create_card_embed, get_card_image_file, get_banner_file, format_resonance_stars, \
    format_resonance_badge, format_number
from engine.data_loader import SCOUT_CONFIG, ITEM_METADATA
from database import get_inventory, perform_scout

# Load scout configurations & item medatadata shortcuts
COST_PER_PULL = SCOUT_CONFIG["cost_per_pull"]
WEIGHTS = SCOUT_CONFIG["rarity_weights"]
TOTAL_WEIGHT = sum(WEIGHTS.values()) or 1

COIN_NAME = ITEM_METADATA["coins"]["name"]
COIN_EMOJI = ITEM_METADATA["coins"]["emoji"]
VOUCHER_NAME = ITEM_METADATA["vouchers"]["name"]
VOUCHER_EMOJI = ITEM_METADATA["vouchers"]["emoji"]

class ScoutSelectMenu(discord.ui.Select):
    def __init__(self, pulled_cards: list):
        self.pulled_cards = pulled_cards

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
        await lock_view_ui(self.view, interaction)

        val = self.values[0]
        if val == "summary":
            self.view.selected_card_data = None
            await self.view.update_screen(interaction)
            return

        selected_idx = int(val)
        self.view.selected_card_data = self.pulled_cards[selected_idx]
        await self.view.update_screen(interaction)

class ScoutScreenView(discord.ui.View):
    def __init__(self, user_id: int, pulled_cards: list[dict] | None = None, balance: int = 0):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.pulled_cards = pulled_cards
        self.balance = balance
        self.state = "scout"  # Can be "scout", "results", "inspect", or "failed"
        self.selected_card_data: dict | None = None
        self.dropdown: ScoutSelectMenu | None = None
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int) -> tuple["ScoutScreenView", str | None, discord.Embed, list[discord.File]]:
        inventory = await get_inventory(user_id)
        view = cls(user_id, balance=inventory.scout_coins)
        embed, attachments = await view._get_screen_payload()
        return view, None, embed, attachments

    async def build_embed(self) -> discord.Embed:
        # State 1: Inspecting a specific card from x10 results
        if self.selected_card_data:
            embed = create_card_embed(self.selected_card_data, show_level_info=False)
            self._attach_scout_status_field(embed, self.selected_card_data)
            embed.set_footer(text=f"Balance: {COIN_EMOJI} {format_number(self.balance)}")
            return embed

        # Determine title, description, and balance value based on active state
        if self.state == "failed":
            title = "❌ Scout Failed"
            description = (
                f"You don't have enough {COIN_NAME}!\n\n"
                f"• Required: {COIN_EMOJI} **{self.failed_cost:,}**\n"
                f"• Your Balance: {COIN_EMOJI} **{self.failed_balance:,}**"
            )
            balance_val = self.failed_balance

        elif self.pulled_cards:
            # State 2: x10 Summary View Content
            results_formatted = []
            for idx, c in enumerate(self.pulled_cards, 1):
                status_tag = ""
                if c["status"] == "NEW":
                    status_tag = " `NEW`"
                elif c["status"] == "DUPLICATE":
                    res_str = format_resonance_badge(c.get('new_resonance', 0))
                    status_tag = f" `{res_str}`"
                elif c["status"] == "OVERFLOW":
                    status_tag = f" `+{c['drink_vouchers']}{VOUCHER_EMOJI}`"

                line = f"`{idx:02d}.` **[{c['position']}]** {c['name']} *({c['rarity']})*{status_tag}"
                results_formatted.append(line)

            title = "🔍 Scout Results (x10 Pull)"
            description = "\n".join(results_formatted) + "\n\n👇 Select a player from the dropdown below to view details!"
            balance_val = self.balance

        else:
            # State 3: Default Main Scout Menu Content
            inventory = await get_inventory(self.user_id)
            cost_10x = COST_PER_PULL * 10
            rates_str = " • ".join(
                [f"{rarity}: {weight / TOTAL_WEIGHT * 100:.0f}%" for rarity, weight in WEIGHTS.items()]
            )

            title = "🔍 Player Scouting"
            description = (
                "Scout elite players across schools to build your dream lineup!\n\n"
                f"• Scout x1: {COIN_EMOJI} **{COST_PER_PULL:,}**\n"
                f"• Scout x10: {COIN_EMOJI} **{cost_10x:,}**\n\n"
                f"📊 **Drop Rates:** {rates_str}"
            )
            balance_val = inventory.scout_coins

        # Unified presentation for Failed, 10x Summary, and Main Menu states
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Balance: {COIN_EMOJI} {format_number(balance_val)}")
        return embed

    def _setup_components(self):
        self.clear_items()

        # Row 0: Dropdown Menu (active whenever pulled cards exist)
        if self.pulled_cards:
            self.dropdown = ScoutSelectMenu(self.pulled_cards)
            self.add_item(self.dropdown)

        # Row 1: Scout Buttons (Always available)
        btn_scout_1 = discord.ui.Button(label="Scout x1", style=discord.ButtonStyle.primary, row=1)
        btn_scout_10 = discord.ui.Button(label="Scout x10", style=discord.ButtonStyle.success, row=1)

        btn_scout_1.callback = lambda i: self._handle_scout(i, count=1)
        btn_scout_10.callback = lambda i: self._handle_scout(i, count=10)

        self.add_item(btn_scout_1)
        self.add_item(btn_scout_10)

        # Row 2: Back Button (Returns to Main Menu / UserHomeView)
        btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
        btn_back.callback = self._handle_back
        self.add_item(btn_back)

    async def update_screen(self, interaction: discord.Interaction):
        self._setup_components()
        embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(embed=embed, view=self, attachments=attachments)

    def _cleanup_dropdown(self):
        self.pulled_cards = None
        self.selected_card_data = None
        if self.dropdown:
            self.remove_item(self.dropdown)
            self.dropdown = None

    async def _handle_back(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        home_view = UserHomeView(self.user_id)
        embed = await home_view.build_embed(interaction)
        await interaction.edit_original_response(content=None, embed=embed, view=home_view, attachments=[])

    async def _handle_scout(self, interaction: discord.Interaction, count: int):
        cost = count * COST_PER_PULL
        inventory = await get_inventory(interaction.user.id)
        self.selected_card_data = None

        if inventory.scout_coins < cost:
            await lock_view_ui(self, interaction)
            self.state = "failed"  # Switch to failure state
            self.failed_cost = cost
            self.failed_balance = inventory.scout_coins
            await self.update_screen(interaction)
            return

        self.state = "scout"

        await lock_view_ui(self, interaction)
        pulled_cards = await perform_scout(interaction.user.id, count)

        if not pulled_cards:
            await interaction.followup.send(
                "❌ An error occurred while processing your scout. Please try again.",
                ephemeral=True
            )
            return

        # Update view state
        self.balance = inventory.scout_coins - cost
        self._cleanup_dropdown()

        if count == 1:
            # x1 pull: Show the card directly without any dropdown/summary
            self.pulled_cards = None
            self.selected_card_data = pulled_cards[0]
        else:
            # x10 pull: Show the summary list and dropdown
            self.pulled_cards = pulled_cards
            self.selected_card_data = None

        await self.update_screen(interaction)

    @staticmethod
    def _attach_scout_status_field(embed: discord.Embed, card_data: dict):
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
            embed.add_field(
                name="Status",
                value=f"{VOUCHER_EMOJI} Max Resonance (+{count} {VOUCHER_NAME})",
                inline=False,
            )

    async def _get_screen_payload(self) -> tuple[discord.Embed, list[discord.File]]:
        embed = await self.build_embed()

        if self.state == "failed":
            banner_file = get_banner_file("scout_fail")
            if banner_file:
                embed.set_image(url=f"attachment://{banner_file.filename}")
            attachments = [banner_file] if banner_file else []
        elif self.selected_card_data:
            image_file = get_card_image_file(self.selected_card_data)
            attachments = [image_file] if image_file else []
        elif self.pulled_cards:
            attachments = []
        else:
            banner_file = get_banner_file("scout")
            if banner_file:
                embed.set_image(url=f"attachment://{banner_file.filename}")
            attachments = [banner_file] if banner_file else []

        return embed, attachments