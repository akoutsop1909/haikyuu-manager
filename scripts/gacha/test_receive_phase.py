from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import serve_phase, receive_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_rotation_receive_shift():
    print("Testing Rotation-Driven Back-Row Shift for Reception...")

    asymmetric_team = create_asymmetric_team(base_serve=100, base_receive=150, carry_position="libero", carry_receive=950)
    incoming_power = 600

    for step in range(6):
        res = receive_phase(incoming_power, asymmetric_team, step, source_type="serve", source_name="Server")
        assert "outcome" in res, f"LOGIC ERROR: Receive phase failed to return a valid outcome at rotation step {step}!"

    print(" -> [PASS] Rotation-driven back-row shifts execute smoothly without errors.\n")


def test_extreme_mismatch_receive_error():
    print("Testing Extreme Mismatch: 1000 Incoming Power vs 110-Receive Defense (Stat Floor)...")

    incoming_power = 1000
    terrible_defense = create_dummy_team(serve_val=100, receive_val=110)

    error_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, terrible_defense, 0, source_type="serve", source_name="GodServer")[
            'outcome'] == 'error'
    )

    error_pct = (error_count / TOTAL_RUNS) * 100
    print(f" -> Extreme Mismatch Error Rate: {error_pct:.1f}%")

    # Expect dominant pressure (85% - 98%), accounting for the 8% underdog miracle window
    assert 85 <= error_pct <= 98, f"UNBALANCED: Extreme mismatch error rate of {error_pct}% is out of bounds!"
    print(" -> [PASS] Extreme mismatch receive error rate behaves correctly.\n")


def test_elite_defense_stability():
    print("Testing Elite Defense Stability: 400 Incoming Power vs 900-Receive Defense...")

    incoming_power = 400
    elite_defense = create_dummy_team(serve_val=100, receive_val=900)

    error_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, elite_defense, 0, source_type="serve", source_name="NormalServer")[
            'outcome'] == 'error'
    )

    error_pct = (error_count / TOTAL_RUNS) * 100
    print(f" -> Elite Defense Error Rate: {error_pct:.1f}%")

    # With the new realistic error floor, even elite defenses have a microscopic error chance (~1.2%),
    # but against a weak 400 power ball, it should remain very close to 0 (allow up to 2.5%).
    assert error_pct <= 2.5, f"UNBALANCED: Elite defense error rate of {error_pct}% is too high!"
    print(" -> [PASS] Elite defense stability behaves correctly.\n")


def test_libero_targeting_frequency():
    print("Testing Libero Target Frequency Bias (Weighted Selection)...")
    # Create an asymmetric team where the libero has 900 receive, others have 200
    team = create_asymmetric_team(base_serve=100, base_receive=200, carry_position="libero", carry_receive=900)

    libero_target_count = 0
    incoming_power = 500

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")
        if "GodLibero" in res["message"]:
            libero_target_count += 1

    libero_pct = (libero_target_count / TOTAL_RUNS) * 100
    print(f" -> Libero targeted in {libero_pct:.1f}% of receptions (Stat 900 vs 200 baseline teammates)")

    # Bump upper bound slightly to account for random variance across 1000 runs
    assert 45 <= libero_pct <= 73, f"UNBALANCED: Libero selection frequency of {libero_pct}% is out of bounds!"
    print(" -> [PASS] Libero targeting frequency reflects weighted stat dominance correctly.\n")


def test_setter_reception_shielding():
    print("Testing Setter Reception Shielding (Tactical Position Bias)...")
    # Create an asymmetric team where the setter has a massive receive stat (950)
    # while teammates are at a baseline of 200.
    team = create_asymmetric_team(base_serve=100, base_receive=200, carry_position="setter", carry_receive=950)

    setter_target_count = 0
    incoming_power = 500

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")
        if "GodSetter" in res["message"]:
            setter_target_count += 1

    setter_pct = (setter_target_count / TOTAL_RUNS) * 100
    print(f" -> Setter (Stat 950) targeted in {setter_pct:.1f}% of receptions due to tactical shield")

    # With the stronger 0.20 shield, the setter is safely hidden below 25%
    assert setter_pct <= 25, f"UNBALANCED: Setter selection frequency of {setter_pct}% is too high despite shielding!"
    print(" -> [PASS] Setter reception shielding works correctly and protects stat investment.\n")


