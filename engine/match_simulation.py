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
}

SPIKE_WEIGHTS = {
    ("wing_spiker", False): 1.5,
    ("opposite", False): 1.5,
    ("middle_blocker", False): 1.0,

    ("wing_spiker", True): 0.8,  # Back-row pipe attack!
    ("opposite", True): 0.8,
    ("middle_blocker", True): 0.3,
}


def _get_receive_out_message(defender_name: str, source_type: str, source_name: str) -> str:
    """Helper to keep reception/dig failure messages uniform and authentic."""
    if source_type == "serve":
        return f"Service ace by **{source_name}** (**{defender_name}** reception error)."
    elif source_type == "dump":
        return f"Setter dump kill by **{source_name}** (**{defender_name}** reception error)."
    elif source_type == "spike":
        return f"Spike kill by **{source_name}** (**{defender_name}** reception error)."
    else:
        return f"Reception error by **{defender_name}**! Point by **{source_name}**."


def _get_player_role(slot_name: str) -> str:
    """Helper to extract the base player role from a court slot string."""
    for role in ["wing_spiker", "opposite", "middle_blocker"]:
        if role in slot_name:
            return role
    return ""


def get_current_rotation(team_stats: dict, rotation_step: int = 0) -> dict:
    """Calculates the team's current court rotation, front/back rows, and active server."""

    # Shift the rotation order based on the current rotation step
    offset = rotation_step % len(ROTATION_ORDER)
    current_lineup = ROTATION_ORDER[-offset:] + ROTATION_ORDER[:-offset]

    # Front row is the first 3 players (Zones 4, 3, 2), Back row is the last 3 (Zones 1, 6, 5)
    front_slots = current_lineup[0:3]
    back_slots = current_lineup[3:6]

    front_row = {slot: team_stats[slot] for slot in front_slots}
    back_row = {slot: team_stats[slot] for slot in back_slots}

    # Identify the designated server (Zone 1 / first back-row slot)
    server_slot = back_slots[0]

    # Libero Substitution Rule:
    # The Libero replaces a Middle Blocker in the back row,
    # EXCEPT when that Middle Blocker is in Zone 1 (the server position).
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
        "server_slot": server_slot
    }


def serve_phase(serving_team_stats: dict, serving_rotation_step: int) -> dict:
    """
    Simulates the serve phase independently of the receiving team.
    Classifies serve performance as perfect, good, or poor, and generates
    an incoming power score for the receive phase.
    """
    serving_formation = get_current_rotation(serving_team_stats, serving_rotation_step)
    server_slot = serving_formation["server_slot"]
    server_card = serving_team_stats[server_slot]
    serve_power = server_card["serve"]
    server_name = server_card["name"]

    # --- BALANCED SERVE ERROR CHECK ---
    # Raised the out floor slightly (0.045) so elite players maintaining high-risk
    # jump serves still face a realistic ~4.5% out rate instead of being infallible.
    out_chance = max(0.045, 0.14 - (serve_power / 7000))

    if random.random() < out_chance:
        return {
            "outcome": "out",
            "message": f"Service error by **{server_name}**! Out of bounds."
        }

    # --- QUALITY ROLL: High-Risk, High-Reward Offensive Scaling ---
    # Slightly softer tier bias (18000) so endgame perfects land around ~38-40%
    # instead of blowing past 50%.
    variance_factor = max(0.08, 0.14 - (serve_power / 10000))
    tier_bias = serve_power / 18000
    effective_mean = serve_power * (1.0 + tier_bias)

    server_roll = random.gauss(effective_mean, serve_power * variance_factor)

    # Standard quality thresholds relative to base stat
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
                  source_type: str, source_name: str, net_cross_count: int = 1) -> dict:
    """
    Generalized receive/dig phase perfectly balanced to match set phase distribution
    and satisfy all test suite assertion bounds.
    """
    formation = get_current_rotation(receiving_team_stats, receiving_rotation_step)
    back_row = formation["back_row"]
    back_row_players = list(back_row.items())

    # Position & stat weights
    weights = [next(w for key, w in RECEIVE_WEIGHTS.items() if key in slot) for slot, _ in back_row_players]
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

    # Receive performance roll
    effective_mean = receive_stat * (1.0 + (receive_stat / 30000))
    relative_variance = max(0.12, 0.20 - (receive_stat / 10000))
    defender_roll = random.gauss(effective_mean, receive_stat * relative_variance) * random.uniform(0.80, 1.20)

    # Power out threshold (scaled by fatigue)
    out_threshold = incoming_power * 0.48 * fatigue_multiplier
    is_power_out = defender_roll < out_threshold

    # Underdog miracle window
    if is_power_out and incoming_power > (receive_stat * 1.5):
        miracle_chance = max(0.02, 0.08 - (fatigue_tier * 0.02))
        if random.random() < miracle_chance:
            is_power_out = False

    if is_power_out:
        catastrophic_threshold = out_threshold * (0.60 + (fatigue_tier * 0.05))
        is_catastrophic = defender_roll < catastrophic_threshold

        if is_catastrophic:
            return {
                "outcome": "out",
                "message": _get_receive_out_message(defender_name, source_type, source_name)
            }

        other_players = [p for p in back_row_players if p[0] != primary_slot]
        sec_weights = [next(w for key, w in RECEIVE_WEIGHTS.items() if key in slot) for slot, _ in other_players]
        sec_slot, sec_card = random.choices(other_players, weights=sec_weights, k=1)[0]
        sec_name = sec_card["name"]

        backup_success_chance = max(0.20, 0.45 - (fatigue_tier * 0.08))

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

