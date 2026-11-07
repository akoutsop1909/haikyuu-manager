from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import serve_phase, receive_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_extreme_mismatch_receive_error():
    print("Testing Extreme Mismatch: 1000 Incoming Power vs 110-Receive Defense (Stat Floor)...")

    incoming_power = 1000
    terrible_defense = create_dummy_team(serve_val=100, receive_val=110)

    error_count = sum(
        1 for _ in range(TOTAL_RUNS)
        if receive_phase(incoming_power, terrible_defense, 0, source_type="serve", source_name="GodServer")[
            'outcome'] == 'receive_error'
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
            'outcome'] == 'receive_error'
    )

    error_pct = (error_count / TOTAL_RUNS) * 100
    print(f" -> Elite Defense Error Rate: {error_pct:.1f}%")

    # An elite 900-receive defense should never shank a modest 400-power ball
    assert error_pct == 0, f"UNBALANCED: Elite 900-receive defense shanked a ball ({error_pct}%)!"
    print(" -> [PASS] Elite defense stability behaves correctly.\n")


def run_receive_distribution_test(test_name, stat_val, error_bounds, perfect_bounds, good_bounds, poor_bounds):
    print(f"Testing {test_name} ({stat_val} vs {stat_val} Stats) Receive Phase...")

    team = create_dummy_team(serve_val=stat_val, receive_val=stat_val)

    outcomes = {"receive_error": 0, "perfect": 0, "good": 0, "poor": 0}
    runs = 0

    # Simulate live serves to generate organic incoming power matching this stat tier
    for _ in range(TOTAL_RUNS):
        serve_res = serve_phase(team, team, 0, 0)
        if serve_res["outcome"] == "in-play":
            incoming_power = serve_res["incoming_power"]
            server_name = serve_res["server_name"]

            receive_res = receive_phase(incoming_power, team, 0, source_type="serve", source_name=server_name)

            if receive_res["outcome"] == "receive_error":
                outcomes["receive_error"] += 1
            else:
                outcomes[receive_res["quality"]] += 1
            runs += 1

    if runs == 0:
        runs = 1

    err_pct = (outcomes["receive_error"] / runs) * 100
    perf_pct = (outcomes["perfect"] / runs) * 100
    good_pct = (outcomes["good"] / runs) * 100
    poor_pct = (outcomes["poor"] / runs) * 100

    print(
        f" -> Results ({runs} incoming balls): {err_pct:.1f}% Errors | {perf_pct:.1f}% Perfect | {good_pct:.1f}% Good | {poor_pct:.1f}% Poor")

    min_err, max_err = error_bounds
    min_perf, max_perf = perfect_bounds
    min_good, max_good = good_bounds
    min_poor, max_poor = poor_bounds

    assert min_err <= err_pct <= max_err, f"UNBALANCED: Receive error rate of {err_pct}% is out of bounds!"
    assert min_perf <= perf_pct <= max_perf, f"UNBALANCED: Perfect pass rate of {perf_pct}% is out of bounds!"
    assert min_good <= good_pct <= max_good, f"UNBALANCED: Good pass rate of {good_pct}% is out of bounds!"
    assert min_poor <= poor_pct <= max_poor, f"UNBALANCED: Poor pass rate of {poor_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Receive Distribution is healthy and balanced.\n")


def test_rotation_receive_shift():
    print("Testing Rotation-Driven Back-Row Shift for Reception...")

    asymmetric_team = create_asymmetric_team(base_serve=100, base_receive=150, carry_position="libero", carry_receive=950)
    incoming_power = 600

    for step in range(6):
        res = receive_phase(incoming_power, asymmetric_team, step, source_type="serve", source_name="Server")
        assert "outcome" in res, f"LOGIC ERROR: Receive phase failed to return a valid outcome at rotation step {step}!"

    print(" -> [PASS] Rotation-driven back-row shifts execute smoothly without errors.\n")


if __name__ == "__main__":
    print("=== STARTING RECEIVE PHASE TESTS ===")

    tests = [
        ("Extreme Mismatch Receive Error", test_extreme_mismatch_receive_error),
        ("Elite Defense Stability", test_elite_defense_stability),
        ("Rotation Receive Shift", test_rotation_receive_shift),
        ("Early-Game Receive Distribution", lambda: run_receive_distribution_test("Early-Game", 150, (0, 2), (10, 45), (40, 75), (10, 40))),
        ("Mid-Game Receive Distribution", lambda: run_receive_distribution_test("Mid-Game", 450, (0, 2), (10, 45), (40, 75), (10, 40))),
        ("Endgame Receive Distribution", lambda: run_receive_distribution_test("Endgame", 800, (0, 2), (10, 45), (40, 75), (10, 40))),
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