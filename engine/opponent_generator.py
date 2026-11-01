import random
from engine.data_loader import CARDS_BY_RARITY, CARDS_BY_ID, BONDS_BY_ID, SYNERGIES_BY_ID, TEAM_CONFIG, MATCH_CONFIG, \
    STARTING_SLOTS, POSITION_MAPPING
from engine.game_logic import calculate_card_stats

# Module-level constants
DIFFICULTY_SETTINGS = MATCH_CONFIG["difficulties"]
MIN_SYNERGY_COUNT = TEAM_CONFIG["min_synergy_players"]


def generate_opponent_team(difficulty: str) -> dict:
    config = DIFFICULTY_SETTINGS[difficulty]

    allowed_rarities = config["rarities"]
    min_lvl, max_lvl = config["level_range"]
    min_res, max_res = config["resonance_range"]
    force_synergy = config["force_school_synergy"]
    target_bonds = config["target_bonds_count"]
    allowed_bond_sizes = config["allowed_bond_sizes"]
    mandatory_synergy_size = config.get("mandatory_synergy_bond_size")
    has_pinch_server = config["has_pinch_server"]

    # 1. Determine Synergy School safely based on allowed rarities
    selected_school = None
    if force_synergy:
        all_schools = [data["school"] for data in SYNERGIES_BY_ID.values()]
        selected_school = random.choice(all_schools)

    # 2. Select valid bond companion pairs
    forced_card_ids = set()
    if target_bonds > 0:
        synergy_bonds = []
        other_bonds = []

        for bond in BONDS_BY_ID.values():
            req_ids = bond["required_players"]

            # Ensure all required players exist and match allowed rarities
            if all(cid in CARDS_BY_ID and CARDS_BY_ID[cid]["rarity"] in allowed_rarities for cid in req_ids):

                # Filter bond size dynamically based on config configuration
                if len(req_ids) not in allowed_bond_sizes:
                    continue

                if selected_school:
                    if all(CARDS_BY_ID[cid]["school"] == selected_school for cid in req_ids):
                        synergy_bonds.append(req_ids)  # Pure school bond
                    else:
                        other_bonds.append(req_ids)  # Cross-school bond
                else:
                    synergy_bonds.append(req_ids)

        chosen_bonds = []
        remaining_slots = target_bonds

        # 1. Prioritize mandatory synergy bond size dynamically if configured
        if mandatory_synergy_size and selected_school:
            matching_synergies = [b for b in synergy_bonds if len(b) == mandatory_synergy_size]
            if matching_synergies:
                forced_synergy_bond = random.choice(matching_synergies)
                if forced_synergy_bond in synergy_bonds:
                    synergy_bonds.remove(forced_synergy_bond)
                chosen_bonds.append(forced_synergy_bond)
                remaining_slots -= mandatory_synergy_size

        # 2. Limit additional synergy bonds so we don't fill 100% of the team with one school
        max_synergy_bonds_allowed = 1
        if remaining_slots > 0:
            allowed_syn_count = min(remaining_slots, max_synergy_bonds_allowed)
            taken_synergy = synergy_bonds[:allowed_syn_count]
            chosen_bonds.extend(taken_synergy)
            remaining_slots -= len(taken_synergy)

        # 3. Fill the absolute remainder of slots with cross-school / other bonds
        if remaining_slots > 0:
            taken_others = other_bonds[:remaining_slots]
            chosen_bonds.extend(taken_others)
            remaining_slots -= len(taken_others)

        for b_group in chosen_bonds:
            for cid in b_group:
                forced_card_ids.add(cid)

    opponent_lineup = {}
    opponent_cards_list = []

    synergy_slots_filled = 0
    assigned_card_ids = set()

    for slot in STARTING_SLOTS:
        required_position = POSITION_MAPPING[slot]
        chosen_card = None

        # Try to place a forced bond card matching this position first
        for cid in forced_card_ids:
            card = CARDS_BY_ID.get(cid)
            if card and card["position"] == required_position and cid not in assigned_card_ids:
                chosen_card = card
                assigned_card_ids.add(cid)
                break

        # Prioritize synergy school for matching positions
        if not chosen_card and selected_school and synergy_slots_filled < MIN_SYNERGY_COUNT:
            school_pos_cards = [
                c for c in CARDS_BY_ID.values()
                if c["school"] == selected_school
                and c["position"] == required_position
                and c["rarity"] in allowed_rarities
                and c["id"] not in assigned_card_ids
            ]
            if school_pos_cards:
                chosen_card = random.choice(school_pos_cards)
                assigned_card_ids.add(chosen_card["id"])
                synergy_slots_filled += 1

        # Fallback to general allowed rarities & positions
        if not chosen_card:
            eligible_cards = []
            for rarity in allowed_rarities:
                for cid in CARDS_BY_RARITY.get(rarity, []):
                    card = CARDS_BY_ID.get(cid)
                    if card and card["position"] == required_position and card["id"] not in assigned_card_ids:
                        eligible_cards.append(card)

            if eligible_cards:
                chosen_card = random.choice(eligible_cards)
                assigned_card_ids.add(chosen_card["id"])

        # Ultimate fallback
        if not chosen_card:
            fallback_cards = [
                CARDS_BY_ID[cid] for cid in CARDS_BY_RARITY.get("R", [])
                if CARDS_BY_ID[cid]["position"] == required_position
            ]
            chosen_card = random.choice(fallback_cards)

        card_level = random.randint(min_lvl, max_lvl)
        card_resonance = random.randint(min_res, max_res)

        scaled_stats = calculate_card_stats(
            base_stats=chosen_card["base_stats"],
            level=card_level,
            rarity=chosen_card["rarity"],
            resonance=card_resonance
        )

        card_info = {
            "id": chosen_card["id"],
            "name": chosen_card["name"],
            "school": chosen_card["school"],
            "position": chosen_card["position"],
            "rarity": chosen_card["rarity"],
            "level": card_level,
            "resonance": card_resonance,
            "scaled_stats": scaled_stats,
            "image_file": chosen_card.get("image_file")
        }

        opponent_lineup[slot] = card_info
        opponent_cards_list.append(card_info)

    # 3. Optional Pinch Server Evaluation
    if has_pinch_server:
        # Find eligible pinch server candidates from allowed rarities not yet in team
        ps_candidates = []
        for rarity in allowed_rarities:
            for cid in CARDS_BY_RARITY.get(rarity, []):
                if cid not in assigned_card_ids:
                    ps_candidates.append(CARDS_BY_ID[cid])

        if ps_candidates:
            chosen_ps_card = random.choice(ps_candidates)
            ps_level = random.randint(min_lvl, max_lvl)
            ps_resonance = random.randint(min_res, max_res)

            ps_scaled_stats = calculate_card_stats(
                base_stats=chosen_ps_card["base_stats"],
                level=ps_level,
                rarity=chosen_ps_card["rarity"],
                resonance=ps_resonance
            )

            # Find the lowest serve stat strictly among Middle Blockers (MB)
            eligible_starting_slots = [
                (s_name, s_data) for s_name, s_data in opponent_lineup.items()
                if s_data["position"] == "MB"
            ]

            if eligible_starting_slots:
                weakest_slot, weakest_data = min(
                    eligible_starting_slots,
                    key=lambda item: item[1]["scaled_stats"]["serve"]
                )

                # Only use pinch server if his serve stat is strictly higher than the weakest starter's serve
                if ps_scaled_stats["serve"] > weakest_data["scaled_stats"]["serve"]:
                    ps_card_info = {
                        "id": chosen_ps_card["id"],
                        "name": chosen_ps_card["name"],
                        "school": chosen_ps_card["school"],
                        "position": chosen_ps_card["position"],
                        "rarity": chosen_ps_card["rarity"],
                        "level": ps_level,
                        "resonance": ps_resonance,
                        "scaled_stats": ps_scaled_stats,
                        "image_file": chosen_ps_card.get("image_file")
                    }
                    opponent_lineup["pinch_server"] = ps_card_info
                    opponent_cards_list.append(ps_card_info)

    return {
        "roster": opponent_lineup,
        "cards_list": opponent_cards_list
    }