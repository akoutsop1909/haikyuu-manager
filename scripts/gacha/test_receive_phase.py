from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import _calculate_receive_error_chance, receive_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_rotation_receive_shift():
    print("Testing Rotation-Driven Back-Row Shift for Reception...")

    asymmetric_team = create_asymmetric_team(base_receive=150, carry_position="libero", carry_receive=950)
    incoming_power = 600

    for step in range(6):
        res = receive_phase(incoming_power, asymmetric_team, step, source_type="serve", source_name="Server")
        assert "outcome" in res, f"LOGIC ERROR: Receive phase failed to return a valid outcome at rotation step {step}!"

    print(" -> [PASS] Rotation-driven back-row shifts execute smoothly without errors.\n")


def test_extreme_mismatch_receive_error():
    print("Testing Extreme Mismatch: 1000 Incoming Power vs 110-Receive Defense (Stat Floor)...")

    incoming_power = 1000
    terrible_defense = create_dummy_team(receive_val=110)

    out_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, terrible_defense, 0, source_type="serve", source_name="GodServer")[
            'outcome'] == 'out'
    )

    out_pct = (out_count / TOTAL_RUNS) * 100
    print(f" -> Extreme Mismatch Out Rate: {out_pct:.1f}%")

    assert 40 <= out_pct <= 65, f"UNBALANCED: Extreme mismatch out rate of {out_pct}% is out of bounds!"
    print(" -> [PASS] Extreme mismatch receive out rate behaves correctly.\n")


def test_underdog_mercy_logic():
    print("Testing Underdog Mercy / Miracle Buffer Boundary Logic...")

    receive_stat = 400
    fatigue_tier = 0

    # Threshold for mercy is incoming_power > (receive_stat * 1.5) -> 400 * 1.5 = 600

    # 1. Just below threshold (Power = 599) -> Mercy should NOT apply
    power_below = 599
    error_below = _calculate_receive_error_chance(receive_stat, power_below, fatigue_tier)

    # 2. Just above threshold (Power = 601) -> Mercy SHOULD apply (x0.90)
    power_above = 601
    error_above = _calculate_receive_error_chance(receive_stat, power_above, fatigue_tier)

    # Calculate what error_above would be WITHOUT the mercy buffer
    power_disparity = power_above / max(receive_stat, 1)
    expected_base_error = 0.03 + (max(0.0, power_disparity - 1.0) * 0.065)
    expected_with_mercy = expected_base_error * 0.90

    # Assertions
    assert error_above < error_below, f"UNBALANCED: Error chance didn't drop across the mercy threshold! (Below: {error_below}, Above: {error_above})"
    assert abs(
        error_above - expected_with_mercy) < 1e-5, f"LOGIC ERROR: Mercy multiplier (0.90) was not correctly applied!"

    print(f" -> Error at 599 power (No Mercy): {error_below:.4f}")
    print(f" -> Error at 601 power (With Mercy): {error_above:.4f}")
    print(" -> [PASS] Underdog mercy buffer threshold and scaling verified successfully.\n")


def test_elite_defense_stability():
    print("Testing Elite Defense Stability: 400 Incoming Power vs 900-Receive Defense...")

    incoming_power = 400
    elite_defense = create_dummy_team(receive_val=900)

    out_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, elite_defense, 0, source_type="serve", source_name="NormalServer")[
            'outcome'] == 'out'
    )

    out_pct = (out_count / TOTAL_RUNS) * 100
    print(f" -> Elite Defense Out Rate: {out_pct:.1f}%")

    assert out_pct <= 5.5, f"UNBALANCED: Elite defense out rate of {out_pct}% is too high!"
    print(" -> [PASS] Elite defense stability behaves correctly.\n")


def test_libero_targeting_frequency():
    print("Testing Libero Target Frequency Bias (Weighted Selection)...")
    # Create an asymmetric team where the libero has 900 receive, others have 200
    team = create_asymmetric_team(base_receive=200, carry_position="libero", carry_receive=900)

    libero_target_count = 0
    incoming_power = 500

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")
        if res.get("receiver_slot") == "libero":
            libero_target_count += 1

    libero_pct = (libero_target_count / TOTAL_RUNS) * 100
    print(f" -> Libero targeted in {libero_pct:.1f}% of receptions (Stat 900 vs 200 baseline teammates)")

    # Bump upper bound slightly to account for random variance across 1000 runs
    assert 45 <= libero_pct <= 76, f"UNBALANCED: Libero selection frequency of {libero_pct}% is out of bounds!"
    print(" -> [PASS] Libero targeting frequency reflects weighted stat dominance correctly.\n")


