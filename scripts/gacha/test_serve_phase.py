from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import serve_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_low_stat_high_risk_tier():
    print("Testing Low-Stat High-Risk Tier (Serve Power 90)...")

    bad_server_team = create_dummy_team(serve_val=90, receive_val=200)

    error_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(bad_server_team, 0)['outcome'] == 'error'
    )

    error_pct = (error_count / TOTAL_RUNS) * 100
    print(f" -> Stat Floor Error Rate: {error_pct:.1f}%")

    # Verify error rate falls within expected range
    assert 1 <= error_pct <= 5, f"UNBALANCED: Stat floor error rate of {error_pct}% is out of bounds!"
    print(" -> [PASS] Absolute serve floor behaves correctly.\n")


def test_power_threshold_transition():
    print("Testing 500-Power Threshold Transition (499 vs 500 Stats)...")

    # Team just below the elite tier (< 500 rule)
    sub_threshold_team = create_dummy_team(serve_val=499, receive_val=200)
    # Team right at the elite tier boundary (>= 500 rule)
    at_threshold_team = create_dummy_team(serve_val=500, receive_val=200)

    # Test sub-threshold error rate
    sub_errors = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(sub_threshold_team, 0)['outcome'] == 'error'
    )
    sub_error_pct = (sub_errors / TOTAL_RUNS) * 100

    # Test elite threshold error rate
    at_errors = sum(
        1 for _ in range(TOTAL_RUNS)
        if serve_phase(at_threshold_team, 0)['outcome'] == 'error'
    )
    at_error_pct = (at_errors / TOTAL_RUNS) * 100

    print(f" -> 499 Power Error Rate: {sub_error_pct:.1f}%")
    print(f" -> 500 Power Error Rate: {at_error_pct:.1f}%")

    # Assert both remain in their correct logical brackets and 500 is safer
    assert 1 <= sub_error_pct <= 5, f"UNBALANCED: 499 error rate of {sub_error_pct}% is out of bounds!"
    assert 0.5 <= at_error_pct <= 3, f"UNBALANCED: 500 error rate of {at_error_pct}% is out of bounds!"
    assert at_error_pct < sub_error_pct, f"LOGIC ERROR: Elite 500 serve should be safer than 499!"

    print(" -> [PASS] 500-power threshold transition behaves correctly.\n")


def test_rotation_server_shift():
    print("Testing Rotation-Driven Server Shift...")

    # Create a team where the default server (Setter) is weak (90),
    # but another position in the rotation has a powerhouse serve (900).
    asymmetric_team = create_asymmetric_team(base_serve=90, carry_position="opposite", carry_serve=900)

    # Give the setter a specific name to check via message output
    asymmetric_team["setter"]["name"] = "WeakSetter"

    # Step 0: Setter is in Zone 1
    # Step 3: Opposite rotates into Zone 1
    step_0_result = serve_phase(asymmetric_team, serving_rotation_step=0)
    step_3_result = serve_phase(asymmetric_team, serving_rotation_step=3)

    print(f" -> Rotation Step 0 Server Message: {step_0_result['message']}")
    print(f" -> Rotation Step 3 Server Message: {step_3_result['message']}")

    # Assert that rotation successfully shifted the active server name
    assert "WeakSetter" in step_0_result['message'], "LOGIC ERROR: Rotation 0 should feature the Setter serving!"
    assert "GodOpposite" in step_3_result['message'], "LOGIC ERROR: Rotation 3 should rotate the Opposite into the server slot!"

    print(" -> [PASS] Rotation-driven server shift behaves correctly.\n")


def test_serve_quality_scaling():
    print("Testing Serve Quality Power Scaling...")
    base_stat = 500
    team = create_dummy_team(serve_val=base_stat, receive_val=200)

    # Run a batch to catch different qualities
    found_qualities = set()
    for _ in range(200):
        res = serve_phase(team, 0)
        if res["outcome"] == "in-play":
            q = res["quality"]
            found_qualities.add(q)
            # Verify that perfect gives more power than poor
            if q == "perfect":
                assert res["incoming_power"] > base_stat * 1.0, "Perfect serve should boost power!"
            elif q == "poor":
                assert res["incoming_power"] < base_stat * 1.0, "Poor serve should scale power down!"

    print(f" -> [PASS] Successfully verified quality tiers generated: {list(found_qualities)}\n")


def test_integration_serve_to_ace():
    print("Testing Integration: Perfect Serve -> Weak Defense Ace Transition...")
    from engine.match_simulation import receive_phase

    server_team = create_dummy_team(serve_val=900, receive_val=200)
    weak_defense_team = create_dummy_team(serve_val=100, receive_val=110)

    ace_triggered = False
    for _ in range(500):
        serve_res = serve_phase(server_team, 0)
        if serve_res["outcome"] == "in-play":
            receive_res = receive_phase(
                serve_res["incoming_power"],
                weak_defense_team,
                0,
                source_type="serve",
                source_name=serve_res["server_name"]
            )
            if receive_res["outcome"] == "receive_error":
                ace_triggered = True
                break

    assert ace_triggered, "LOGIC ERROR: A max-tier serve against a floor defense should eventually trigger a service ace via receive error!"
    print(" -> [PASS] Serve-to-receive ace integration works seamlessly.\n")

def run_distribution_test(test_name, stat_val, error_bounds, in_play_bounds):
    print(f"Testing {test_name} Distribution (Serve Stat: {stat_val})...")

    team = create_dummy_team(serve_val=stat_val, receive_val=200)

    outcomes = {"error": 0, "in-play": 0}
    qualities = {"perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        result = serve_phase(team, 0)
        outcomes[result["outcome"]] += 1
        if result["outcome"] == "in-play":
            qualities[result["quality"]] += 1

    error_pct = (outcomes["error"] / TOTAL_RUNS) * 100
    in_play_pct = (outcomes["in-play"] / TOTAL_RUNS) * 100

    print(f" -> Results: {error_pct:.1f}% Errors | {in_play_pct:.1f}% In-Play")
    print(f"    (Qualities -> Perfect: {qualities['perfect']/TOTAL_RUNS*100:.1f}%, Good: {qualities['good']/TOTAL_RUNS*100:.1f}%, Poor: {qualities['poor']/TOTAL_RUNS*100:.1f}%)")

    min_err, max_err = error_bounds
    min_ip, max_ip = in_play_bounds

    assert min_err <= error_pct <= max_err, f"UNBALANCED: Error rate of {error_pct}% is out of bounds!"
    assert min_ip <= in_play_pct <= max_ip, f"UNBALANCED: In-play rate of {in_play_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING SERVE PHASE TESTS ===")

    tests = [
        ("Stat Floor Baseline", test_low_stat_high_risk_tier),
        ("Power Threshold Transition", test_power_threshold_transition),
        ("Rotation Server Shift", test_rotation_server_shift),
        ("Serve Quality Scaling", test_serve_quality_scaling),
        ("Serve-to-Receive Ace Integration", test_integration_serve_to_ace),
        ("Early-Game Distribution", lambda: run_distribution_test("Early-Game", 150, (7, 13), (87, 93))),
        ("Mid-Game Distribution", lambda: run_distribution_test("Mid-Game", 450, (3, 8), (92, 97))),
        ("Endgame Distribution", lambda: run_distribution_test("Endgame", 800, (1, 4), (96, 99))),
        ("God-Tier Distribution", lambda: run_distribution_test("God-Tier", 1000, (0.5, 3), (97, 99.5))),
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