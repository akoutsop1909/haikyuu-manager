# ==============================================================================
# 1. CONSTANTS & GLOBAL WEIGHTS
# ==============================================================================
import random

ROTATION_ORDER = [
    "opposite",         # Zone 2 (Front-Right)
    "middle_blocker_1", # Zone 3 (Front-Center)
    "wing_spiker_1",    # Zone 4 (Front-Left)
    "setter",           # Zone 1 (Back-Right / Server)
    "middle_blocker_2", # Zone 6 (Back-Center)
    "wing_spiker_2",    # Zone 5 (Back-Left)
]

RECEIVE_WEIGHTS = {
    "libero": 2.5,
    "setter": 0.4,
    "wing_spiker": 1.2,
    "opposite": 1.0,
    "middle_blocker": 1.0,
    "pinch_server": 0.8,  # Lower weight since they are serving specialists
}

SPIKE_WEIGHTS = {
    ("wing_spiker", False): 1.5,
    ("opposite", False): 1.5,
    ("middle_blocker", False): 1.0,

    ("wing_spiker", True): 0.8,  # Back-row pipe attack!
    ("opposite", True): 0.8,
    ("middle_blocker", True): 0.3,
}

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def calculate_receive_error_chance(receive_stat: float, incoming_power: float, fatigue_tier: int) -> float:
    power_disparity = incoming_power / max(receive_stat, 1)
    base_mismatch_error = 0.03 + (max(0.0, power_disparity - 1.0) * 0.065)
    error_chance = max(0.02, base_mismatch_error) + (fatigue_tier * 0.30)

    # --- UNDERDOG MERCY / MIRACLE BUFFER ---
    # If facing overwhelming power, give low-stat defenders a tiny break
    if incoming_power > (receive_stat * 1.5):
        error_chance *= 0.90  # Reduces error chance by 10% for severe underdogs

    return error_chance


def _get_receive_out_message(defender_name: str, source_type: str, source_name: str) -> str:
    """Helper to keep reception/dig failure messages uniform and authentic."""
    if source_type == "serve":
        return f"Service ace by **{source_name}** (**{defender_name}** reception error)."
    elif source_type == "dump":
        return f"Setter dump kill by **{source_name}** (**{defender_name}** reception error)."
    else:
        return f"Spike kill by **{source_name}** (**{defender_name}** reception error)."


def _get_player_role(slot_name: str) -> str:
    """Helper to extract the base player role from a court slot string."""
    for role in ["wing_spiker", "opposite", "middle_blocker"]:
        if role in slot_name:
            return role
    return ""


def _handle_side_out(team_stats: dict, rotation_step: int) -> tuple[int, bool, str]:
    """Advances rotation, activates pinch server if MB1 is now serving, and formats log."""
    new_rotation_step = (rotation_step + 1) % 6

    # Check who the new server slot is without pinch active first
    base_formation = get_current_rotation(team_stats, new_rotation_step, pinch_active=False)
    server_slot = base_formation["server_slot"]

    new_pinch_active = (server_slot == "middle_blocker_1") and ("pinch_server" in team_stats)

    formation = get_current_rotation(team_stats, new_rotation_step, pinch_active=new_pinch_active)
    server_card = formation["back_row"][server_slot]
    server_name = server_card["name"]

    message = f"🔄 Side-out! **{server_name}** rotates to the service line."
    return new_rotation_step, new_pinch_active, message

# ==============================================================================
# 3. ROTATION MANAGEMENT & MATCH PHASES
# ==============================================================================
def get_current_rotation(team_stats: dict, rotation_step: int, pinch_active: bool = False) -> dict:
    """Calculates court rotation, handles libero rules, and keeps pinch server in if active."""
    offset = rotation_step % len(ROTATION_ORDER)
    current_lineup = ROTATION_ORDER[-offset:] + ROTATION_ORDER[:-offset]

    front_slots = current_lineup[0:3]
    back_slots = current_lineup[3:6]

    front_row = {slot: team_stats[slot] for slot in front_slots}
    back_row = {slot: team_stats[slot] for slot in back_slots}

    server_slot = back_slots[0]

    # --- PINCH SERVER SUBSTITUTION LOGIC ---
    if pinch_active and server_slot == "middle_blocker_1" and "pinch_server" in team_stats:
        back_row[server_slot] = team_stats["pinch_server"]
        is_pinch_active = True
    else:
        is_pinch_active = False

    # Libero Substitution Rule (unchanged)
    for slot in back_slots:
        if "middle_blocker" in slot:
            if slot == server_slot:
                break
            else:
                back_row["libero"] = team_stats["libero"]
                del back_row[slot]
                break

    return {
        "front_row": front_row,
        "back_row": back_row,
        "server_slot": server_slot,
        "is_pinch_active": is_pinch_active
    }


