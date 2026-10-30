# ==============================================================================
# SETUP & CONFIGURATION
# ==============================================================================
from datetime import datetime
import os
import logging
import random
import asyncpg

from pydantic import BaseModel, Field

from engine.game_logic import calculate_card_stats, get_single_level_cost, calculate_tokyo_trip_rewards

# Import all pre-loaded static configurations and lookup dictionaries
from engine.data_loader import (
    CARDS_BY_ID, CARDS_BY_RARITY, BIRTHDAYS_BY_DATE,
    STARTER_PACK, DAILY_REWARD, BIRTHDAY_REWARD, SCOUT_CONFIG,
    TEAM_CONFIG, TRAINING_CONFIG, TOKYO_TRIP_CONFIG, ADMIN_PACK, ALL_SLOTS
)

# Connection pool setup
pool: asyncpg.Pool | None = None
logger = logging.getLogger(__name__)

# ==============================================================================
# DATA MODELS
# ==============================================================================
class DailyClaim(BaseModel):
    claimed: bool = False
    scout_coins: int = Field(default=0, ge=0)
    practice_balls: int = Field(default=0, ge=0)
    match_passes: int = Field(default=0, ge=0)
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
    match_passes: int = Field(default=0, ge=0)
    scout_coins: int = Field(default=0, ge=0)
    practice_balls: int = Field(default=0, ge=0)
    sports_drinks: int = Field(default=0, ge=0)
    drink_vouchers: int = Field(default=0, ge=0)
    voucher_scraps: int = Field(default=0, ge=0)

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

                match_passes INT DEFAULT 0 CHECK (match_passes >= 0),
                scout_coins INT DEFAULT 0 CHECK (scout_coins >= 0),
                practice_balls INT DEFAULT 0 CHECK (practice_balls >= 0),
                sports_drinks INT DEFAULT 0 CHECK (sports_drinks >= 0),
                drink_vouchers INT DEFAULT 0 CHECK (drink_vouchers >= 0),
                voucher_scraps INT DEFAULT 0 CHECK (voucher_scraps >= 0),

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

        # Create Team Lineups Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_team_lineups (
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

        # Create Tokyo Trip Squads Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_trip_squads (
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                squad_number INT NOT NULL,
                squad_name TEXT DEFAULT 'Trip Squad',
                        
                slot_1 TEXT,
                slot_2 TEXT,
                slot_3 TEXT,
                slot_4 TEXT,
                slot_5 TEXT,

                PRIMARY KEY (user_id, squad_number)
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
                INSERT INTO user_team_lineups (
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
            SELECT match_passes, scout_coins, practice_balls, sports_drinks, drink_vouchers, voucher_scraps 
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
            rarity = card_info["rarity"]

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

    # Define rarity weights for sorting (higher number = higher priority)
    rarity_weights = {"SSR": 3, "SR": 2, "R": 1}

    # Sort: Highest level first (-), highest rarity first (-), then alphabetical name (A-Z)
    user_cards.sort(key=lambda card: (
        -card["level"],
        -rarity_weights.get(card["rarity"], 0),
        card["name"]
    ))

    return user_cards


async def claim_daily(user_id: int) -> DailyClaim:
    claimed = False
    scout_coins = 0
    practice_balls = 0
    match_passes_gained = 0
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

            # Fetch user's last claim and current match passes
            row = await conn.fetchrow(
                "SELECT last_daily_claim, total_logins, match_passes FROM users WHERE user_id = $1",
                user_id
            )

            if row:
                last_claim, total_logins, current_passes = row["last_daily_claim"], row["total_logins"] or 0, row["match_passes"] or 0

                can_claim = True if last_claim is None else db_now.date() > last_claim.date()

                if can_claim:
                    scout_coins = DAILY_REWARD["scout_coins"]
                    practice_balls = DAILY_REWARD["practice_balls"]

                    # Calculate how many passes are actually added respecting the config cap
                    target_passes = min(DAILY_REWARD["match_passes_cap"], current_passes + DAILY_REWARD["match_passes"])
                    match_passes_gained = target_passes - current_passes

                    total_logins += 1
                    claimed = True

                    await conn.execute("""
                        UPDATE users 
                        SET scout_coins = scout_coins + $1,
                            practice_balls = practice_balls + $2,
                            match_passes = LEAST($3, match_passes + $4),
                            total_logins = total_logins + 1,
                            last_daily_claim = $5
                        WHERE user_id = $6
                    """, scout_coins, practice_balls, DAILY_REWARD["match_passes_cap"], DAILY_REWARD["match_passes"], db_now, user_id)

    return DailyClaim(
        claimed=claimed,
        scout_coins=scout_coins,
        practice_balls=practice_balls,
        match_passes=match_passes_gained,
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
                    rarity = card_data["rarity"]
                    bonus_cfg = BIRTHDAY_REWARD["owner_bonus_by_rarity"].get(
                        rarity, BIRTHDAY_REWARD["owner_bonus_by_rarity"]["R"]
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
    cost = scout_count * SCOUT_CONFIG["cost_per_pull"]

    rarities = list(SCOUT_CONFIG["rarity_weights"].keys())
    weights = list(SCOUT_CONFIG["rarity_weights"].values())

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
                rarity = card_info["rarity"]

                if cid in owned_cards:
                    current_res = owned_cards[cid]
                    if current_res < SCOUT_CONFIG["max_resonance"]:
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
                        drink_vouchers = SCOUT_CONFIG["overflow_vouchers_by_rarity"].get(rarity, 1)
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


async def train_card(user_id: int, card_id: str, levels_to_add: int = 1, max_mode: bool = False):
    """Calculates and applies level upgrades using Practice Balls based on TRAINING_CONFIG."""
    card_meta = CARDS_BY_ID.get(card_id)
    rarity = card_meta["rarity"]

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

            target_levels = TRAINING_CONFIG["max_level"] - current_level if max_mode else levels_to_add
            levels_gained = 0
            total_cost = 0

            for _ in range(target_levels):
                next_lvl = current_level + levels_gained
                if next_lvl >= TRAINING_CONFIG["max_level"]:
                    break

                cost = get_single_level_cost(next_lvl, rarity)
                if total_cost + cost > practice_balls:
                    break

                total_cost += cost
                levels_gained += 1

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


async def increase_resonance(user_id: int, card_id: str):
    card_meta = CARDS_BY_ID.get(card_id)
    rarity = card_meta["rarity"]
    drink_cost = TRAINING_CONFIG["resonance_drink_cost_by_rarity"].get(rarity, 1)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT sports_drinks FROM users WHERE user_id = $1", user_id
            )

            await conn.execute(
                "UPDATE users SET sports_drinks = sports_drinks - $1 WHERE user_id = $2",
                drink_cost, user_id
            )
            await conn.execute(
                "UPDATE user_cards SET resonance = resonance + 1 WHERE user_id = $1 AND card_id = $2",
                user_id, card_id
            )


async def redeem_drink(user_id: int):
    """Redeems 1 Sports Drink using drink vouchers. Returns True on success."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT drink_vouchers FROM users WHERE user_id = $1", user_id
            )

            await conn.execute(
                """
                UPDATE users 
                SET drink_vouchers = drink_vouchers - $1,
                    sports_drinks = sports_drinks + 1
                WHERE user_id = $2
                """,
                TRAINING_CONFIG["drink_craft_cost"], user_id
            )

# ==============================================================================
# 5. TEAM & LINEUP MANAGEMENT
# ==============================================================================
async def get_lineups(user_id: int) -> dict[int, dict]:
    """Fetches all lineup data (names and slots) for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM user_team_lineups
            WHERE user_id = $1
            ORDER BY lineup_number ASC
            """,
            user_id
        )
        # Returns a dictionary like {1: {"lineup_name": "Starter Team", "setter": "card_id_1", ...}, 2: {...}}
        return {row["lineup_number"]: dict(row) for row in rows}


async def update_lineup_name(user_id: int, lineup_number: int, lineup_name: str):
    """Inserts or updates the custom name of a specific user lineup."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_team_lineups (user_id, lineup_number, lineup_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, lineup_number) 
            DO UPDATE SET lineup_name = EXCLUDED.lineup_name
            """,
            user_id, lineup_number, lineup_name
        )


async def clear_lineup(user_id: int, lineup_number: int):
    """Clears all player slots for a specific lineup."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_team_lineups 
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


async def remove_pinch(user_id: int, lineup_number: int):
    """Removes the pinch server from a specific user lineup."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_team_lineups 
            SET pinch_server = NULL 
            WHERE user_id = $1 AND lineup_number = $2
            """,
            user_id, lineup_number
        )


async def add_to_lineup(user_id: int, lineup_number: int, slot_name: str, card_id: str):
    """Assigns a card to any specified lineup slot, clearing it from any other slot in the same lineup."""

    # 1. Whitelist valid slot columns to prevent SQL injection
    if slot_name not in ALL_SLOTS:
        raise ValueError(f"Invalid slot name: {slot_name}")

    # 2. Dynamically build SET clauses to prevent duplicate column assignments
    set_clauses = []
    for col in ALL_SLOTS:
        if col == slot_name:
            set_clauses.append(f"{col} = $3")
        else:
            set_clauses.append(f"{col} = CASE WHEN t.{col} = $3 THEN NULL ELSE t.{col} END")

    set_sql = ", ".join(set_clauses)

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO user_team_lineups AS t (user_id, lineup_number, lineup_name, {slot_name})
            VALUES ($1, $2, $4, $3)
            ON CONFLICT (user_id, lineup_number) 
            DO UPDATE SET {set_sql}
            """,
            user_id, lineup_number, card_id, TEAM_CONFIG["default_lineup_name_format"].format(lineup_number)
        )

# ==============================================================================
# 6. TOKYO TRIP
# ==============================================================================
async def get_trip_squads(user_id: int) -> dict[int, dict]:
    """Fetches all saved Tokyo trip squads for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM user_trip_squads
            WHERE user_id = $1
            ORDER BY squad_number ASC
            """,
            user_id
        )
        return {row["squad_number"]: dict(row) for row in rows}


async def clear_trip_squad(user_id: int, squad_number: int):
    """Clears all slots for a specific Tokyo trip squad dynamically based on config."""
    set_clause = ", ".join([f"slot_{i} = NULL" for i in range(1, TOKYO_TRIP_CONFIG["max_players"] + 1)])

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE user_trip_squads 
            SET {set_clause}
            WHERE user_id = $1 AND squad_number = $2
            """,
            user_id, squad_number
        )


