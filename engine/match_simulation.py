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
            "message": f"Serve by **{server_name}** is sent over and kept in play!"
        }


def run_match_simulation(user_stats: dict, opponent_stats: dict) -> dict:
    user_score = 0
    opponent_score = 0

    user_rotation_step = 0
    opp_rotation_step = 0

    serving_team = "user"  # User serves first
    match_log = []

    while user_score < 5 and opponent_score < 5:
        if serving_team == "user":
            # Pass user's rotation and opponent's rotation
            result = serve_phase(user_stats, opponent_stats, user_rotation_step, opp_rotation_step)
        else:
            # Pass opponent's rotation and user's rotation
            result = serve_phase(opponent_stats, user_stats, opp_rotation_step, user_rotation_step)

        match_log.append(result["message"])

        # Temporary resolution logic for the rally based on serve outcome
        if result["outcome"] == "ace":
            if serving_team == "user":
                user_score += 1
            else:
                opponent_score += 1
            # Ace means no side-out change, serving team keeps serving, no rotation

        elif result["outcome"] == "error":
            # Serving team messed up -> Point to the other team + Side-out & Rotate!
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

        else:
            # In play placeholder (we will add the Spike/Block phase here next!)
            # For now, alternate point winner randomly on standard plays
            if random.choice([True, False]):
                if serving_team == "user":
                    user_score += 1
                else:
                    opponent_score += 1
            else:
                if serving_team == "user":
                    opponent_score += 1
                    serving_team = "opponent"
                    opp_rotation_step = (opp_rotation_step + 1) % 6
                else:
                    user_score += 1
                    serving_team = "user"
                    user_rotation_step = (user_rotation_step + 1) % 6

    return {
        "winner": "user" if user_score > opponent_score else "opponent",
        "user_score": user_score,
        "opponent_score": opponent_score,
        "match_log": match_log
    }