import random


def resolve_serve_phase(server_card: dict, back_row_cards: list[dict]) -> dict:
    """
    Simulates the Serve & Receive phase between a Server and back-row Receivers.
    """
    server_name = server_card.get("name", "Server")
    serve_stat = server_card.get("scaled_stats", {}).get("serve", 50)

    # 1. Select Receiver (Weighted towards Libero)
    candidates = []
    weights = []

    for card in back_row_cards:
        if not card:
            continue
        candidates.append(card)
        # Liberos cover more ground -> 60% relative weight
        if card.get("position") == "L":
            weights.append(60)
        else:
            weights.append(20)

    if not candidates:
        raise ValueError("No back-row receivers available!")

    receiver_card = random.choices(candidates, weights=weights, k=1)[0]
    receiver_name = receiver_card.get("name", "Receiver")
    receive_stat = receiver_card.get("scaled_stats", {}).get("receive", 50)

    # 2. Compare Stats & Calculate Pass Quality Probability
    stat_diff = receive_stat - serve_stat

    # Base Ace Chance (Server advantage)
    ace_chance = max(0.02, 0.08 - (stat_diff * 0.002))

    # Perfect Pass Chance (Receiver advantage)
    perfect_chance = max(0.15, min(0.80, 0.50 + (stat_diff * 0.005)))

    # Poor Pass Chance
    poor_chance = max(0.05, min(0.40, 0.20 - (stat_diff * 0.003)))

    # Roll for outcome
    roll = random.random()

    if roll < ace_chance:
        outcome = "ACE"
        description = f"🔥 SERVICE ACE! **{server_name}** scores directly off the serve!"
        setter_stat_modifier = 0.0
    elif roll < ace_chance + perfect_chance:
        outcome = "PERFECT"
        description = f"🛡️ Perfect pass! **{receiver_name}** digs the serve cleanly to the Setter."
        setter_stat_modifier = 1.20  # +20% boost to Setter's Set stat
    elif roll < ace_chance + perfect_chance + poor_chance:
        outcome = "POOR"
        description = f"⚠️ Off-system pass! **{receiver_name}** barely keeps **{server_name}**'s serve in play!"
        setter_stat_modifier = 0.85  # -15% penalty to Setter's Set stat
    else:
        outcome = "GOOD"
        description = f"🏐 Solid receive by **{receiver_name}**. The play continues normally."
        setter_stat_modifier = 1.00  # Baseline

    return {
        "outcome": outcome,
        "server": server_name,
        "receiver": receiver_name,
        "description": description,
        "setter_stat_modifier": setter_stat_modifier
    }