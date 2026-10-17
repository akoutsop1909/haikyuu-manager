import discord

from ui.utils import create_card_embed, get_card_image_file, get_banner_file, PositionFilterSelectMenu, CardSelectMenu, \
    BaseCardRosterView
from data_loader import TOKYO_TRIP_CONFIG
from database import get_user_cards, get_lineups, start_tokyo_trip, claim_tokyo_trip

# Load Tokyo trip configurations
TOKYO_TRIP_MIN_OWNED = TOKYO_TRIP_CONFIG.get("min_s3_s4_owned", 17)
TOKYO_TRIP_MAX_PLAYERS = TOKYO_TRIP_CONFIG.get("max_players", 5)
ALLOWED_RARITIES = tuple(TOKYO_TRIP_CONFIG.get("allowed_rarities", ["S3", "S4"]))
RARITY_LABEL = "/".join(ALLOWED_RARITIES)

STARTING_SLOTS = [
    "setter", "opposite", "wing_spiker_1", "wing_spiker_2",
    "middle_blocker_1", "middle_blocker_2", "libero"
]

ALL_SLOTS = [
    "setter", "opposite", "wing_spiker_1", "wing_spiker_2",
    "middle_blocker_1", "middle_blocker_2", "libero", "pinch_server"
]


class TripScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], all_user_cards: list[dict] | None = None,
                 selected_card_id: str | None = None, is_active_trip: bool = False,
                 has_full_lineup: bool = True, has_met_requirement: bool = True):
        super().__init__(user_id, user_cards, selected_card_id)
        self.all_user_cards = all_user_cards or user_cards
        self.is_active_trip = is_active_trip
        self.has_full_lineup = has_full_lineup
        self.has_met_requirement = has_met_requirement
        self.is_slot_selection_mode = False # Track whether we are in the slot picker screen
        self.trip_slots: dict[int, str] = {}  # {slot_index: card_id}
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards, all_cards, is_active, full_lineup, met_req = await cls._fetch_trip_data(user_id)
        view = cls(
            user_id, user_cards,
            all_user_cards=all_cards,
            selected_card_id=selected_card_id,
            is_active_trip=is_active,
            has_full_lineup=full_lineup,
            has_met_requirement=met_req
        )
        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    def get_filtered_cards(self) -> list[dict]:
        cards = super().get_filtered_cards()
        return [c for c in cards if c.get("rarity") in ALLOWED_RARITIES]

    async def build_content(self) -> str | None:
        filtered_cards = self.get_filtered_cards()

        # Suppress text content for active trips or empty/locked rosters
        if self.is_active_trip or not filtered_cards:
            return None

        slot_lines = []
        for i in range(1, TOKYO_TRIP_MAX_PLAYERS + 1):
            card_id = self.trip_slots.get(i)
            if card_id:
                card = next((c for c in self.all_user_cards if c.get("id") == card_id), None)
                card_name = card["name"]
                slot_lines.append(f"Slot {i}: {card_name}")
            else:
                slot_lines.append(f"Slot {i}: *Empty*")

        return "🚌 **Tokyo Training Camp Trip Squad**\n" + "\n".join(slot_lines)

    async def build_embed(self) -> discord.Embed:
        # State 1: Active Trip
        if self.is_active_trip:
            player_lines = [
                f"• {c["name"]} ({c["rarity"]})"
                for c in self.user_cards
            ]
            players_list_str = "\n".join(player_lines)
            title = "🚌 Tokyo Training Camp Trip - Active Squad"
            description = f"Your squad is currently training hard in Tokyo!\n\n**Active Members:**\n{players_list_str}"

        # State 2: Locked (Requirement not met)
        elif not self.has_met_requirement:
            _, total_owned = self._check_unlock_requirement(self.all_user_cards)
            title = "🔒 Tokyo Training Camp Locked"
            description = (
                "The powerhouse schools in Tokyo won't invite a small roster for a joint practice. "
                "Scout more players to expand your team and get the invite.\n\n"
                f"*(Progress: {total_owned}/{TOKYO_TRIP_MIN_OWNED} {RARITY_LABEL} players)*"
            )

        # State 3: Missing a complete lineup
        elif not self.has_full_lineup:
            title = "⚠️ Incomplete Starting Lineup"
            description = (
                "You can't leave the club short-handed! You need at least one complete lineup "
                "with all 7 starting positions filled before sending anyone away on a trip."
            )

        # State 4: No available filtered cards left
        elif not self.get_filtered_cards():
            title = "⚠️ No Players Available for the Trip"
            description = (
                "Every qualified player is either locked into your team lineups! "
                f"Free up roster slots or recruit more {RARITY_LABEL} players to fill out your trip squad."
            )

        else:
            # State 5: Default card preview (Normal Selection)
            filtered_cards = self.get_filtered_cards()
            target_card = self._get_target_card(filtered_cards)
            scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))
            return create_card_embed(target_card, extra_stats=scaled_stats)

        # Shared setup for States 1 through 4
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.teal()
        )
        embed.set_image(url="attachment://tokyo_trip.jpg")
        return embed

    def _setup_components(self):
        self.clear_items()

        if self.is_active_trip:
            # Active Trip View Components: Claim Rewards & Back
            btn_claim = discord.ui.Button(label="Claim Rewards", style=discord.ButtonStyle.success, emoji="🎁", row=0)
            btn_claim.callback = self._handle_claim_rewards
            self.add_item(btn_claim)

            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
            btn_back.callback = self._handle_back
            self.add_item(btn_back)
            return

        if not self.user_cards:
            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=3)
            btn_back.callback = self._handle_back
            self.add_item(btn_back)
            return

        filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()

        # Row 0: Position Filter
        self.add_item(PositionFilterSelectMenu(self.user_cards, self.selected_position, row=0))

        # Row 1: Cards Dropdown
        self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                     custom_placeholder="Select player for trip...", row=1))

        if not self.is_slot_selection_mode:
            btn_add = discord.ui.Button(label="Add", style=discord.ButtonStyle.primary, emoji="➕", row=2)
            btn_clear = discord.ui.Button(
                label="Clear", style=discord.ButtonStyle.secondary, emoji="🧹", row=2, disabled=not self.trip_slots
            )
            btn_trip = discord.ui.Button(
                label="Send", style=discord.ButtonStyle.success, emoji="🚌", row=2, disabled=not self.trip_slots
            )

            btn_add.callback = self._handle_enter_slot_selection
            btn_clear.callback = self._handle_clear_players
            btn_trip.callback = self._handle_trip

            self.add_item(btn_add)
            self.add_item(btn_clear)
            self.add_item(btn_trip)

            btn_prev = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, emoji="◀️", row=3,
                                         disabled=(self.current_page == 0))
            btn_next = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️", row=3,
                                         disabled=(self.current_page >= max_pages - 1))
            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=3)

            btn_prev.callback = self._handle_prev_page
            btn_next.callback = self._handle_next_page
            btn_back.callback = self._handle_back

            self.add_item(btn_prev)
            self.add_item(btn_next)
            self.add_item(btn_back)

        else:
            for i in range(1, 4):
                btn_slot = discord.ui.Button(label=f"Slot {i}", style=discord.ButtonStyle.primary, row=2)
                btn_slot.callback = self._create_trip_slot_callback(i)
                self.add_item(btn_slot)

            for i in range(4, TOKYO_TRIP_MAX_PLAYERS + 1):
                btn_slot = discord.ui.Button(label=f"Slot {i}", style=discord.ButtonStyle.primary, row=3)
                btn_slot.callback = self._create_trip_slot_callback(i)
                self.add_item(btn_slot)

            btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=3)
            btn_cancel.callback = self._handle_cancel_slot_selection
            self.add_item(btn_cancel)

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
        user_cards, all_cards, is_active, full_lineup, met_req = await self._fetch_trip_data(self.user_id)
        self.user_cards = user_cards
        self.all_user_cards = all_cards
        self.is_active_trip = is_active
        self.has_full_lineup = full_lineup
        self.has_met_requirement = met_req

        self._setup_components()
        content, embed, attachments = await self._get_screen_payload()
        await interaction.response.edit_message(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_claim_rewards(self, interaction: discord.Interaction):
        await claim_tokyo_trip(self.user_id)
        view, content, embed, attachments = await TripScreenView.create(self.user_id)
        await interaction.response.edit_message(content=content, embed=embed, view=view, attachments=attachments)

    async def _handle_enter_slot_selection(self, interaction: discord.Interaction):
        self.is_slot_selection_mode = True
        await self.update_screen(interaction)

    def _create_trip_slot_callback(self, slot_index: int):
        async def callback(interaction: discord.Interaction):
            self.trip_slots[slot_index] = self.selected_card_id
            self.is_slot_selection_mode = True
            await self.update_screen(interaction)

        return callback

    async def _handle_cancel_slot_selection(self, interaction: discord.Interaction):
        self.is_slot_selection_mode = False
        await self.update_screen(interaction)

    async def _handle_clear_players(self, interaction: discord.Interaction):
        self.trip_slots.clear()
        await self.update_screen(interaction)

    async def _handle_trip(self, interaction: discord.Interaction):
        card_ids = list(self.trip_slots.values())
        await start_tokyo_trip(self.user_id, card_ids)
        self.trip_slots.clear()
        await self.update_screen(interaction)

    @staticmethod
    def _check_unlock_requirement(user_cards: list[dict]) -> tuple[bool, int]:
        total_owned = sum(1 for c in user_cards if c["rarity"] in ALLOWED_RARITIES)
        return total_owned >= TOKYO_TRIP_MIN_OWNED, total_owned

    @staticmethod
    async def _fetch_trip_data(user_id: int):
        """Shared helper to load and filter user cards for Tokyo Trip states."""
        user_cards = await get_user_cards(user_id)
        trip_cards = [c for c in user_cards if c.get("is_on_trip", False)]
        is_active_trip = len(trip_cards) > 0

        if is_active_trip:
            return trip_cards, user_cards, True, True, True

        has_met_requirement, _ = TripScreenView._check_unlock_requirement(user_cards)
        has_full_lineup = True
        lineups = {}

        if has_met_requirement:
            lineups = await get_lineups(user_id)
            has_full_lineup = any(
                all(lineup_data.get(slot) for slot in STARTING_SLOTS)
                for lineup_data in lineups.values()
            )

        if not has_met_requirement or not has_full_lineup:
            filtered_user_cards = []
        else:
            assigned_card_ids = {
                lineup_data[key]
                for lineup_data in lineups.values()
                for key in ALL_SLOTS
                if lineup_data.get(key)
            }

            filtered_user_cards = [
                c for c in user_cards
                if c["rarity"] in ALLOWED_RARITIES
                   and c["id"] not in assigned_card_ids
                   and not c["is_on_trip"]
            ]

        return filtered_user_cards, user_cards, False, has_full_lineup, has_met_requirement

    async def _get_screen_payload(self) -> tuple[str | None, discord.Embed, list[discord.File]]:
        content = await self.build_content()
        embed = await self.build_embed()

        filtered_cards = self.get_filtered_cards()

        # Determine whether to show the banner or the selected card image
        if self.is_active_trip or not filtered_cards:
            banner_file = get_banner_file("tokyo_trip")
            attachments = [banner_file] if banner_file else []
        else:
            target_card = self._get_target_card(filtered_cards)
            image_file = get_card_image_file(target_card) if target_card else None
            attachments = [image_file] if image_file else []

        return content, embed, attachments