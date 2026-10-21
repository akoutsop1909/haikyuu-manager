from pathlib import Path
import discord

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"

RARITY_EMOJIS = {"S3": "🔵", "S4": "🟣", "S5": "🟡"}

# Global path cache to make card image lookups instant across all views
CARD_PATH_CACHE: dict[str, Path | None] = {}

# ==============================================================================
# 1. GENERAL UTILITY FUNCTIONS
# ==============================================================================
async def lock_view_ui(view: discord.ui.View, interaction: discord.Interaction):
    """Disables only the buttons on the view and immediately edits the message to prevent race conditions."""
    for child in view.children:
        if isinstance(child, discord.ui.Button):
            child.disabled = True
    if not interaction.response.is_done():
        await interaction.response.edit_message(view=view)

def format_number(val: int) -> str:
    """Formats large integers into compact strings (e.g., 100M, 10.5K, 1,200)."""
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f}B".replace(".0B", "B")
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M".replace(".0M", "M")
    if val >= 10_000:
        return f"{val / 1_000:.1f}K".replace(".0K", "K")
    return f"{val:,}"

def get_short_name(full_name: str) -> str:
    """Formats full player name into 'F. LastName' (e.g., 'Tobio Kageyama' -> 'T. Kageyama')."""
    parts = full_name.split()
    if len(parts) > 1:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"
    return full_name

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

def format_resonance_stars(resonance_level: int, max_resonance: int = 5) -> str:
    """Formats integer resonance into star icons: ★★★☆☆ """
    filled_stars = "★" * resonance_level
    empty_stars = "☆" * (max_resonance - resonance_level)
    return f"{filled_stars}{empty_stars}"

def create_card_embed(
    card_data: dict,
    extra_stats: dict | None = None,
    override_title: str | None = None,
    show_level_info: bool = True
) -> discord.Embed:
    color_val = int(card_data.get("embed_color", "0xFF6600"), 16)
    rarity = card_data.get("rarity", "S3")
    name = card_data.get("name", "Unknown Player")
    quote = card_data.get("quote", "")

    rarity_emoji = RARITY_EMOJIS.get(rarity, "🔵")

    embed = discord.Embed(
        title=override_title or f"{rarity_emoji} {rarity} {name}",
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

# ==============================================================================
# 2. REUSABLE UI VIEWS & MENUS
# ==============================================================================
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

    async def _handle_prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            await lock_view_ui(self, interaction)

            self.current_page -= 1
            filtered_cards = self.get_filtered_cards()
            page_cards, _ = self.get_paged_cards(filtered_cards)
            if page_cards:
                self.selected_card_id = page_cards[0]["id"]
            await self.update_screen(interaction)

    async def _handle_next_page(self, interaction: discord.Interaction):
        filtered_cards = self.get_filtered_cards()
        _, max_pages = self.get_paged_cards(filtered_cards)
        if self.current_page < max_pages - 1:
            await lock_view_ui(self, interaction)

            self.current_page += 1
            page_cards, _ = self.get_paged_cards(filtered_cards)
            if page_cards:
                self.selected_card_id = page_cards[0]["id"]
            await self.update_screen(interaction)

    async def _handle_back(self, interaction: discord.Interaction):
        from ui.gacha import UserHomeView

        await lock_view_ui(self, interaction)
        embed = await UserHomeView.build_embed(interaction)
        await interaction.edit_original_response(content=None, embed=embed, view=UserHomeView(self.user_id), attachments=[])


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
            discord.SelectOption(label="All Positions", value="ALL", default=(current_filter == "ALL"), emoji="🏐")
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
            resonance = card["resonance"]
            res_str = f"★{resonance}" if resonance > 0 else "★0"

            options.append(
                discord.SelectOption(
                    label=f"{card['name']} (Lv.{card['level']})",
                    description=f"{card['rarity']} | {res_str} | Pos: {card['position']} | {card['school']}",
                    value=card["id"],
                    default=is_default
                )
            )

        placeholder = f"{custom_placeholder} {page_info}" if page_info else custom_placeholder

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, disabled=(len(page_cards) == 0), row=row)

    async def callback(self, interaction: discord.Interaction):
        await lock_view_ui(self.view, interaction)
        self.view.selected_card_id = self.values[0]
        await self.view.update_screen(interaction)