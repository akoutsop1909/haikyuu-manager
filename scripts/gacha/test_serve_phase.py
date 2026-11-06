from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import serve_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_extreme_mismatch_ace_rate():
    print("Testing Extreme Mismatch: 1000-Power Server vs. 110-Receive Defense (Stat Floor)...")

    god_server_team = create_dummy_team(serve_val=1000, receive_val=200)
    terrible_receive_team = create_dummy_team(serve_val=100, receive_val=110)

    ace_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(god_server_team, terrible_receive_team, 0, 0)['outcome'] == 'ace'
    )

    ace_pct = (ace_count / TOTAL_RUNS) * 100
    print(f" -> Extreme Mismatch Ace Rate: {ace_pct:.1f}%")

    # Even against the lowest legal receive stat (110), a maxed server should still heavily dominate
    assert 70 <= ace_pct <= 100, f"UNBALANCED: Extreme mismatch ace rate of {ace_pct}% is out of bounds!"
    print(" -> [PASS] Extreme mismatch dominance behaves correctly.\n")


def test_low_stat_high_risk_tier():
    print("Testing Low-Stat High-Risk Tier (Serve Power 90 vs Normal Defense)...")

    bad_server_team = create_dummy_team(serve_val=90, receive_val=200)
    normal_receive_team = create_dummy_team(serve_val=100, receive_val=200)

    error_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(bad_server_team, normal_receive_team, 0, 0)['outcome'] == 'error'
    )

    error_pct = (error_count / TOTAL_RUNS) * 100
    print(f" -> Stat Floor Error Rate: {error_pct:.1f}%")

    # Verify it hits the expected ~8.3% math curve safely
    assert 5 <= error_pct <= 12, f"UNBALANCED: Stat floor error rate of {error_pct}% is out of bounds!"
    print(" -> [PASS] Absolute serve floor behaves correctly.\n")


def test_power_threshold_transition():
    print("Testing 500-Power Threshold Transition (499 vs 500 Stats)...")

    # Team just below the elite tier (< 500 rule)
    sub_threshold_team = create_dummy_team(serve_val=499, receive_val=200)
    # Team right at the elite tier boundary (>= 500 rule)
    at_threshold_team = create_dummy_team(serve_val=500, receive_val=200)
    receiver_team = create_dummy_team(serve_val=100, receive_val=200)

    # Test sub-threshold error rate (~8.3% expected)
    sub_errors = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(sub_threshold_team, receiver_team, 0, 0)['outcome'] == 'error'
    )
    sub_error_pct = (sub_errors / TOTAL_RUNS) * 100

    # Test elite threshold error rate (~5.0% expected)
    at_errors = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(at_threshold_team, receiver_team, 0, 0)['outcome'] == 'error'
    )
    at_error_pct = (at_errors / TOTAL_RUNS) * 100

    print(f" -> 499 Power Error Rate: {sub_error_pct:.1f}%")
    print(f" -> 500 Power Error Rate: {at_error_pct:.1f}%")

    # Assert both remain in their correct logical brackets and 500 is safer
    assert 5 <= sub_error_pct <= 12, f"UNBALANCED: 499 error rate of {sub_error_pct}% is out of bounds!"
    assert 2 <= at_error_pct <= 8, f"UNBALANCED: 500 error rate of {at_error_pct}% is out of bounds!"
    assert at_error_pct < sub_error_pct, f"LOGIC ERROR: Elite 500 serve should be safer than 499!"

    print(" -> [PASS] 500-power threshold transition behaves correctly.\n")


def test_receiver_defense_mitigation():
    print("Testing Receiver Defense Impact (Poor Defense vs Elite Defense)...")

    server_team = create_dummy_team(serve_val=600, receive_val=200)
    poor_defense = create_dummy_team(serve_val=100, receive_val=110)   # Floor receive (110)
    elite_defense = create_dummy_team(serve_val=100, receive_val=900) # Elite receive (900)

    poor_aces = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(server_team, poor_defense, 0, 0)['outcome'] == 'ace'
    )
    elite_aces = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(server_team, elite_defense, 0, 0)['outcome'] == 'ace'
    )

    poor_ace_pct = (poor_aces / TOTAL_RUNS) * 100
    elite_ace_pct = (elite_aces / TOTAL_RUNS) * 100

    print(f" -> Ace Rate vs Poor Defense (110 Receive): {poor_ace_pct:.1f}%")
    print(f" -> Ace Rate vs Elite Defense (900 Receive): {elite_ace_pct:.1f}%")

    # Assert that elite defense significantly reduces aces compared to poor defense
    assert elite_ace_pct < poor_ace_pct, f"LOGIC ERROR: Elite defense must allow fewer aces than poor defense!"
    print(" -> [PASS] Receiver defense stat mitigation behaves correctly.\n")


