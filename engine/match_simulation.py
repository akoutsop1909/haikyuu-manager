import random

ROTATION_ORDER = [
    "opposite",         # Zone 2 (Front-Right)
    "middle_blocker_1", # Zone 3 (Front-Center)
    "wing_spiker_1",    # Zone 4 (Front-Left)
    "setter",           # Zone 1 (Back-Right / Server)
    "middle_blocker_2", # Zone 6 (Back-Center)
    "wing_spiker_2",    # Zone 5 (Back-Left)
]

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


def serve_phase(serving_team_stats: dict, receiving_team_stats: dict, serving_rotation_step: int,
                receiving_rotation_step: int) -> dict:
    serving_formation = get_current_rotation(serving_team_stats, serving_rotation_step)
    server_slot = serving_formation["server_slot"]
    server_card = serving_team_stats[server_slot]
    serve_power = server_card["serve"]
    server_name = server_card["name"]

    # Use the receiving team's actual rotation step instead of hardcoding 0!
    receiving_formation = get_current_rotation(receiving_team_stats, receiving_rotation_step)
    back_row_receivers = receiving_formation["back_row"].values()
    receives = [card["receive"] for card in back_row_receivers]
    best_receive = max(receives)

    # Libero influences 35% of the defense, the overall team average covers 65%
    avg_receive = (best_receive * 0.35) + (sum(receives) * 0.65 / len(receives))

    server_roll = serve_power * random.uniform(0.85, 1.15)
    receiver_roll = avg_receive * random.uniform(0.85, 1.15)

    # STREAMLINED ERROR LOGIC:
    # 1. Normal servers (< 500): ~5% chance to fault on low rolls.
    # 2. Elite/God-tier servers (500+): Rare ~1.5% chance to fault on unluckily low rolls.
    is_error = False
    if serve_power < 500:
        if server_roll < (serve_power * 0.875):
            is_error = True
    else:
        if server_roll < (serve_power * 0.865):
            is_error = True

    if is_error:
        return {
            "outcome": "error",
            "message": f"Service error by **{server_name}**!"
        }
    elif server_roll >= receiver_roll * 1.22:
        return {
            "outcome": "ace",
            "message": f"Service Ace by **{server_name}**!"
        }
    else:
        return {
            "outcome": "in-play",
            "incoming_power": server_roll,
            "server_name": server_name,
            "message": f"Serve by **{server_name}** is sent over and kept in play!"
        }


