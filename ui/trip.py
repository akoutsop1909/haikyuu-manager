import asyncio
from datetime import datetime, timezone
import discord

from ui.utils import lock_view_ui, create_card_embed, get_card_image_file, get_banner_file, PositionFilterSelectMenu, \
    CardSelectMenu, BaseCardRosterView
from engine.game_logic import calculate_tokyo_trip_rewards
from engine.data_loader import TOKYO_TRIP_CONFIG, ITEM_METADATA, STARTING_SLOTS, ALL_SLOTS
from database import get_user_cards, get_lineups, get_trip_squads, add_to_trip_squad, clear_trip_squad, \
    get_tokyo_trip_start, start_tokyo_trip, claim_tokyo_trip

# Load Tokyo trip configurations & item medatadata shortcuts
TOKYO_TRIP_MIN_OWNED = TOKYO_TRIP_CONFIG["min_r_sr_owned"]
TOKYO_TRIP_MAX_PLAYERS = TOKYO_TRIP_CONFIG["max_players"]
TOKYO_TRIP_MAX_SQUADS = TOKYO_TRIP_CONFIG["max_squads"]
ALLOWED_RARITIES = tuple(TOKYO_TRIP_CONFIG.get("allowed_rarities", ["R", "SR"]))
RARITY_LABEL = "/".join(ALLOWED_RARITIES)
REWARDS_CONFIG = TOKYO_TRIP_CONFIG.get("rewards_by_rarity", {})
R_R = REWARDS_CONFIG.get("R", {"scout_coins": 30, "practice_balls": 150})
SR_R = REWARDS_CONFIG.get("SR", {"scout_coins": 50, "practice_balls": 200})
INTERVAL_HOURS = TOKYO_TRIP_CONFIG["milestone_interval_hours"]
EXHAUSTION_HOURS = TOKYO_TRIP_CONFIG["exhaustion_hours"]
MAX_DURATION_HOURS = TOKYO_TRIP_CONFIG["max_duration_hours"]
MAX_DURATION_BONUS_VOUCHERS = TOKYO_TRIP_CONFIG["max_duration_bonus_vouchers"]

COIN_NAME = ITEM_METADATA["coins"]["name"]
COIN_EMOJI = ITEM_METADATA["coins"]["emoji"]
BALL_NAME = ITEM_METADATA["balls"]["name"]
BALL_EMOJI = ITEM_METADATA["balls"]["emoji"]
VOUCHER_NAME = ITEM_METADATA["vouchers"]["name"]
VOUCHER_EMOJI = ITEM_METADATA["vouchers"]["emoji"]


