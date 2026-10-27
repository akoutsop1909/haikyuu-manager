import asyncio
import discord

from ui.utils import lock_view_ui, format_lineup_court_display, create_card_embed, add_card_metadata_fields, \
    LineupSelectMenu, CardSelectMenu, BaseCardRosterView
from engine.data_loader import TEAM_CONFIG, STARTING_SLOTS, ALL_SLOTS
from engine.mechanics_boosts import apply_lineup_boosts
from database import get_lineups, get_user_cards

DEFAULT_LINEUP_NAME = TEAM_CONFIG["default_lineup_name_format"]

class MatchScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], lineups: dict[int, dict] = None,
                 selected_card_id: str | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.selected_lineup_index = 1
        self.lineups = lineups or {}
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards, lineups = await asyncio.gather(
            get_user_cards(user_id),
            get_lineups(user_id)
        )

        view = cls(user_id, user_cards, lineups, selected_card_id)
        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    def get_filtered_cards(self) -> list[dict]:
        team_data = self.lineups.get(self.selected_lineup_index, {})
        card_lookup = {c["id"]: c for c in self.user_cards}
        return [card_lookup[cid] for slot in ALL_SLOTS if (cid := team_data.get(slot)) and cid in card_lookup]

    async def build_content(self) -> str:
        team_data = self.lineups.get(self.selected_lineup_index, {})
        content = format_lineup_court_display(team_data, self.user_cards, self.selected_lineup_index)
        return content

    async def build_embed(self) -> discord.Embed | None:
        filtered_cards = self.get_filtered_cards()
        target_card = self._get_target_card(filtered_cards)

        if not target_card:
            return None

        team_data = self.lineups.get(self.selected_lineup_index, {})

        # 1. Get all fully boosted stats for the lineup
        boosted_stats_map = apply_lineup_boosts(team_data, self.user_cards)

        # 2. Find which slot this target card occupies, and grab its boosted stats
        target_slot = next((slot for slot, cid in team_data.items() if cid == target_card["id"]), None)
        card_stats = boosted_stats_map.get(target_slot, target_card.get("scaled_stats", target_card.get("base_stats", {})))

        card_lookup = {c["id"]: c for c in self.user_cards}
        active_lineup_card_ids = {
            team_data.get(slot) for slot in STARTING_SLOTS
            if team_data.get(slot) in card_lookup
        }

        # 3. Pass the boosted stats into the embed!
        embed = create_card_embed(target_card, extra_stats=card_stats)
        add_card_metadata_fields(embed, target_card, active_lineup_card_ids=active_lineup_card_ids)
        return embed

    def _setup_components(self):
        filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()
        lineup_names_map = {i: data.get("lineup_name", DEFAULT_LINEUP_NAME.format(i)) for i, data in self.lineups.items()}

        # Row 0: Lineup Selector
        self.add_item(LineupSelectMenu(self.selected_lineup_index, lineup_names_map))

        # Row 1: Cards Dropdown (Contains all active lineup members)
        self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info, custom_placeholder="Select lineup player...", row=1))

        # Check if all starting slots in the active lineup are filled
        team_data = self.lineups.get(self.selected_lineup_index, {})
        is_lineup_complete = all(team_data.get(slot) for slot in STARTING_SLOTS)

        # Row 2: Action Buttons
        btn_confirm = discord.ui.Button(label="Confirm Lineup", style=discord.ButtonStyle.success, row=2, disabled=not is_lineup_complete)
        btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)

        btn_confirm.callback = self.confirm_lineup_callback
        btn_back.callback = self._handle_back

        self.add_item(btn_confirm)
        self.add_item(btn_back)

    async def update_screen(self, interaction: discord.Interaction):
        self.lineups = await get_lineups(self.user_id)
        self._setup_components()

        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def confirm_lineup_callback(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        # TODO: Lock in this chosen lineup and transition to Opponent Selection View!
        await interaction.followup.send("Lineup confirmed! Opponent selection screen coming up next.", ephemeral=True)

    async def _get_screen_payload(self) -> tuple[str, discord.Embed | None, list[discord.File]]:
        """Helper to build content, embed, and card image attachments for the match screen."""
        content = await self.build_content()
        embed = await self.build_embed()
        attachments = self._get_target_card_attachments()
        return content, embed, attachments