async def add_to_trip_squad(user_id: int, squad_number: int, slot_name: str, slot_id: str):
    """Assigns a card to a Tokyo squad slot, inserting the squad row if it doesn't exist yet."""
    valid_slots = {f"slot_{i}" for i in range(1, TOKYO_TRIP_CONFIG["max_players"] + 1)}

    if slot_name not in valid_slots:
        raise ValueError(f"Invalid slot name: {slot_name}")

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Ensure the squad row exists for this user and squad number
            await conn.execute(
                """
                INSERT INTO user_trip_squads (user_id, squad_number, squad_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, squad_number) DO NOTHING
                """,
                user_id, squad_number, TOKYO_TRIP_CONFIG["default_squad_name_format"].format(squad_number)
            )

            # Clear this card from any other slot within the same squad first (prevents duplicates in same squad)
            set_null_clauses = ", ".join([f"{col} = CASE WHEN {col} = $3 THEN NULL ELSE {col} END" for col in valid_slots])
            await conn.execute(
                f"""
                UPDATE user_trip_squads
                SET {set_null_clauses}
                WHERE user_id = $1 AND squad_number = $2
                """,
                user_id, squad_number, slot_id
            )

            # Assign the card to the target slot
            await conn.execute(
                f"""
                UPDATE user_trip_squads
                SET {slot_name} = $3
                WHERE user_id = $1 AND squad_number = $2
                """,
                user_id, squad_number, slot_id
            )

