import discord

from ui.gacha import UserHomeView
from ui.utils import create_card_embed, get_card_image_file, format_number, PositionFilterSelectMenu, CardSelectMenu, BaseCardRosterView
from database import get_inventory, get_user_cards, get_level_cost, train_card, craft_drink, increase_resonance, TRAINING_CONFIG

# Load training configurations
MAX_LVL = TRAINING_CONFIG.get("max_level", 100)
MAX_RES = TRAINING_CONFIG.get("max_resonance", 5)
CRAFT_VOUCHER_COST = TRAINING_CONFIG.get("drink_craft_cost", 20)
COSTS = TRAINING_CONFIG.get("resonance_drink_cost_by_rarity", {"S3": 1, "S4": 3, "S5": 5})

class TrainScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], selected_card_id: str | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards = await get_user_cards(user_id)
        view = cls(user_id, user_cards, selected_card_id)

        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    async def build_embed(self) -> discord.Embed:
        inventory = await get_inventory(self.user_id)
        filtered_cards = self.get_filtered_cards()

        target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), filtered_cards[0])
        current_lvl = target_card["level"]
        current_res = target_card.get("resonance", 0)
        rarity = target_card.get("rarity", "S3")

        scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))

        embed = create_card_embed(
            target_card,
            extra_stats=scaled_stats,
        )

        # 1. Level Upgrade Section
        if current_lvl < MAX_LVL:
            cost_next = get_level_cost(current_lvl, 1, rarity)
            cost_5 = get_level_cost(current_lvl, 5, rarity)
            cost_10 = get_level_cost(current_lvl, 10, rarity)
            cost_max = get_level_cost(current_lvl, MAX_LVL - current_lvl, rarity)

            cost_text = (
                f"• +1 Level: 🏐 **{format_number(cost_next)}**\n"
                f"• +5 Levels: 🏐 **{format_number(cost_5)}**\n"
                f"• +10 Levels: 🏐 **{format_number(cost_10)}**\n"
                f"• To MAX (Lv.{MAX_LVL}): 🏐 **{format_number(cost_max)}**"
            )
            embed.add_field(name="📈 Upgrade Costs", value=cost_text, inline=False)
        else:
            embed.add_field(name="📈 Max Level Reached", value="This player is already at maximum level!", inline=False)

        # 2. Resonance & Crafting Info Section
        res_drink_cost = COSTS.get(rarity, 1)
        if current_res < MAX_RES:
            res_text = (
                f"• +1 Resonance: 🥤 **{res_drink_cost}**\n"
                f"• Craft **1** 🥤 Sports Drink: 🎟️ **{CRAFT_VOUCHER_COST}**"
            )
        else:
            res_text = (
                f"• Max Resonance Reached! (★{MAX_RES})\n"
                f"• Craft **1** 🥤 Sports Drink: 🎟️ **{CRAFT_VOUCHER_COST}**"
            )

        embed.add_field(name="🌟 Resonance & Crafting", value=res_text, inline=False)

        embed.set_footer(
            text=
            f"Balance: 🏐 {format_number(inventory.practice_balls)}  •  "
            f"🥤 {format_number(inventory.sports_drinks)}  •  "
            f"🎟️ {format_number(inventory.drink_vouchers)}"
        )

        return embed

    def _setup_components(self):
        self.clear_items()
        if not self.user_cards:
            return

        filtered_cards = self.get_filtered_cards()
        page_cards, max_pages = self.get_paged_cards(filtered_cards)

        if page_cards:
            if not self.selected_card_id or not any(c["id"] == self.selected_card_id for c in filtered_cards):
                self.selected_card_id = page_cards[0]["id"]
        else:
            self.selected_card_id = None

        page_info = f"(Page {self.current_page + 1}/{max_pages})" if max_pages > 1 else ""

        # Fetch selected card data for button states
        target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), None) if self.selected_card_id else None

        is_max_level = target_card and target_card.get("level", 1) >= MAX_LVL
        is_max_resonance = target_card and target_card.get("resonance", 0) >= MAX_RES

        # Row 0: Position Filter
        self.add_item(PositionFilterSelectMenu(self.user_cards, self.selected_position, row=0))

        # Row 1: Cards Dropdown
        self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                     custom_placeholder="Select a player to train...", row=1))

        # Row 2: Level Actions
        btn_1 = discord.ui.Button(label="+1 Lv", style=discord.ButtonStyle.primary, row=2)
        btn_5 = discord.ui.Button(label="+5 Lv", style=discord.ButtonStyle.primary, row=2)
        btn_10 = discord.ui.Button(label="+10 Lv", style=discord.ButtonStyle.primary, row=2)
        btn_max = discord.ui.Button(label="Train MAX", style=discord.ButtonStyle.success, row=2)

        has_card = self.selected_card_id is not None
        disable_train = (not has_card) or is_max_level

        btn_1.disabled = disable_train
        btn_5.disabled = disable_train
        btn_10.disabled = disable_train
        btn_max.disabled = disable_train

        btn_1.callback = lambda i: self._handle_train(i, levels=1)
        btn_5.callback = lambda i: self._handle_train(i, levels=5)
        btn_10.callback = lambda i: self._handle_train(i, levels=10)
        btn_max.callback = lambda i: self._handle_train(i, max_mode=True)

        self.add_item(btn_1)
        self.add_item(btn_5)
        self.add_item(btn_10)
        self.add_item(btn_max)

        # Row 3: Resonance & Exchange Actions
        btn_res = discord.ui.Button(label="+1 Resonance", style=discord.ButtonStyle.primary, row=3)
        btn_exchange = discord.ui.Button(label="Craft Sports Drink", style=discord.ButtonStyle.secondary, emoji="🥤", row=3)

        btn_res.disabled = (not has_card) or is_max_resonance
        btn_res.callback = self._handle_resonance
        btn_exchange.callback = self._handle_craft

        self.add_item(btn_res)
        self.add_item(btn_exchange)

        # Row 4: Navigation
        btn_prev = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, emoji="◀️", row=4,
                                     disabled=(self.current_page == 0))
        btn_next = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️", row=4,
                                     disabled=(self.current_page >= max_pages - 1))
        btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=4)

        btn_prev.callback = self._handle_prev_page
        btn_next.callback = self._handle_next_page
        btn_back.callback = self._handle_back

        self.add_item(btn_prev)
        self.add_item(btn_next)
        self.add_item(btn_back)

    async def update_screen(self, interaction: discord.Interaction):
        self.user_cards[:] = await get_user_cards(self.user_id)
        self._setup_components()

        content, embed, attachments = await self._get_screen_payload()
        await interaction.response.edit_message(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_resonance(self, interaction: discord.Interaction):
        if not self.selected_card_id:
            return

        filtered_cards = self.get_filtered_cards()
        target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), None)
        rarity = target_card.get("rarity", "S3") if target_card else "S3"
        res_drink_cost = COSTS.get(rarity, 1)

        success = await increase_resonance(self.user_id, self.selected_card_id)
        if not success:
            await interaction.response.send_message(
                f"❌ You need at least 🥤 **{res_drink_cost}** Sports Drinks to increase Resonance for this player!",
                ephemeral=True
            )
            return

        await self.update_screen(interaction)

    async def _handle_train(self, interaction: discord.Interaction, levels: int = 1, max_mode: bool = False):
        if not self.selected_card_id:
            return

        success = await train_card(self.user_id, self.selected_card_id, levels, max_mode)
        if not success:
            await interaction.response.send_message(
                "❌ You don't have enough 🏐 **Practice Balls** to train this player!",
                ephemeral=True
            )
            return

        await self.update_screen(interaction)

    async def _handle_craft(self, interaction: discord.Interaction):
        success = await craft_drink(self.user_id)
        if not success:
            await interaction.response.send_message(
                f"❌ You need at least 🎟️ **{CRAFT_VOUCHER_COST}** Drink Vouchers to craft a Sports Drink!",
                ephemeral=True
            )
            return

        await self.update_screen(interaction)

    async def _get_screen_payload(self) -> tuple[str, discord.Embed, list[discord.File]]:
        """Helper to build content, embed, and attachments for the training screen."""
        content = "🏋️ **Player Training**"
        embed = await self.build_embed()

        filtered_cards = self.get_filtered_cards()
        target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), None)
        image_file = get_card_image_file(target_card) if target_card else None
        attachments = [image_file] if image_file else []

        return content, embed, attachments