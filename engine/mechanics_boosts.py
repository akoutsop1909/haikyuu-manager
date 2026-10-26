from collections import defaultdict
from engine.data_loader import SPECIALTIES_BY_ID, BONDS_BY_ID, SYNERGIES_BY_ID, TEAM_CONFIG, STARTING_SLOTS

MIN_SYNERGY_PLAYERS = TEAM_CONFIG["min_synergy_players"]

def apply_lineup_boosts(lineup_data: dict, user_cards: list[dict]) -> dict[str, dict]:
    """
    Calculates final match stats for all starting cards in a lineup,
    applying Synergies -> Bonds -> Setter Specialties in sequence.
    Returns a dict mapping slot_name -> boosted stat dictionary.
    """
    card_lookup = {c["id"]: c for c in user_cards}

    # 1. Initialize starting cards with their baseline scaled stats (level & resonance)
    starting_cards = {}
    starting_card_ids = set()
    school_counts = defaultdict(int)

    for slot in STARTING_SLOTS:
        cid = lineup_data.get(slot)
        if cid and cid in card_lookup:
            card = card_lookup[cid]
            starting_card_ids.add(cid)
            # Copy base/scaled stats so we don't mutate original objects in memory
            base_stats = card.get("scaled_stats", card.get("base_stats", {})).copy()
            starting_cards[slot] = {
                "card_id": cid,
                "school": card.get("school"),
                "position": card.get("position"),
                "stats": base_stats
            }
            school_counts[card.get("school")] += 1

    # Helper map to find a card's stats dictionary by its card_id across starting slots
    id_to_slot_stats = {data["card_id"]: data["stats"] for data in starting_cards.values()}

# =========================================================================
# STEP 1: APPLY SCHOOL SYNERGIES
# =========================================================================
    active_synergy_school = None

    for school, count in school_counts.items():
        if count >= MIN_SYNERGY_PLAYERS:
            active_synergy_school = school
            break

    if active_synergy_school:
        # Find matching synergy config
        matched_synergy = next(
            (s for s in SYNERGIES_BY_ID.values() if s.get("school", "").lower() == active_synergy_school.lower()),
            None
        )
        if matched_synergy:
            for boost in matched_synergy.get("boosts", []):
                stat_key = boost.get("stat")
                percent = boost.get("percent", 0.0)
                # Apply to all cards of that school in the starting slots
                for data in starting_cards.values():
                    if data["school"].lower() == active_synergy_school.lower():
                        if stat_key in data["stats"]:
                            data["stats"][stat_key] += int(round(data["stats"][stat_key] * percent))

# =========================================================================
# STEP 2: APPLY CHARACTER BONDS
# =========================================================================
    for bond in BONDS_BY_ID.values():
        req_players = set(bond.get("required_players", []))
        if req_players and req_players.issubset(starting_card_ids):
            # Bond conditions met! Apply target boosts
            for boost in bond.get("target_boosts", []):
                target_id = boost.get("player_id")
                stat_key = boost.get("stat")

                if target_id not in id_to_slot_stats or stat_key not in id_to_slot_stats[target_id]:
                    continue

                # Case A: Flat percentage boost
                if "percent" in boost:
                    percent = boost["percent"]
                    id_to_slot_stats[target_id][stat_key] += int(round(id_to_slot_stats[target_id][stat_key] * percent))

                # Case B: Ratio boost from a partner card's stat (e.g. 30% of Kageyama's set)
                elif "ratio_from_partner" in boost:
                    ratio_info = boost["ratio_from_partner"]
                    partner_id = ratio_info.get("partner_id")
                    partner_stat = ratio_info.get("stat")
                    ratio = ratio_info.get("ratio", 0.0)

                    if partner_id in id_to_slot_stats and partner_stat in id_to_slot_stats[partner_id]:
                        partner_value = id_to_slot_stats[partner_id][partner_stat]
                        added_val = int(round(partner_value * ratio))
                        id_to_slot_stats[target_id][stat_key] += added_val

# =========================================================================
# STEP 3: APPLY SETTER SPECIALTIES
# =========================================================================
    setter_cid = lineup_data.get("setter")
    if setter_cid and setter_cid in card_lookup:
        setter_card_data = card_lookup[setter_cid]
        spec_id = setter_card_data.get("specialty_id")
        specialty = SPECIALTIES_BY_ID.get(spec_id) if spec_id else None

        if specialty:
            team_boost = specialty.get("team_boost", {})
            stat_key = team_boost.get("stat")  # e.g. "spike"

            # Case A: Scaling boost from Setter's source stat (e.g., 25% of Setter's SET stat)
            if "ratio" in team_boost:
                ratio = team_boost.get("ratio", 0.0)
                source_stat = specialty.get("source_stat", "set")

                if setter_cid in id_to_slot_stats and source_stat in id_to_slot_stats[setter_cid]:
                    setter_source_val = id_to_slot_stats[setter_cid][source_stat]
                    bonus_val = int(round(setter_source_val * ratio))

                    # Apply team-wide bonus to the specified stat
                    for data in starting_cards.values():
                        if stat_key in data["stats"]:
                            data["stats"][stat_key] += bonus_val

            # Case B: Flat percentage boost to team stat (e.g., +10% Spike)
            elif "percent" in team_boost:
                percent = team_boost.get("percent", 0.0)
                for data in starting_cards.values():
                    if stat_key in data["stats"]:
                        data["stats"][stat_key] += int(round(data["stats"][stat_key] * percent))

    # Return structured dictionary of slot -> final boosted stats
    return {slot: data["stats"] for slot, data in starting_cards.items() if slot in lineup_data}

# =========================================================================
# STEP 4: APPLY OPPONENT DEBUFFS
# =========================================================================
def apply_opponent_debuffs(opponent_stats: dict, setter_slot_stats: dict, setter_card: dict) -> dict:
    """
    Applies the active setter specialty's opponent debuff using the
    setter's fully boosted stats.
    """
    spec_id = setter_card.get("specialty_id")
    specialty = SPECIALTIES_BY_ID.get(spec_id)

    debuff_rule = specialty.get("opponent_debuff", {})
    stat_key = debuff_rule.get("stat")

    # Case A: Flat percentage debuff (e.g., -10% Block, -15% Receive)
    if "percent" in debuff_rule:
        percent = debuff_rule["percent"]
        opponent_stats[stat_key] = max(0, opponent_stats[stat_key] - int(round(opponent_stats[stat_key] * percent)))

    # Case B: Ratio debuff based on Setter's stat (e.g., -15% of Setter's Set stat)
    elif "ratio" in debuff_rule:
        ratio = debuff_rule["ratio"]
        source_stat = specialty.get("source_stat", "set")

        # Use the FULLY BOOSTED setter stats, not raw scaled stats!
        source_val = setter_slot_stats.get(source_stat, 0)

        reduction = int(round(source_val * ratio))
        opponent_stats[stat_key] = max(0, opponent_stats[stat_key] - reduction)

    return opponent_stats