def test_backup_dive_scramble_telemetry():
    print("Testing Emergency Backup Dive Scramble Telemetry...")
    team = create_dummy_team(serve_val=300, receive_val=300)
    incoming_power = 750

    backup_dives_triggered = 0
    backup_saves_successful = 0

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")

        # Check explicit telemetry flags returned by the engine
        if res.get("backup_triggered"):
            backup_dives_triggered += 1
            if res.get("backup_success"):
                backup_saves_successful += 1

    print(f" -> Triggered {backup_dives_triggered} emergency backup dives out of {TOTAL_RUNS} runs.")

    if backup_dives_triggered > 0:
        success_pct = (backup_saves_successful / backup_dives_triggered) * 100
        print(
            f" -> Backup dive success rate: {success_pct:.1f}% ({backup_saves_successful}/{backup_dives_triggered} saved)")

        assert 25 <= success_pct <= 70, f"UNBALANCED: Backup dive success rate of {success_pct}% is out of bounds!"
    else:
        assert False, "UNBALANCED: Backup dives were never triggered!"

    print(" -> [PASS] Emergency backup dive scramble telemetry recorded successfully.\n")


def run_receive_distribution_test(test_name, stat_val, error_bounds, perfect_bounds, good_bounds, poor_bounds):
    print(f"Testing {test_name} Distribution (Receive Stat: {stat_val})...")

    team = create_dummy_team(serve_val=stat_val, receive_val=stat_val)

    outcomes = {"error": 0, "perfect": 0, "good": 0, "poor": 0}
    runs = 0

    for _ in range(TOTAL_RUNS):
        serve_res = serve_phase(team, 0)
        if serve_res["outcome"] == "in-play":
            incoming_power = serve_res["incoming_power"]
            server_name = serve_res["server_name"]

            receive_res = receive_phase(incoming_power, team, 0, source_type="serve", source_name=server_name)

            if receive_res["outcome"] == "error":
                outcomes["error"] += 1
            else:
                outcomes[receive_res["quality"]] += 1
            runs += 1

    if runs == 0:
        runs = 1

    err_pct = (outcomes["error"] / runs) * 100
    handled_pct = 100.0 - err_pct
    perf_pct = (outcomes["perfect"] / runs) * 100
    good_pct = (outcomes["good"] / runs) * 100
    poor_pct = (outcomes["poor"] / runs) * 100

    print(f" -> Results: {err_pct:.1f}% Errors | {handled_pct:.1f}% Handled")
    print(f"    (Qualities -> Perfect: {perf_pct:.1f}%, Good: {good_pct:.1f}%, Poor: {poor_pct:.1f}%)")

    min_err, max_err = error_bounds
    min_perf, max_perf = perfect_bounds
    min_good, max_good = good_bounds
    min_poor, max_poor = poor_bounds

    assert min_err <= err_pct <= max_err, f"UNBALANCED: Receive error rate of {err_pct}% is out of bounds!"
    assert min_perf <= perf_pct <= max_perf, f"UNBALANCED: Perfect pass rate of {perf_pct}% is out of bounds!"
    assert min_good <= good_pct <= max_good, f"UNBALANCED: Good pass rate of {good_pct}% is out of bounds!"
    assert min_poor <= poor_pct <= max_poor, f"UNBALANCED: Poor pass rate of {poor_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Receive Distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING RECEIVE PHASE TESTS ===")

    tests = [
        ("Rotation Receive Shift", test_rotation_receive_shift),
        ("Extreme Mismatch Receive Error", test_extreme_mismatch_receive_error),
        ("Elite Defense Stability", test_elite_defense_stability),
        ("Libero Targeting Frequency", test_libero_targeting_frequency),
        ("Setter Reception Shielding", test_setter_reception_shielding),
        ("Backup Dive Scramble Telemetry", test_backup_dive_scramble_telemetry),
        ("Early-Game Receive Distribution", lambda: run_receive_distribution_test("Early-Game", 200, (0.5, 5.0), (10, 45), (35, 75), (10, 40))),
        ("Mid-Game Receive Distribution", lambda: run_receive_distribution_test("Mid-Game", 600, (0.5, 5.0), (10, 45), (40, 75), (10, 40))),
        ("Endgame Receive Distribution", lambda: run_receive_distribution_test("Endgame", 1200, (0.5, 5.0), (10, 45), (40, 75), (9.0, 42))),
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
        print("=== SOME TESTS FAILED ===")
        exit(1)
    else:
        print("=== ALL TESTS PASSED SUCCESSFULLY ===")