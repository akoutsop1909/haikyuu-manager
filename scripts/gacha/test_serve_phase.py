from helpers import create_dummy_team, create_asymmetric_team
from engine.match_simulation import get_current_rotation, serve_phase, receive_phase

# Global test configuration constant
TOTAL_RUNS = 1000


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


def test_libero_server_exemption():
    print("Testing Libero-Server Exemption Rule...")
    # Create a team dictionary with a Middle Blocker in Zone 1 (Rotation step where MB becomes server)
    # Verify that the server slot holds the middle blocker and the libero is NOT in the back row as server.
    team = create_dummy_team(serve_val=500, receive_val=500)

    # Find which rotation step places a middle_blocker in Zone 1 (server_slot)
    target_step = 0
    for step in range(6):
        formation = get_current_rotation(team, step)
        if "middle_blocker" in formation["server_slot"]:
            target_step = step
            break

    formation = get_current_rotation(team, target_step)
    server_slot = formation["server_slot"]

    assert "middle_blocker" in server_slot, "SETUP ERROR: Could not isolate a Middle Blocker in Zone 1 for this test."
    assert "libero" not in formation["back_row"] or formation["back_row"].get("libero") is None or not any(
        s == server_slot for s in formation["back_row"]), \
        "LOGIC ERROR: Libero illegally replaced the serving Middle Blocker!"

    print(f" -> [PASS] Libero successfully steps aside for serving Middle Blocker at rotation step {target_step}.\n")


def test_serve_math_multiplier_invariants():
    print("Testing Serve Phase Mathematical Multiplier Invariants...")
    base_stat = 600
    team = create_dummy_team(serve_val=base_stat, receive_val=200)

    perfect_count = 0
    poor_count = 0
    min_perfect_observed = float('inf')
    max_poor_observed = float('-inf')

    for _ in range(500):
        res = serve_phase(team, 0)
        if res["outcome"] == "in-play":
            quality = res["quality"]
            incoming_power = res["incoming_power"]

            # Mathematical constraint checks based on match_simulation.py logic:
            if quality == "perfect":
                perfect_count += 1
                min_perfect_observed = min(min_perfect_observed, incoming_power)

                # Perfect requires ratio >= 1.08 and incoming_power = server_roll * 1.20
                # Therefore, incoming_power must mathematically be >= base_stat * 1.08 * 1.20
                min_expected = base_stat * 1.08 * 1.20
                assert incoming_power >= min_expected - 1e-5, (
                    f"MATH ERROR: Perfect serve incoming_power ({incoming_power}) "
                    f"violates lower math bound ({min_expected})."
                )
            elif quality == "poor":
                poor_count += 1
                max_poor_observed = max(max_poor_observed, incoming_power)

                # Poor requires ratio < 0.93 and incoming_power = server_roll * 0.80
                # Therefore, incoming_power must mathematically be < base_stat * 0.93 * 0.80
                max_allowed = base_stat * 0.93 * 0.80
                assert incoming_power <= max_allowed + 1e-5, (
                    f"MATH ERROR: Poor serve incoming_power ({incoming_power}) "
                    f"violates upper math bound ({max_allowed})."
                )

    print(f" -> Verified {perfect_count} 'perfect' serves (Lowest power seen: {min_perfect_observed:.1f} | Required min: {base_stat * 1.08 * 1.20:.1f})")
    print(f" -> Verified {poor_count} 'poor' serves (Highest power seen: {max_poor_observed:.1f} | Required max: {base_stat * 0.93 * 0.80:.1f})")
    print(" -> [PASS] All serve quality mathematical multiplier invariants hold true.\n")


def test_integration_serve_to_ace():
    print("Testing Integration: Perfect Serve -> Weak Defense Ace Transition...")

    server_team = create_dummy_team(serve_val=900, receive_val=200)
    weak_defense_team = create_dummy_team(serve_val=100, receive_val=110)

    aces_count = 0
    total_in_play = 0
    sample_ace_message = None

    for _ in range(500):
        serve_res = serve_phase(server_team, 0)
        if serve_res["outcome"] == "in-play":
            total_in_play += 1
            receive_res = receive_phase(
                serve_res["incoming_power"],
                weak_defense_team,
                0,
                source_type="serve",
                source_name=serve_res["server_name"]
            )
            if receive_res["outcome"] == "out":
                aces_count += 1
                # Capture the first real game message generated by this handoff for inspection
                if not sample_ace_message:
                    sample_ace_message = receive_res["message"]

    assert aces_count > 0, "LOGIC ERROR: A max-tier serve against a floor defense should eventually trigger a service ace via receive error!"

    print(f" -> Handled {total_in_play} in-play high-power serves across the net into weak defense.")
    print(f" -> Successfully triggered {aces_count} service aces ({aces_count / total_in_play * 100:.1f}% ace conversion rate).")
    if sample_ace_message:
        print(f" -> Sample Game Message Handed Off: \"{sample_ace_message}\"")
    print(" -> [PASS] Serve-to-receive ace integration works seamlessly.\n")

def run_distribution_test(test_name, stat_val, out_bounds, in_play_bounds):
    print(f"Testing {test_name} Distribution (Serve Stat: {stat_val})...")

    team = create_dummy_team(serve_val=stat_val, receive_val=200)

    outcomes = {"out": 0, "in-play": 0}
    qualities = {"perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        result = serve_phase(team, 0)
        outcomes[result["outcome"]] += 1
        if result["outcome"] == "in-play":
            qualities[result["quality"]] += 1

    out_pct = (outcomes["out"] / TOTAL_RUNS) * 100
    in_play_pct = (outcomes["in-play"] / TOTAL_RUNS) * 100

    print(f" -> Results: {out_pct:.1f}% Out | {in_play_pct:.1f}% In-Play")
    print(f"    (Qualities -> Perfect: {qualities['perfect']/TOTAL_RUNS*100:.1f}%, Good: {qualities['good']/TOTAL_RUNS*100:.1f}%, Poor: {qualities['poor']/TOTAL_RUNS*100:.1f}%)")

    min_out, max_out = out_bounds
    min_ip, max_ip = in_play_bounds

    assert min_out <= out_pct <= max_out, f"UNBALANCED: Out rate of {out_pct}% is out of bounds!"
    assert min_ip <= in_play_pct <= max_ip, f"UNBALANCED: In-play rate of {in_play_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Serve distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING SERVE PHASE TESTS ===")

    tests = [
        ("Rotation Server Shift", test_rotation_server_shift),
        ("Libero Server Exemption", test_libero_server_exemption),
        ("Serve Quality Scaling", test_serve_math_multiplier_invariants),
        ("Serve-to-Receive Ace Integration", test_integration_serve_to_ace),
        ("Early-Game Distribution", lambda: run_distribution_test("Early-Game", 200, (8.0, 15.0), (85.0, 92.0))),
        ("Mid-Game Distribution", lambda: run_distribution_test("Mid-Game", 600, (4.0, 8.5), (91.5, 96.0))),
        ("Endgame Distribution", lambda: run_distribution_test("Endgame", 1200, (3.5, 7.0), (93.0, 96.5))),
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