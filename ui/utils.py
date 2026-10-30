from collections import defaultdict
from pathlib import Path
import discord

from engine.data_loader import CARDS_BY_ID, SPECIALTIES_BY_ID, BONDS_BY_ID, SYNERGIES_BY_ID, TEAM_CONFIG, ITEM_METADATA
from engine.mechanics_boosts import apply_lineup_boosts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"

RARITY_EMOJIS = {"R": "🔵", "SR": "🟣", "SSR": "🟡"}

# Global path cache to make card image lookups instant across all views
CARD_PATH_CACHE: dict[str, Path | None] = {}

MAX_LINEUPS = TEAM_CONFIG["max_lineups"]
DEFAULT_LINEUP_NAME = TEAM_CONFIG["default_lineup_name_format"]
MIN_SYNERGY_PLAYERS = TEAM_CONFIG["min_synergy_players"]


# ==============================================================================
# 1. DISCORD UI & GENERAL HELPERS
# ==============================================================================
async def lock_view_ui(view: discord.ui.View, interaction: discord.Interaction):
    """Disables only the buttons on the view and immediately edits the message to prevent race conditions."""
    for child in view.children:
        if isinstance(child, discord.ui.Button):
            child.disabled = True
    if not interaction.response.is_done():
        await interaction.response.edit_message(view=view)

def format_inventory_lines(data: dict | object) -> str:
    """Formats the standard 4 game inventory from either a dict or an inventory/pack object."""
    resource_keys = [
        ("pass", "match_passes"),
        ("coins", "scout_coins"),
        ("balls", "practice_balls"),
        ("drinks", "sports_drinks"),
        ("vouchers", "drink_vouchers"),
        ("scraps", "voucher_scraps")
    ]
    lines = []
    for meta_key, attr_key in resource_keys:
        meta = ITEM_METADATA[meta_key]
        amount = data.get(attr_key, 0) if isinstance(data, dict) else getattr(data, attr_key, 0)
        lines.append(f"{meta['emoji']} {meta['name']}: **{format_number(amount)}**")

    return "\n".join(lines)

def format_number(val: int) -> str:
    """Formats large integers into compact strings (e.g., 100M, 10.5K, 1,200)."""
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f}B".replace(".0B", "B")
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M".replace(".0M", "M")
    if val >= 10_000:
        return f"{val / 1_000:.1f}K".replace(".0K", "K")
    return f"{val:,}"

def get_short_name(full_name: str | None) -> str:
    """Formats full player name into 'F. LastName' (e.g., 'Tobio Kageyama' -> 'T. Kageyama')."""
    if not full_name:
        return "Unknown"
    parts = full_name.split()
    if len(parts) > 1:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"
    return full_name

def format_resonance_stars(resonance_level: int, max_resonance: int = 5) -> str:
    """Formats integer resonance into star icons: ★★★☆☆ """
    filled_stars = "★" * resonance_level
    empty_stars = "☆" * (max_resonance - resonance_level)
    return f"{filled_stars}{empty_stars}"

def format_resonance_badge(resonance: int) -> str:
    """Formats resonance into a compact badge string like ★1 or ★0."""
    return f"★{resonance}" if resonance > 0 else "★0"

# ==============================================================================
# 2. ASSET & FILE HELPERS
# ==============================================================================
def get_banner_file(banner_name: str, category: str = "banners") -> discord.File | None:
    banner_dir = ASSETS_DIR / "gacha" / category
    if path := next(banner_dir.glob(f"{banner_name}.*"), None):
        return discord.File(path, filename=path.name)
    return None

