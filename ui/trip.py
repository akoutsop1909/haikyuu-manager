import asyncio
from datetime import datetime, timezone
import discord

from ui.utils import lock_view_ui, create_card_embed, get_card_image_file, get_banner_file, PositionFilterSelectMenu, \
    CardSelectMenu, BaseCardRosterView
from game_logic import calculate_tokyo_trip_rewards
from data_loader import TOKYO_TRIP_CONFIG, STARTING_SLOTS, ALL_SLOTS
from database import get_user_cards, get_lineups, get_tokyo_trip_start, start_tokyo_trip, claim_tokyo_trip

# Load Tokyo trip configurations
TOKYO_TRIP_MIN_OWNED = TOKYO_TRIP_CONFIG["min_s3_s4_owned"]
TOKYO_TRIP_MAX_PLAYERS = TOKYO_TRIP_CONFIG["max_players"]
ALLOWED_RARITIES = tuple(TOKYO_TRIP_CONFIG.get("allowed_rarities", ["S3", "S4"]))
RARITY_LABEL = "/".join(ALLOWED_RARITIES)
REWARDS_CONFIG = TOKYO_TRIP_CONFIG.get("rewards_by_rarity", {})
S3_R = REWARDS_CONFIG.get("S3", {"scout_coins": 30, "practice_balls": 150})
S4_R = REWARDS_CONFIG.get("S4", {"scout_coins": 50, "practice_balls": 200})
INTERVAL_HOURS = TOKYO_TRIP_CONFIG["milestone_interval_hours"]
EXHAUSTION_HOURS = TOKYO_TRIP_CONFIG["exhaustion_hours"]
MAX_DURATION_HOURS = TOKYO_TRIP_CONFIG["max_duration_hours"]
MAX_DURATION_BONUS_VOUCHERS = TOKYO_TRIP_CONFIG["max_duration_bonus_vouchers"]

class TripScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], all_user_cards: list[dict] | None = None,
                 selected_card_id: str | None = None, is_active_trip: bool = False,
                 trip_start: datetime | None = None,
                 has_full_lineup: bool = True, has_met_requirement: bool = True):
        super().__init__(user_id, user_cards, selected_card_id)
        self.all_user_cards = all_user_cards or user_cards
        self.is_active_trip = is_active_trip
        self.trip_start = trip_start
        self.has_full_lineup = has_full_lineup
        self.has_met_requirement = has_met_requirement
        self.is_slot_selection_mode = False  # Track whether we are in the slot picker screen
        self.is_clearing_confirmation = False  # Track early claim confirmation state
        self.trip_slots: dict[int, str] = {}  # {slot_index: card_id}
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        data = await cls._fetch_trip_data(user_id)
        view = cls(
            user_id,
            data["user_cards"],
            all_user_cards=data["all_user_cards"],
            selected_card_id=selected_card_id,
            is_active_trip=data["is_active_trip"],
            trip_start=data.get("trip_start"),
            has_full_lineup=data["has_full_lineup"],
            has_met_requirement=data["has_met_requirement"]
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

        # Map card_id to full card data dictionary for quick lookup
        card_lookup = {c["id"]: c for c in self.all_user_cards}

        slot_lines = []
        selected_cards = []
        for i in range(1, TOKYO_TRIP_MAX_PLAYERS + 1):
            card_id = self.trip_slots.get(i)
            if card_id and card_id in card_lookup:
                card = card_lookup[card_id]
                selected_cards.append(card)
                slot_lines.append(f"Slot {i}: {card['name']} ({card['rarity']})")
            else:
                slot_lines.append(f"Slot {i}: *Empty*")

        squad_str = "🚌 **Tokyo Training Camp Trip Squad**\n" + "\n".join(slot_lines)

        # Calculate yield and milestones dynamically for selected cards (handles empty slots safely)
        dummy_start = datetime.now(timezone.utc)
        rewards = calculate_tokyo_trip_rewards(dummy_start, selected_cards)

        coins_per_milestone = rewards.coins_per_milestone
        balls_per_milestone = rewards.balls_per_milestone
        max_milestones = rewards.max_milestones

        reward_preview = (
            f"\n\n**Trip Rules & Rewards:**\n"
            f"• Rewards per Rarity:\n"
            f"  ▫️ S3: +{S3_R['scout_coins']} 🪙 | +{S3_R['practice_balls']} 🏐\n"
            f"  ▫️ S4: +{S4_R['scout_coins']} 🪙 | +{S4_R['practice_balls']} 🏐\n"
            f"• Rewards (every {INTERVAL_HOURS}h, max {max_milestones}): +{coins_per_milestone:,} 🪙 | +{balls_per_milestone:,} 🏐\n"
            f"• Max Duration Bonus ({MAX_DURATION_HOURS}h): +{MAX_DURATION_BONUS_VOUCHERS} 🎟️\n"
            f"• Exhaustion: {EXHAUSTION_HOURS}h upon claim\n"
            f"*(Note: Lineup and exhausted players are hidden)*"
        )
        return squad_str + reward_preview

    async def build_embed(self) -> discord.Embed:
        # State 1: Active Trip
        if self.is_active_trip:
            rewards = calculate_tokyo_trip_rewards(self.trip_start, self.user_cards)

            player_lines = [
                f"• {c['name']} ({c['rarity']})"
                for c in self.user_cards
            ]
            players_list_str = "\n".join(player_lines) if player_lines else "None"

            next_milestone_val = (
                f"<t:{rewards.next_milestone_ts}:R>"
                if rewards.next_milestone_ts else "Max milestones reached!"
            )

            voucher_val = (
                f"<t:{rewards.max_duration_ts}:R>"
                if rewards.max_duration_ts else "Ready to claim!"
            )

            embed = discord.Embed(
                title="🚌 Tokyo Training Camp - Active Squad",
                description="Your squad is currently training hard in Tokyo!",
                color=discord.Color.teal()
            )
            embed.add_field(
                name=f"Active Members ({len(self.user_cards)}/{TOKYO_TRIP_MAX_PLAYERS})",
                value=players_list_str,
                inline=False
            )

            # Left Column: Progress & Countdown
            progress_value = (
                f"Milestones: {rewards.current_milestones}/{rewards.max_milestones}\n"
                f"Next milestone: {next_milestone_val}\n"
                f"Next gain: +{rewards.coins_per_milestone:,} 🪙 | +{rewards.balls_per_milestone:,} 🏐"
            )
            embed.add_field(
                name="Progress",
                value=progress_value,
                inline=True
            )

            voucher_label = (
                f"+{MAX_DURATION_BONUS_VOUCHERS} Voucher"
                if MAX_DURATION_BONUS_VOUCHERS == 1
                else f"+{MAX_DURATION_BONUS_VOUCHERS} Vouchers"
            )

            # Right Column: Accumulated Rewards & Voucher status
            rewards_value = (
                f"🪙 **{rewards.scout_coins:,}** Scout Coins\n"
                f"🏐 **{rewards.practice_balls:,}** Practice Balls\n"
                f"🎟️ {voucher_label}: {voucher_val}"
            )
            embed.add_field(
                name="Accumulated Rewards",
                value=rewards_value,
                inline=True
            )

            # Bottom Full-Width Field: Exhaustion & Claim Rules
            bottom_notice = (
                f"Claiming rewards always makes your squad exhausted for **{EXHAUSTION_HOURS} hours**. "
                "Claiming before the first milestone yields **0 rewards**!"
            )
            embed.add_field(
                name="Rules & Exhaustion",
                value=bottom_notice,
                inline=False
            )

            embed.set_image(url="attachment://tokyo_trip.jpg")
            return embed

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
                "Every qualified player is either locked into your team lineups or exhausted! "
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

        # State 1: Active Trip
        if self.is_active_trip:
            if self.is_clearing_confirmation:
                btn_confirm = discord.ui.Button(label="Yes, End Trip Early", style=discord.ButtonStyle.danger,
                                                emoji="⚠️", row=0)
                btn_cancel_claim = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌",
                                                     row=0)
                btn_confirm.callback = self._confirm_early_claim_action
                btn_cancel_claim.callback = self._cancel_early_claim_action
                self.add_item(btn_confirm)
                self.add_item(btn_cancel_claim)
            else:
                btn_claim = discord.ui.Button(label="Claim Rewards", style=discord.ButtonStyle.success, emoji="🎁",
                                              row=0)
                btn_claim.callback = self._handle_claim_rewards
                self.add_item(btn_claim)

                btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
                btn_back.callback = self._handle_back
                self.add_item(btn_back)
            return

        filtered_cards = self.get_filtered_cards()

        # States 2, 3, & 4: Locked, Incomplete Lineup, or No Available Cards
        if not self.has_met_requirement or not self.has_full_lineup or not filtered_cards:
            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
            btn_back.callback = self._handle_back
            self.add_item(btn_back)
            return

        # State 5: Normal Squad Building UI
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

    async def update_screen(self, interaction: discord.Interaction, fetch_db: bool = False):
        if fetch_db:
            data = await self._fetch_trip_data(self.user_id)
            self.user_cards = data["user_cards"]
            self.all_user_cards = data["all_user_cards"]
            self.is_active_trip = data["is_active_trip"]
            self.trip_start = data.get("trip_start")
            self.has_full_lineup = data["has_full_lineup"]
            self.has_met_requirement = data["has_met_requirement"]

        self._setup_components()
        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_claim_rewards(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)

        elapsed_seconds = (datetime.now(timezone.utc) - self.trip_start).total_seconds()

        if elapsed_seconds < (INTERVAL_HOURS * 3600):
            self.is_clearing_confirmation = True
            await self.update_screen(interaction)
            return

        await claim_tokyo_trip(self.user_id)
        self.is_clearing_confirmation = False
        await self.update_screen(interaction, fetch_db=True)

    async def _confirm_early_claim_action(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await claim_tokyo_trip(self.user_id)
        self.is_clearing_confirmation = False
        await self.update_screen(interaction, fetch_db=True)

    async def _cancel_early_claim_action(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_clearing_confirmation = False
        await self.update_screen(interaction)

    async def _handle_enter_slot_selection(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_slot_selection_mode = True
        await self.update_screen(interaction)

    def _create_trip_slot_callback(self, slot_index: int):
        async def callback(interaction: discord.Interaction):
            await lock_view_ui(self, interaction)

            keys_to_remove = [
                idx for idx, cid in self.trip_slots.items()
                if cid == self.selected_card_id
            ]
            for idx in keys_to_remove:
                del self.trip_slots[idx]

            self.trip_slots[slot_index] = self.selected_card_id
            self.is_slot_selection_mode = True

            await self.update_screen(interaction)

        return callback

    async def _handle_cancel_slot_selection(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_slot_selection_mode = False
        await self.update_screen(interaction)

    async def _handle_clear_players(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.trip_slots.clear()
        await self.update_screen(interaction)

    async def _handle_trip(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        card_ids = list(self.trip_slots.values())
        await start_tokyo_trip(self.user_id, card_ids)
        self.trip_slots.clear()
        await self.update_screen(interaction, fetch_db=True)

    @staticmethod
    def _check_unlock_requirement(user_cards: list[dict]) -> tuple[bool, int]:
        total_owned = sum(1 for c in user_cards if c["rarity"] in ALLOWED_RARITIES)
        return total_owned >= TOKYO_TRIP_MIN_OWNED, total_owned

    @staticmethod
    async def _fetch_trip_data(user_id: int) -> dict:
        """Shared helper to load and filter user cards for Tokyo Trip states."""
        trip_start, user_cards = await asyncio.gather(
            get_tokyo_trip_start(user_id),
            get_user_cards(user_id)
        )
        is_active_trip = trip_start is not None

        if is_active_trip:
            trip_cards = [c for c in user_cards if c.get("is_on_trip", False)]
            return {
                "user_cards": trip_cards,
                "all_user_cards": user_cards,
                "is_active_trip": True,
                "trip_start": trip_start,
                "has_full_lineup": True,
                "has_met_requirement": True
            }

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

            now_utc = datetime.now(timezone.utc)
            filtered_user_cards = [
                c for c in user_cards
                if c["rarity"] in ALLOWED_RARITIES
                   and c["id"] not in assigned_card_ids
                   and not c["is_on_trip"]
                   and (not c.get("exhausted_until") or c["exhausted_until"] <= now_utc)
            ]

        return {
            "user_cards": filtered_user_cards,
            "all_user_cards": user_cards,
            "is_active_trip": False,
            "has_full_lineup": has_full_lineup,
            "has_met_requirement": has_met_requirement
        }

    async def _get_screen_payload(self) -> tuple[str | None, discord.Embed, list[discord.File]]:
        """Helper to build content, embed, and attachments for the trip screen."""
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