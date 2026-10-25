import asyncio
import discord

from ui.utils import lock_view_ui, create_card_embed, format_number, PositionFilterSelectMenu, CardSelectMenu, BaseCardRosterView
from engine.game_logic import get_level_cost
from engine.data_loader import TRAINING_CONFIG, ITEM_METADATA
from database import get_inventory, get_user_cards, train_card, redeem_drink, increase_resonance

# Load training configurations & item metadata shortcuts
MAX_LVL = TRAINING_CONFIG["max_level"]
MAX_RES = TRAINING_CONFIG["max_resonance"]
CRAFT_VOUCHER_COST = TRAINING_CONFIG["drink_craft_cost"]
COSTS = TRAINING_CONFIG["resonance_drink_cost_by_rarity"]

BALL_NAME = ITEM_METADATA["balls"]["name"]
BALL_EMOJI = ITEM_METADATA["balls"]["emoji"]
DRINK_NAME = ITEM_METADATA["drinks"]["name"]
DRINK_EMOJI = ITEM_METADATA["drinks"]["emoji"]
VOUCHER_NAME = ITEM_METADATA["vouchers"]["name"]
VOUCHER_EMOJI = ITEM_METADATA["vouchers"]["emoji"]

class TrainScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], inventory, selected_card_id: str | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.inventory = inventory
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards, inventory = await asyncio.gather(
            get_user_cards(user_id),
            get_inventory(user_id)
        )
        view = cls(user_id, user_cards, inventory, selected_card_id)

        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    async def build_embed(self) -> discord.Embed:
        target_card = self._get_target_card()

        current_lvl = target_card["level"]
        current_res = target_card["resonance"]
        rarity = target_card["rarity"]

        scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))

        embed = create_card_embed(target_card, extra_stats=scaled_stats)

        # 1. Level Upgrade Section
        if current_lvl < MAX_LVL:
            cost_next = get_level_cost(current_lvl, 1, rarity)
            cost_5 = get_level_cost(current_lvl, 5, rarity)
            cost_10 = get_level_cost(current_lvl, 10, rarity)
            cost_max = get_level_cost(current_lvl, MAX_LVL - current_lvl, rarity)

            cost_text = (
                f"• +1 Level: {BALL_EMOJI} **{format_number(cost_next)}**\n"
                f"• +5 Levels: {BALL_EMOJI} **{format_number(cost_5)}**\n"
                f"• +10 Levels: {BALL_EMOJI} **{format_number(cost_10)}**\n"
                f"• To MAX (Lv.{MAX_LVL}): {BALL_EMOJI} **{format_number(cost_max)}**"
            )
            embed.add_field(name="📈 Upgrade Costs", value=cost_text, inline=False)
        else:
            embed.add_field(name="📈 Max Level Reached", value="This player is already at maximum level!", inline=False)

        # 2. Resonance & Crafting Info Section
        res_drink_cost = COSTS.get(rarity, 1)

        if current_res < MAX_RES:
            res_line = f"• +1 Resonance: {DRINK_EMOJI} **{res_drink_cost}**"
        else:
            res_line = f"• Max Resonance Reached! (★{MAX_RES})"

        craft_line = f"• Craft **1** {DRINK_EMOJI} {DRINK_NAME}: {VOUCHER_EMOJI} **{CRAFT_VOUCHER_COST}**"
        res_text = f"{res_line}\n{craft_line}"

        embed.add_field(name="🌟 Resonance & Crafting", value=res_text, inline=False)

        embed.set_footer(
            text=
            f"Balance: {BALL_EMOJI} {format_number(self.inventory.practice_balls)}  •  "
            f"{DRINK_EMOJI} {format_number(self.inventory.sports_drinks)}  •  "
            f"{VOUCHER_EMOJI} {format_number(self.inventory.drink_vouchers)}"
        )

        return embed

    def _setup_components(self):
        filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()

        # Fetch selected card data cleanly using the helper
        target_card = self._get_target_card(filtered_cards)

        is_max_level = target_card and target_card["level"] >= MAX_LVL
        is_max_resonance = target_card and target_card["resonance"] >= MAX_RES

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

        disable_train = is_max_level

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
        btn_redeem = discord.ui.Button(label="Redeem Sports Drink", style=discord.ButtonStyle.secondary, emoji="🥤", row=3)

        btn_res.disabled = is_max_resonance
        btn_res.callback = self._handle_resonance
        btn_redeem.callback = self._handle_redeem

        self.add_item(btn_res)
        self.add_item(btn_redeem)

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
        self.user_cards[:], self.inventory = await asyncio.gather(
            get_user_cards(self.user_id),
            get_inventory(self.user_id)
        )

        self._setup_components()
        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_train(self, interaction: discord.Interaction, levels: int = 1, max_mode: bool = False):
        target_card = self._get_target_card()
        current_lvl = target_card["level"]
        rarity = target_card["rarity"]

        cost_one_level = get_level_cost(current_lvl, 1, rarity)

        if self.inventory.practice_balls < cost_one_level:
            await interaction.response.send_message(
                f"❌ You don't have enough {BALL_EMOJI} **{BALL_NAME}** to train this player!",
                ephemeral=True
            )
            return

        await lock_view_ui(self, interaction)
        await train_card(self.user_id, self.selected_card_id, levels, max_mode)
        await self.update_screen(interaction)

    async def _handle_resonance(self, interaction: discord.Interaction):
        target_card = self._get_target_card()
        rarity = target_card["rarity"]
        res_drink_cost = COSTS.get(rarity, 1)

        if self.inventory.sports_drinks < res_drink_cost:
            await interaction.response.send_message(
                f"❌ You need at least {DRINK_EMOJI} **{res_drink_cost}** {DRINK_NAME} to increase Resonance for this player!",
                ephemeral=True
            )
            return

        await lock_view_ui(self, interaction)
        await increase_resonance(self.user_id, self.selected_card_id)
        await self.update_screen(interaction)

    async def _handle_redeem(self, interaction: discord.Interaction):
        if self.inventory.drink_vouchers < CRAFT_VOUCHER_COST:
            await interaction.response.send_message(
                f"❌ You need at least {VOUCHER_EMOJI} **{CRAFT_VOUCHER_COST}** {VOUCHER_NAME} to redeem **1** {DRINK_NAME}!",
                ephemeral=True
            )
            return

        await lock_view_ui(self, interaction)
        await redeem_drink(self.user_id)
        await self.update_screen(interaction)

    async def _get_screen_payload(self) -> tuple[str, discord.Embed, list[discord.File]]:
        """Helper to build content, embed, and attachments for the training screen."""
        content = "🏋️ **Player Training**"
        embed = await self.build_embed()
        attachments = self._get_target_card_attachments()

        return content, embed, attachments