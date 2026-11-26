import asyncio
import discord

from ui.utils import lock_view_ui, format_lineup_court_display, format_resonance_badge, format_number, get_short_name, \
    shorten_log_names, create_card_embed, calculate_team_context, add_card_metadata_fields, LineupSelectMenu, \
    CardSelectMenu, BaseCardRosterView
from engine.data_loader import TEAM_CONFIG, MATCH_CONFIG, STARTING_SLOTS, ALL_SLOTS, POSITION_MAPPING, ITEM_METADATA
from engine.opponent_generator import unpack_opponent_team
from engine.mechanics_boosts import apply_lineup_boosts, prepare_match_matchup
from engine.match_simulation import run_match_simulation
from database import get_lineups, get_inventory, get_user_cards, get_or_create_opponent, consume_match_refresh, \
    redeem_voucher, apply_match_rewards

DIFFICULTY_EMOJIS = {"Casual": "🌱", "Easy": "👟", "Normal": "⚡", "Hard": "💥", "Nightmare": "💀"}

# Load match configurations & item medatadata shortcuts
DIFFICULTY_REWARDS = MATCH_CONFIG["difficulties"]
DEFAULT_LINEUP_NAME = TEAM_CONFIG["default_lineup_name_format"]
PASS_COST = MATCH_CONFIG["pass_cost"]
SCRAP_COST = MATCH_CONFIG["voucher_redeem_cost"]

COIN_EMOJI = ITEM_METADATA["coins"]["emoji"]
BALL_EMOJI = ITEM_METADATA["balls"]["emoji"]
SCRAP_NAME = ITEM_METADATA["scraps"]["name"]
SCRAP_EMOJI = ITEM_METADATA["scraps"]["emoji"]
VOUCHER_SINGULAR = ITEM_METADATA["vouchers"]["singular"]
VOUCHER_EMOJI = ITEM_METADATA["vouchers"]["emoji"]
PASS_EMOJI = ITEM_METADATA["pass"]["emoji"]