class TokyoSquadSelectMenu(discord.ui.Select):
    def __init__(self, current_squad: int = 1, squad_names: dict[int, str] = None):
        squad_names = squad_names or {}
        options = []

        for i in range(1, TOKYO_TRIP_MAX_SQUADS + 1):
            name = squad_names.get(i, f"Squad {i}")
            options.append(
                discord.SelectOption(
                    label=name,
                    value=str(i),
                    default=(current_squad == i),
                    emoji="🚌"
                )
            )

        super().__init__(placeholder="Select Trip Squad...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        await lock_view_ui(view, interaction)
        view.current_squad_number = int(self.values[0])
        await view.update_screen(interaction)

class TripScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], all_user_cards: list[dict] | None = None,
                 selected_card_id: str | None = None, is_active_trip: bool = False,
                 trip_start: datetime | None = None,
                 has_full_lineup: bool = True, has_met_requirement: bool = True,
                 trip_squads: dict[int, dict] | None = None,
                 assigned_card_ids: set[str] | None = None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.all_user_cards = all_user_cards or user_cards
        self.is_active_trip = is_active_trip
        self.trip_start = trip_start
        self.has_full_lineup = has_full_lineup
        self.has_met_requirement = has_met_requirement
        self.trip_squads = trip_squads or {}
        self.assigned_card_ids = assigned_card_ids or set()
        self.current_squad_number = 1
        self.is_slot_selection_mode = False  # Track whether we are in the slot picker screen
        self.is_clearing_confirmation = False  # Track early claim confirmation state
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
            has_met_requirement=data["has_met_requirement"],
            trip_squads=data.get("trip_squads"),
            assigned_card_ids=data.get("assigned_card_ids")
        )
        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    def get_filtered_cards(self) -> list[dict]:
        cards = super().get_filtered_cards()
        return [c for c in cards if c.get("rarity") in ALLOWED_RARITIES]

    async def build_content(self) -> str | None:
        filtered_cards = self.get_filtered_cards()
        if self.is_active_trip or not filtered_cards:
            return None

        info = self._get_squad_validation_info()
        squad_data = self.trip_squads.get(self.current_squad_number, {})
        squad_name = squad_data.get("squad_name", f"Squad {self.current_squad_number}")

        squad_str = f"🚌 **Tokyo Training Camp ({squad_name})**\n" + "\n".join(info["slot_lines"])

        warnings = []
        if info["has_exhausted"]:
            warnings.append("exhausted")
        if info["has_lineup_conflict"]:
            warnings.append("assigned to a team lineup")

        warning_str = f"\n\n⚠️ *Squad contains {' and '.join(warnings)} players! Clear or replace them to send.*" if warnings else ""

        dummy_start = datetime.now(timezone.utc)
        rewards = calculate_tokyo_trip_rewards(dummy_start, info["selected_cards"])

        reward_preview = (
            f"\n\n**Trip Rules & Rewards:**\n"
            f"• Rewards per Rarity:\n"
            f"  ▫️ R: +{R_R['scout_coins']} {COIN_EMOJI} | +{R_R['practice_balls']} {BALL_EMOJI}\n"
            f"  ▫️ SR: +{SR_R['scout_coins']} {COIN_EMOJI} | +{SR_R['practice_balls']} {BALL_EMOJI}\n"
            f"• Rewards (every {INTERVAL_HOURS}h, max {rewards.max_milestones}): +{rewards.coins_per_milestone:,} {COIN_EMOJI} | +{rewards.balls_per_milestone:,} {BALL_EMOJI}\n"
            f"• Max Duration Bonus ({MAX_DURATION_HOURS}h): +{MAX_DURATION_BONUS_VOUCHERS} {VOUCHER_EMOJI}\n"
            f"• Exhaustion: {EXHAUSTION_HOURS}h upon claim\n"
            f"*(Note: Lineup and exhausted players are hidden)*"
        )
        return squad_str + warning_str + reward_preview

    async def build_embed(self) -> discord.Embed:
        banner_filename = "tokyo_trip.jpg"

        # State 1: Active Trip
        if self.is_active_trip:
            rewards = calculate_tokyo_trip_rewards(self.trip_start, self.user_cards)

            player_lines = [
                f"• {c['name']} ({c['rarity']})"
                for c in self.user_cards
            ]
            players_list_str = "\n".join(player_lines)

            embed = discord.Embed(
                title="🚌 Tokyo Training Camp - Active Squad",
                description="Your squad is currently training hard in Tokyo!"
            )
            embed.add_field(
                name=f"Active Members ({len(self.user_cards)}/{TOKYO_TRIP_MAX_PLAYERS})",
                value=players_list_str,
                inline=False
            )

            # Check if max duration has been reached
            is_max_duration = rewards.max_duration_ts is None

            if is_max_duration:
                progress_value = "Trip complete! Rewards are ready to claim."
                rewards_value = (
                    f"{COIN_EMOJI} **{rewards.scout_coins:,}** {COIN_NAME}\n"
                    f"{BALL_EMOJI} **{rewards.practice_balls:,}** {BALL_NAME}\n"
                    f"{VOUCHER_EMOJI} **{MAX_DURATION_BONUS_VOUCHERS}** {VOUCHER_NAME}"
                )
                banner_filename = "tokyo_trip_complete.webp"
            else:
                progress_value = (
                    f"Milestones: {rewards.current_milestones}/{rewards.max_milestones}\n"
                    f"Next milestone: <t:{rewards.next_milestone_ts}:R>\n"
                    f"Next gain: +{rewards.coins_per_milestone:,} {COIN_EMOJI} | +{rewards.balls_per_milestone:,} {BALL_EMOJI}\n"
                    f"{VOUCHER_EMOJI} +{MAX_DURATION_BONUS_VOUCHERS} {VOUCHER_NAME}: <t:{rewards.max_duration_ts}:R>"
                )
                rewards_value = (
                    f"{COIN_EMOJI} **{rewards.scout_coins:,}** {COIN_NAME}\n"
                    f"{BALL_EMOJI} **{rewards.practice_balls:,}** {BALL_NAME}"
                )

            embed.add_field(name="Progress", value=progress_value, inline=True)
            embed.add_field(name="Accumulated Rewards", value=rewards_value, inline=True)

            bottom_notice = (
                f"Claiming rewards always makes your squad exhausted for **{EXHAUSTION_HOURS} hours**. "
                "Claiming before the first milestone yields **0 rewards**!"
            )
            embed.add_field(name="Rules & Exhaustion", value=bottom_notice, inline=False)

        # State 2: Locked (Requirement not met)
        elif not self.has_met_requirement:
            _, total_owned = self._check_unlock_requirement(self.all_user_cards)
            embed = discord.Embed(
                title="🔒 Tokyo Training Camp Locked",
                description=(
                    "The powerhouse schools in Tokyo won't invite a small roster for a joint practice. "
                    "Scout more players to expand your team and get the invite.\n\n"
                    f"*(Progress: {total_owned}/{TOKYO_TRIP_MIN_OWNED} {RARITY_LABEL} players)*"
                )
            )

        # State 3: Missing a complete lineup
        elif not self.has_full_lineup:
            embed = discord.Embed(
                title="⚠️ Incomplete Starting Lineup",
                description=(
                    "You can't leave the club short-handed! You need at least one complete lineup "
                    "with all 7 starting positions filled before sending anyone away on a trip."
                )
            )

        # State 4: No available filtered cards left
        elif not self.get_filtered_cards():
            embed = discord.Embed(
                title="⚠️ No Players Available for the Trip",
                description=(
                    "Every qualified player is either locked into your team lineups or exhausted! "
                    f"Free up roster slots or recruit more {RARITY_LABEL} players to fill out your trip squad."
                )
            )

        else:
            # State 5: Default card preview (Normal Selection)
            filtered_cards = self.get_filtered_cards()
            target_card = self._get_target_card(filtered_cards)
            scaled_stats = target_card.get("scaled_stats", target_card.get("base_stats", {}))
            return create_card_embed(target_card, extra_stats=scaled_stats)

        # Shared color, image attachment, and return for States 1 through 4
        embed.color = discord.Color.teal()
        embed.set_image(url=f"attachment://{banner_filename}")
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

        squad_names_map = {num: data.get("squad_name", f"Squad {num}") for num, data in self.trip_squads.items()}

        # Row 0: Tokyo Squad Dropdown
        self.add_item(TokyoSquadSelectMenu(self.current_squad_number, squad_names_map))

        # Row 1: Position Filter Dropdown
        self.add_item(PositionFilterSelectMenu(self.user_cards, self.selected_position, row=1))

        # Row 2: Cards Dropdown
        self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                     custom_placeholder="Select player for trip...", row=2))

        squad_data = self.trip_squads.get(self.current_squad_number, {})
        is_squad_empty = all(not squad_data.get(f"slot_{i}") for i in range(1, TOKYO_TRIP_MAX_PLAYERS + 1))

        info = self._get_squad_validation_info()
        is_send_disabled = is_squad_empty or info["has_exhausted"] or info["has_lineup_conflict"]

        if not self.is_slot_selection_mode:
            # Row 3: Action Buttons
            btn_add = discord.ui.Button(label="Edit", style=discord.ButtonStyle.primary, emoji="📋", row=3)
            btn_clear = discord.ui.Button(
                label="Clear", style=discord.ButtonStyle.secondary, emoji="🧹", row=3, disabled=is_squad_empty
            )
            btn_trip = discord.ui.Button(
                label="Send", style=discord.ButtonStyle.success, emoji="🚌", row=3, disabled=is_send_disabled
            )

            btn_add.callback = self._handle_enter_slot_selection
            btn_clear.callback = self._handle_clear_players
            btn_trip.callback = self._handle_trip

            self.add_item(btn_add)
            self.add_item(btn_clear)
            self.add_item(btn_trip)

            # Row 4: Navigation / Back Buttons
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
            # Row 3: Slot Buttons 1 to 3
            for i in range(1, 4):
                btn_slot = discord.ui.Button(label=f"Slot {i}", style=discord.ButtonStyle.primary, row=3)
                btn_slot.callback = self._create_trip_slot_callback(i)
                self.add_item(btn_slot)

            # Row 4: Slot Buttons 4 & 5 + Cancel Button
            for i in range(4, TOKYO_TRIP_MAX_PLAYERS + 1):
                btn_slot = discord.ui.Button(label=f"Slot {i}", style=discord.ButtonStyle.primary, row=4)
                btn_slot.callback = self._create_trip_slot_callback(i)
                self.add_item(btn_slot)

            btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", row=4)
            btn_cancel.callback = self._handle_cancel_slot_selection
            self.add_item(btn_cancel)

    async def update_screen(self, interaction: discord.Interaction, fetch_db: bool = False):
        if fetch_db:
            data = await self._fetch_trip_data(self.user_id)
            self.user_cards = data["user_cards"]
            self.all_user_cards = data["all_user_cards"]
            self.is_active_trip = data["is_active_trip"]
            self.trip_start = data.get("trip_start")
            self.has_full_lineup = data["has_full_lineup"]
            self.has_met_requirement = data["has_met_requirement"]
            self.assigned_card_ids = data.get("assigned_card_ids", set())
            self.trip_squads = data["trip_squads"]
        else:
            # Only hit DB for squads when doing local UI updates where fetch_db is False
            self.trip_squads = await get_trip_squads(self.user_id)

        self._setup_components()
        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_claim_rewards(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)

        rewards = calculate_tokyo_trip_rewards(self.trip_start, self.user_cards)

        # Trigger confirmation if max duration has not been reached yet
        if rewards.max_duration_ts is not None:
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
            slot_key = f"slot_{slot_index}"
            await add_to_trip_squad(interaction.user.id, self.current_squad_number, slot_key, self.selected_card_id)
            self.is_slot_selection_mode = True
            await self.update_screen(interaction)

        return callback

    async def _handle_cancel_slot_selection(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.is_slot_selection_mode = False
        await self.update_screen(interaction)

    async def _handle_clear_players(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await clear_trip_squad(self.user_id, self.current_squad_number)
        await self.update_screen(interaction)

    async def _handle_trip(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await start_tokyo_trip(self.user_id, self.current_squad_number)
        await self.update_screen(interaction, fetch_db=True)

    @staticmethod
    def _check_unlock_requirement(user_cards: list[dict]) -> tuple[bool, int]:
        total_owned = sum(1 for c in user_cards if c["rarity"] in ALLOWED_RARITIES)
        return total_owned >= TOKYO_TRIP_MIN_OWNED, total_owned

    @staticmethod
    async def _fetch_trip_data(user_id: int) -> dict:
        """Shared helper to load and filter user cards for Tokyo Trip states."""
        # Fetch trip start, user cards, and squads concurrently to eliminate waiting bottlenecks
        trip_start, user_cards, trip_squads = await asyncio.gather(
            get_tokyo_trip_start(user_id),
            get_user_cards(user_id),
            get_trip_squads(user_id)
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
                "has_met_requirement": True,
                "trip_squads": trip_squads,
                "assigned_card_ids": set()
            }

        has_met_requirement, _ = TripScreenView._check_unlock_requirement(user_cards)
        has_full_lineup = True
        assigned_card_ids = set()

        if has_met_requirement:
            lineups = await get_lineups(user_id)
            has_full_lineup = any(
                all(lineup_data.get(slot) for slot in STARTING_SLOTS)
                for lineup_data in lineups.values()
            )
            assigned_card_ids = {
                lineup_data[key]
                for lineup_data in lineups.values()
                for key in ALL_SLOTS
                if lineup_data.get(key)
            }

        if not has_met_requirement or not has_full_lineup:
            filtered_user_cards = []
        else:
            now_utc = datetime.now(timezone.utc)
            filtered_user_cards = [
                c for c in user_cards
                if c["rarity"] in ALLOWED_RARITIES
                   and c["id"] not in assigned_card_ids
                   and (not c.get("exhausted_until") or c["exhausted_until"] <= now_utc)
            ]

        return {
            "user_cards": filtered_user_cards,
            "all_user_cards": user_cards,
            "is_active_trip": False,
            "has_full_lineup": has_full_lineup,
            "has_met_requirement": has_met_requirement,
            "trip_squads": trip_squads,
            "assigned_card_ids": assigned_card_ids
        }

    def _get_squad_validation_info(self) -> dict:
        """Helper to process squad slots, resolve cards, check for exhaustion and lineup conflicts."""
        card_lookup = {c["id"]: c for c in self.all_user_cards}
        squad_data = self.trip_squads.get(self.current_squad_number, {})
        now_utc = datetime.now(timezone.utc)

        slot_lines = []
        selected_cards = []
        has_exhausted = False
        has_lineup_conflict = False

        for i in range(1, TOKYO_TRIP_MAX_PLAYERS + 1):
            slot_id = squad_data.get(f"slot_{i}")
            if slot_id and slot_id in card_lookup:
                card = card_lookup[slot_id]
                exhausted_until = card.get("exhausted_until")
                is_exhausted = exhausted_until and exhausted_until > now_utc
                is_in_lineup = slot_id in self.assigned_card_ids

                if is_exhausted:
                    has_exhausted = True
                    slot_lines.append(f"Slot {i}: {card['name']} ({card['rarity']}) - ⚠️ *Exhausted*")
                elif is_in_lineup:
                    has_lineup_conflict = True
                    slot_lines.append(f"Slot {i}: {card['name']} ({card['rarity']}) - ⚠️ *In Lineup*")
                else:
                    selected_cards.append(card)
                    slot_lines.append(f"Slot {i}: {card['name']} ({card['rarity']})")
            else:
                if slot_id:
                    has_exhausted = True
                slot_lines.append(f"Slot {i}: *Empty*")

        return {
            "selected_cards": selected_cards,
            "slot_lines": slot_lines,
            "has_exhausted": has_exhausted,
            "has_lineup_conflict": has_lineup_conflict
        }

    async def _get_screen_payload(self) -> tuple[str | None, discord.Embed, list[discord.File]]:
        """Helper to build content, embed, and attachments for the trip screen."""
        content = await self.build_content()
        embed = await self.build_embed()

        filtered_cards = self.get_filtered_cards()

        # Determine whether to show the banner or the selected card image
        if self.is_active_trip or not filtered_cards:
            banner_key = "tokyo_trip"

            if self.is_active_trip:
                rewards = calculate_tokyo_trip_rewards(self.trip_start, self.user_cards)
                if rewards.max_duration_ts is None:
                    banner_key = "tokyo_trip_complete"

            banner_file = get_banner_file(banner_key)
            attachments = [banner_file] if banner_file else []
        else:
            target_card = self._get_target_card(filtered_cards)
            image_file = get_card_image_file(target_card) if target_card else None
            attachments = [image_file] if image_file else []

        return content, embed, attachments