def serve_phase(serving_team_stats: dict, serving_rotation_step: int, pinch_active: bool = False) -> dict:
    serving_formation = get_current_rotation(serving_team_stats, serving_rotation_step, pinch_active=pinch_active)
    server_slot = serving_formation["server_slot"]

    # Pulls the active server card (automatically grabs pinch_server if pinch_active is True)
    server_card = serving_formation["back_row"][server_slot]
    serve_power = server_card["serve"]
    server_name = server_card["name"]

    out_chance = max(0.045, 0.14 - (serve_power / 7000))
    if random.random() < out_chance:
        return {
            "outcome": "out",
            "message": f"Service error by **{server_name}**! Out of bounds."
        }

    variance_factor = max(0.08, 0.14 - (serve_power / 10000))
    tier_bias = serve_power / 18000
    effective_mean = serve_power * (1.0 + tier_bias)
    server_roll = random.gauss(effective_mean, serve_power * variance_factor)
    ratio = server_roll / max(serve_power, 1)

    if ratio >= 1.08:
        quality = "perfect"
        incoming_power = server_roll * 1.20
    elif ratio >= 0.93:
        quality = "good"
        incoming_power = server_roll
    else:
        quality = "poor"
        incoming_power = server_roll * 0.80

    return {
        "outcome": "in-play",
        "incoming_power": incoming_power,
        "quality": quality,
        "server_name": server_name,
        "message": f"A **{quality}** serve by **{server_name}**."
    }