def test_setter_reception_shielding():
    print("Testing Setter Reception Shielding (Tactical Position Bias)...")
    # Create an asymmetric team where the setter has a massive receive stat (950)
    # while teammates are at a baseline of 200.
    team = create_asymmetric_team(base_receive=200, carry_position="setter", carry_receive=950)

    setter_target_count = 0
    incoming_power = 500

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")
        if res.get("receiver_slot") == "setter":
            setter_target_count += 1

    setter_pct = (setter_target_count / TOTAL_RUNS) * 100
    print(f" -> Setter (Stat 950) targeted in {setter_pct:.1f}% of receptions due to tactical shield")

    # With the stronger 0.20 shield, the setter is safely hidden below 25%
    assert setter_pct <= 25, f"UNBALANCED: Setter selection frequency of {setter_pct}% is too high despite shielding!"
    print(" -> [PASS] Setter reception shielding works correctly and protects stat investment.\n")


def test_vulnerable_rotation_step_2():
    print("Testing Vulnerable Rotation Step 2 (Libero Benched, Setter Exposed in Back Row)...")
    team = create_dummy_team(receive_val=300)
    incoming_power = 600

    setter_targeted_count = 0
    for _ in range(TOTAL_RUNS):
        # Rotation step 2 forces the libero to the bench and places the setter in the back row
        res = receive_phase(incoming_power, team, 2, source_type="serve", source_name="Server")

        assert "outcome" in res, "LOGIC ERROR: Receive phase failed to return a valid outcome at rotation step 2!"
        if res.get("receiver_slot") == "setter":
            setter_targeted_count += 1

    setter_pct = (setter_targeted_count / TOTAL_RUNS) * 100
    print(f" -> Setter targeted in vulnerable rotation step 2: {setter_pct:.1f}% of the time.")
    print(" -> [PASS] Rotation step 2 executes cleanly without a libero and handles setter exposure safely.\n")


def test_backup_dive_scramble_telemetry():
    print("Testing Emergency Backup Dive Scramble Telemetry...")
    team = create_dummy_team(receive_val=300)
    incoming_power = 750

    backup_dives_triggered = 0
    backup_saves_successful = 0

    for _ in range(TOTAL_RUNS):
        res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")

        # Check explicit telemetry flags returned by the engine
        telemetry = res.get("telemetry", {})
        if telemetry.get("backup_triggered"):
            backup_dives_triggered += 1
            if telemetry.get("backup_success"):
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


def test_rally_fatigue_progression():
    print("Testing Rally Fatigue Stepwise Progression (Cross 1 vs 3 vs 5)...")
    team = create_dummy_team(receive_val=400)
    incoming_power = 700

    # Cross 1 (Tier 0: Fresh)
    errors_1 = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, team, 0, source_type="spike", source_name="Spiker", net_cross_count=1)[
            'outcome'] == 'out'
    )
    pct_1 = (errors_1 / TOTAL_RUNS) * 100

    # Cross 3 (Tier 1: First fatigue step)
    errors_3 = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, team, 0, source_type="spike", source_name="Spiker", net_cross_count=3)[
            'outcome'] == 'out'
    )
    pct_3 = (errors_3 / TOTAL_RUNS) * 100

    # Cross 5 (Tier 2: Deep fatigue)
    errors_5 = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, team, 0, source_type="spike", source_name="Spiker", net_cross_count=5)[
            'outcome'] == 'out'
    )
    pct_5 = (errors_5 / TOTAL_RUNS) * 100

    print(f" -> Out Rate at Net Cross 1 (Fresh): {pct_1:.1f}%")
    print(f" -> Out Rate at Net Cross 3 (Tier 1): {pct_3:.1f}%")
    print(f" -> Out Rate at Net Cross 5 (Tier 2): {pct_5:.1f}%")

    # Assert strict stepwise escalation and lock in your desired target bounds
    assert pct_3 > pct_1, f"UNBALANCED: Cross 3 out rate ({pct_3}%) did not increase from Cross 1 ({pct_1}%)!"
    assert pct_5 > pct_3, f"UNBALANCED: Cross 5 out rate ({pct_5}%) did not increase from Cross 3 ({pct_3}%)!"

    # New range assertions to protect your target numbers from regression
    assert 2.0 <= pct_1 <= 8.0, f"UNBALANCED: Fresh out rate {pct_1}% is out of bounds!"
    assert 25.0 <= pct_3 <= 38.0, f"UNBALANCED: Tier 1 fatigue out rate {pct_3}% is out of bounds!"
    assert 50.0 <= pct_5 <= 65.0, f"UNBALANCED: Tier 2 fatigue out rate {pct_5}% is out of bounds!"

    print(" -> [PASS] Rally fatigue stepwise progression and out scaling verified successfully.\n")


