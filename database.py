# ==============================================================================
# SETUP & CONFIGURATION
# ==============================================================================
from collections import defaultdict
import os
import json
import logging
from pathlib import Path
import random

import asyncpg
from pydantic import BaseModel, Field

# Connection pool setup
pool: asyncpg.Pool | None = None

logger = logging.getLogger(__name__)

# Define project root relative to this file and target paths safely
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "haikyuu_config.json"
DATA_DIR = PROJECT_ROOT / "data"

# Ensure required subdirectories exist
(DATA_DIR / "cards").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "mechanics").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "mechanics" / "bonds").mkdir(parents=True, exist_ok=True)

# Check for required files
if not CONFIG_PATH.exists():
    logger.critical(f"Missing config file at: {CONFIG_PATH}")
    raise SystemExit(1)

# Load game config once into memory on startup
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# 1. Load Cards
CARDS_BY_ID = {}
CARDS_BY_RARITY = {"S3": [], "S4": [], "S5": []}
BIRTHDAYS_BY_DATE = defaultdict(list)

for json_file in (DATA_DIR / "cards").glob("*.json"):
    with open(json_file, "r", encoding="utf-8") as f:
        for card in json.load(f):
            CARDS_BY_ID[card["id"]] = card
            CARDS_BY_RARITY[card["rarity"]].append(card["id"])
            BIRTHDAYS_BY_DATE[card["birthday"]].append(card)

def _load_json_items(file_path: Path, target_dict: dict, item_name: str):
    """Helper to safely load list-based JSON config files into a dictionary by 'id'."""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for item in json.load(f):
                    target_dict[item["id"]] = item
        except Exception as e:
            logger.error(f"Failed to parse {item_name} file {file_path.name}: {e}")
    else:
        logger.warning(f"Missing {item_name} file at: {file_path}")

# 2. Load Mechanics (Specialties)
SPECIALTIES_BY_ID = {}
_load_json_items(DATA_DIR / "mechanics" / "specialties.json", SPECIALTIES_BY_ID, "specialties")

# 3. Load Mechanics (Synergies)
SYNERGIES_BY_ID = {}
_load_json_items(DATA_DIR / "mechanics" / "synergies.json", SYNERGIES_BY_ID, "synergies")

# 4. Load Mechanics (Bonds - Directory-based)
BONDS_BY_ID = {}
bonds_dir = DATA_DIR / "mechanics" / "bonds"

if bonds_dir.exists():
    for json_file in bonds_dir.glob("*.json"):
        _load_json_items(json_file, BONDS_BY_ID, "bond")
else:
    logger.warning(f"Missing bonds directory at: {bonds_dir}")

STARTER_PACK = CONFIG.get("STARTER_PACK", {})
DAILY_REWARD = CONFIG.get("DAILY_REWARD", {})
BIRTHDAY_REWARD = CONFIG.get("BIRTHDAY_REWARD", {})
SCOUT_CONFIG = CONFIG.get("SCOUT", {})
TRAINING_CONFIG = CONFIG.get("TRAINING", {})
TOKYO_TRIP_CONFIG = CONFIG.get("TOKYO_TRIP", {})
ADMIN_PACK = CONFIG.get("ADMIN_PACK", {})

# ==============================================================================
# DATA MODELS
# ==============================================================================
class DailyClaim(BaseModel):
    claimed: bool = False
    scout_coins: int = Field(default=0, ge=0)
    practice_balls: int = Field(default=0, ge=0)
    total_logins: int = Field(default=0, ge=0)
    next_reset: int

class BirthdayClaim(BaseModel):
    claimed: bool = False
    birthdays_today: list[str] = []
    birthdays_tomorrow: list[str] = []
    bonus_names: list[str] = []
    scout_coins: int = Field(default=0, ge=0)
    practice_balls: int = Field(default=0, ge=0)

class Inventory(BaseModel):
    scout_coins: int = Field(default=0, ge=0)  # ge=0 guarantees non-negative balances
    practice_balls: int = Field(default=0, ge=0)
    sports_drinks: int = Field(default=0, ge=0)
    drink_vouchers: int = Field(default=0, ge=0)