def receive_phase(incoming_power: float, receiving_team_stats: dict, receiving_rotation_step: int,
                  source_type: str, source_name: str = None) -> dict:
    """
    Generalized receive/dig phase for ANY incoming ball (serve, spike, or dump).
    1. Selects a primary defender from the back row weighted by receive stat.
    2. Checks for a receive/dig error based on defender performance.
    3. Includes a tiny 'miracle scramble' window so underdogs always have a small chance of survival.
    4. Classifies pass quality as Perfect, Good, or Poor, yielding a pass modifier.
    """
    formation = get_current_rotation(receiving_team_stats, receiving_rotation_step)
    back_row = formation["back_row"]
    back_row_players = list(back_row.items())

    weights = [card["receive"] for _, card in back_row_players]
    primary_slot, primary_card = random.choices(back_row_players, weights=weights, k=1)[0]

    receive_stat = primary_card["receive"]
    defender_name = primary_card["name"]

    defender_roll = receive_stat * random.uniform(0.85, 1.15)

    # ERROR CHECK: Standard error threshold
    error_threshold = incoming_power * 0.45
    is_primary_error = defender_roll < error_threshold

    # MIRACLE SCRAMBLE WINDOW: Even in an extreme mismatch, give the underdog
    # a flat ~8% chance of a miraculous hustle save (classic Haikyuu underdog moment!)
    if is_primary_error and incoming_power > (receive_stat * 1.5):
        if random.random() < 0.08:  # 8% miracle survival chance
            is_primary_error = False

    action_label = "Service" if source_type == "serve" else "Attack"
    failure_result = "receive_error"

    if is_primary_error:
        # Determine if it's a catastrophic shank or a playable pop-up
        is_catastrophic = defender_roll < (error_threshold * 0.60)

        if is_catastrophic:
            # Catastrophic: No backup can reach it
            if source_type == "serve" and source_name:
                msg = f"Heavy service completely overpowers **{defender_name}**! Blown away for a Service Ace by **{source_name}**!"
            else:
                scorer_str = f" by **{source_name}**" if source_name else ""
                msg = f"**{action_label}** completely overpowers **{defender_name}**! Unplayable shank! Point{scorer_str}!"
            return {"outcome": failure_result, "message": msg}

        # Close shank: Triggers emergency backup dive
        other_players = [p for p in back_row_players if p[0] != primary_slot]
        if other_players:
            sec_weights = [c["receive"] for _, c in other_players]
            sec_slot, sec_card = random.choices(other_players, weights=sec_weights, k=1)[0]
            sec_stat = sec_card["receive"]
            sec_name = sec_card["name"]

            sec_roll = sec_stat * random.uniform(0.80, 1.15)
            sec_error_threshold = incoming_power * 0.40

            if sec_roll < sec_error_threshold:
                if source_type == "serve" and source_name:
                    msg = f"Service shanked by **{defender_name}**, and **{sec_name}** couldn't reach the emergency recovery in time! Service Ace by **{source_name}**!"
                else:
                    scorer_str = f" by **{source_name}**" if source_name else ""
                    msg = f"**{action_label}** shanked by **{defender_name}**, and **{sec_name}** couldn't reach the emergency save! Point{scorer_str}!"
                return {"outcome": failure_result, "message": msg}
            else:
                msg = f"**{defender_name}** shanks the **{source_type}**, but **{sec_name}** dives for a desperate save! **Poor Pass** scrambled up."
                return {"outcome": "in_play", "quality": "poor", "pass_modifier": 0.75, "message": msg}
        else:
            if source_type == "serve" and source_name:
                msg = f"Service error/shank by **{defender_name}**! Service Ace by **{source_name}**!"
            else:
                scorer_str = f" by **{source_name}**" if source_name else ""
                msg = f"**{action_label}** error/shank by **{defender_name}**! Point{scorer_str}!"
            return {"outcome": failure_result, "message": msg}

    # NO ERROR: Classify pass quality based on performance ratio
    ratio = defender_roll / max(incoming_power, 1)

    if ratio >= 1.15:
        quality = "perfect"
        pass_modifier = 1.25
        message = f"A stellar reception of the **{source_type}** by **{defender_name}**! **Perfect Pass** right on target!"
    elif ratio >= 0.85:
        quality = "good"
        pass_modifier = 1.00
        message = f"Stable control of the **{source_type}** by **{defender_name}**. Clean **Good Pass**."
    else:
        quality = "poor"
        pass_modifier = 0.80
        message = f"Heavy **{source_type}** pushes **{defender_name}** back. A **Poor Pass**, limiting options."

    return {
        "outcome": "in_play",
        "quality": quality,
        "pass_modifier": pass_modifier,
        "message": message
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
        # Execute the serve phase based on who currently holds the serve
        if serving_team == "user":
            result = serve_phase(user_stats, opponent_stats, user_rotation_step, opp_rotation_step)
        else:
            result = serve_phase(opponent_stats, user_stats, opp_rotation_step, user_rotation_step)

        match_log.append(result["message"])

        # Handle direct service aces (serving team scores immediately and keeps the serve)
        if result["outcome"] == "ace":
            if serving_team == "user":
                user_score += 1
            else:
                opponent_score += 1
            # An ace means no side-out change; the serving team continues serving

        # Handle direct service errors (serving team faults, opponent scores + side-out & rotates)
        elif result["outcome"] == "error":
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
            server_name = result.get("server_name")  # Retrieve the active server's name passed from serve_phase

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

            # Check if the receive phase resulted in a shank/error (point to the serving team)
            if receive_result["outcome"] == "receive_error":
                if serving_team == "user":
                    user_score += 1
                else:
                    opponent_score += 1
                # TODO: Add side-out and rotation logic here for receive errors if desired!
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