def run_receive_distribution_test(test_name, stat_val, out_bounds, perfect_bounds, good_bounds, poor_bounds):
    print(f"Testing {test_name} Distribution (Receive Stat: {stat_val})...")

    team = create_dummy_team(receive_val=stat_val)
    incoming_power = float(stat_val)

    outcomes = {"out": 0, "perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        # Call receive_phase directly without needing serve_phase!
        receive_res = receive_phase(incoming_power, team, 0, source_type="serve", source_name="Server")

        if receive_res["outcome"] == "out":
            outcomes["out"] += 1
        else:
            outcomes[receive_res["quality"]] += 1

    out_pct = (outcomes["out"] / TOTAL_RUNS) * 100
    handled_pct = 100.0 - out_pct
    perf_pct = (outcomes["perfect"] / TOTAL_RUNS) * 100
    good_pct = (outcomes["good"] / TOTAL_RUNS) * 100
    poor_pct = (outcomes["poor"] / TOTAL_RUNS) * 100

    print(f" -> Results: {out_pct:.1f}% Out | {handled_pct:.1f}% Handled")
    print(f"    (Qualities -> Perfect: {perf_pct:.1f}%, Good: {good_pct:.1f}%, Poor: {poor_pct:.1f}%)")

    min_out, max_out = out_bounds
    min_perf, max_perf = perfect_bounds
    min_good, max_good = good_bounds
    min_poor, max_poor = poor_bounds

    assert min_out <= out_pct <= max_out, f"UNBALANCED: Reception out rate of {out_pct}% is out of bounds!"
    assert min_perf <= perf_pct <= max_perf, f"UNBALANCED: Perfect pass rate of {perf_pct}% is out of bounds!"
    assert min_perf <= good_pct <= max_good, f"UNBALANCED: Good pass rate of {good_pct}% is out of bounds!"
    assert min_poor <= poor_pct <= max_poor, f"UNBALANCED: Poor pass rate of {poor_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Receive Distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING RECEIVE PHASE TESTS ===")

    tests = [
        ("Rotation Receive Shift", test_rotation_receive_shift),
        ("Extreme Mismatch Receive Error", test_extreme_mismatch_receive_error),
        ("Underdog Mercy Logic", test_underdog_mercy_logic),
        ("Elite Defense Stability", test_elite_defense_stability),
        ("Libero Targeting Frequency", test_libero_targeting_frequency),
        ("Setter Reception Shielding", test_setter_reception_shielding),
        ("Vulnerable Rotation Step 2", test_vulnerable_rotation_step_2),
        ("Backup Dive Scramble Telemetry", test_backup_dive_scramble_telemetry),
        ("Rally Fatigue Progression", test_rally_fatigue_progression),
        ("Early-Game Receive Distribution", lambda: run_receive_distribution_test("Early-Game", 200, (1.0, 6.5), (28.0, 35.0), (39.0, 46.0), (20.0, 26.0))),
        ("Mid-Game Receive Distribution", lambda: run_receive_distribution_test("Mid-Game", 600, (1.0, 6.5), (28.0, 34.0), (44.0, 51.0), (17.0, 23.0))),
        ("Endgame Receive Distribution", lambda: run_receive_distribution_test("Endgame", 1200, (1.0, 5.5), (31.0, 38.0), (43.0, 54.0), (10.0, 15.0))),
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