# ==============================================================================
# 1. DATABASE SETUP & CONNECTION HELPERS
# ==============================================================================
async def init_db_pool():
    global pool
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.critical("DATABASE_URL must be set in .env")
        raise SystemExit(1)

    pool = await asyncpg.create_pool(database_url)

    async with pool.acquire() as conn:
        # Create Users Table (Note: user_id is BIGINT for Discord IDs)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,

                scout_coins INT DEFAULT 0 CHECK (scout_coins >= 0),
                practice_balls INT DEFAULT 0 CHECK (practice_balls >= 0),
                sports_drinks INT DEFAULT 0 CHECK (sports_drinks >= 0),
                drink_vouchers INT DEFAULT 0 CHECK (drink_vouchers >= 0),

                last_daily_claim TIMESTAMPTZ,
                last_birthday_claim TIMESTAMPTZ,
                total_logins INT DEFAULT 0,

                tokyo_trip_start TIMESTAMPTZ,

                match_wins INT DEFAULT 0,
                current_streak INT DEFAULT 0,
                highest_streak INT DEFAULT 0,

                totc_weekly_score INT DEFAULT 0,
                totc_highest_daily_score INT DEFAULT 0,
                totc_days_participated INT DEFAULT 0,

                interhigh_floor INT DEFAULT 1,
                karasuno_nekoma_floor INT DEFAULT 1,
                aoba_shiratorizawa_floor INT DEFAULT 1,
                date_fuku_inari_floor INT DEFAULT 1,
                johze_hebi_waku_floor INT DEFAULT 1
            );
        """)

        # Create Cards Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_cards (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                card_id TEXT NOT NULL,

                level INT DEFAULT 1,
                resonance INT DEFAULT 0,

                is_on_trip BOOLEAN DEFAULT FALSE,
                exhausted_until TIMESTAMPTZ DEFAULT NULL,

                UNIQUE(user_id, card_id)
            );
        """)

        # Create Teams Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_teams (
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                lineup_number INT NOT NULL,
                lineup_name TEXT DEFAULT 'Lineup',

                setter TEXT,
                opposite TEXT,
                wing_spiker_1 TEXT,
                wing_spiker_2 TEXT,
                middle_blocker_1 TEXT,
                middle_blocker_2 TEXT,
                libero TEXT,
                pinch_server TEXT,

                PRIMARY KEY (user_id, lineup_number)
            );
        """)

# ==============================================================================
# 2. USER ACCOUNT MANAGEMENT
# ==============================================================================
async def user_exists(user_id: int) -> bool:
    """Checks if a user record exists in the database."""
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
        return val is not None


async def register_user(user_id: int) -> bool:
    """Registers a new user if they don't exist."""
    if await user_exists(user_id):
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Insert user
            await conn.execute(
                "INSERT INTO users (user_id, scout_coins, practice_balls) VALUES ($1, $2, $3)",
                user_id, STARTER_PACK["scout_coins"], STARTER_PACK["practice_balls"]
            )

            # Insert starter cards
            cards_to_insert = [(user_id, cid) for cid in STARTER_PACK["cards"]]
            await conn.executemany(
                "INSERT INTO user_cards (user_id, card_id) VALUES ($1, $2)",
                cards_to_insert
            )

            # 2. Map positions dynamically
            slots = {
                "S": ["setter"],
                "OP": ["opposite"],
                "WS": ["wing_spiker_1", "wing_spiker_2"],
                "MB": ["middle_blocker_1", "middle_blocker_2"],
                "L": ["libero"],
            }

            team = {}
            bench_candidates = []

            for cid in STARTER_PACK["cards"]:
                pos = CARDS_BY_ID.get(cid, {}).get("position")
                if pos in slots and slots[pos]:
                    team[slots[pos].pop(0)] = cid
                else:
                    # Collect unmapped starter cards (e.g., extra MB/WS) for Pinch Server
                    bench_candidates.append(cid)

            # Assign the first available extra card as the Pinch Server
            if bench_candidates:
                team["pinch_server"] = bench_candidates[0]

            # Insert Lineup 1 into Database
            await conn.execute(
                """
                INSERT INTO user_teams (
                    user_id, lineup_number, lineup_name, setter, opposite, 
                    wing_spiker_1, wing_spiker_2, middle_blocker_1, middle_blocker_2, libero, pinch_server
                )
                VALUES ($1, 1, 'Starter Team', $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                user_id,
                team.get("setter"),
                team.get("opposite"),
                team.get("wing_spiker_1"),
                team.get("wing_spiker_2"),
                team.get("middle_blocker_1"),
                team.get("middle_blocker_2"),
                team.get("libero"),
                team.get("pinch_server"),
            )

    return True


async def delete_user(user_id: int) -> bool:
    """Deletes a user and cascades deletion to their cards and teams."""
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)
        # asyncpg returns status string formatted as "DELETE <count>"
        rows_deleted = int(status.split(" ")[1])
        return rows_deleted > 0

# ==============================================================================
# 3. INVENTORY, CARDS & CLAIMS
# ==============================================================================
async def get_inventory(user_id: int) -> Inventory:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT scout_coins, practice_balls, sports_drinks, drink_vouchers 
            FROM users WHERE user_id = $1
            """,
            user_id
        )

        if row:
            return Inventory(**dict(row))

        return Inventory()