async def get_tokyo_trip_start(user_id: int) -> datetime | None:
    """Fetches the Tokyo trip start timestamp for a user."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT tokyo_trip_start FROM users WHERE user_id = $1",
            user_id
        )


async def start_tokyo_trip(user_id: int, squad_number: int):
    """Sets is_on_trip = TRUE for the cards in the specified squad using max_players config."""
    slot_columns = ", ".join([f"slot_{i}" for i in range(1, TOKYO_TRIP_CONFIG["max_players"] + 1)])

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {slot_columns}
                FROM user_trip_squads
                WHERE user_id = $1 AND squad_number = $2
                """,
                user_id, squad_number
            )

            card_ids = [row[f"slot_{i}"] for i in range(1, TOKYO_TRIP_CONFIG["max_players"] + 1) if row[f"slot_{i}"]]

            await conn.execute(
                "UPDATE users SET tokyo_trip_start = NOW() WHERE user_id = $1",
                user_id
            )

            await conn.execute(
                """
                UPDATE user_cards 
                SET is_on_trip = TRUE 
                WHERE user_id = $1 AND card_id = ANY($2::text[])
                """,
                user_id, card_ids
            )

async def claim_tokyo_trip(user_id: int):
    """Ends the Tokyo trip using the centralized calculation function from game_logic."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Fetch trip start time
            trip_start = await conn.fetchval(
                "SELECT tokyo_trip_start FROM users WHERE user_id = $1", user_id
            )

            # 2. Fetch cards currently on the trip
            rows = await conn.fetch(
                """
                SELECT card_id
                FROM user_cards
                WHERE user_id = $1 AND is_on_trip = TRUE
                """,
                user_id
            )

            # 3. Build the minimal card dict list required by game_logic
            user_cards_for_calc = []
            for row in rows:
                cid = row["card_id"]
                card_meta = CARDS_BY_ID.get(cid, {})
                user_cards_for_calc.append({"rarity": card_meta.get("rarity", "R")})

            # 4. Delegate reward, milestone, and voucher calculation to game_logic
            rewards = calculate_tokyo_trip_rewards(trip_start, user_cards_for_calc)

            # 5. Update user inventory and clear trip start timestamp
            await conn.execute(
                """
                UPDATE users 
                SET scout_coins = scout_coins + $2,
                    practice_balls = practice_balls + $3,
                    drink_vouchers = drink_vouchers + $4,
                    tokyo_trip_start = NULL
                WHERE user_id = $1
                """,
                user_id, rewards.scout_coins, rewards.practice_balls, rewards.drink_vouchers
            )

            # 6. Reset cards: take them off the trip and apply the exhaustion timer
            await conn.execute(
                """
                UPDATE user_cards 
                SET is_on_trip = FALSE,
                    exhausted_until = NOW() + INTERVAL '1 hour' * $2
                WHERE user_id = $1 AND is_on_trip = TRUE
                """,
                user_id, TOKYO_TRIP_CONFIG["exhaustion_hours"]
            )

# ==============================================================================
# 7. ADMIN & UTILITY OPERATIONS
# ==============================================================================
async def boost_admin_account(user_id: int) -> bool:
    """
    Registers an admin with the Starter Pack first if missing, then grants them +1 ADMIN_PACK to their balance.
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
    Registers the admin with Starter Pack if brand-new, or unlocks all missing cards without re-granting items if existing.
    """
    is_new = not await user_exists(user_id)

    if is_new:
        await register_user(user_id)

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


async def force_complete_tokyo_trip(user_id: int):
    """Forces an active Tokyo trip to reach its max duration instantly for testing/admin purposes."""
    max_hours = TOKYO_TRIP_CONFIG["max_duration_hours"] + 1  # Add 1 hour buffer past max duration

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET tokyo_trip_start = NOW() - INTERVAL '1 hour' * $1 WHERE user_id = $2",
            max_hours, user_id
        )