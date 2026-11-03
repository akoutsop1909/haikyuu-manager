import random

# Standard clockwise rotation order starting from Front-Left (Zone 4) -> ... -> Zone 1 (Server)
ROTATION_ORDER = [
    "wing_spiker_1",   # Front Left (Zone 4)
    "middle_blocker_1",# Front Center (Zone 3)
    "opposite",        # Front Right (Zone 2)
    "setter",          # Back Right / Server (Zone 1)
    "middle_blocker_2",# Back Center (Zone 6)
    "wing_spiker_2",   # Back Left (Zone 5)
]

def get_current_rotation(team_stats: dict, rotation_step: int = 0) -> dict:
    """
    Calculates the team's current court rotation, front/back rows,
    active server, and Libero substitutions based on the rotation step (0-5).
    """
    # Shift the rotation order based on the current rotation step
    offset = rotation_step % len(ROTATION_ORDER)
    current_lineup = ROTATION_ORDER[offset:] + ROTATION_ORDER[:offset]

    # Front row is the first 3 players (Zones 4, 3, 2), Back row is the last 3 (Zones 1, 6, 5)
    front_slots = current_lineup[0:3]
    back_slots = current_lineup[3:6]

    front_row = {slot: team_stats[slot] for slot in front_slots}
    back_row = {slot: team_stats[slot] for slot in back_slots}

    # Identify the designated server (Zone 1 / first back-row slot) BEFORE libero substitution
    server_slot = back_slots[0]

    # Libero Substitution Rule:
    # The Libero replaces whichever Middle Blocker has rotated into the back row.
    for slot in back_slots:
        if "middle_blocker" in slot:
            back_row["libero"] = team_stats["libero"]
            del back_row[slot]
            break

    return {
        "front_row": front_row,
        "back_row": back_row,
        "server_slot": server_slot
    }


def run_match_simulation(user_stats: dict, opponent_stats: dict) -> dict:
    user_score = 0
    opponent_score = 0

    # 1. State Trackers: Rotation counters start at 0
    user_rotation_step = 0
    opp_rotation_step = 0

    serving_team = "user"  # User serves first in rotation 0
    match_log = []

    # 2. Main Match Loop (Play until 5 points)
    while user_score < 5 and opponent_score < 5:
        # Get active formations for this specific rally step
        user_formation = get_current_rotation(user_stats, user_rotation_step)
        opp_formation = get_current_rotation(opponent_stats, opp_rotation_step)

        # --- Example Rally Outcome ---
        # Suppose User is serving, but Opponent wins the point (Side-Out!)
        if serving_team == "user":
            opponent_score += 1
            serving_team = "opponent"

            # Opponent won a side-out -> Opponent team rotates!
            opp_rotation_step = (opp_rotation_step + 1) % 6
            match_log.append("Opponent wins side-out and rotates!")

        # Next rally: Suppose Opponent serves, and User wins the point (Side-Out!)
        else:
            user_score += 1
            serving_team = "user"

            # User won a side-out -> User team rotates!
            user_rotation_step = (user_rotation_step + 1) % 6
            match_log.append("User wins side-out! Rotating to next formation.")

    return {
        "winner": "user" if user_score > opponent_score else "opponent",
        "user_score": user_score,
        "opponent_score": opponent_score,
        "match_log": match_log
    }