async def get_user_cards(user_id: int) -> list[dict]:
    """Fetches all cards owned by the user, joined with their card meta info, levels, resonance, and trip status."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT card_id, level, resonance, is_on_trip, exhausted_until
            FROM user_cards
            WHERE user_id = $1
            ORDER BY level DESC
            """,
            user_id
        )

    user_cards = []
    for row in rows:
        cid = row["card_id"]
        if cid in CARDS_BY_ID:
            card_info = CARDS_BY_ID[cid].copy()
            level = row["level"]
            resonance = row["resonance"]
            rarity = card_info.get("rarity", "S3")

            card_info["level"] = level
            card_info["resonance"] = resonance
            card_info["is_on_trip"] = row["is_on_trip"]
            card_info["exhausted_until"] = row["exhausted_until"]

            # Attach fully scaled combat stats (Level + Resonance)
            card_info["scaled_stats"] = calculate_card_stats(
                card_info.get("base_stats", {}),
                level,
                rarity,
                resonance
            )
            user_cards.append(card_info)

    return user_cards


async def claim_daily(user_id: int) -> DailyClaim:
    claimed = False
    scout_coins = 0
    practice_balls = 0
    total_logins = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Dynamically uses the PostgreSQL database's configured timezone
            row_time = await conn.fetchrow("""
                SELECT 
                    NOW() AS db_now,
                    EXTRACT(EPOCH FROM (
                        date_trunc('day', NOW() AT TIME ZONE current_setting('TimeZone')) + INTERVAL '1 day'
                    ) AT TIME ZONE current_setting('TimeZone'))::BIGINT AS next_reset_ts;
            """)

            db_now = row_time["db_now"]
            next_reset_timestamp = int(row_time["next_reset_ts"])

            # Fetch user's last claim
            row = await conn.fetchrow(
                "SELECT last_daily_claim, total_logins FROM users WHERE user_id = $1",
                user_id
            )

            if row:
                last_claim, total_logins = row["last_daily_claim"], row["total_logins"] or 0

                can_claim = True if last_claim is None else db_now.date() > last_claim.date()

                if can_claim:
                    scout_coins = DAILY_REWARD["scout_coins"]
                    practice_balls = DAILY_REWARD["practice_balls"]
                    total_logins += 1
                    claimed = True

                    await conn.execute("""
                        UPDATE users 
                        SET scout_coins = scout_coins + $1,
                            practice_balls = practice_balls + $2,
                            total_logins = total_logins + 1,
                            last_daily_claim = $3
                        WHERE user_id = $4
                    """, scout_coins, practice_balls, db_now, user_id)

    return DailyClaim(
        claimed=claimed,
        scout_coins=scout_coins,
        practice_balls=practice_balls,
        total_logins=total_logins,
        next_reset=next_reset_timestamp,
    )