def get_card_image_file(card_data: dict) -> discord.File | None:
    """Gets cached card image path from disk once, then generates fresh discord.Files instantly."""
    card_id = card_data.get("id")

    # Cache path lookup on first request
    if card_id not in CARD_PATH_CACHE:
        school = card_data.get("school", "").lower().replace(" ", "_")
        img_filename = card_data.get("image_file")
        if school and img_filename:
            image_path = ASSETS_DIR / "gacha" / "cards" / school / img_filename
            CARD_PATH_CACHE[card_id] = image_path if image_path.exists() else None
        else:
            CARD_PATH_CACHE[card_id] = None

    cached_path = CARD_PATH_CACHE.get(card_id)
    if cached_path:
        return discord.File(cached_path, filename=cached_path.name)
    return None

# ==============================================================================
# 3. EMBED & COURT DISPLAY BUILDERS
# ==============================================================================
def calculate_team_context(lineup_data: dict, user_cards: list[dict]) -> dict:
    """Calculates core team power using fully boosted stats, active bonds, and synergy school."""
    boosted_stats_map = apply_lineup_boosts(lineup_data, user_cards)

    card_lookup = {c["id"]: c for c in user_cards}
    team_power = 0
    starting_card_ids = set()
    school_counts = defaultdict(int)

    for slot, stats in boosted_stats_map.items():
        team_power += sum(stats.values())  # Sums the *boosted* stats instead of raw base stats!

        cid = lineup_data.get(slot)
        if cid and cid in card_lookup:
            starting_card_ids.add(cid)
            school_counts[card_lookup[cid]["school"]] += 1

    # Bonds check
    active_bonds_count = 0
    for bond in BONDS_BY_ID.values():
        req_players = set(bond.get("required_players", []))
        if req_players and req_players.issubset(starting_card_ids):
            active_bonds_count += 1

    # Synergy check
    active_synergy_school = None
    for school, count in school_counts.items():
        if count >= MIN_SYNERGY_PLAYERS:
            active_synergy_school = school
            break

    return {
        "team_power": team_power,
        "active_bonds_count": active_bonds_count,
        "active_synergy_school": active_synergy_school
    }

def format_lineup_court_display(lineup_data: dict, user_cards: list[dict], lineup_index: int = 1) -> str:
    """Builds the ASCII court layout and summary text."""
    ctx = calculate_team_context(lineup_data, user_cards)
    lineup_name = lineup_data.get("lineup_name", f"Lineup {lineup_index}")

    # Check setter specialty for the UI summary bar
    setter_cid = lineup_data.get("setter")
    setter_card = CARDS_BY_ID.get(setter_cid) if setter_cid else None
    spec_id = setter_card["specialty_id"] if setter_card else None
    active_specialty_name = SPECIALTIES_BY_ID[spec_id]["name"] if spec_id else None

    # Build summary string
    meta_parts = [f"Power: {ctx['team_power']:,}"]
    if active_specialty_name:
        meta_parts.append(active_specialty_name)
    if ctx['active_bonds_count'] > 0:
        meta_parts.append(f"{ctx['active_bonds_count']} Bond{'s' if ctx['active_bonds_count'] > 1 else ''}")

    summary_str = " • ".join(meta_parts)

    # Synergy description lookup specifically for the UI display
    if ctx['active_synergy_school']:
        matched_synergy = next(
            (s for s in SYNERGIES_BY_ID.values() if s.get("school", "").lower() == ctx['active_synergy_school'].lower()),
            None
        )
        syn_desc = matched_synergy.get("description", "Active Synergy") if matched_synergy else "Active Synergy"
        active_synergy_line = f"*🏫 Synergy ({ctx['active_synergy_school']})*\n*{syn_desc}*"
    else:
        active_synergy_line = f"*🏫 Synergy (None)*\n*Needs at least {MIN_SYNERGY_PLAYERS} starter players of the same school*"

    def get_slot_short(key: str) -> str:
        card_id = lineup_data.get(key)
        if card_id and card_id in CARDS_BY_ID:
            return get_short_name(CARDS_BY_ID[card_id]["name"])
        return "*Empty*"

    s = get_slot_short("setter")
    op = get_slot_short("opposite")
    mb1 = get_slot_short("middle_blocker_1")
    mb2 = get_slot_short("middle_blocker_2")
    ws1 = get_slot_short("wing_spiker_1")
    ws2 = get_slot_short("wing_spiker_2")
    l = get_slot_short("libero")
    ps = get_slot_short("pinch_server")

    # 4. Return just the formatted content string
    content = (
        f"### 🎽 {lineup_name}\n"
        f"*{summary_str}*\n"
        f"\n"
        f"{active_synergy_line}\n"
        f"```text\n"
        f"{'[L]':<13} {'[Pinch Server]'}\n"
        f"{l:<13} {ps}\n\n"
        f"{'[S]':<13} {'[MB2]':<13} {'[WS2]'}\n"
        f"{s:<13} {mb2:<13} {ws2}\n\n"
        f"{'[WS1]':<13} {'[MB1]':<13} {'[OP]'}\n"
        f"{ws1:<13} {mb1:<13} {op}\n"
        f"```"
    )

    return content

