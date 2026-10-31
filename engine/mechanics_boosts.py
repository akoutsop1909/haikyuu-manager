from collections import defaultdict
from engine.data_loader import SPECIALTIES_BY_ID, BONDS_BY_ID, SYNERGIES_BY_ID, TEAM_CONFIG, STARTING_SLOTS, ALL_SLOTS

MIN_SYNERGY_PLAYERS = TEAM_CONFIG["min_synergy_players"]


def apply_lineup_boosts(lineup_data: dict, user_cards: list[dict]) -> dict[str, dict]:
    """
    Calculates final match stats for all cards in a lineup (starters + pinch server),
    applying Synergies -> Bonds (starters only) -> Setter Specialties in sequence.
    Returns a dict mapping slot_name -> boosted stat dictionary.
    """
    card_lookup = {c["id"]: c for c in user_cards}

    # 1. Initialize all lineup cards (starters + pinch server) with baseline scaled stats
    lineup_cards = {}
    starting_card_ids = set()
    school_counts = defaultdict(int)

    for slot in ALL_SLOTS:
        cid = lineup_data.get(slot)
        if not cid:
            continue

        card = card_lookup[cid]

        # Only track core starting slots for character bonds and school synergies
        if slot in STARTING_SLOTS:
            starting_card_ids.add(cid)
            school_counts[card["school"]] += 1

        # Copy base/scaled stats so we don't mutate original objects in memory
        base_stats = card.get("scaled_stats", card["base_stats"]).copy()
        lineup_cards[slot] = {
            "card_id": cid,
            "school": card["school"],
            "position": card["position"],
            "stats": base_stats
        }

    # Helper map to find a card's stats dictionary by its card_id across all lineup slots
    id_to_slot_stats = {data["card_id"]: data["stats"] for data in lineup_cards.values()}

# =========================================================================
# STEP 1: APPLY SCHOOL SYNERGIES (All Positions)
# =========================================================================
    active_synergy_school = None

    for school, count in school_counts.items():
        if count >= MIN_SYNERGY_PLAYERS:
            active_synergy_school = school
            break

    if active_synergy_school:
        matched_synergy = next(
            s for s in SYNERGIES_BY_ID.values() if s["school"].lower() == active_synergy_school.lower()
        )
        for boost in matched_synergy["boosts"]:
            stat_key = boost["stat"]
            percent = boost["percent"]
            for data in lineup_cards.values():
                if data["school"].lower() == active_synergy_school.lower():
                    data["stats"][stat_key] += data["stats"][stat_key] * percent

# =========================================================================
# STEP 2: APPLY CHARACTER BONDS (Starters Only)
# =========================================================================
    # Pass 1: Apply all flat percentage boosts first so partner stats are fully updated
    for bond in BONDS_BY_ID.values():
        req_players = set(bond["required_players"])
        if req_players and req_players.issubset(starting_card_ids):
            for boost in bond["target_boosts"]:
                if "percent" in boost:
                    target_id = boost["player_id"]
                    stat_key = boost["stat"]
                    percent = boost["percent"]

                    id_to_slot_stats[target_id][stat_key] += id_to_slot_stats[target_id][stat_key] * percent

    # Pass 2: Apply all ratio boosts using the newly updated partner stats
    for bond in BONDS_BY_ID.values():
        req_players = set(bond["required_players"])
        if req_players and req_players.issubset(starting_card_ids):
            for boost in bond["target_boosts"]:
                if "ratio_from_partner" in boost:
                    target_id = boost["player_id"]
                    stat_key = boost["stat"]
                    ratio_info = boost["ratio_from_partner"]
                    partner_id = ratio_info["partner_id"]
                    partner_stat = ratio_info["stat"]
                    ratio = ratio_info["ratio"]

                    partner_value = id_to_slot_stats[partner_id][partner_stat]
                    id_to_slot_stats[target_id][stat_key] += partner_value * ratio

# =========================================================================
# STEP 3: APPLY SETTER SPECIALTIES (All Positions)
# =========================================================================
    setter_cid = lineup_data.get("setter")
    if setter_cid:
        setter_card = card_lookup[setter_cid]
        specialty = SPECIALTIES_BY_ID[setter_card["specialty_id"]]
        team_boost = specialty["team_boost"]
        stat_key = team_boost["stat"]

        # Case A: Scaling boost from Setter's source stat
        if "ratio" in team_boost:
            ratio = team_boost["ratio"]
            source_stat = specialty["source_stat"]
            setter_source_val = id_to_slot_stats[setter_cid][source_stat]
            bonus_val = setter_source_val * ratio
            for data in lineup_cards.values():
                data["stats"][stat_key] += bonus_val

        # Case B: Flat percentage boost to team stat
        elif "percent" in team_boost:
            percent = team_boost["percent"]
            for data in lineup_cards.values():
                data["stats"][stat_key] += data["stats"][stat_key] * percent

    # Return structured dictionary of slot -> final boosted stats
    final_boosted_stats = {}
    for slot, data in lineup_cards.items():
        final_boosted_stats[slot] = {stat_name: int(round(val)) for stat_name, val in data["stats"].items()}

    return final_boosted_stats

# =========================================================================
# STEP 4: APPLY OPPONENT DEBUFFS
# =========================================================================
def apply_opponent_debuffs(opponent_slot_stats: dict[str, dict], setter_slot_stats: dict, setter_card: dict) -> dict[str, dict]:
    """
    Applies the active setter specialty's opponent debuff to every player
    slot on the opponent team (starters + pinch server).
    """
    specialty = SPECIALTIES_BY_ID[setter_card["specialty_id"]]
    debuff_rule = specialty["opponent_debuff"]
    stat_key = debuff_rule["stat"]

    # Case A: Flat percentage debuff (e.g., -10% Block, -15% Receive)
    if "percent" in debuff_rule:
        percent = debuff_rule["percent"]
        for slot_stats in opponent_slot_stats.values():
            current_val = slot_stats[stat_key]
            slot_stats[stat_key] = max(0.0, current_val - (current_val * percent))

    # Case B: Ratio debuff based on Setter's stat (e.g., -15% of Setter's Set stat)
    elif "ratio" in debuff_rule:
        ratio = debuff_rule["ratio"]
        source_stat = specialty["source_stat"]
        source_val = setter_slot_stats[source_stat]
        reduction = source_val * ratio
        for slot_stats in opponent_slot_stats.values():
            slot_stats[stat_key] = max(0.0, slot_stats[stat_key] - reduction)

    # FINAL STEP: Round all opponent slot stats for that stat key to clean integers
    for slot_stats in opponent_slot_stats.values():
        slot_stats[stat_key] = int(round(slot_stats[stat_key]))

    return opponent_slot_stats