async def claim_birthday(user_id: int) -> BirthdayClaim:
    total_coins = 0
    total_balls = 0
    birthdays_today = []
    birthdays_tomorrow = []
    bonus_names = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Fetch current database time, today's date, AND tomorrow's date
            row = await conn.fetchrow("""
                SELECT 
                    NOW() AS db_now,
                    TO_CHAR(NOW() AT TIME ZONE current_setting('TimeZone'), 'MM-DD') AS db_today_mm_dd,
                    TO_CHAR((NOW() AT TIME ZONE current_setting('TimeZone')) + INTERVAL '1 day', 'MM-DD') AS db_tomorrow_mm_dd,
                    last_birthday_claim 
                FROM users WHERE user_id = $1
            """, user_id)

            db_now = row["db_now"]
            today_str = row["db_today_mm_dd"]
            tomorrow_str = row["db_tomorrow_mm_dd"]
            last_claim = row["last_birthday_claim"]

            # 2. Check for tomorrow's birthdays (Direct Lookup)
            seen_upcoming = set()
            for card_data in BIRTHDAYS_BY_DATE.get(tomorrow_str, []):
                cname = card_data.get("name")
                if cname not in seen_upcoming:
                    seen_upcoming.add(cname)
                    birthdays_tomorrow.append(cname)

            # 3. Check if user already claimed today
            can_claim = True if last_claim is None else db_now.date() > last_claim.date()

            # 4. Check for today's birthdays (Direct Lookup)
            today_cards = BIRTHDAYS_BY_DATE.get(today_str, [])

            if not can_claim or not today_cards:
                return BirthdayClaim(claimed=False, birthdays_tomorrow=birthdays_tomorrow)

            # 5. Fetch owned cards to check for character ownership
            owned_rows = await conn.fetch(
                "SELECT card_id FROM user_cards WHERE user_id = $1", user_id
            )
            owned_ids = {r["card_id"] for r in owned_rows}

            # 6. Process character rewards
            seen_names = set()
            for card_data in today_cards:
                cname = card_data["name"]
                if cname in seen_names:
                    continue
                seen_names.add(cname)
                birthdays_today.append(cname)

                coins = BIRTHDAY_REWARD["base"]["scout_coins"]
                balls = BIRTHDAY_REWARD["base"]["practice_balls"]

                if card_data["id"] in owned_ids:
                    rarity = card_data.get("rarity", "S3")
                    bonus_cfg = BIRTHDAY_REWARD["owner_bonus_by_rarity"].get(
                        rarity, BIRTHDAY_REWARD["owner_bonus_by_rarity"]["S3"]
                    )

                    coins += bonus_cfg["scout_coins"]
                    balls += bonus_cfg["practice_balls"]
                    bonus_names.append(cname)

                total_coins += coins
                total_balls += balls

            # 7. Award resources and update claim timestamp
            await conn.execute("""
                UPDATE users 
                SET scout_coins = scout_coins + $1,
                    practice_balls = practice_balls + $2,
                    last_birthday_claim = $3
                WHERE user_id = $4
            """, total_coins, total_balls, db_now, user_id)

    return BirthdayClaim(
        claimed=True,
        birthdays_today=birthdays_today,
        birthdays_tomorrow=birthdays_tomorrow,
        bonus_names=bonus_names,
        scout_coins=total_coins,
        practice_balls=total_balls,
    )