def create_card_embed(
    card_data: dict,
    extra_stats: dict | None = None,
    show_level_info: bool = True
) -> discord.Embed:
    color_val = int(card_data.get("embed_color", "0xFF6600"), 16)
    rarity = card_data.get("rarity", "R")
    name = card_data.get("name", "Unknown Player")
    quote = card_data.get("quote", "")

    rarity_emoji = RARITY_EMOJIS.get(rarity, "🔵")

    embed = discord.Embed(
        title=f"{rarity_emoji} *({rarity})* {name}",
        description=f"*{quote}*" if quote else None,
        color=color_val
    )

    pos = card_data.get("position", "N/A")
    school = card_data.get("school", "N/A")
    level = card_data.get("level", 1)
    resonance = card_data.get("resonance", 0)

    extra_info = ""
    if show_level_info:
        resonance_str = format_resonance_stars(resonance)
        extra_info = f"\nLevel:    {level:<5}  Resonance: {resonance_str}"

    info_text = (
        "```text\n"
        f"Position: {pos:<5}  School: {school}"
        f"{extra_info}\n"
        "```"
    )
    embed.add_field(name="👤 Player Info", value=info_text, inline=False)

    stats = extra_stats or card_data.get("base_stats", {})
    total_power = sum(stats.get(key, 0) for key in ("spike", "block", "set", "serve", "receive"))
    stats_text = (
        "```text\n"
        f"Total Power: {total_power}\n"
        f"Spike:   {stats.get('spike', 0):<3}  Block: {stats.get('block', 0)}\n"
        f"Set:     {stats.get('set', 0):<3}  Serve: {stats.get('serve', 0)}\n"
        f"Receive: {stats.get('receive', 0):<3}\n"
        "```"
    )
    embed.add_field(name="📊 Player Stats", value=stats_text, inline=False)

    img_filename = card_data.get("image_file")
    if img_filename:
        embed.set_image(url=f"attachment://{img_filename}")

    return embed

def add_card_metadata_fields(
    embed: discord.Embed,
    target_card: dict,
    active_lineup_card_ids: set[str] | None = None
) -> discord.Embed:
    """Appends setter specialty and school bonds to a card embed if applicable."""
    if not target_card:
        return embed

    # Show the setter's specialty only if the card's position is Setter ('S')
    if target_card.get("position") == "S":
        spec_id = target_card.get("specialty_id")
        specialty = SPECIALTIES_BY_ID.get(spec_id) if spec_id else None

        if specialty:
            embed.add_field(
                name=f"🎯 Setter Specialty: {specialty['name']}",
                value=specialty["description"],
                inline=False
            )

    # Show school bonds only if card rarity is SR or SSR
    if target_card.get("rarity") in ("SR", "SSR"):
        card_id = target_card.get("id")
        card_bonds = [
            bond for bond in BONDS_BY_ID.values()
            if card_id in bond.get("required_players", [])
        ]

        is_match_mode = active_lineup_card_ids is not None
        title = "🤝 Active Bonds" if is_match_mode else "🤝 Bonds"

        applicable_bonds = (
            [b for b in card_bonds if set(b.get("required_players", [])).issubset(active_lineup_card_ids)]
            if is_match_mode else card_bonds
        )

        if applicable_bonds:
            bond_lines = []
            for bond in applicable_bonds:
                req_ids = bond.get("required_players", [])
                req_names = [
                    get_short_name(CARDS_BY_ID.get(rid, {}).get("name"))
                    for rid in req_ids if rid != card_id and rid in CARDS_BY_ID
                ]
                req_str = f"with {' + '.join(req_names)}" if req_names else ""
                bond_lines.append(f"• **{bond['name']}** *({req_str})*\n  {bond['description']}")

            embed.add_field(name=title, value="\n".join(bond_lines), inline=False)
        else:
            embed.add_field(name=title, value="*No active bonds in this lineup.*", inline=False)

    return embed