def receive_phase(incoming_power: float, receiving_team_stats: dict, receiving_rotation_step: int,
                  source_type: str, source_name: str, net_cross_count: int = 1,
                  pinch_active: bool = False) -> dict:
    formation = get_current_rotation(receiving_team_stats, receiving_rotation_step, pinch_active=pinch_active)
    back_row = formation["back_row"]
    back_row_players = list(back_row.items())

    # --- UPDATED WEIGHT LOOKUP ---
    weights = []
    for slot, card in back_row_players:
        # Check if this specific card is the pinch server
        if "pinch_server" in receiving_team_stats and card == receiving_team_stats["pinch_server"]:
            weights.append(RECEIVE_WEIGHTS["pinch_server"])
        else:
            # Fallback to standard slot-based role weights
            weight = next((w for key, w in RECEIVE_WEIGHTS.items() if key in slot), 1.0)
            weights.append(weight)

    primary_slot, primary_card = random.choices(back_row_players, weights=weights, k=1)[0]

    receive_stat = primary_card["receive"]
    defender_name = primary_card["name"]

    # Rally fatigue calculation
    fatigue_tier = max(0, (net_cross_count - 1) // 2)
    fatigue_multiplier = 1.0 + (fatigue_tier * 0.40)

    # Unforced mental out check (tuned floor ensures endgame out stay >= 1.4%)
    unforced_out_chance = max(0.014, (0.028 - (receive_stat / 30000))) * fatigue_multiplier
    if random.random() < unforced_out_chance:
        return {
            "outcome": "out",
            "message": _get_receive_out_message(defender_name, source_type, source_name)
        }

    # --- DYNAMIC RECEIVE ERROR CHECK ---
    dynamic_error_chance = calculate_receive_error_chance(receive_stat, incoming_power, fatigue_tier)

    if random.random() < dynamic_error_chance:
        # When a receive error triggers, determine if it's an immediate catastrophic error
        # or if a teammate gets a chance to trigger a backup dive!
        is_catastrophic = random.random() < (0.50 + (fatigue_tier * 0.05))

        if is_catastrophic:
            return {
                "outcome": "out",
                "message": _get_receive_out_message(defender_name, source_type, source_name)
            }

        # --- BACKUP DIVE MECHANIC ---
        other_players = [p for p in back_row_players if p[0] != primary_slot]
        pinch_card = receiving_team_stats.get("pinch_server")
        sec_weights = [
            RECEIVE_WEIGHTS["pinch_server"]
            if pinch_card is not None and card == pinch_card
            else next((w for key, w in RECEIVE_WEIGHTS.items() if key in slot), 1.0)
            for slot, card in other_players
        ]
        sec_slot, sec_card = random.choices(other_players, weights=sec_weights, k=1)[0]

        sec_receive_stat = sec_card["receive"]
        sec_name = sec_card["name"]

        # Convert error chance into a success probability (lower error chance = higher success)
        sec_error_chance = calculate_receive_error_chance(sec_receive_stat, incoming_power, fatigue_tier)
        backup_success_chance = max(0.15, min(0.85, 0.70 - sec_error_chance))

        if random.random() < backup_success_chance:
            return {
                "outcome": "in-play",
                "quality": "poor",
                "pass_modifier": max(0.50, 0.75 - (fatigue_tier * 0.05)),
                "message": f"Poor Pass: **{sec_name}** recovers after **{defender_name}** error.",
                "receiver_slot": sec_slot,
                "telemetry": {
                    "backup_triggered": True,
                    "backup_success": True
                }
            }
        else:
            return {
                "outcome": "out",
                "message": _get_receive_out_message(f"{defender_name}/{sec_name}", source_type, source_name),
                "telemetry": {
                    "backup_triggered": True,
                    "backup_success": False
                }
            }

    # --- STANDARD PERFORMANCE ROLL (For Perfect, Good, Poor passes) ---
    effective_mean = receive_stat * (1.0 + (receive_stat / 30000))
    relative_variance = max(0.12, 0.20 - (receive_stat / 10000))
    defender_roll = random.gauss(effective_mean, receive_stat * relative_variance) * random.uniform(0.80, 1.20)

    ratio = (defender_roll / max(receive_stat, 1)) / fatigue_multiplier

    if ratio >= 1.10:
        quality = "perfect"
        pass_modifier = 1.25
    elif ratio >= 0.85:
        quality = "good"
        pass_modifier = 1.00
    else:
        quality = "poor"
        pass_modifier = 0.80

    return {
        "outcome": "in-play",
        "quality": quality,
        "pass_modifier": pass_modifier,
        "receiver_slot": primary_slot,
        "message": f"A **{quality}** pass by **{defender_name}**."
    }

def set_phase(pass_quality: str, pass_modifier: float, receiver_slot: str,
              team_stats: dict, rotation_step: int, pinch_active: bool = False) -> dict:
    """Simulates the setting phase, supporting pinch servers during emergency setter lookups."""
    designated_setter = team_stats.get("setter")

    # --- SETTER SELECTION LOGIC ---
    if receiver_slot != "setter":
        setter_card = designated_setter
        set_stat = setter_card["set"]
    else:
        # Edge case: the setter received the ball and cannot set!
        # Pass is_serving down here so the pinch server stays on the court!
        formation = get_current_rotation(team_stats, rotation_step, pinch_active=pinch_active)
        active_players = {**formation["front_row"], **formation["back_row"]}

        if "libero" in active_players:
            setter_card = active_players["libero"]
            set_stat = setter_card["set"]
        else:
            _, setter_card = max(
                ((slot, card) for slot, card in active_players.items() if slot != "setter"),
                key=lambda item: item[1]["set"]
            )
            if setter_card.get("position") == "S":
                set_stat = setter_card["set"]
            else:
                set_stat = int(max(setter_card["set"], designated_setter["set"] * 0.5))

    setter_name = setter_card["name"]

    # --- SETTER DUMP CHECK (The Wildcard) ---
    if receiver_slot != "setter" and pass_quality == "perfect" and random.random() < 0.12:
        dump_tier_bias = set_stat / 15000
        effective_mean = set_stat * (1.0 + dump_tier_bias)

        # Roll normally without inflating the raw pool with a flat multiplier
        base_dump_roll = random.gauss(effective_mean, set_stat * 0.12) * random.uniform(0.80, 1.20)

        # Calculate ratio based on the roll, then factor the pass modifier into the effectiveness
        raw_ratio = base_dump_roll / max(set_stat, 1)
        ratio = raw_ratio * (pass_modifier / 1.25)  # Scales properly so low rolls can hit "poor"

        if ratio >= 1.12:
            quality = "perfect"
            incoming_power = base_dump_roll * 1.25
        elif ratio >= 0.84:
            quality = "good"
            incoming_power = base_dump_roll
        else:
            quality = "poor"  # This will now actually trigger on lower rolls!
            incoming_power = base_dump_roll * 0.75

        return {
            "outcome": "incoming_dump",
            "source_type": "dump",
            "quality": quality,
            "incoming_power": incoming_power,
            "source_name": setter_name,
            "message": f"A **{quality}** setter dump by **{setter_name}**!"
        }

    # --- STANDARD SET PERFORMANCE ROLL (Balanced Tail Protection) ---
    # 1. Slightly softer mean shift (divisor 30000) to keep the endgame
    #    perfect rate locked right around ~36-37%.
    effective_mean = set_stat * (1.0 + (set_stat / 30000))

    # 2. Adjusted variance floor (0.12) so the endgame poor rate rises
    #    back up to ~14% (matching receive) instead of collapsing to 9.9%.
    relative_variance = max(0.12, 0.20 - (set_stat / 10000))

    base_roll = random.gauss(effective_mean, set_stat * relative_variance) * random.uniform(0.80, 1.20)
    set_roll = base_roll * pass_modifier

    ratio = set_roll / max(set_stat, 1)

    if ratio >= 1.10:
        quality = "perfect"
        attack_modifier = 1.30
    elif ratio >= 0.85:
        quality = "good"
        attack_modifier = 1.00
    else:
        quality = "poor"
        attack_modifier = 0.75

    return {
        "outcome": "in-play",
        "quality": quality,
        "attack_modifier": attack_modifier,
        "setter_name": setter_name,
        "message": f"A **{quality}** set by **{setter_name}**."
    }


def spike_phase(attack_modifier: float, setter_name: str, attacking_team_stats: dict,
                rotation_step: int, pinch_active: bool = False) -> dict:
    formation = get_current_rotation(attacking_team_stats, rotation_step, pinch_active=pinch_active)

    # Get the pinch server card if it exists
    pinch_card = attacking_team_stats.get("pinch_server")

    candidates = [
        ((slot, card), SPIKE_WEIGHTS[(_get_player_role(slot), is_back_row)])
        for row_type, is_back_row in [(formation["front_row"], False), (formation["back_row"], True)]
        for slot, card in row_type.items()
        if card["name"] != setter_name
           and slot != "libero"
           and "setter" not in slot
           and card != pinch_card  # <--- THIS LINE PREVENTS THE PINCH SERVER FROM SPIKING!
           and (_get_player_role(slot), is_back_row) in SPIKE_WEIGHTS
    ]

    # Unzip directly into population and weights for random.choices
    spiker_choices, weights = zip(*candidates)
    spiker_slot, spiker_card = random.choices(spiker_choices, weights=weights, k=1)[0]

    spike_stat = spiker_card["spike"]
    spiker_name = spiker_card["name"]

    # --- CONTINUOUS STAT SCALING ---
    effective_mean = spike_stat * (1.0 + (spike_stat / 30000))
    relative_variance = max(0.12, 0.20 - (spike_stat / 10000))

    # Dampen the attack modifier so it doesn't entirely dictate the outcome
    dampened_modifier = 1.0 + (attack_modifier - 1.0) * 0.5
    base_spike_roll = random.gauss(effective_mean, spike_stat * relative_variance) * random.uniform(0.80, 1.20)
    spike_roll = base_spike_roll * dampened_modifier

    # --- QUALITY EVALUATION RATIO ---
    ratio = spike_roll / max(spike_stat, 1)

    if ratio >= 1.10:
        quality = "perfect"
        incoming_power = spike_roll * 1.30
    elif ratio >= 0.85:
        quality = "good"
        incoming_power = spike_roll
    else:
        quality = "poor"
        incoming_power = spike_roll * 0.75

    return {
        "outcome": "in-play",
        "quality": quality,
        "incoming_power": incoming_power,
        "spiker_name": spiker_name,
        "message": f"A **{quality}** spike by **{spiker_name}**!"
    }


def block_phase(incoming_power: float, defending_team_stats: dict, defending_rotation_step: int,
                spiker_name: str) -> dict:
    """
    Simulates the block phase where all front-row players participate,
    but the Middle Blocker heavily anchors and influences the block stat.
    """
    formation = get_current_rotation(defending_team_stats, defending_rotation_step)
    front_row = formation["front_row"]
    front_row_players = list(front_row.items())

    # Isolate the Middle Blocker and the other two front-row players cleanly
    mb_card = next(card for slot, card in front_row_players if "middle_blocker" in slot)
    mb_stat = mb_card["block"]
    blocker_name = mb_card["name"]
    other_stats = [card["block"] for slot, card in front_row_players if "middle_blocker" not in slot]

    # Calculate blended stat (MB = 70%, Others = 30%)
    effective_block_stat = (mb_stat * 0.70) + ((sum(other_stats) / len(other_stats)) * 0.30)

    # --- DYNAMIC BLOCK-OUT CHECK (Balanced Mismatch Scaling) ---
    power_disparity = incoming_power / max(effective_block_stat, 1)

    # Scale much more gently (e.g., multiplier 0.015 instead of 0.12)
    dynamic_out_chance = max(0.015, 0.03 + (max(0.0, power_disparity - 1.0) * 0.018))

    if random.random() < dynamic_out_chance:
        return {
            "outcome": "out",
            "message": f"Block out! Point by **{spiker_name}**."
        }

    # Block Performance Roll
    effective_mean = effective_block_stat * (1.0 + (effective_block_stat / 30000))
    relative_variance = max(0.12, 0.20 - (effective_block_stat / 10000))
    block_roll = random.gauss(effective_mean, effective_block_stat * relative_variance) * random.uniform(0.80, 1.20)

    ratio = block_roll / max(effective_block_stat, 1)

    # Quality Tiers & Stuff Block Check
    if ratio >= 1.10:
        quality = "perfect"

        power_advantage = block_roll / max(incoming_power, 1)
        stuff_chance = min(0.65, max(0.15, 0.25 * power_advantage))

        if random.random() < stuff_chance:
            return {
                "outcome": "kill_block",
                "quality": quality,
                "message": f"Kill block by **{blocker_name}** and the front row!"
            }

        power_multiplier = 0.25

    elif ratio >= 0.85:
        quality = "good"
        power_multiplier = 0.55
    else:
        quality = "poor"
        power_multiplier = 0.85

    mitigated_power = incoming_power * power_multiplier

    return {
        "outcome": "in-play",
        "quality": quality,
        "mitigated_power": mitigated_power,
        "spiker_name": spiker_name,
        "message": f"A **{quality}** block by **{blocker_name}**!"
    }


# ==============================================================================
# 4. MATCH ORCHESTRATION / LOOP
# ==============================================================================
def simulate_single_rally(user_stats: dict, opponent_stats: dict, serving_team: str,
                          user_rotation_step: int, opp_rotation_step: int,
                          user_pinch_active: bool = False, opp_pinch_active: bool = False,
                          audit_dict: dict = None,
                          debug: bool = False) -> dict:
    match_log = []
    net_cross_count = 1

    # --- 1. SERVE PHASE ---
    if serving_team == "user":
        serve_res = serve_phase(user_stats, user_rotation_step, pinch_active=user_pinch_active)
        attacking_team = "user"
        defending_team = "opponent"
        def_stats = opponent_stats
        def_rot = opp_rotation_step
        def_pinch = opp_pinch_active
    else:
        serve_res = serve_phase(opponent_stats, opp_rotation_step, pinch_active=opp_pinch_active)
        attacking_team = "opponent"
        defending_team = "user"
        def_stats = user_stats
        def_rot = user_rotation_step
        def_pinch = user_pinch_active

    if serve_res["outcome"] == "out":
        match_log.append(serve_res["message"])
        scoring_team = "opponent" if serving_team == "user" else "user"
        return {"scoring_team": scoring_team, "match_log": match_log}

    if debug:
        match_log.append(serve_res["message"])

    incoming_power = serve_res["incoming_power"]
    source_type = "serve"
    source_name = serve_res["server_name"]

    # --- RALLY LOOP ---
    while True:
        # --- 2. RECEIVE PHASE ---
        receive_res = receive_phase(
            incoming_power, def_stats, def_rot, source_type, source_name,
            net_cross_count, pinch_active=def_pinch
        )

        if audit_dict is not None:
            if receive_res["outcome"] == "out":
                audit_dict["receive"]["out"] += 1
            else:
                audit_dict["receive"][receive_res["quality"]] += 1

        if receive_res["outcome"] == "out":
            match_log.append(receive_res["message"])
            scoring_team = attacking_team
            return {"scoring_team": scoring_team, "match_log": match_log}

        if debug:
            match_log.append(receive_res["message"])

        pass_quality = receive_res["quality"]
        pass_modifier = receive_res["pass_modifier"]
        receiver_slot = receive_res["receiver_slot"]

        # Swap roles for transition offense
        attacking_team, defending_team = defending_team, attacking_team
        atk_stats = user_stats if attacking_team == "user" else opponent_stats
        atk_rot = user_rotation_step if attacking_team == "user" else opp_rotation_step
        atk_pinch = user_pinch_active if attacking_team == "user" else opp_pinch_active

        def_stats = user_stats if defending_team == "user" else opponent_stats
        def_rot = user_rotation_step if defending_team == "user" else opp_rotation_step
        def_pinch = user_pinch_active if defending_team == "user" else opp_pinch_active

        # --- 3. SET PHASE ---
        set_res = set_phase(pass_quality, pass_modifier, receiver_slot, atk_stats, atk_rot, pinch_active=atk_pinch)

        if audit_dict is not None:
            if set_res["outcome"] == "incoming_dump":
                audit_dict["set"]["incoming_dump"] += 1
            else:
                audit_dict["set"][set_res["quality"]] += 1

        if set_res["outcome"] == "incoming_dump":
            if debug:
                match_log.append(set_res["message"])
            net_cross_count += 1
            incoming_power = set_res["incoming_power"]
            source_type = set_res["source_type"]
            source_name = set_res["source_name"]
            continue

        if debug:
            match_log.append(set_res["message"])

        # --- 4. SPIKE PHASE ---
        spike_res = spike_phase(set_res["attack_modifier"], set_res["setter_name"], atk_stats, atk_rot, pinch_active=atk_pinch)

        if audit_dict is not None:
            audit_dict["spike"][spike_res["quality"]] += 1

        if debug:
            match_log.append(spike_res["message"])

        net_cross_count += 1
        incoming_power = spike_res["incoming_power"]
        source_type = "spike"
        source_name = spike_res["spiker_name"]

        # --- 5. BLOCK PHASE ---
        block_res = block_phase(incoming_power, def_stats, def_rot, source_name)

        if audit_dict is not None:
            audit_dict["block_outcome"][block_res["outcome"]] += 1
            if "quality" in block_res:
                audit_dict["block_quality"][block_res["quality"]] += 1

        if block_res["outcome"] == "out":
            match_log.append(block_res["message"])
            scoring_team = attacking_team
            return {"scoring_team": scoring_team, "match_log": match_log}

        elif block_res["outcome"] == "kill_block":
            match_log.append(block_res["message"])
            scoring_team = defending_team
            return {"scoring_team": scoring_team, "match_log": match_log}

        else:
            if debug:
                match_log.append(block_res["message"])
            incoming_power = block_res["mitigated_power"]
            continue

    return {"scoring_team": "user", "match_log": match_log}


def run_match_simulation(user_stats: dict, opponent_stats: dict, debug: bool = False) -> dict:
    user_score = 0
    opponent_score = 0
    user_rotation_step = 0
    opp_rotation_step = 0
    user_pinch_active = False
    opp_pinch_active = False
    serving_team = "user"
    match_log = []

    while user_score < 5 and opponent_score < 5:
        rally_res = simulate_single_rally(
            user_stats, opponent_stats, serving_team,
            user_rotation_step, opp_rotation_step,
            user_pinch_active=user_pinch_active,
            opp_pinch_active=opp_pinch_active,
            debug=debug
        )
        scoring_team = rally_res["scoring_team"]
        emoji = "🔵" if scoring_team == "user" else "🔴"

        if rally_res["match_log"]:
            if debug:
                for line in rally_res["match_log"][:-1]:
                    match_log.append(f"> {line}")
            scoring_line = rally_res["match_log"][-1]
            match_log.append(f"{emoji} {scoring_line}")

        if scoring_team == "user":
            user_score += 1
        else:
            opponent_score += 1

        if scoring_team != serving_team:
            # The team that just lost the serve no longer has their pinch server active
            if serving_team == "user":
                user_pinch_active = False
            else:
                opp_pinch_active = False

            serving_team = scoring_team
            if scoring_team == "user":
                user_rotation_step, user_pinch_active, log_msg = _handle_side_out(user_stats, user_rotation_step)
                match_log.append(log_msg)
            else:
                opp_rotation_step, opp_pinch_active, log_msg = _handle_side_out(opponent_stats, opp_rotation_step)
                match_log.append(log_msg)

    return {
        "user_score": user_score,
        "opponent_score": opponent_score,
        "match_log": match_log
    }