# ==============================================================================
# 4. SCOUT & TRAINING SYSTEMS
# ==============================================================================
async def perform_scout(user_id: int, scout_count: int) -> list[dict]:
    cost_per_pull = SCOUT_CONFIG["cost_per_pull"]
    max_res = SCOUT_CONFIG["max_resonance"]
    voucher_rates = SCOUT_CONFIG["overflow_vouchers_by_rarity"]

    cost = scout_count * cost_per_pull

    rarity_weights = SCOUT_CONFIG["rarity_weights"]
    rarities = list(rarity_weights.keys())
    weights = list(rarity_weights.values())

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Check current balance
            coins = await conn.fetchval("SELECT scout_coins FROM users WHERE user_id = $1", user_id)
            if coins is None or coins < cost:
                return []

            # 2. Perform weighted gacha pulls
            pulled_cids = []
            for _ in range(scout_count):
                chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
                pool_cards = CARDS_BY_RARITY.get(chosen_rarity) or list(CARDS_BY_ID.keys())
                pulled_cids.append(random.choice(pool_cards))

            # 3. Deduct coins
            await conn.execute("UPDATE users SET scout_coins = scout_coins - $1 WHERE user_id = $2", cost, user_id)

            # 4. Fetch existing card details owned by the user
            rows = await conn.fetch("SELECT card_id, resonance FROM user_cards WHERE user_id = $1", user_id)
            owned_cards = {r["card_id"]: r["resonance"] for r in rows}

            # 5. Process pulls with Resonance Cap & Voucher Compensation
            overflow_vouchers_earned = 0
            scout_results = []

            for cid in pulled_cids:
                card_info = CARDS_BY_ID[cid].copy()
                rarity = card_info.get("rarity", "S3")

                if cid in owned_cards:
                    current_res = owned_cards[cid]
                    if current_res < max_res:
                        new_res = current_res + 1
                        await conn.execute("""
                            UPDATE user_cards 
                            SET resonance = resonance + 1 
                            WHERE user_id = $1 AND card_id = $2
                        """, user_id, cid)
                        owned_cards[cid] = new_res
                        card_info["status"] = "DUPLICATE"
                        card_info["new_resonance"] = new_res
                    else:
                        drink_vouchers = voucher_rates.get(rarity, 1)
                        overflow_vouchers_earned += drink_vouchers
                        card_info["status"] = "OVERFLOW"
                        card_info["drink_vouchers"] = drink_vouchers
                else:
                    await conn.execute("""
                        INSERT INTO user_cards (user_id, card_id) 
                        VALUES ($1, $2)
                    """, user_id, cid)
                    owned_cards[cid] = 0
                    card_info["status"] = "NEW"
                    card_info["new_resonance"] = 0

                scout_results.append(card_info)

            # Deposit total vouchers earned from maxed overflow duplicates
            if overflow_vouchers_earned > 0:
                await conn.execute("""
                    UPDATE users 
                    SET drink_vouchers = drink_vouchers + $1 
                    WHERE user_id = $2
                """, overflow_vouchers_earned, user_id)

            return scout_results


def calculate_card_stats(base_stats: dict, level: int, rarity: str = "S3", resonance: int = 0) -> dict:
    """Calculates final stats based on current level, rarity-specific growth, and resonance rank."""
    boost_rate = TRAINING_CONFIG["stat_boost_per_level"].get(rarity, 0.020)

    # Fetch per-rarity resonance rate from config (e.g. S3: 0.03, S4: 0.04, S5: 0.05)
    res_boost_rate = TRAINING_CONFIG["stat_boost_per_resonance"].get(rarity, 0.03)

    # Multiplier formula combining Level + Resonance boost
    level_multiplier = 1.0 + (boost_rate * (level - 1))
    resonance_multiplier = 1.0 + (res_boost_rate * resonance)

    total_multiplier = level_multiplier * resonance_multiplier

    return {
        stat: int(round(value * total_multiplier))
        for stat, value in base_stats.items()
    }


def get_single_level_cost(level: int, rarity: str = "S3") -> int:
    """Calculates the exponential cost to upgrade from `level` to `level + 1` based on card rarity."""
    base_cost = TRAINING_CONFIG["base_cost"]
    growth_rate = TRAINING_CONFIG["cost_growth_rate"]
    multipliers = TRAINING_CONFIG["rarity_cost_multipliers"]

    rarity_mult = multipliers.get(rarity, 1.0)

    # Exponential scaling: base_cost * (growth_rate ^ (level - 1)) * rarity_multiplier
    raw_cost = base_cost * (growth_rate ** (level - 1)) * rarity_mult
    return max(1, int(round(raw_cost)))


def get_level_cost(current_level: int, levels_to_add: int = 1, rarity: str = "S3") -> int:
    """Calculates cumulative cost to upgrade N levels from current level for a given rarity."""
    max_lvl = TRAINING_CONFIG["max_level"]
    actual_levels = min(levels_to_add, max_lvl - current_level)
    if actual_levels <= 0:
        return 0

    total_cost = 0
    for i in range(actual_levels):
        lvl = current_level + i
        total_cost += get_single_level_cost(lvl, rarity)

    return total_cost