def test_rotation_server_shift():
    print("Testing Rotation-Driven Server Shift...")

    # Create a team where the default server (Setter) is weak (90),
    # but another position in the rotation has a powerhouse serve (900).
    asymmetric_team = create_asymmetric_team(base_serve=90, carry_position="opposite", carry_serve=900)
    opponent = create_dummy_team(serve_val=100, receive_val=200)

    # Give the setter the specific name the assertion is looking for
    asymmetric_team["setter"]["name"] = "WeakSetter"

    # Step 0: Setter is in Zone 1 (Server stats = 90 -> high error or weak serve)
    # Step 3: Opposite (GodOpposite) rotates into Zone 1 (Server stats = 900 -> high ace rate)
    step_0_result = serve_phase(asymmetric_team, opponent, serving_rotation_step=0, receiving_rotation_step=0)
    step_3_result = serve_phase(asymmetric_team, opponent, serving_rotation_step=3, receiving_rotation_step=0)

    print(f" -> Rotation Step 0 Server Message: {step_0_result['message']}")
    print(f" -> Rotation Step 3 Server Message: {step_3_result['message']}")

    # Assert that rotation successfully shifted the active server name
    assert "WeakSetter" in step_0_result['message'], "LOGIC ERROR: Rotation 0 should feature the Setter serving!"
    assert "GodOpposite" in step_3_result['message'], "LOGIC ERROR: Rotation 3 should rotate the Opposite into the server slot!"

    print(" -> [PASS] Rotation-driven server shift behaves correctly.\n")


def run_distribution_test(test_name, stat_val, error_bounds, ace_bounds, in_play_bounds):
    print(f"Testing {test_name} ({stat_val} vs {stat_val} Stats)...")

    team = create_dummy_team(serve_val=stat_val, receive_val=stat_val)

    outcomes = {"ace": 0, "error": 0, "in-play": 0}

    for _ in range(TOTAL_RUNS):
        result = serve_phase(team, team, 0, 0)
        outcomes[result["outcome"]] += 1

    ace_pct = (outcomes["ace"] / TOTAL_RUNS) * 100
    error_pct = (outcomes["error"] / TOTAL_RUNS) * 100
    in_play_pct = (outcomes["in-play"] / TOTAL_RUNS) * 100

    print(f" -> Results: {ace_pct:.1f}% Aces | {error_pct:.1f}% Errors | {in_play_pct:.1f}% In-Play")

    min_err, max_err = error_bounds
    min_ace, max_ace = ace_bounds
    min_ip, max_ip = in_play_bounds

    assert min_err <= error_pct <= max_err, f"UNBALANCED: Error rate of {error_pct}% is out of bounds!"
    assert min_ace <= ace_pct <= max_ace, f"UNBALANCED: Ace rate of {ace_pct}% is out of bounds!"
    assert min_ip <= in_play_pct <= max_ip, f"UNBALANCED: In-play rate of {in_play_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING SERVE PHASE TESTS ===")

    # All tests registered cleanly in one list without repeating boilerplate code
    tests = [
        ("Extreme Mismatch Ace Rate", test_extreme_mismatch_ace_rate),
        ("Stat Floor Baseline", test_low_stat_high_risk_tier),
        ("Power Threshold Transition", test_power_threshold_transition),
        ("Receiver Defense Mitigation", test_receiver_defense_mitigation),
        ("Rotation Server Shift", test_rotation_server_shift),
        ("Early-Game Distribution", lambda: run_distribution_test("Early-Game", 150, (1, 10), (2, 15), (75, 95))),
        ("Mid-Game Distribution", lambda: run_distribution_test("Mid-Game", 450, (1, 10), (2, 15), (75, 95))),
        ("Endgame Distribution", lambda: run_distribution_test("Endgame", 800, (0, 6), (2, 15), (80, 96))),
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