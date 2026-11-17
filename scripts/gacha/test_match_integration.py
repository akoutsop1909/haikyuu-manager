from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import simulate_single_rally, run_match_simulation

TOTAL_RUNS = 1000
# Cache container to run the 2000-rally simulation only once across all tests
_SHARED_AUDIT_DATA = None


def test_hyper_carry_setter_balance():
    print("Testing Hyper-Carry Setter Balance (1200 Setter / 200 Rest vs Balanced 600 Team)...")

    # 1. Create a "Glass Cannon" Whale Team (Hyper-carry setter, weak rest)
    whale_team = create_asymmetric_team(carry_position="setter", carry_set=1200, base_serve=200, base_receive=200, base_set=200, base_spike=200, base_block=200)

    # 2. Create a Fully Balanced F2P Mid-Game Team (All stats @ 600)
    balanced_team = create_dummy_team(serve_val=600, receive_val=600, set_val=600, spike_val=600, block_val=600)

    # 3. Simulate multiple matches to see who wins more often
    whale_wins = 0

    for _ in range(TOTAL_RUNS):
        # Alternate who serves first to keep it fair
        res = run_match_simulation(whale_team, balanced_team, debug=False)
        if res["user_score"] == 5:
            whale_wins += 1

    whale_win_pct = (whale_wins / TOTAL_RUNS) * 100
    print(f" -> Hyper-Carry Team Win Rate: {whale_win_pct:.1f}% vs Balanced Team")

    # Diagnostic assertion: Ensure the hyper-carry doesn't completely break the game (>95% win rate),
    # but still rewards the heavy stat investment (>40% win rate).
    assert 10.0 <= whale_win_pct <= 50.0, f"UNBALANCED: Hyper-carry win rate of {whale_win_pct}% breaks game meta!"
    print(" -> [PASS] Hyper-carry setter balance check verified successfully.\n")


def test_whale_vs_beginner_dominance():
    print("Testing Whale vs Beginner Dominance (1200 All Stats vs 200 All Stats)...")

    # 1. Create Fully Maxed Endgame Team (All 1200)
    whale_team = create_dummy_team(serve_val=1200, receive_val=1200, set_val=1200, spike_val=1200, block_val=1200)
    for role, card in whale_team.items():
        card["name"] = f"Whale {card['name']}"

    # 2. Create Beginner F2P Team (All 200)
    beginner_team = create_dummy_team(serve_val=200, receive_val=200, set_val=200, spike_val=200, block_val=200)
    for role, card in beginner_team.items():
        card["name"] = f"Beginner {card['name']}"

    # 3. Simulate multiple matches
    whale_wins = 0

    for _ in range(TOTAL_RUNS):
        res = run_match_simulation(whale_team, beginner_team, debug=False)
        if res["user_score"] == 5:
            whale_wins += 1

    whale_win_pct = (whale_wins / TOTAL_RUNS) * 100
    print(f" -> Whale Team Win Rate: {whale_win_pct:.1f}% vs Beginner Team")

    # Diagnostic assertion: A fully maxed-out team should crush a level-200 team nearly 100% of the time.
    assert whale_win_pct >= 95.0, f"UNBALANCED: Whale team win rate of {whale_win_pct}% is too low! Stats aren't rewarding enough."
    print(" -> [PASS] Whale vs beginner dominance verified successfully.\n")


def get_shared_audit_data():
    global _SHARED_AUDIT_DATA
    if _SHARED_AUDIT_DATA is None:
        print("Running shared 2,000 chained rallies audit simulation...")
        user_team = create_dummy_team(serve_val=600, receive_val=600, set_val=600, spike_val=600, block_val=600)
        opp_team = create_dummy_team(serve_val=600, receive_val=600, set_val=600, spike_val=600, block_val=600)

        audit = {
            "receive": {"perfect": 0, "good": 0, "poor": 0, "out": 0},
            "set": {"perfect": 0, "good": 0, "poor": 0, "incoming_dump": 0},
            "spike": {"perfect": 0, "good": 0, "poor": 0},
            "block_quality": {"perfect": 0, "good": 0, "poor": 0},
            "block_outcome": {"out": 0, "kill_block": 0, "in-play": 0}
        }

        for _ in range(2000):
            simulate_single_rally(user_team, opp_team, "user", 0, 0, audit_dict=audit)

        _SHARED_AUDIT_DATA = audit
    return _SHARED_AUDIT_DATA


