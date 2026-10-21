from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from data_loader import TRAINING_CONFIG, TOKYO_TRIP_CONFIG

class TokyoTripRewards(BaseModel):
    scout_coins: int = Field(default=0, ge=0)
    practice_balls: int = Field(default=0, ge=0)
    drink_vouchers: int = Field(default=0, ge=0)
    current_milestones: int = Field(default=0, ge=0)
    max_milestones: int = Field(default=0, ge=0)
    coins_per_milestone: int = Field(default=0, ge=0)
    balls_per_milestone: int = Field(default=0, ge=0)
    next_milestone_ts: int | None = None
    max_duration_ts: int | None = None

def calculate_card_stats(base_stats: dict, level: int, rarity: str = "S3", resonance: int = 0) -> dict:
    boost_rate = TRAINING_CONFIG["stat_boost_per_level"].get(rarity, 0.020)
    res_boost_rate = TRAINING_CONFIG["stat_boost_per_resonance"].get(rarity, 0.03)
    level_multiplier = 1.0 + (boost_rate * (level - 1))
    resonance_multiplier = 1.0 + (res_boost_rate * resonance)
    total_multiplier = level_multiplier * resonance_multiplier
    return {stat: int(round(value * total_multiplier)) for stat, value in base_stats.items()}

def get_single_level_cost(level: int, rarity: str = "S3") -> int:
    base_cost = TRAINING_CONFIG["base_cost"]
    growth_rate = TRAINING_CONFIG["cost_growth_rate"]
    multipliers = TRAINING_CONFIG["rarity_cost_multipliers"]
    rarity_mult = multipliers.get(rarity, 1.0)
    raw_cost = base_cost * (growth_rate ** (level - 1)) * rarity_mult
    return max(1, int(round(raw_cost)))

def get_level_cost(current_level: int, levels_to_add: int = 1, rarity: str = "S3") -> int:
    max_lvl = TRAINING_CONFIG["max_level"]
    actual_levels = min(levels_to_add, max_lvl - current_level)
    if actual_levels <= 0:
        return 0
    total_cost = 0
    for i in range(actual_levels):
        lvl = current_level + i
        total_cost += get_single_level_cost(lvl, rarity)
    return total_cost

def calculate_tokyo_trip_rewards(trip_start: datetime, user_cards: list[dict]) -> TokyoTripRewards:
    milestone_interval = TOKYO_TRIP_CONFIG.get("milestone_interval_hours", 3)
    max_duration = TOKYO_TRIP_CONFIG.get("max_duration_hours", 12)
    max_milestones = max_duration // milestone_interval

    rewards_by_rarity = TOKYO_TRIP_CONFIG.get("rewards_by_rarity", {})
    bonus_vouchers_config = TOKYO_TRIP_CONFIG.get("max_duration_bonus_vouchers", 0)

    now = datetime.now(timezone.utc)
    if trip_start.tzinfo is None:
        trip_start = trip_start.replace(tzinfo=timezone.utc)

    elapsed_seconds = (now - trip_start).total_seconds()
    elapsed_hours = max(0.0, elapsed_seconds / 3600.0)

    current_milestones = min(max_milestones, int(elapsed_hours // milestone_interval))

    coins_per_milestone = 0
    balls_per_milestone = 0

    for card in user_cards:
        rarity = card.get("rarity")
        rarity_rewards = rewards_by_rarity.get(rarity, {})
        coins_per_milestone += rarity_rewards.get("scout_coins", 0)
        balls_per_milestone += rarity_rewards.get("practice_balls", 0)

    # Calculate exact Unix timestamps for next milestone and max duration (vouchers)
    next_milestone_ts = None
    if current_milestones < max_milestones:
        next_milestone_dt = trip_start + timedelta(hours=milestone_interval * (current_milestones + 1))
        next_milestone_ts = int(next_milestone_dt.timestamp())

    max_duration_dt = trip_start + timedelta(hours=max_duration)
    max_duration_ts = int(max_duration_dt.timestamp()) if current_milestones < max_milestones else None

    earned_vouchers = bonus_vouchers_config if current_milestones >= max_milestones else 0

    return TokyoTripRewards(
        scout_coins=coins_per_milestone * current_milestones,
        practice_balls=balls_per_milestone * current_milestones,
        drink_vouchers=earned_vouchers,
        current_milestones=current_milestones,
        max_milestones=max_milestones,
        coins_per_milestone=coins_per_milestone,
        balls_per_milestone=balls_per_milestone,
        next_milestone_ts=next_milestone_ts,
        max_duration_ts=max_duration_ts
    )