class DifficultySelectMenu(discord.ui.Select):
    def __init__(self, current_difficulty: str):
        difficulties = [
            ("Casual", "Relaxed match for beginners"),
            ("Easy", "Light challenge with basic rewards"),
            ("Normal", "Standard match difficulty"),
            ("Hard", "Intense match with skilled opponents"),
            ("Nightmare", "Extreme challenge for elite teams"),
        ]

        options = []
        for name, desc in difficulties:
            options.append(
                discord.SelectOption(
                    label=name,
                    emoji=DIFFICULTY_EMOJIS.get(name),
                    description=desc,
                    default=(name == current_difficulty),
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
        await self.view.update_screen(interaction, refresh_opponent=True)


class MatchScreenView(BaseCardRosterView):
    def __init__(self, user_id: int, user_cards: list[dict], lineups: dict[int, dict] = None,
                 selected_card_id: str | None = None, initial_opponent: dict | None = None,
                 inventory=None):
        super().__init__(user_id, user_cards, selected_card_id)
        self.selected_lineup_index = 1
        self.lineups = lineups or {}
        self.state = "opponent_select"
        self.selected_difficulty = "Normal"
        self.current_opponent = initial_opponent or {}
        self.inventory = inventory
        self.latest_match_result: dict | None = None
        self._setup_components()

    @classmethod
    async def create(cls, user_id: int, selected_card_id: str | None = None):
        user_cards, lineups, initial_opponent, inventory = await asyncio.gather(
            get_user_cards(user_id),
            get_lineups(user_id),
            get_or_create_opponent(user_id, "Normal"),
            get_inventory(user_id)
        )

        view = cls(user_id, user_cards, lineups, selected_card_id, initial_opponent, inventory)
        content, embed, attachments = await view._get_screen_payload()
        return view, content, embed, attachments

    def get_filtered_cards(self) -> list[dict]:
        team_data = self.lineups.get(self.selected_lineup_index, {})
        card_lookup = {c["id"]: c for c in self.user_cards}
        return [card_lookup[cid] for slot in ALL_SLOTS if (cid := team_data.get(slot)) and cid in card_lookup]

    async def build_content(self) -> str | None:
        if self.state in ("opponent_select", "match_results"):
            return None  # No court display text needed on opponent or results screens

        team_data = self.lineups.get(self.selected_lineup_index, {})
        return format_lineup_court_display(team_data, self.user_cards, self.selected_lineup_index)

    async def build_embed(self) -> discord.Embed | None:
        # State 1: Opponent Scouting & Selection
        if self.state == "opponent_select":
            diff_emoji = DIFFICULTY_EMOJIS[self.selected_difficulty]

            # 1. Unpack opponent team using your generator helper
            lineup, cards_list, slot_to_id = unpack_opponent_team(self.current_opponent)

            # 2. Extract active bonuses via calculate_team_context
            ctx = calculate_team_context(slot_to_id, cards_list)

            # 3. Format clean team info values
            synergy_val = f"{ctx['active_synergy_school']}" if ctx['active_synergy_school'] else "None"
            specialty_val = ctx['active_specialty_name']
            bonds_val = ctx['active_bonds_count']

            embed = discord.Embed(
                title="⚔️ Match - Opponent Scouting",
                description=(
                    f"• **Difficulty:** {diff_emoji} {self.selected_difficulty}\n"
                    f"• **Synergy:** 🏫 {synergy_val}\n"
                    f"• **Specialty:** 🎯 {specialty_val}\n"
                    f"• **Bonds:** 🤝 {bonds_val} Active"
                ),
            )

            # Build clean player lines from the generated lineup
            player_lines = []
            for slot, label in POSITION_MAPPING.items():
                p_data = lineup.get(slot)
                if p_data:
                    short_name = get_short_name(p_data['name'])
                    res_badge = format_resonance_badge(p_data['resonance'])
                    player_lines.append(
                        f"• **[{label}]:** {short_name} *({p_data['rarity']} | Lv.{p_data['level']} | {res_badge})*"
                    )

            embed.add_field(name="🎽 Opponent Lineup", value="\n".join(player_lines), inline=False)

            rew_cfg = DIFFICULTY_REWARDS.get(self.selected_difficulty, {}).get("rewards", {})
            win_line = self._format_reward_line(rew_cfg.get("win", {}), prefix="• **Win:** ")
            loss_line = self._format_reward_line(rew_cfg.get("loss", {}), prefix="• **Loss:** ")
            redeem_line = f"• Redeem **1** {VOUCHER_EMOJI} {VOUCHER_SINGULAR}: {SCRAP_EMOJI} **{SCRAP_COST}**"

            embed.add_field(
                name="🎁 Match Rewards",
                value=f"{win_line}\n{loss_line}\n{redeem_line}",
                inline=False,
            )

            embed.set_footer(
                text=(
                    f"Balance: {PASS_EMOJI} {format_number(self.inventory.match_passes)}  •  "
                    f"{SCRAP_EMOJI} {format_number(self.inventory.voucher_scraps)}  •  "
                    f"{VOUCHER_EMOJI} {format_number(self.inventory.drink_vouchers)}"
                )
            )

        # State 2: Post-Match Results Screen
        elif self.state == "match_results":
            res = self.latest_match_result
            user_score = res["user_score"]
            opp_score = res["opponent_score"]
            match_log = res["match_log"]

            won = user_score > opp_score
            outcome_text = "VICTORY" if won else "DEFEAT"
            outcome_key = "win" if won else "loss"

            lineup_data = self.lineups.get(self.selected_lineup_index, {})
            user_team_name = lineup_data.get("lineup_name") or DEFAULT_LINEUP_NAME.format(self.selected_lineup_index)
            opp_team_name = f"{self.selected_difficulty} Opponent"

            rew = DIFFICULTY_REWARDS.get(self.selected_difficulty, {}).get("rewards", {}).get(outcome_key, {})
            rewards_line = self._format_reward_line(rew, prefix="🎁 **Rewards:** ", sep="  ")

            score_section = (
                f"📊 **Final Score:**\n"
                f"{user_team_name} `{user_score}` - `{opp_score}` {opp_team_name}\n"
                f"{rewards_line}"
            )

            embed = discord.Embed(
                title=f"⚔️ Match Results - {outcome_text}",
                description=score_section,
            )

            max_len = 1024
            notice = "\n*(...earlier rallies truncated)*"
            lines: list[str] = []

            for entry in match_log:
                short_entry = shorten_log_names(entry)
                candidate = short_entry if not lines else f"\n{short_entry}"
                current_len = sum(len(x) for x in lines)

                if current_len + len(candidate) + len(notice) > max_len:
                    lines.append(notice)
                    break

                lines.append(candidate)

            log_text = "".join(lines)
            embed.add_field(name="📜 Match Log", value=log_text, inline=False)


        else:
            # State 3: Lineup Selection & Card Preview (Default Fallthrough)
            card_lookup = {c["id"]: c for c in self.user_cards}
            filtered_cards = self.get_filtered_cards()
            target_card = self._get_target_card(filtered_cards)

            if not target_card:
                return None

            team_data = self.lineups.get(self.selected_lineup_index, {})
            boosted_stats_map = apply_lineup_boosts(team_data, self.user_cards)
            target_slot = next((slot for slot, cid in team_data.items() if cid == target_card["id"]), None)
            card_stats = boosted_stats_map.get(
                target_slot, target_card.get("scaled_stats", target_card.get("base_stats", {}))
            )

            active_lineup_card_ids = {
                team_data.get(slot) for slot in STARTING_SLOTS
                if team_data.get(slot) in card_lookup
            }

            embed = create_card_embed(target_card, extra_stats=card_stats, show_quote=False)
            add_card_metadata_fields(embed, target_card, active_lineup_card_ids=active_lineup_card_ids)
            return embed

        embed.color = discord.Color.from_rgb(217, 56, 58)
        return embed

    def _setup_components(self):
        self.clear_items()  # Clear old items when switching states

        if self.state == "opponent_select":
            # Row 0: Difficulty Dropdown Menu
            self.add_item(DifficultySelectMenu(self.selected_difficulty))

            # Row 1: Challenge & Refresh buttons
            btn_challenge = discord.ui.Button(label="Challenge", style=discord.ButtonStyle.success, row=1)
            btn_challenge.callback = self._handle_challenge_click
            self.add_item(btn_challenge)

            btn_refresh = discord.ui.Button(label=f"Refresh ({self.inventory.match_refreshes})", style=discord.ButtonStyle.primary,
                emoji="🔄", row=1, disabled=(self.inventory.match_refreshes <= 0))
            btn_refresh.callback = self._handle_refresh_click
            self.add_item(btn_refresh)

            # Row 2: Redeem Drink Voucher & Back buttons
            btn_redeem = discord.ui.Button(label="Redeem Drink Voucher", style=discord.ButtonStyle.secondary,
                emoji=VOUCHER_EMOJI, row=2)
            btn_redeem.callback = self._handle_redeem_voucher_click
            self.add_item(btn_redeem)

            btn_back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
            btn_back.callback = self._handle_back
            self.add_item(btn_back)

        elif self.state == "lineup_select":
            filtered_cards, page_cards, max_pages, page_info = self._setup_pagination()
            lineup_names_map = {i: data.get("lineup_name", DEFAULT_LINEUP_NAME.format(i)) for i, data in self.lineups.items()}

            # Row 0: Lineup Selector
            self.add_item(LineupSelectMenu(self.selected_lineup_index, lineup_names_map))

            # Row 1: Cards Dropdown
            self.add_item(CardSelectMenu(page_cards, self.selected_card_id, page_info,
                                         custom_placeholder="Select lineup player...", row=1))

            team_data = self.lineups.get(self.selected_lineup_index, {})
            is_lineup_complete = all(team_data.get(slot) for slot in STARTING_SLOTS)
            has_enough_passes = self.inventory.match_passes >= PASS_COST

            # Row 2: Action Buttons
            btn_play = discord.ui.Button(label=f"Play Match ({self.inventory.match_passes})", style=discord.ButtonStyle.success,
                emoji=PASS_EMOJI, row=2, disabled=not (is_lineup_complete and has_enough_passes))

            btn_back_match = discord.ui.Button(label="Back to Match Menu", style=discord.ButtonStyle.secondary,
                                               emoji="⬅️", row=2)

            btn_play.callback = self.play_callback
            btn_back_match.callback = self._handle_back_to_opponent

            self.add_item(btn_play)
            self.add_item(btn_back_match)

        elif self.state == "match_results":
            # Row 0: Post-Match Actions (Play Again & Back to Menu)
            btn_play_again = discord.ui.Button(label="Play Again", style=discord.ButtonStyle.success, emoji="⚔️", row=0)
            btn_play_again.callback = self._handle_play_again

            btn_back_menu = discord.ui.Button(label="Back to Menu", style=discord.ButtonStyle.secondary, emoji="⬅️", row=0)
            btn_back_menu.callback = self._handle_back

            self.add_item(btn_play_again)
            self.add_item(btn_back_menu)

    async def update_screen(
        self,
        interaction: discord.Interaction,
        refresh_opponent: bool = False,
        refresh_lineups: bool = True,
    ):
        tasks = [get_inventory(self.user_id)]
        if refresh_lineups:
            tasks.append(get_lineups(self.user_id))

        should_fetch_opponent = refresh_opponent or not self.current_opponent
        if should_fetch_opponent:
            tasks.append(get_or_create_opponent(self.user_id, self.selected_difficulty))

        results = await asyncio.gather(*tasks)
        idx = 0
        self.inventory = results[idx]
        idx += 1

        if refresh_lineups:
            self.lineups = results[idx]
            idx += 1

        if should_fetch_opponent:
            self.current_opponent = results[idx]

        self._setup_components()
        content, embed, attachments = await self._get_screen_payload()
        await interaction.edit_original_response(content=content, embed=embed, view=self, attachments=attachments)

    async def _handle_back_to_opponent(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.state = "opponent_select"  # Switch back to opponent menu
        self.selected_card_id = None
        await self.update_screen(interaction, refresh_lineups=False)

    async def _handle_challenge_click(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        self.state = "lineup_select"  # Switch state to lineup selection
        await self.update_screen(interaction, refresh_lineups=False)

    async def _handle_refresh_click(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        await consume_match_refresh(self.user_id)
        await get_or_create_opponent(self.user_id, self.selected_difficulty, force_regenerate=True)
        await self.update_screen(interaction, refresh_opponent=True, refresh_lineups=False)

    async def _handle_redeem_voucher_click(self, interaction: discord.Interaction):
        if self.inventory.voucher_scraps < SCRAP_COST:
            await interaction.response.send_message(
                f"❌ You need at least {SCRAP_EMOJI} **{SCRAP_COST}** {SCRAP_NAME} to redeem **1** {VOUCHER_SINGULAR}!",
                ephemeral=True,
            )
            return

        await lock_view_ui(self, interaction)
        await redeem_voucher(self.user_id)
        await self.update_screen(interaction, refresh_lineups=False)

    async def _handle_play_again(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        res = self.latest_match_result or {}
        did_win = res.get("user_score", 0) > res.get("opponent_score", 0)

        self.state = "opponent_select"
        if did_win:
            self.current_opponent = await get_or_create_opponent(
                self.user_id, self.selected_difficulty, force_regenerate=True
            )
        await self.update_screen(interaction, refresh_opponent=not did_win, refresh_lineups=False)

    async def play_callback(self, interaction: discord.Interaction):
        await lock_view_ui(self, interaction)
        team_data = self.lineups.get(self.selected_lineup_index, {})

        # 1. Unpack the computer-generated opponent data into lineup slots and card lists
        opp_lineup, opp_cards_list, opp_slot_to_id = unpack_opponent_team(self.current_opponent)

        # 2. Calculate stats and apply debuffs using the newly unpacked opponent format
        user_stats, opponent_stats = prepare_match_matchup(
            user_lineup_data=team_data,
            user_cards=self.user_cards,
            opponent_lineup_data=opp_slot_to_id,
            opponent_cards=opp_cards_list
        )

        # 3. Run the match simulation and save it to the view instance
        result = run_match_simulation(user_stats, opponent_stats)
        self.latest_match_result = result

        won = result["user_score"] > result["opponent_score"]
        await apply_match_rewards(self.user_id, self.selected_difficulty, won)

        # 4. Transition state to match results and refresh the interface
        self.state = "match_results"
        self.selected_card_id = None
        await self.update_screen(interaction)

    @staticmethod
    def _format_reward_line(rew: dict, prefix: str = "", sep: str = "\u00a0\u00a0\u00a0") -> str:
        parts = [
            f"+{rew.get('scout_coins', 0):,} {COIN_EMOJI}",
            f"+{rew.get('practice_balls', 0):,} {BALL_EMOJI}",
            f"+{rew.get('voucher_scraps', 0):,} {SCRAP_EMOJI}",
        ]
        return f"{prefix}{sep.join(parts)}"

    async def _get_screen_payload(self) -> tuple[str | None, discord.Embed | None, list[discord.File]]:
        content = await self.build_content()
        embed = await self.build_embed()

        if self.state in ("opponent_select", "match_results"):
            attachments = []
        else:
            attachments = self._get_target_card_attachments() if embed else []

        return content, embed, attachments