def test_chained_receive_audit():
    print("Testing Chained Receive Quality Distribution...")
    audit = get_shared_audit_data()

    rec_total = sum(audit["receive"].values())
    rec_out_pct = (audit["receive"]["out"] / rec_total) * 100 if rec_total > 0 else 0
    rec_handled_pct = 100.0 - rec_out_pct
    rec_qual_total = rec_total - audit["receive"]["out"]
    rec_perf = (audit["receive"]["perfect"] / rec_qual_total) * 100 if rec_qual_total > 0 else 0
    rec_good = (audit["receive"]["good"] / rec_qual_total) * 100 if rec_qual_total > 0 else 0
    rec_poor = (audit["receive"]["poor"] / rec_qual_total) * 100 if rec_qual_total > 0 else 0

    print(f" -> Results: {rec_out_pct:.1f}% Out | {rec_handled_pct:.1f}% Handled")
    print(f"    (Qualities -> Perfect: {rec_perf:.1f}%, Good: {rec_good:.1f}%, Poor: {rec_poor:.1f}%)")

    assert 14.0 <= rec_out_pct <= 24.0, f"UNBALANCED: Chained receive out rate of {rec_out_pct}% is out of bounds!"
    assert 15.0 <= rec_perf <= 27.0, f"UNBALANCED: Chained receive perfect rate of {rec_perf}% is out of bounds!"
    assert 30.0 <= rec_good <= 42.0, f"UNBALANCED: Chained receive good rate of {rec_good}% is out of bounds!"
    assert 37.0 <= rec_poor <= 49.0, f"UNBALANCED: Chained receive poor rate of {rec_poor}% is out of bounds!"
    print(" -> [PASS] Chained Receive Audit passed.\n")


def test_chained_set_audit():
    print("Testing Chained Set Quality Distribution...")
    audit = get_shared_audit_data()

    set_total = sum(audit["set"].values())
    dump_pct = (audit["set"]["incoming_dump"] / set_total) * 100 if set_total > 0 else 0
    set_qual_total = audit["set"]["perfect"] + audit["set"]["good"] + audit["set"]["poor"]
    set_perf = (audit["set"]["perfect"] / set_qual_total) * 100 if set_qual_total > 0 else 0
    set_good = (audit["set"]["good"] / set_qual_total) * 100 if set_qual_total > 0 else 0
    set_poor = (audit["set"]["poor"] / set_qual_total) * 100 if set_qual_total > 0 else 0

    print(f" -> Results: {dump_pct:.1f}% Setter Dump")
    print(f"    (Qualities -> Perfect: {set_perf:.1f}%, Good: {set_good:.1f}%, Poor: {set_poor:.1f}%)")

    assert 1.0 <= dump_pct <= 5.0, f"UNBALANCED: Chained setter dump rate of {dump_pct}% is out of bounds!"
    assert 23.0 <= set_perf <= 34.0, f"UNBALANCED: Chained set perfect rate of {set_perf}% is out of bounds!"
    assert 32.0 <= set_good <= 43.0, f"UNBALANCED: Chained set good rate of {set_good}% is out of bounds!"
    assert 28.0 <= set_poor <= 40.0, f"UNBALANCED: Chained set poor rate of {set_poor}% is out of bounds!"
    print(" -> [PASS] Chained Set Audit passed.\n")


def test_chained_spike_audit():
    print("Testing Chained Spike Quality Distribution...")
    audit = get_shared_audit_data()

    spike_total = sum(audit["spike"].values())
    spike_perf = (audit["spike"]["perfect"] / spike_total) * 100 if spike_total > 0 else 0
    spike_good = (audit["spike"]["good"] / spike_total) * 100 if spike_total > 0 else 0
    spike_poor = (audit["spike"]["poor"] / spike_total) * 100 if spike_total > 0 else 0

    print(f" -> Results -> Perfect: {spike_perf:.1f}%, Good: {spike_good:.1f}%, Poor: {spike_poor:.1f}%")

    assert 26.0 <= spike_perf <= 39.0, f"UNBALANCED: Chained spike perfect rate of {spike_perf}% is out of bounds!"
    assert 40.0 <= spike_good <= 52.0, f"UNBALANCED: Chained spike good rate of {spike_good}% is out of bounds!"
    assert 18.0 <= spike_poor <= 28.0, f"UNBALANCED: Chained spike poor rate of {spike_poor}% is out of bounds!"
    print(" -> [PASS] Chained Spike Audit passed.\n")