# ==============================================================================
# 4. REUSABLE UI COMPONENTS & BASE VIEWS
# ==============================================================================
class LineupSelectMenu(discord.ui.Select):
    def __init__(self, current_lineup: int = 1, lineup_names: dict[int, str] = None):
        lineup_names = lineup_names or {}
        options = []

        for i in range(1, MAX_LINEUPS + 1):
            name = lineup_names.get(i, DEFAULT_LINEUP_NAME.format(i))
            options.append(
                discord.SelectOption(
                    label=name,
                    value=str(i),
                    default=(current_lineup == i),
                    emoji="🎽"
                )
            )

        super().__init__(placeholder="Select Lineup...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        await lock_view_ui(self.view, interaction)
        self.view.selected_lineup_index = int(self.values[0])
        await self.view.update_screen(interaction)


class BaseCardRosterView(discord.ui.View):
    PAGE_SIZE = 25

    def __init__(self, user_id: int, user_cards: list[dict], selected_card_id: str | None = None):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.user_cards = user_cards
        self.selected_position = "ALL"
        self.selected_card_id = selected_card_id
        self.current_page = 0

    def get_filtered_cards(self) -> list[dict]:
        if self.selected_position == "ALL":
            return self.user_cards
        return [c for c in self.user_cards if c.get("position") == self.selected_position]

    def _get_target_card(self, filtered_cards: list[dict] | None = None) -> dict | None:
        """Helper to get the currently selected card from filtered results."""
        if filtered_cards is None:
            filtered_cards = self.get_filtered_cards()
        return next((c for c in filtered_cards if c["id"] == self.selected_card_id), None)

    def get_paged_cards(self, filtered_cards: list[dict]) -> tuple[list[dict], int]:
        total_cards = len(filtered_cards)
        max_pages = max(1, (total_cards + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self.current_page >= max_pages:
            self.current_page = max_pages - 1
        start_idx = self.current_page * self.PAGE_SIZE
        end_idx = start_idx + self.PAGE_SIZE
        return filtered_cards[start_idx:end_idx], max_pages

    def _validate_and_sync_selection(self, page_cards: list[dict]):
        """Ensures selected_card_id points to a valid card on the current page."""
        if page_cards:
            if not self.selected_card_id or not any(c["id"] == self.selected_card_id for c in page_cards):
                self.selected_card_id = page_cards[0]["id"]
        else:
            self.selected_card_id = None

    def _get_target_card_attachments(self) -> list[discord.File]:
        """Helper to get image attachments for the currently selected card."""
        target_card = self._get_target_card()
        image_file = get_card_image_file(target_card) if target_card else None
        return [image_file] if image_file else []

    def _setup_pagination(self) -> tuple[list[dict], list[dict], int, str]:
        """Clears items, filters cards, gets current page slice, syncs selection, and builds page info."""
        self.clear_items()
        filtered_cards = self.get_filtered_cards()
        page_cards, max_pages = self.get_paged_cards(filtered_cards)
        self._validate_and_sync_selection(page_cards)
        page_info = f"(Page {self.current_page + 1}/{max_pages})" if max_pages > 1 else ""
        return filtered_cards, page_cards, max_pages, page_info

    async def _navigate_page(self, interaction: discord.Interaction, direction: int):
        """Helper to handle page switching forward (+1) or backward (-1)."""
        filtered_cards = self.get_filtered_cards()
        _, max_pages = self.get_paged_cards(filtered_cards)
        new_page = self.current_page + direction

        if 0 <= new_page < max_pages:
            await lock_view_ui(self, interaction)
            self.current_page = new_page
            page_cards, _ = self.get_paged_cards(filtered_cards)
            if page_cards:
                self.selected_card_id = page_cards[0]["id"]
            await self.update_screen(interaction)

    async def _handle_prev_page(self, interaction: discord.Interaction):
        await self._navigate_page(interaction, -1)

    async def _handle_next_page(self, interaction: discord.Interaction):
        await self._navigate_page(interaction, 1)

    async def _handle_back(self, interaction: discord.Interaction):
        from ui.gacha import UserHomeView

        await lock_view_ui(self, interaction)
        home_view = UserHomeView(self.user_id)
        embed = await home_view.build_embed(interaction)
        await interaction.edit_original_response(content=None, embed=embed, view=home_view, attachments=[])


class PositionFilterSelectMenu(discord.ui.Select):
    def __init__(self, user_cards: list[dict], current_filter: str = "ALL", row: int = 0):
        # Define all possible position configurations with labels and emojis
        all_position_meta = {
            "S": {"label": "Setter (S)", "emoji": "🎯"},
            "OP": {"label": "Opposite Hitter (OP)", "emoji": "💥"},
            "WS": {"label": "Wing Spiker (WS)", "emoji": "🗡️"},
            "MB": {"label": "Middle Blocker (MB)", "emoji": "🧱"},
            "L": {"label": "Libero (L)", "emoji": "🛡️"},
        }

        # Find which positions actually exist in the user's cards
        available_positions = {c.get("position") for c in user_cards if c.get("position")}

        # Always include "All Positions" if there are cards
        options = [
            discord.SelectOption(label="All Positions", value="ALL", default=(current_filter == "ALL"), emoji="🗂️")
        ]

        # Add only positions that have at least one card
        for pos, meta in all_position_meta.items():
            if pos in available_positions:
                options.append(
                    discord.SelectOption(
                        label=meta["label"],
                        value=pos,
                        default=(current_filter == pos),
                        emoji=meta["emoji"]
                    )
                )

        super().__init__(placeholder="Filter by Position...", min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        await lock_view_ui(self.view, interaction)
        self.view.selected_position = self.values[0]
        self.view.current_page = 0
        filtered = self.view.get_filtered_cards()
        if filtered:
            self.view.selected_card_id = filtered[0]["id"]
        await self.view.update_screen(interaction)


class CardSelectMenu(discord.ui.Select):
    def __init__(self, page_cards: list[dict], selected_card_id: str | None = None, page_info: str = "",
                 custom_placeholder: str = "Select a player...", row: int = 1):
        options = []
        for card in page_cards:
            is_default = (card["id"] == selected_card_id)
            res_str = format_resonance_badge(card["resonance"])

            options.append(
                discord.SelectOption(
                    label=f"{card['name']} (Lv.{card['level']})",
                    description=f"{card['rarity']} | {res_str} | Pos: {card['position']} | {card['school']}",
                    value=card["id"],
                    default=is_default
                )
            )

        # Fallback dummy option if there are no cards to prevent Discord API 400 errors when disabled
        if not options:
            options.append(
                discord.SelectOption(
                    label="No players available",
                    value="NONE",
                    default=True
                )
            )

        placeholder = f"{custom_placeholder} {page_info}" if page_info else custom_placeholder

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, disabled=(len(page_cards) == 0), row=row)

    async def callback(self, interaction: discord.Interaction):
        await lock_view_ui(self.view, interaction)
        self.view.selected_card_id = self.values[0]
        await self.view.update_screen(interaction)