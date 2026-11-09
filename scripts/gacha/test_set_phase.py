from helpers import create_dummy_team
from engine.match_simulation import set_phase

# Global test configuration constant
TOTAL_RUNS = 1000


def test_standard_setter_flow():
    print("Testing Standard Setter Flow (Receiver is not setter)...")
    team = create_dummy_team(set_val=500)

    # Receive happened at wing_spiker_1, so designated setter takes second touch
    res = set_phase(pass_quality="good", pass_modifier=1.00, receiver_slot="wing_spiker_1", team_stats=team, rotation_step=0)

    assert res["outcome"] == "in-play", f"LOGIC ERROR: Standard set resulted in unexpected outcome: {res['outcome']}"
    assert "set by" in res["message"], f"LOGIC ERROR: Incorrect message format: {res['message']}"
    assert res["quality"] in ["perfect", "good", "poor"], f"LOGIC ERROR: Invalid quality tier: {res['quality']}"

    print(" -> [PASS] Standard setter execution handles normal flows correctly.\n")


def test_setter_dump_wildcard_frequency():
    print("Testing Setter Dump Wildcard Frequency & Tiers (~12% on Perfect Pass)...")
    team = create_dummy_team(set_val=800)

    dump_triggered_count = 0
    dump_qualities = {"perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        # Perfect pass + receiver is NOT setter allows the setter dump check
        res = set_phase(pass_quality="perfect", pass_modifier=1.25, receiver_slot="wing_spiker_1", team_stats=team, rotation_step=0)

        if res.get("outcome") == "incoming_dump":
            dump_triggered_count += 1
            dump_qualities[res["quality"]] += 1

    dump_pct = (dump_triggered_count / TOTAL_RUNS) * 100
    print(f" -> Setter Dump triggered in {dump_pct:.1f}% of perfect passes (Target: ~12%)")
    print(f"    (Dump Qualities -> Perfect: {dump_qualities['perfect']}, Good: {dump_qualities['good']}, Poor: {dump_qualities['poor']})")

    # Expect roughly 12% frequency (allowing generous statistical bounds between 8% and 17%)
    assert 8.0 <= dump_pct <= 17.0, f"UNBALANCED: Setter dump trigger rate of {dump_pct}% is out of bounds!"
    print(" -> [PASS] Setter dump wildcard frequency is properly balanced.\n")


def test_libero_emergency_setter_fallback():
    print("Testing Libero Emergency Setter Fallback (When Setter Receives)...")
    team = create_dummy_team(set_val=300)
    # Give libero a distinct high set stat to identify them
    team["libero"]["set"] = 999
    team["libero"]["name"] = "SuperLibero"

    # Receiver slot is "setter", forcing an emergency substitution
    res = set_phase(pass_quality="good", pass_modifier=1.00, receiver_slot="setter", team_stats=team, rotation_step=0)

    assert res["outcome"] == "in-play", "LOGIC ERROR: Emergency set failed!"
    assert "SuperLibero" in res["message"], f"LOGIC ERROR: Libero did not take the emergency set! Message: {res['message']}"

    # Ensure libero CANNOT perform a setter dump even on a perfect pass
    dump_count = 0
    for _ in range(500):
        dump_res = set_phase(pass_quality="perfect", pass_modifier=1.25, receiver_slot="setter", team_stats=team,
                             rotation_step=0)
        if dump_res.get("outcome") == "incoming_dump":
            dump_count += 1

    assert dump_count == 0, "CRITICAL RULE VIOLATION: Libero was able to perform an illegal setter dump!"
    print(" -> [PASS] Libero emergency fallback works and successfully blocks illegal dumps.\n")


def test_highest_stat_emergency_setter_fallback():
    print("Testing Highest-Stat Emergency Setter Fallback (Libero Benched during MB Serve)...")
    team = create_dummy_team(set_val=200)

    # At rotation_step = 2, middle_blocker_1 is serving, so the libero is benched.
    team["middle_blocker_1"]["set"] = 950
    team["middle_blocker_1"]["name"] = "EmergencyAce"

    # Setter receives the ball at rotation step 2 (libero is benched)
    res = set_phase(pass_quality="good", pass_modifier=1.00, receiver_slot="setter", team_stats=team, rotation_step=2)

    assert res["outcome"] == "in-play", "LOGIC ERROR: Highest-stat emergency set failed!"
    assert "EmergencyAce" in res["message"], f"LOGIC ERROR: Highest stat player did not take the set! Message: {res['message']}"
    print(" -> [PASS] Highest-stat emergency setter fallback selects the optimal substitute correctly when the libero is benched.\n")


def run_set_distribution_test(test_name, stat_val, perfect_bounds, good_bounds, poor_bounds):
    print(f"Testing {test_name} Set Quality Distribution (Set Stat: {stat_val})...")

    team = create_dummy_team(set_val=stat_val)
    qualities = {"perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        # Using receiver_slot = "wing_spiker_1" to guarantee standard setter execution (no dumps skewing distribution)
        res = set_phase(pass_quality="good", pass_modifier=1.00, receiver_slot="wing_spiker_1", team_stats=team,
                        rotation_step=0)
        if res["outcome"] == "in-play":
            qualities[res["quality"]] += 1

    perf_pct = (qualities["perfect"] / TOTAL_RUNS) * 100
    good_pct = (qualities["good"] / TOTAL_RUNS) * 100
    poor_pct = (qualities["poor"] / TOTAL_RUNS) * 100

    print(f" -> Results -> Perfect: {perf_pct:.1f}%, Good: {good_pct:.1f}%, Poor: {poor_pct:.1f}%")

    min_perf, max_perf = perfect_bounds
    min_good, max_good = good_bounds
    min_poor, max_poor = poor_bounds

    assert min_perf <= perf_pct <= max_perf, f"UNBALANCED: Perfect set rate of {perf_pct}% is out of bounds!"
    assert min_good <= good_pct <= max_good, f"UNBALANCED: Good set rate of {good_pct}% is out of bounds!"
    assert min_poor <= poor_pct <= max_poor, f"UNBALANCED: Poor set rate of {poor_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Set Quality Distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING SET PHASE TESTS ===")

    tests = [
        ("Standard Setter Flow", test_standard_setter_flow),
        ("Setter Dump Wildcard Frequency", test_setter_dump_wildcard_frequency),
        ("Libero Emergency Setter Fallback", test_libero_emergency_setter_fallback),
        ("Highest-Stat Emergency Setter Fallback", test_highest_stat_emergency_setter_fallback),
        ("Early-Game Set Distribution", lambda: run_set_distribution_test("Early-Game", 200, (10, 45), (35, 75), (10, 40))),
        ("Mid-Game Set Distribution", lambda: run_set_distribution_test("Mid-Game", 600, (10, 45), (40, 75), (10, 40))),
        ("Endgame Set Distribution", lambda: run_set_distribution_test("Endgame", 1200, (10, 45), (40, 75), (10, 40))),
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
        print("=== SOME SET TESTS FAILED ===")
        exit(1)
    else:
        print("=== ALL SET TESTS PASSED SUCCESSFULLY ===")