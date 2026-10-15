import discord

from ui.gacha import UserHomeView
from ui.utils import create_card_embed, get_card_image_file, get_banner_file, PositionFilterSelectMenu, CardSelectMenu, \
    BaseCardRosterView
from database import get_user_cards, get_lineups, TOKYO_TRIP_CONFIG

# Load Tokyo trip configurations
TOKYO_TRIP_MIN_OWNED = TOKYO_TRIP_CONFIG.get("min_s3_s4_owned", 17)
TOKYO_TRIP_MAX_PLAYERS = TOKYO_TRIP_CONFIG.get("max_players", 5)
ALLOWED_RARITIES = tuple(TOKYO_TRIP_CONFIG.get("allowed_rarities", ["S3", "S4"]))
RARITY_LABEL = "/".join(ALLOWED_RARITIES)

ALL_SLOTS = [
    "setter", "opposite", "wing_spiker_1", "wing_spiker_2",
    "middle_blocker_1", "middle_blocker_2", "libero", "pinch_server"
]

class TripScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], selected_card_id: str | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.is_slot_selection_mode = False  # Track slot selection state
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards = await get_user_cards(user_id)
        lineups = await get_lineups(user_id)

        # Count total owned cards matching allowed rarities
        has_met_requirement, total_owned = cls._check_trip_requirement(user_cards)

        # If they don't meet the minimum count, pass an empty list of cards
        if not has_met_requirement:
            filtered_user_cards = []
        else:
            # Collect all card IDs currently used in any lineup slots across all lineups
            assigned_card_ids = set()

            for lineup_data in lineups.values():
                for key in ALL_SLOTS:
                    cid = lineup_data.get(key)
                    if cid:
                        assigned_card_ids.add(cid)

            # Filter user cards: Must match allowed rarities AND NOT assigned to any lineup
            filtered_user_cards = [
                c for c in user_cards
                if c.get("rarity") in ALLOWED_RARITIES and c.get("id") not in assigned_card_ids
            ]

        view = cls(user_id, filtered_user_cards, selected_card_id)

        content = await view.build_content()
        embed = await view.build_embed()

        filtered_cards = view.get_filtered_cards()
        if not has_met_requirement or not filtered_cards:
            banner_file = get_banner_file("tokyo_trip")
            attachments = [banner_file] if banner_file else []
        else:
            target_card = next((c for c in view.user_cards if c["id"] == view.selected_card_id), None)
            image_file = get_card_image_file(target_card) if target_card else None
            attachments = [image_file] if image_file else []

        return view, content, embed, attachments

    def get_filtered_cards(self) -> list[dict]:
        cards = super().get_filtered_cards()
        # Filter by configured rarities
        return [c for c in cards if c.get("rarity") in ALLOWED_RARITIES]

    async def build_content(self) -> str | None:
        """Helper to generate the text content header for the trip screen."""
        user_cards = await get_user_cards(self.user_id)
        has_met_requirement, _ = self._check_trip_requirement(user_cards)
        filtered_cards = self.get_filtered_cards()

        # Suppress plain text header if locked OR if no eligible cards exist
        if not has_met_requirement or not filtered_cards:
            return None

        return "🚌 **Tokyo Training Camp Trip**"

    async def build_embed(self) -> discord.Embed:
        user_cards = await get_user_cards(self.user_id)
        has_met_requirement, total_owned = self._check_trip_requirement(user_cards)

        # Determine if we need to show a banner-backed status message instead of a card
        if not has_met_requirement:
            title = "🔒 Tokyo Training Camp Locked"
            description = (
                "The powerhouse schools in Tokyo won't invite a small roster for a joint practice. "
                "Scout more players to expand your team and get the invite.\n\n"
                f"*(Progress: {total_owned}/{TOKYO_TRIP_MIN_OWNED} {RARITY_LABEL} players)*"
            )
        else:
            filtered_cards = self.get_filtered_cards()
            if not filtered_cards:
                title = "🚌 Tokyo Training Camp Trip"
                description = (
                    "Every qualified player is already locked into your team lineups! "
                    f"Free up some roster slots or recruit more {RARITY_LABEL} players to fill out your trip squad."
                )
            else:
                # If requirements are met and we have eligible cards, render the card embed normally
                target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), filtered_cards[0])
                scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))
                return create_card_embed(target_card, extra_stats=scaled_stats)

        # Shared fallback embed for both locked and empty states (applies the banner and teal theme)
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.teal()
        )
        embed.set_image(url="attachment://tokyo_trip.jpg")
        return embed

    def _setup_components(self):
        self.clear_items()

        if not self.user_cards:
            # Always ensure the Back button is available even if there are no eligible cards
            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=3)
            btn_back.callback = self._handle_back
            self.add_item(btn_back)
            return

        filtered_cards = self.get_filtered_cards()
        page_cards, max_pages = self.get_paged_cards(filtered_cards)

        if page_cards:
            if not self.selected_card_id or not any(c["id"] == self.selected_card_id for c in filtered_cards):
                self.selected_card_id = page_cards[0]["id"]
        else:
            self.selected_card_id = None

        page_info = f"(Page {self.current_page + 1}/{max_pages})" if max_pages > 1 else ""

        # Row 0: Position Filter
        self.add_item(PositionFilterSelectMenu(self.user_cards, self.selected_position, row=0))

        # Row 1: Cards Dropdown
        self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                     custom_placeholder="Select player for trip...", row=1))

        # Row 2 & 3: Action Buttons (Depending on mode)
        if not self.is_slot_selection_mode:
            if not self.is_slot_selection_mode:
                # Normal Mode: Add, Clear, and Send (Row 2)
                btn_add = discord.ui.Button(label="Add", style=discord.ButtonStyle.primary, emoji="➕", row=2)
                btn_clear = discord.ui.Button(label="Clear", style=discord.ButtonStyle.secondary, emoji="🧹", row=2)
                btn_trip = discord.ui.Button(label="Send", style=discord.ButtonStyle.success, emoji="🚌", row=2)

                btn_add.callback = self._handle_enter_slot_selection
                btn_clear.callback = self._handle_clear_players
                btn_trip.callback = self._handle_trip

                self.add_item(btn_add)
                self.add_item(btn_clear)
                self.add_item(btn_trip)

            # Row 3: Navigation (Prev, Next, Back)
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
                # Slot Selection Mode
                # Row 2: First 3 slots (Slots 1, 2, 3)
                for i in range(1, 4):
                    btn_slot = discord.ui.Button(
                        label=f"Slot {i}",
                        style=discord.ButtonStyle.primary,
                        row=2
                    )
                    btn_slot.callback = self._create_trip_slot_callback(i)
                    self.add_item(btn_slot)

                # Row 3: Remaining slots (e.g., Slots 4, 5) and Cancel button together
                for i in range(4, TOKYO_TRIP_MAX_PLAYERS + 1):
                    btn_slot = discord.ui.Button(
                        label=f"Slot {i}",
                        style=discord.ButtonStyle.primary,
                        row=3
                    )
                    btn_slot.callback = self._create_trip_slot_callback(i)
                    self.add_item(btn_slot)

                btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=3)
                btn_cancel.callback = self._handle_cancel_slot_selection
                self.add_item(btn_cancel)

                # Row 4: Navigation buttons (Prev, Next, Back)
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
        user_cards = await get_user_cards(self.user_id)
        lineups = await get_lineups(self.user_id)

        # Count total owned cards matching allowed rarities
        has_met_requirement, total_owned = self._check_trip_requirement(user_cards)

        if not has_met_requirement:
            self.user_cards[:] = []
        else:
            assigned_card_ids = set()
            for lineup_data in lineups.values():
                for key in ALL_SLOTS:
                    cid = lineup_data.get(key)
                    if cid:
                        assigned_card_ids.add(cid)

            self.user_cards[:] = [
                c for c in user_cards
                if c.get("rarity") in ALLOWED_RARITIES and c.get("id") not in assigned_card_ids
            ]

        self._setup_components()

        content = await self.build_content()
        embed = await self.build_embed()

        filtered_cards = self.get_filtered_cards()
        if not has_met_requirement or not filtered_cards:
            banner_file = get_banner_file("tokyo_trip")
            attachments = [banner_file] if banner_file else []
        else:
            target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), None)
            image_file = get_card_image_file(target_card) if target_card else None
            attachments = [image_file] if image_file else []

        await interaction.response.edit_message(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_enter_slot_selection(self, interaction: discord.Interaction):
        self.is_slot_selection_mode = True
        self._setup_components()

        content = await self.build_content()
        embed = await self.build_embed()
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    def _create_trip_slot_callback(self, slot_index: int):
        """Helper factory to generate callbacks for the trip squad slots."""
        async def callback(interaction: discord.Interaction):
            # TODO: Add your backend database assignment logic for trip slot `slot_index` here
            await interaction.response.send_message(
                f"➕ Player assigned to Trip Slot {slot_index}!",
                ephemeral=True
            )

            # Exit slot selection mode and refresh
            self.is_slot_selection_mode = False
            self._setup_components()

            content = await self.build_content()
            embed = await self.build_embed()

            filtered_cards = self.get_filtered_cards()
            target_card = next((c for c in filtered_cards if c["id"] == self.selected_card_id), None)
            image_file = get_card_image_file(target_card) if target_card else None
            attachments = [image_file] if image_file else []

            await interaction.response.edit_message(content=content, embed=embed, view=self, attachments=attachments)

        return callback

    async def _handle_cancel_slot_selection(self, interaction: discord.Interaction):
        self.is_slot_selection_mode = False
        self._setup_components()

        content = await self.build_content()
        embed = await self.build_embed()
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    async def _handle_clear_players(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "🧹 Cleared all players from the current trip squad.",
            ephemeral=True
        )
        await self.update_screen(interaction)

    async def _handle_trip(self, interaction: discord.Interaction):
        if not self.selected_card_id:
            return

        await interaction.response.send_message(
            "🚌 Your players have been sent on a Tokyo Training Camp trip!",
            ephemeral=True
        )
        await self.update_screen(interaction)

    @staticmethod
    def _check_trip_requirement(user_cards: list[dict]) -> tuple[bool, int]:
        """Helper to check if user meets the minimum ownership requirement for Tokyo Trip."""
        total_owned = sum(1 for c in user_cards if c.get("rarity") in ALLOWED_RARITIES)
        return total_owned >= TOKYO_TRIP_MIN_OWNED, total_owned