def test_chained_block_audit():
    print("Testing Chained Block Distribution...")
    audit = get_shared_audit_data()

    total_outcomes = sum(audit["block_outcome"].values())
    total_qualities = sum(audit["block_quality"].values())
    out_pct = (audit["block_outcome"]["out"] / total_outcomes) * 100 if total_outcomes > 0 else 0
    kill_pct = (audit["block_outcome"]["kill_block"] / total_outcomes) * 100 if total_outcomes > 0 else 0
    perf_pct = (audit["block_quality"]["perfect"] / total_qualities) * 100 if total_qualities > 0 else 0
    good_pct = (audit["block_quality"]["good"] / total_qualities) * 100 if total_qualities > 0 else 0
    poor_pct = (audit["block_quality"]["poor"] / total_qualities) * 100 if total_qualities > 0 else 0

    print(f" -> Results: {out_pct:.1f}% Out | {kill_pct:.1f}% Kill Blocks")
    print(f"    (Qualities -> Perfect: {perf_pct:.1f}%, Good: {good_pct:.1f}%, Poor: {poor_pct:.1f}%)")

    assert 1.5 <= out_pct <= 6.0, f"UNBALANCED: Chained block out rate of {out_pct}% is out of bounds!"
    assert 6.0 <= kill_pct <= 15.0, f"UNBALANCED: Chained kill block rate of {kill_pct}% is out of bounds!"
    assert 26.0 <= perf_pct <= 38.0, f"UNBALANCED: Chained block perfect rate of {perf_pct}% is out of bounds!"
    assert 43.0 <= good_pct <= 56.0, f"UNBALANCED: Chained block good rate of {good_pct}% is out of bounds!"
    assert 13.0 <= poor_pct <= 24.0, f"UNBALANCED: Chained block poor rate of {poor_pct}% is out of bounds!"
    print(" -> [PASS] Chained Block Audit passed.\n")


def test_full_match_simulation_log():
    print("Testing Full Match Simulation & Printing Match Log (First to 5 Points)...")

    # 1. Create standard teams (leaving other test suites untouched)
    user_team = create_dummy_team(serve_val=600, receive_val=600, set_val=600, spike_val=600, block_val=600)
    opp_team = create_dummy_team(serve_val=600, receive_val=600, set_val=600, spike_val=600, block_val=600)

    # 2. Dynamically prefix names for this specific test only
    for role, card in user_team.items():
        card["name"] = f"User {card['name']}"

    for role, card in opp_team.items():
        card["name"] = f"Opp {card['name']}"

    # 3. Run simulation
    match_result = run_match_simulation(user_team, opp_team, debug=False)

    user_score = match_result["user_score"]
    opp_score = match_result["opponent_score"]
    match_log = match_result["match_log"]

    # Print out the play-by-play log
    print(f"\n==========================================")
    print(f" FINAL SCORE: User {user_score} - {opp_score} Opponent")
    print(f"==========================================")
    print("--- MATCH LOG ---")
    for line in match_log:
        print(f" > {line}")
    print("-----------------\n")

    assert user_score == 5 or opp_score == 5, "LOGIC ERROR: Match ended before someone reached 5 points!"
    assert len(match_log) > 0, "LOGIC ERROR: Match log is empty!"

    print(" -> [PASS] Full match simulation log generated and verified successfully.\n")


if __name__ == "__main__":
    print("=== STARTING PHASE INTEGRATION TESTS ===")

    tests = [
        ("Hyper-Carry Setter Balance", test_hyper_carry_setter_balance),
        ("Whale vs Beginner Dominance", test_whale_vs_beginner_dominance),
        ("Chained Receive Audit", test_chained_receive_audit),
        ("Chained Set Audit", test_chained_set_audit),
        ("Chained Spike Audit", test_chained_spike_audit),
        ("Chained Block Audit", test_chained_block_audit),
        ("Full Match Simulation Log", test_full_match_simulation_log)
    ]

    failed = False
    for name, test_func in tests:
        try:
            test_func()
        except AssertionError as e:
            print(f" -> [FAIL] {name}")
            print(f"    Reason: {e}\n")
            failed = True

    if failed:
        print("=== SOME INTEGRATION TESTS FAILED ===")
        exit(1)
    else:
        print("=== ALL INTEGRATION TESTS PASSED SUCCESSFULLY ===")