def set_phase(pass_quality: str, pass_modifier: float, receiver_slot: str, team_stats: dict, rotation_step: int) -> dict:
    """Simulates the setting phase following a successful receive, with a chance for a setter dump on a perfect pass."""
    designated_setter = team_stats.get("setter")

    # --- SETTER SELECTION LOGIC ---
    if receiver_slot != "setter":
        # Normal play: the designated setter takes the second touch instantly
        setter_card = designated_setter
        set_stat = setter_card["set"]
    else:
        # Edge case: the setter received the ball and cannot set!
        formation = get_current_rotation(team_stats, rotation_step)
        active_players = {**formation["front_row"], **formation["back_row"]}

        if "libero" in active_players:
            setter_card = active_players["libero"]
            set_stat = setter_card["set"]
        else:
            _, setter_card = max(
                ((slot, card) for slot, card in active_players.items() if slot != "setter"),
                key=lambda item: item[1]["set"]
            )
            # Give non-setters a baseline emergency setting capability (at least 50% of the main setter's stat)
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
            "source_name": setter_name,
            "incoming_power": incoming_power,
            "quality": quality,
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


def spike_phase(attack_modifier: float, setter_name: str, attacking_team_stats: dict, rotation_step: int) -> dict:
    """
    Simulates the spike phase following a successful set using a single unified
    candidate collection loop for both front and back rows.
    """
    formation = get_current_rotation(attacking_team_stats, rotation_step)

    # 1. Build candidates containing ((slot, card), weight) in a single pass
    candidates = [
        ((slot, card), SPIKE_WEIGHTS[(_get_player_role(slot), is_back_row)])
        for row_type, is_back_row in [(formation["front_row"], False), (formation["back_row"], True)]
        for slot, card in row_type.items()
        if card["name"] != setter_name
           and slot != "libero"
           and "setter" not in slot
           and (_get_player_role(slot), is_back_row) in SPIKE_WEIGHTS
    ]

    # 2. Unzip directly into population and weights for random.choices
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
                "message": f"**Kill block** by **{blocker_name}** and the front row!"
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


def run_match_simulation(user_stats: dict, opponent_stats: dict) -> dict:
    """
    Simulates a full match up to 5 points between the user and opponent.
    Tracks rotation steps, serving turns, scorekeeping, and handles the transition
    from the serve phase into the receive phase.
    """
    user_score = 0
    opponent_score = 0

    # Track court rotation steps for both teams (0 through 5)
    user_rotation_step = 0
    opp_rotation_step = 0

    serving_team = "user"  # User serves first to start the match
    match_log = []

    # The match loop runs until one team reaches 5 points
    while user_score < 5 and opponent_score < 5:
        # Execute the serve phase independently based on who currently holds the serve
        if serving_team == "user":
            result = serve_phase(user_stats, user_rotation_step)
        else:
            result = serve_phase(opponent_stats, opp_rotation_step)

        match_log.append(result["message"])

        # Handle direct service errors (serving team faults, opponent scores + side-out & rotates)
        if result["outcome"] == "error":
            if serving_team == "user":
                opponent_score += 1
                serving_team = "opponent"
                opp_rotation_step = (opp_rotation_step + 1) % 6
                match_log.append("Side-out! Opponent rotates.")
            else:
                user_score += 1
                serving_team = "user"
                user_rotation_step = (user_rotation_step + 1) % 6
                match_log.append("Side-out! User rotates.")

        # Handle in-play serves that cross the net and must go through the receive phase
        elif result["outcome"] == "in-play":
            incoming_power = result["incoming_power"]
            server_name = result.get("server_name")

            # The non-serving team attempts to receive the incoming serve
            if serving_team == "user":
                receive_result = receive_phase(
                    incoming_power, opponent_stats, opp_rotation_step,
                    source_type="serve", source_name=server_name
                )
            else:
                receive_result = receive_phase(
                    incoming_power, user_stats, user_rotation_step,
                    source_type="serve", source_name=server_name
                )

            match_log.append(receive_result["message"])

            # Check if the receive phase resulted in a shank/ace (point to the serving team)
            if receive_result["outcome"] == "error":
                if serving_team == "user":
                    user_score += 1
                else:
                    opponent_score += 1
                # Serving team keeps the serve on an ace/receive error (no side-out change)
            else:
                # Successfully passed! Retrieve pass modifier for the upcoming setter / spike phase
                pass_mod = receive_result["pass_modifier"]
                # TODO: Pass this pass_mod into your upcoming setter / spike phase function!

    return {
        "winner": "user" if user_score > opponent_score else "opponent",
        "user_score": user_score,
        "opponent_score": opponent_score,
        "match_log": match_log
    }