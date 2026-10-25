from collections import defaultdict
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Define project root relative to this file and target paths safely
PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
CARDS_BY_RARITY = {"R": [], "SR": [], "SSR": []}
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
TEAM_CONFIG = CONFIG.get("TEAM", {})
MATCH_CONFIG = CONFIG.get("MATCH", {})
TOKYO_TRIP_CONFIG = CONFIG.get("TOKYO_TRIP", {})
ADMIN_PACK = CONFIG.get("ADMIN_PACK", {})

ITEM_METADATA = {
    "pass": {"name": "Match Passes", "short": "Passes", "emoji": "🪪"},
    "coins": {"name": "Scout Coins", "short": "Coins", "emoji": "🪙"},
    "balls": {"name": "Practice Balls", "short": "Balls", "emoji": "🏐"},
    "drinks": {"name": "Sports Drinks", "short": "Drinks", "emoji": "🥤"},
    "vouchers": {"name": "Drink Vouchers", "short": "Vouchers", "emoji": "🎟️"},
    "scraps": {"name": "Voucher Scraps", "short": "Scraps", "emoji": "🧾"},
}

STARTING_SLOTS = [
    "setter", "opposite", "wing_spiker_1", "wing_spiker_2",
    "middle_blocker_1", "middle_blocker_2", "libero"
]

ALL_SLOTS = STARTING_SLOTS + ["pinch_server"]