import asyncio
from datetime import datetime, timezone

from better_profanity import profanity
import discord

from ui.utils import lock_view_ui, format_lineup_court_display, create_card_embed, add_card_metadata_fields, \
    LineupSelectMenu, PositionFilterSelectMenu, CardSelectMenu, BaseCardRosterView
from engine.data_loader import ALL_SLOTS
from database import get_user_cards, get_lineups, clear_lineup, update_lineup_name, add_to_lineup, remove_pinch

class LineupRenameModal(discord.ui.Modal, title="Rename Lineup"):
    lineup_name = discord.ui.TextInput(
        label="New Lineup Name",
        placeholder="Enter lineup name...",
        max_length=16,
        required=True
    )

    def __init__(self, parent_view, lineup_index: int):
        super().__init__()
        self.parent_view = parent_view
        self.lineup_index = lineup_index

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.lineup_name.value

        # Check for profanity
        if profanity.contains_profanity(new_name):
            await interaction.response.send_message(
                "❌ That lineup name contains prohibited words. Please choose a different name.",
                ephemeral=True
            )
            return

        # Write to DB and immediately edit the original message in one atomic step
        await update_lineup_name(interaction.user.id, self.lineup_index, new_name)
        await self.parent_view.update_screen(interaction)


class TeamScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], selected_card_id: str | None = None,
                 lineups: dict[int, dict] = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.selected_lineup_index = 1
        self.lineups = lineups or {}
        self.is_slot_selection_mode = False  # Track whether we are in the slot picker screen
        self.is_clearing_confirmation = False  # Track clear confirmation state
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards, lineups = await asyncio.gather(
            get_user_cards(user_id),
            get_lineups(user_id)
        )

        view = cls(user_id, user_cards, selected_card_id, lineups)

        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    async def build_content(self) -> str:
        team_data = self.lineups.get(self.selected_lineup_index, {})
        result = format_lineup_court_display(team_data, self.user_cards, self.selected_lineup_index)
        return result["content"]

    async def build_embed(self) -> discord.Embed:
        filtered_cards = self.get_filtered_cards()
        target_card = self._get_target_card(filtered_cards)

        scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))
        embed = create_card_embed(target_card, extra_stats=scaled_stats)

        # Team screen checks player trip/exhaustion status locally
        is_on_trip, is_exhausted, exhausted_until = self._check_card_availability(target_card)

        if is_on_trip or is_exhausted:
            status_lines = []
            if is_on_trip:
                status_lines.append("This player is currently away on a Tokyo Trip.")
            if is_exhausted:
                ts = int(exhausted_until.timestamp())
                status_lines.append(f"This player is exhausted until <t:{ts}:R> (<t:{ts}:f>).")

            embed.add_field(
                name="⚠️ Player Unavailable",
                value="\n".join(status_lines),
                inline=False
            )

        # Adds Setter Specialty & School Bonds
        add_card_metadata_fields(embed, target_card)
        return embed

    def _setup_components(self):
        filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()
        lineup_names_map = {i: data.get("lineup_name", f"Lineup {i}") for i, data in self.lineups.items()}

        # Row 0: Lineup Selector
        self.add_item(LineupSelectMenu(self.selected_lineup_index, lineup_names_map))

        # Row 1: Position Filter
        self.add_item(PositionFilterSelectMenu(self.user_cards, self.selected_position, row=1))

        # Row 2: Cards Dropdown
        self.add_item(
            CardSelectMenu(page_cards, self.selected_card_id, page_info, custom_placeholder="Select player...", row=2))

        if not self.is_slot_selection_mode:
            if self.is_clearing_confirmation:
                # Row 3: Confirmation buttons for clearing the lineup
                btn_confirm = discord.ui.Button(label="Yes, Clear Lineup", style=discord.ButtonStyle.danger, emoji="🗑️", row=3)
                btn_cancel_clear = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=3)

                btn_confirm.callback = self._confirm_clear_action
                btn_cancel_clear.callback = self._cancel_clear_action

                self.add_item(btn_confirm)
                self.add_item(btn_cancel_clear)

            else:
                # Check if the current lineup is completely empty
                team_data = self.lineups.get(self.selected_lineup_index, {})
                is_lineup_empty = all(not team_data.get(k) for k in ALL_SLOTS)

                # Row 3: Main Screen Buttons (Edit, Rename, Clear)
                btn_edit = discord.ui.Button(label="Edit", style=discord.ButtonStyle.primary, emoji="📋", row=3)
                btn_rename = discord.ui.Button(label="Rename", style=discord.ButtonStyle.secondary, emoji="✏️", row=3)
                btn_clear = discord.ui.Button(label="Clear", style=discord.ButtonStyle.danger, emoji="🗑️", row=3, disabled=is_lineup_empty)

                btn_edit.callback = self._handle_enter_slot_selection
                btn_rename.callback = self._handle_rename_lineup
                btn_clear.callback = self._handle_clear_lineup

                self.add_item(btn_edit)
                self.add_item(btn_rename)
                self.add_item(btn_clear)

                # Row 4: Navigation (Prev, Next, Back)
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

        else:
            # Slot Selection Sub-Screen Buttons
            target_card = self._get_target_card()
            pos = target_card["position"]

            # Check availability state using the helper method
            is_on_trip, is_exhausted, _ = self._check_card_availability(target_card)
            is_unavailable = is_on_trip or is_exhausted

            # Row 3: Position specific slot buttons
            if pos in ("MB", "WS"):
                btn_slot1 = discord.ui.Button(label=f"Add to {pos}1", style=discord.ButtonStyle.primary, emoji="1️⃣",
                    row=3, disabled=is_unavailable
                )
                btn_slot2 = discord.ui.Button(label=f"Add to {pos}2", style=discord.ButtonStyle.primary, emoji="2️⃣",
                    row=3, disabled=is_unavailable
                )

                prefix = "middle_blocker" if pos == "MB" else "wing_spiker"
                btn_slot1.callback = self._create_slot_callback(f"{prefix}_1")
                btn_slot2.callback = self._create_slot_callback(f"{prefix}_2")

                self.add_item(btn_slot1)
                self.add_item(btn_slot2)

            elif pos in ("L", "OP", "S"):
                pos_map = {"L": "libero", "OP": "opposite", "S": "setter"}
                pos_display = {"L": "Libero (L)", "OP": "Opposite Hitter (OP)", "S": "Setter (S)"}.get(pos, pos)
                slot_name = pos_map.get(pos)

                btn_slot = discord.ui.Button(label=f"Add to {pos_display}", style=discord.ButtonStyle.primary,
                    emoji="📌", row=3, disabled=is_unavailable
                )
                btn_slot.callback = self._create_slot_callback(slot_name)
                self.add_item(btn_slot)

            # Check if a pinch server is assigned in the current lineup team_data
            team_data = self.lineups.get(self.selected_lineup_index, {})
            has_pinch_server = bool(team_data.get("pinch_server"))

            # Check if the selected card is a Libero (Liberos cannot serve)
            is_libero = target_card and target_card["position"] == "L"

            # Row 4: Pinch Server management and Cancel
            btn_pinch = discord.ui.Button(label="Add Pinch", style=discord.ButtonStyle.secondary, row=4,
                disabled=(is_libero or is_unavailable)
            )
            btn_remove_pinch = discord.ui.Button(label="Remove Pinch", style=discord.ButtonStyle.danger, row=4,
                disabled=not has_pinch_server
            )
            btn_remove_pinch.callback = self._handle_remove_pinch
            btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)

            btn_pinch.callback = self._create_slot_callback("pinch_server")
            btn_cancel.callback = self._handle_cancel_slot_selection

            self.add_item(btn_pinch)
            self.add_item(btn_remove_pinch)
            self.add_item(btn_cancel)

    async def update_screen(self, interaction: discord.Interaction):
        self.lineups = await get_lineups(self.user_id)
        self._setup_components()

        content, embed, attachments = await self._get_screen_payload()

        if not interaction.response.is_done():
            await interaction.response.edit_message(content=content, embed=embed, view=self, attachments=attachments)
        else:
            await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_enter_slot_selection(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_slot_selection_mode = True
        await self.update_screen(interaction)

    async def _handle_cancel_slot_selection(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_slot_selection_mode = False
        await self.update_screen(interaction)

    async def _handle_remove_pinch(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await remove_pinch(interaction.user.id, self.selected_lineup_index)
        await self.update_screen(interaction)

    async def _handle_rename_lineup(self, interaction: discord.Interaction):
        modal = LineupRenameModal(self, self.selected_lineup_index)
        await interaction.response.send_modal(modal)

    async def _handle_clear_lineup(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_clearing_confirmation = True
        await self.update_screen(interaction)

    async def _confirm_clear_action(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await clear_lineup(interaction.user.id, self.selected_lineup_index)
        self.is_clearing_confirmation = False
        await self.update_screen(interaction)

    async def _cancel_clear_action(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_clearing_confirmation = False
        await self.update_screen(interaction)

    def _create_slot_callback(self, slot_name: str):
        """Helper factory to generate callbacks for any position/slot button."""
        async def callback(interaction: discord.Interaction):
            await lock_view_ui(self, interaction)
            await add_to_lineup(interaction.user.id, self.selected_lineup_index, slot_name, self.selected_card_id)
            self.is_slot_selection_mode = True
            await self.update_screen(interaction)

        return callback

    @staticmethod
    def _check_card_availability(card: dict | None) -> tuple[bool, bool, datetime | None]:
        """Checks if a card is currently on a trip or exhausted."""
        now = datetime.now(timezone.utc)
        is_on_trip = card["is_on_trip"]
        exhausted_until = card["exhausted_until"]
        is_exhausted = exhausted_until is not None and exhausted_until > now

        return is_on_trip, is_exhausted, exhausted_until

    async def _get_screen_payload(self) -> tuple[str, discord.Embed, list[discord.File]]:
        """Helper to build content, embed, and attachments for the team screen."""
        content = await self.build_content()
        embed = await self.build_embed()
        attachments = self._get_target_card_attachments()

        return content, embed, attachments