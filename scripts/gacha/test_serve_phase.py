from helpers import create_dummy_team, create_asymmetric_team, add_pinch_server
from engine.match_simulation import get_current_rotation, serve_phase

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
    team = create_dummy_team(serve_val=500)

    # Step 2 places middle_blocker_1 in Zone 1 (server_slot)
    # Step 5 places middle_blocker_2 in Zone 1 (server_slot)
    for target_step, expected_mb in [(2, "middle_blocker_1"), (5, "middle_blocker_2")]:
        formation = get_current_rotation(team, target_step)
        server_slot = formation["server_slot"]

        assert server_slot == expected_mb, (f"SETUP ERROR: Expected {expected_mb} in Zone 1 at step {target_step}, got {server_slot}."
        )
        assert server_slot in formation["back_row"], (
            f"LOGIC ERROR: Serving {expected_mb} missing from back_row at step {target_step}!"
        )
        assert formation["back_row"].get("libero") != team["libero"] or server_slot != "libero", (
            f"LOGIC ERROR: Libero illegally replaced serving {expected_mb} at step {target_step}!"
        )
        assert "libero" not in formation["back_row"] or all(
            slot != server_slot for slot in formation["back_row"] if slot == "libero"
        ), f"LOGIC ERROR: Libero is occupying the server slot for {expected_mb} at step {target_step}!"

    print(" -> [PASS] Libero steps aside for both Middle Blocker 1 (step 2) and Middle Blocker 2 (step 5) when serving.\n")


def test_pinch_server_serves_for_mb1():
    print("Testing Pinch Server Actually Serves for Middle Blocker 1...")
    team = add_pinch_server(create_dummy_team(serve_val=50), serve_val=2000)
    mb1_step = 2

    serving_formation = get_current_rotation(team, mb1_step, pinch_active=True)
    assert serving_formation["is_pinch_active"] is True, (
        f"LOGIC ERROR: Expected is_pinch_active=True at step {mb1_step}, got {serving_formation['is_pinch_active']}"
    )
    assert serving_formation["back_row"]["middle_blocker_1"] == team["pinch_server"], (
        "LOGIC ERROR: Pinch server did not replace Middle Blocker in back_row when serving."
    )

    res = serve_phase(team, serving_rotation_step=mb1_step, pinch_active=True)
    if res["outcome"] == "in-play":
        assert res["incoming_power"] > 200, (
            f"LOGIC ERROR: Expected higher incoming_power from 2000-serve pinch server, got {res['incoming_power']:.1f}"
        )

    print(f" -> [PASS] Pinch server replaces Middle Blocker 1 when serving at rotation step {mb1_step}.\n")


def run_distribution_test(test_name, stat_val, out_bounds, in_play_bounds):
    print(f"Testing {test_name} Distribution (Serve Stat: {stat_val})...")

    team = create_dummy_team(serve_val=stat_val)

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
        ("Pinch Server Serves for MB1", test_pinch_server_serves_for_mb1),
        ("Early-Game Distribution", lambda: run_distribution_test("Early-Game", 200, (8.0, 15.0), (85.0, 92.0))),
        ("Mid-Game Distribution", lambda: run_distribution_test("Mid-Game", 600, (4.0, 8.5), (91.5, 96.0))),
        ("Endgame Distribution", lambda: run_distribution_test("Endgame", 1200, (2.5, 7.5), (93.0, 96.5))),
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