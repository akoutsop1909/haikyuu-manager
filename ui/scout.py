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
        self.selected_card_data: dict | None = None  # Tracks if user is inspecting a specific pulled card
        self.dropdown: ScoutSelectMenu | None = None
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int) -> tuple["ScoutScreenView", discord.Embed, list[discord.File]]:
        inventory = await get_inventory(user_id)
        view = cls(user_id, balance=inventory.scout_coins)
        embed, attachments = await view._get_screen_payload()
        return view, embed, attachments

    async def build_embed(self) -> discord.Embed:
        # State 1: Inspecting a specific card from 10x results
        if self.selected_card_data:
            embed = create_card_embed(self.selected_card_data, show_level_info=False)
            self._attach_scout_status_field(embed, self.selected_card_data)
            embed.set_footer(text=f"Balance: {COIN_EMOJI} {format_number(self.balance)}")
            return embed

        # Determine content dynamically for States 2 & 3
        if self.pulled_cards:
            # State 2: 10x Summary View Content
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

            title = "🔍 Scout Results (10x Pull)"
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
                f"• 1x Scout: {COIN_EMOJI} **{COST_PER_PULL:,}**\n"
                f"• 10x Scout: {COIN_EMOJI} **{cost_10x:,}**\n\n"
                f"📊 **Drop Rates:** {rates_str}"
            )
            balance_val = inventory.scout_coins

        # Unified presentation for States 2 & 3
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

        # Row 1: Scout Buttons
        btn_scout_1 = discord.ui.Button(label="Scout 1", style=discord.ButtonStyle.primary, row=1)
        btn_scout_10 = discord.ui.Button(label="Scout 10", style=discord.ButtonStyle.success, row=1)

        btn_scout_1.callback = lambda i: self._handle_scout(i, count=1)
        btn_scout_10.callback = lambda i: self._handle_scout(i, count=10)

        self.add_item(btn_scout_1)
        self.add_item(btn_scout_10)

        # Row 2: Back Button
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
        embed = await UserHomeView.build_embed(interaction)
        await interaction.edit_original_response(content=None, embed=embed, view=UserHomeView(self.user_id), attachments=[])

    async def _handle_scout(self, interaction: discord.Interaction, count: int):
        cost = count * COST_PER_PULL
        inventory = await get_inventory(interaction.user.id)

        if inventory.scout_coins < cost:
            self._cleanup_dropdown()
            embed, attachments = self._build_failed_payload(cost, inventory.scout_coins)
            await interaction.response.send_message(embed=embed, files=attachments, ephemeral=True)
            return

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
        self.pulled_cards = pulled_cards
        self.selected_card_data = pulled_cards[0] if count == 1 else None
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

    @staticmethod
    def _build_failed_payload(cost: int, balance: int) -> tuple[discord.Embed, list[discord.File]]:
        """Helper to build the ephemeral failure message payload cleanly."""
        banner_file = get_banner_file("scout_fail")
        embed = discord.Embed(
            title="❌ Scout Failed",
            description=(
                f"You don't have enough {COIN_NAME}!\n\n"
                f"• Required: {COIN_EMOJI} **{cost:,}**\n"
                f"• Your Balance: {COIN_EMOJI} **{balance:,}**"
            ),
            color=discord.Color.gold(),
        )
        if banner_file:
            embed.set_image(url=f"attachment://{banner_file.filename}")

        return embed, [banner_file] if banner_file else []

    async def _get_screen_payload(self) -> tuple[discord.Embed, list[discord.File]]:
        """Helper to build embed and attachments mirroring trip.py style."""
        embed = await self.build_embed()

        # Determine attachments based on active state
        if self.selected_card_data:
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