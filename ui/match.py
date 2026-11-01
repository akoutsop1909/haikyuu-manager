import asyncio
import discord

from ui.utils import lock_view_ui, format_lineup_court_display, create_card_embed, add_card_metadata_fields, \
    LineupSelectMenu, CardSelectMenu, BaseCardRosterView
from engine.data_loader import TEAM_CONFIG, STARTING_SLOTS, ALL_SLOTS
from engine.opponent_generator import generate_opponent_team
from engine.mechanics_boosts import apply_lineup_boosts
from database import get_lineups, get_user_cards

DEFAULT_LINEUP_NAME = TEAM_CONFIG["default_lineup_name_format"]


class DifficultySelectMenu(discord.ui.Select):
    def __init__(self, current_difficulty: str):
        difficulties = [
            ("Casual", "🌱", "Relaxed match for beginners"),
            ("Easy", "👟", "Light challenge with basic rewards"),
            ("Normal", "⚡", "Standard match difficulty"),
            ("Hard", "💥", "Intense match with skilled opponents"),
            ("Nightmare", "💀", "Extreme challenge for elite teams")
        ]

        options = []
        for name, emoji, desc in difficulties:
            options.append(
                discord.SelectOption(
                    label=name,
                    emoji=emoji,
                    description=desc,
                    default=(name == current_difficulty)
                )
            )

        super().__init__(
            placeholder="Select match difficulty...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        await lock_view_ui(self.view, interaction)
        self.view.selected_difficulty = self.values[0]
        await self.view.update_screen(interaction)


class MatchScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], lineups: dict[int, dict] = None,
                 selected_card_id: str | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.selected_lineup_index = 1
        self.lineups = lineups or {}
        self.state = "opponent_select"
        self.selected_difficulty = "Normal"
        self.current_opponent = generate_opponent_team(self.selected_difficulty)
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

    async def build_content(self) -> str | None:
        if self.state == "opponent_select":
            return None  # No court display text needed on the opponent screen

        team_data = self.lineups.get(self.selected_lineup_index, {})
        return format_lineup_court_display(team_data, self.user_cards, self.selected_lineup_index)

    async def build_embed(self) -> discord.Embed:
        if self.state == "opponent_select":
            difficulty_emojis = {
                "Casual": "🌱", "Easy": "👟", "Normal": "⚡", "Hard": "💥", "Nightmare": "💀"
            }
            diff_emoji = difficulty_emojis.get(self.selected_difficulty, "⚡")

            embed = discord.Embed(
                title="🏐 Match Arena - Opponent Scouting",
                description=(
                    f"• **Difficulty:** {diff_emoji} **{self.selected_difficulty}**\n"
                    "Review the scouted opponent roster below. Click **Play Match** to configure your lineup and challenge them!"
                ),
                color=discord.Color.blue(),
            )

            # Build clean player lines from the generated roster
            roster = self.current_opponent.get("roster", {})
            slot_labels = {
                "setter": "Setter (S)",
                "opposite": "Opposite (OP)",
                "wing_spiker_1": "Wing Spiker (WS)",
                "wing_spiker_2": "Wing Spiker (WS)",
                "middle_blocker_1": "Middle Blocker (MB)",
                "middle_blocker_2": "Middle Blocker (MB)",
                "libero": "Libero (L)",
                "pinch_server": "Pinch Server (PS)"
            }

            player_lines = []
            for slot, label in slot_labels.items():
                p_data = roster.get(slot)
                if p_data:
                    player_lines.append(f"• **{label}:** {p_data['name']} *({p_data['rarity']} | Lv.{p_data['level']} | {p_data['school']})*")

            if player_lines:
                embed.add_field(
                    name="👥 Opponent Roster",
                    value="\n".join(player_lines),
                    inline=False
                )

            return embed

        # State 2: Your existing lineup embed logic
        filtered_cards = self.get_filtered_cards()
        target_card = self._get_target_card(filtered_cards)

        if not target_card:
            return discord.Embed(title="Lineup Empty", description="Please select cards for your lineup.",
                                 color=discord.Color.orange())

        team_data = self.lineups.get(self.selected_lineup_index, {})
        boosted_stats_map = apply_lineup_boosts(team_data, self.user_cards)
        target_slot = next((slot for slot, cid in team_data.items() if cid == target_card["id"]), None)
        card_stats = boosted_stats_map.get(target_slot,
                                           target_card.get("scaled_stats", target_card.get("base_stats", {})))

        card_lookup = {c["id"]: c for c in self.user_cards}
        active_lineup_card_ids = {
            team_data.get(slot) for slot in STARTING_SLOTS
            if team_data.get(slot) in card_lookup
        }

        embed = create_card_embed(target_card, extra_stats=card_stats)
        add_card_metadata_fields(embed, target_card, active_lineup_card_ids=active_lineup_card_ids)
        return embed

    def _setup_components(self):
        self.clear_items()  # Clear old items when switching states

        if self.state == "opponent_select":
            # Row 0: Difficulty Dropdown Menu
            self.add_item(DifficultySelectMenu(self.selected_difficulty))

            # Row 1: Play button to transition to lineup selection
            btn_play = discord.ui.Button(label="Play Match", style=discord.ButtonStyle.success, emoji="🏐", row=1)
            btn_play.callback = self._handle_play_click
            self.add_item(btn_play)

            # Row 2: Back to home/menu button
            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
            btn_back.callback = self._handle_back  # Your existing home back handler
            self.add_item(btn_back)

        elif self.state == "lineup_select":
            filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()
            lineup_names_map = {i: data.get("lineup_name", DEFAULT_LINEUP_NAME.format(i)) for i, data in
                                self.lineups.items()}

            # Row 0: Lineup Selector
            self.add_item(LineupSelectMenu(self.selected_lineup_index, lineup_names_map))

            # Row 1: Cards Dropdown
            self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                         custom_placeholder="Select lineup player...", row=1))

            team_data = self.lineups.get(self.selected_lineup_index, {})
            is_lineup_complete = all(team_data.get(slot) for slot in STARTING_SLOTS)

            # Row 2: Action Buttons
            btn_confirm = discord.ui.Button(label="Confirm Lineup", style=discord.ButtonStyle.success, row=2,
                                            disabled=not is_lineup_complete)
            btn_back_match = discord.ui.Button(label="Back to Match Menu", style=discord.ButtonStyle.secondary,
                                               emoji="⬅️", row=2)

            btn_confirm.callback = self.confirm_lineup_callback
            btn_back_match.callback = self._handle_back_to_opponent

            self.add_item(btn_confirm)
            self.add_item(btn_back_match)

    async def update_screen(self, interaction: discord.Interaction):
        self.lineups = await get_lineups(self.user_id)
        self.current_opponent = generate_opponent_team(self.selected_difficulty)
        self._setup_components()

        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_back_to_opponent(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.state = "opponent_select"  # Switch back to opponent menu
        self.selected_card_id = None
        await self.update_screen(interaction)

    async def _handle_play_click(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.state = "lineup_select"  # Switch state to lineup selection
        await self.update_screen(interaction)

    async def confirm_lineup_callback(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        # You can now access `self.selected_difficulty` here when starting the actual simulation match!
        await interaction.followup.send(f"Lineup confirmed for **{self.selected_difficulty}** difficulty match!",
                                        ephemeral=True)

    async def _get_screen_payload(self) -> tuple[str | None, discord.Embed, list[discord.File]]:
        content = await self.build_content()
        embed = await self.build_embed()

        if self.state == "opponent_select":
            attachments = []  # You can add a match banner file here if you want!
        else:
            attachments = self._get_target_card_attachments()

        return content, embed, attachments