async def train_card(user_id: int, card_id: str, levels_to_add: int = 1, max_mode: bool = False) -> bool:
    """Calculates and applies level upgrades using Practice Balls based on TRAINING_CONFIG."""
    max_lvl = TRAINING_CONFIG["max_level"]

    card_meta = CARDS_BY_ID.get(card_id)
    if not card_meta:
        return False

    rarity = card_meta.get("rarity", "S3")

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Fetch user practice balls & current card level
            practice_balls = await conn.fetchval(
                "SELECT practice_balls FROM users WHERE user_id = $1",
                user_id
            )
            current_level = await conn.fetchval(
                "SELECT level FROM user_cards WHERE user_id = $1 AND card_id = $2",
                user_id, card_id
            )

            if practice_balls is None or current_level is None:
                return False

            target_levels = max_lvl - current_level if max_mode else levels_to_add
            levels_gained = 0
            total_cost = 0

            for _ in range(target_levels):
                next_lvl = current_level + levels_gained
                if next_lvl >= max_lvl:
                    break

                cost = get_single_level_cost(next_lvl, rarity)
                if total_cost + cost > practice_balls:
                    break

                total_cost += cost
                levels_gained += 1

            # Fail if no levels could be afforded
            if levels_gained == 0:
                return False

            new_level = current_level + levels_gained

            # Update DB
            await conn.execute(
                "UPDATE users SET practice_balls = practice_balls - $1 WHERE user_id = $2",
                total_cost, user_id
            )
            await conn.execute(
                "UPDATE user_cards SET level = $1 WHERE user_id = $2 AND card_id = $3",
                new_level, user_id, card_id
            )

            return True


async def increase_resonance(user_id: int, card_id: str) -> bool:
    card_meta = CARDS_BY_ID.get(card_id)
    if not card_meta:
        return False

    rarity = card_meta.get("rarity", "S3")
    costs = TRAINING_CONFIG.get("resonance_drink_cost_by_rarity", {"S3": 1, "S4": 3, "S5": 5})
    drink_cost = costs.get(rarity, 1)

    async with pool.acquire() as conn:
        async with conn.transaction():
            sports_drinks = await conn.fetchval(
                "SELECT sports_drinks FROM users WHERE user_id = $1", user_id
            )
            if sports_drinks is None or sports_drinks < drink_cost:
                return False

            await conn.execute(
                "UPDATE users SET sports_drinks = sports_drinks - $1 WHERE user_id = $2",
                drink_cost, user_id
            )
            await conn.execute(
                "UPDATE user_cards SET resonance = resonance + 1 WHERE user_id = $1 AND card_id = $2",
                user_id, card_id
            )
            return True


async def craft_drink(user_id: int) -> bool:
    """Crafts 1 Sports Drink using drink vouchers. Returns True on success."""
    craft_cost = TRAINING_CONFIG["drink_craft_cost"]

    async with pool.acquire() as conn:
        async with conn.transaction():
            drink_vouchers = await conn.fetchval(
                "SELECT drink_vouchers FROM users WHERE user_id = $1", user_id
            )
            if drink_vouchers is None or drink_vouchers < craft_cost:
                return False

            await conn.execute(
                """
                UPDATE users 
                SET drink_vouchers = drink_vouchers - $1,
                    sports_drinks = sports_drinks + 1
                WHERE user_id = $2
                """,
                craft_cost, user_id
            )
            return True

# ==============================================================================
# 5. TEAM & LINEUP MANAGEMENT
# ==============================================================================
async def get_lineups(user_id: int) -> dict[int, dict]:
    """Fetches all lineup data (names and slots) for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM user_teams
            WHERE user_id = $1
            ORDER BY lineup_number ASC
            """,
            user_id
        )
        # Returns a dictionary like {1: {"lineup_name": "Starter Team", "setter": "card_id_1", ...}, 2: {...}}
        return {row["lineup_number"]: dict(row) for row in rows}


async def update_lineup_name(user_id: int, lineup_number: int, lineup_name: str) -> bool:
    """Inserts or updates the custom name of a specific user lineup."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_teams (user_id, lineup_number, lineup_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, lineup_number) 
            DO UPDATE SET lineup_name = EXCLUDED.lineup_name
            """,
            user_id, lineup_number, lineup_name
        )
        return True


