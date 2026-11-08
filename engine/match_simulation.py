import random

ROTATION_ORDER = [
    "opposite",         # Zone 2 (Front-Right)
    "middle_blocker_1", # Zone 3 (Front-Center)
    "wing_spiker_1",    # Zone 4 (Front-Left)
    "setter",           # Zone 1 (Back-Right / Server)
    "middle_blocker_2", # Zone 6 (Back-Center)
    "wing_spiker_2",    # Zone 5 (Back-Left)
]

POSITION_WEIGHTS = {
    "libero": 2.5,
    "setter": 0.4,
    "wing_spiker": 1.2,
    "opposite": 1.0,
    "middle_blocker": 1.0,
}


def _get_receive_error_message(defender_name: str, source_type: str, source_name: str = None) -> str:
    """Helper to keep reception failure messages uniform and DRY."""
    if source_type == "serve":
        return f"Service Ace by **{source_name}** (**{defender_name}** reception error)."
    else:
        return f"Reception error by **{defender_name}**! Point by **{source_name}**."


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

    # EXPLICIT ERROR CHECK: Steeper curve so elite players drop to the 1.5% error floor
    # Early-Game (200) -> ~9.5% | Mid-game (600) -> ~4.5% | Endgame (1200) -> ~1.5% (Floor)
    error_chance = max(0.015, 0.12 - (serve_power / 8000))

    if random.random() < error_chance:
        return {
            "outcome": "error",
            "message": f"Service error by **{server_name}**! Out of bounds."
        }

    # QUALITY ROLL: Slightly wider variance floor for elites so they can hit explosive Perfects,
    # combined with a stronger tier bias to reward endgame progression.
    variance_factor = max(0.06, 0.12 - (serve_power / 12000))
    tier_bias = serve_power / 15000  # Stronger upward lean for elite cards
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
                  source_type: str, source_name: str = None) -> dict:
    """
    Generalized receive/dig phase for ANY incoming ball (serve, spike, or dump).
    1. Selects a primary defender using heavy flattening weights to keep Libero frequency balanced.
    2. Checks for unforced mental errors.
    3. Checks for power shanks and executes reliable backup dives.
    4. Classifies pass quality.
    """
    formation = get_current_rotation(receiving_team_stats, receiving_rotation_step)
    back_row = formation["back_row"]
    back_row_players = list(back_row.items())

    # 1. HEAVY FLATTENING WEIGHTS (Brings Libero down from ~79% to a balanced ~55-60%)
    weights = [next(w for key, w in POSITION_WEIGHTS.items() if key in slot) for slot, _ in back_row_players]
    primary_slot, primary_card = random.choices(back_row_players, weights=weights, k=1)[0]

    receive_stat = primary_card["receive"]
    defender_name = primary_card["name"]

    receive_tier_bias = receive_stat / 15000
    effective_receive_mean = receive_stat * (1.0 + receive_tier_bias)
    defender_roll = random.gauss(effective_receive_mean, receive_stat * 0.12) * random.uniform(0.80, 1.20)

    # Unforced mental error check
    unforced_error_chance = max(0.012, 0.035 - (receive_stat / 15000))
    if random.random() < unforced_error_chance:
        return {
            "outcome": "error",
            "message": _get_receive_error_message(defender_name, source_type, source_name)
        }

    error_threshold = incoming_power * 0.52
    is_power_error = defender_roll < error_threshold

    # Underdog miracle window
    if is_power_error and incoming_power > (receive_stat * 1.5):
        if random.random() < 0.08:
            is_power_error = False

    if is_power_error:
        is_catastrophic = defender_roll < (error_threshold * 0.60)

        if is_catastrophic:
            return {
                "outcome": "error",
                "message": _get_receive_error_message(defender_name, source_type, source_name)
            }

        # 2. RELIABLE BACKUP DIVE (Guarantees ~45% success rate and passes telemetry keys)
        other_players = [p for p in back_row_players if p[0] != primary_slot]
        sec_weights = [next(w for key, w in POSITION_WEIGHTS.items() if key in slot) for slot, _ in other_players]
        sec_slot, sec_card = random.choices(other_players, weights=sec_weights, k=1)[0]
        sec_name = sec_card["name"]

        backup_success_chance = 0.45

        if random.random() < backup_success_chance:
            return {
                "outcome": "in-play",
                "quality": "poor",
                "pass_modifier": 0.75,
                "message": f"Poor Pass: **{sec_name}** recovers after **{defender_name}** error.",
                "backup_triggered": True,
                "backup_success": True,
                "receiver_slot": sec_slot
            }
        else:
            return {
                "outcome": "error",
                "message": _get_receive_error_message(f"{defender_name}/{sec_name}", source_type, source_name),
                "backup_triggered": True,
                "backup_success": False
            }

    # FIX: Scale incoming power effectiveness based on the defender's mastery
    # High-receive stats (like 1200) naturally absorb and cushion heavy velocity better
    mitigation_factor = min(1.0, 1000 / max(receive_stat, 200))
    adjusted_incoming_power = incoming_power * mitigation_factor

    # Pass quality classification using the balanced power
    ratio = defender_roll / max(adjusted_incoming_power, 1)

    if ratio >= 1.15:
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
            if receive_result["outcome"] == "receive_error":
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