async def clear_lineup(user_id: int, lineup_number: int) -> bool:
    """Clears all player slots for a specific lineup."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_teams 
            SET setter = NULL, 
                opposite = NULL, 
                wing_spiker_1 = NULL, 
                wing_spiker_2 = NULL, 
                middle_blocker_1 = NULL, 
                middle_blocker_2 = NULL, 
                libero = NULL, 
                pinch_server = NULL
            WHERE user_id = $1 AND lineup_number = $2
            """,
            user_id, lineup_number
        )
        return "UPDATE" in result


async def remove_pinch(user_id: int, lineup_number: int) -> bool:
    """Removes the pinch server from a specific user lineup."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_teams 
            SET pinch_server = NULL 
            WHERE user_id = $1 AND lineup_number = $2
            """,
            user_id, lineup_number
        )
        return "UPDATE" in result


async def add_to_lineup(user_id: int, lineup_number: int, slot_name: str, card_id: str) -> bool:
    """Assigns a card to any specified lineup slot, clearing it from any other slot in the same lineup."""

    # 1. Whitelist valid slot columns to prevent SQL injection
    valid_slots = {
        "setter", "opposite", "wing_spiker_1", "wing_spiker_2",
        "middle_blocker_1", "middle_blocker_2", "libero", "pinch_server"
    }
    if slot_name not in valid_slots:
        raise ValueError(f"Invalid slot name: {slot_name}")

    # 2. Dynamically build SET clauses to prevent duplicate column assignments
    set_clauses = []
    for col in valid_slots:
        if col == slot_name:
            set_clauses.append(f"{col} = $3")
        else:
            set_clauses.append(f"{col} = CASE WHEN t.{col} = $3 THEN NULL ELSE t.{col} END")

    set_sql = ", ".join(set_clauses)
    default_name = f"Lineup {lineup_number}"

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO user_teams AS t (user_id, lineup_number, lineup_name, {slot_name})
            VALUES ($1, $2, $4, $3)
            ON CONFLICT (user_id, lineup_number) 
            DO UPDATE SET {set_sql}
            """,
            user_id, lineup_number, card_id, default_name
        )
        return True

# ==============================================================================
# 6. ADMIN & UTILITY OPERATIONS
# ==============================================================================
async def boost_admin_account(user_id: int) -> bool:
    """
    Registers an admin with the Starter Pack first if missing,
    then grants them +1 ADMIN_PACK to their balance.

    Returns True if a new account was created, False if existing.
    """
    is_new = not await user_exists(user_id)

    # 1. If brand-new, run standard registration first (grants Starter Pack & Starter Team 1)
    if is_new:
        await register_user(user_id)

    # 2. Add the Admin Pack resources to their account
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET
                scout_coins = scout_coins + $2,
                practice_balls = practice_balls + $3,
                sports_drinks = sports_drinks + $4,
                drink_vouchers = drink_vouchers + $5
            WHERE user_id = $1;
        """,
                           user_id,
                           ADMIN_PACK["scout_coins"],
                           ADMIN_PACK["practice_balls"],
                           ADMIN_PACK["sports_drinks"],
                           ADMIN_PACK["drink_vouchers"]
                           )

    return is_new

async def grant_all_cards(user_id: int) -> dict:
    """
    Registers the admin with ADMIN_PACK items if brand-new, or unlocks all missing cards without re-granting items if existing.
    """
    is_new = not await user_exists(user_id)

    if is_new:
        await boost_admin_account(user_id)

    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("SELECT card_id FROM user_cards WHERE user_id = $1", user_id)
            owned_cards = {r["card_id"] for r in rows}

            all_cards = set(CARDS_BY_ID.keys())
            missing_cards = list(all_cards - owned_cards)

            if missing_cards:
                await conn.executemany(
                    "INSERT INTO user_cards (user_id, card_id) VALUES ($1, $2)",
                    [(user_id, cid) for cid in missing_cards]
                )

            return {
                "is_new": is_new,
                "granted_cards_count": len(missing_cards)
            }