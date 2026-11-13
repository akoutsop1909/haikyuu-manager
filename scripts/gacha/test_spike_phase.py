from helpers import create_dummy_team
from engine.match_simulation import get_current_rotation, spike_phase

TOTAL_RUNS = 1000


def test_standard_spike_flow():
    print("Testing Standard Spike Flow...")
    team = create_dummy_team(spike_val=500)

    res = spike_phase(attack_modifier=1.00, setter_name="TestSetter", attacking_team_stats=team, rotation_step=0)

    assert "spiker_name" in res, "LOGIC ERROR: Spiker name missing from spike result!"
    assert res["outcome"] == "in-play", f"LOGIC ERROR: Spike resulted in unexpected outcome: {res['outcome']}"
    assert "spike by" in res["message"], f"LOGIC ERROR: Incorrect message format: {res['message']}"
    assert res["quality"] in ["perfect", "good", "poor"], f"LOGIC ERROR: Invalid quality tier: {res['quality']}"

    print(" -> [PASS] Standard spike execution handles normal flows correctly.\n")


def test_exclusion_rules():
    print("Testing Exclusions (Setter, Libero, and Emergency Setter cannot spike)...")
    team = create_dummy_team(spike_val=500)

    # Customize names to explicitly check exclusions
    team["setter"]["name"] = "ForbiddenSetter"
    team["libero"]["name"] = "ForbiddenLibero"
    team["wing_spiker_1"]["name"] = "EmergencySetterWS"

    # Run many iterations to ensure forbidden names never appear as spiker_name
    for _ in range(TOTAL_RUNS):
        # Pass "EmergencySetterWS" as setter_name to check emergency setter exclusion
        res = spike_phase(attack_modifier=1.00, setter_name="EmergencySetterWS", attacking_team_stats=team, rotation_step=0)
        spiker = res["spiker_name"]

        assert spiker != "ForbiddenSetter", "CRITICAL RULE VIOLATION: Designated setter was allowed to spike!"
        assert spiker != "ForbiddenLibero", "CRITICAL RULE VIOLATION: Libero was allowed to spike!"
        assert spiker != "EmergencySetterWS", "CRITICAL RULE VIOLATION: Emergency setter was allowed to spike!"

    print(" -> [PASS] Setter, Libero, and Emergency Setter are successfully excluded from spiking.\n")


def test_attack_modifier_scaling():
    print("Testing Attack Modifier Scaling (Impact of Set Quality on Spikes)...")
    team = create_dummy_team(spike_val=600)

    poor_mod_perfects = 0
    perf_mod_perfects = 0
    runs = 500

    for _ in range(runs):
        res_poor = spike_phase(attack_modifier=0.75, setter_name="TestSetter", attacking_team_stats=team, rotation_step=0)
        if res_poor["quality"] == "perfect":
            poor_mod_perfects += 1

        res_perf = spike_phase(attack_modifier=1.30, setter_name="TestSetter", attacking_team_stats=team, rotation_step=0)
        if res_perf["quality"] == "perfect":
            perf_mod_perfects += 1

    print(f" -> Perfect Spikes from Poor Sets (0.75 mod): {(poor_mod_perfects/runs)*100:.1f}%")
    print(f" -> Perfect Spikes from Perfect Sets (1.30 mod): {(perf_mod_perfects/runs)*100:.1f}%")

    assert perf_mod_perfects > poor_mod_perfects * 2, (
        "LOGIC ERROR: Attack modifier scaling is too weak! "
        "A 1.30 attack modifier must reward the spiker much more than a 0.75 modifier."
    )
    print(" -> [PASS] Attack modifier scaling properly impacts spike performance.\n")


def test_front_back_row_frequency():
    print("Testing Front-Row vs Back-Row Spike Frequency (SPIKE_WEIGHTS check)...")
    team = create_dummy_team(spike_val=500)

    front_row_count = 0
    back_row_count = 0

    for rotation_step in range(6):
        formation = get_current_rotation(team, rotation_step)
        front_names = {card["name"] for card in formation["front_row"].values()}
        back_names = {card["name"] for card in formation["back_row"].values()}
        if "libero" in formation["back_row"]:
            back_names.add(team["libero"]["name"])

        for _ in range(200):
            res = spike_phase(attack_modifier=1.00, setter_name="TestSetter", attacking_team_stats=team, rotation_step=rotation_step)
            spiker = res["spiker_name"]
            if spiker in front_names:
                front_row_count += 1
            elif spiker in back_names:
                back_row_count += 1

    total = front_row_count + back_row_count
    front_pct = (front_row_count / total) * 100
    back_pct = (back_row_count / total) * 100

    print(f" -> Front-Row Spikes: {front_pct:.1f}% | Back-Row Spikes: {back_pct:.1f}% (Target: Front-row dominant)")

    # Front row should heavily outweigh back row based on SPIKE_WEIGHTS
    assert front_pct > 68.0, f"UNBALANCED: Front row frequency of {front_pct}% is too low!"
    print(" -> [PASS] Front-row vs back-row spike frequency aligns with realistic volleyball weights.\n")


def run_spike_distribution_test(test_name, stat_val, perfect_bounds, good_bounds, poor_bounds):
    print(f"Testing {test_name} Spike Quality Distribution (Spike Stat: {stat_val})...")
    team = create_dummy_team(spike_val=stat_val)
    qualities = {"perfect": 0, "good": 0, "poor": 0}

    for _ in range(TOTAL_RUNS):
        res = spike_phase(attack_modifier=1.00, setter_name="TestSetter", attacking_team_stats=team, rotation_step=0)
        qualities[res["quality"]] += 1

    perf_pct = (qualities["perfect"] / TOTAL_RUNS) * 100
    good_pct = (qualities["good"] / TOTAL_RUNS) * 100
    poor_pct = (qualities["poor"] / TOTAL_RUNS) * 100

    print(f" -> Results -> Perfect: {perf_pct:.1f}%, Good: {good_pct:.1f}%, Poor: {poor_pct:.1f}%")

    min_perf, max_perf = perfect_bounds
    min_good, max_good = good_bounds
    min_poor, max_poor = poor_bounds

    assert min_perf <= perf_pct <= max_perf, f"UNBALANCED: Perfect spike rate of {perf_pct}% is out of bounds!"
    assert min_good <= good_pct <= max_good, f"UNBALANCED: Good spike rate of {good_pct}% is out of bounds!"
    assert min_poor <= poor_pct <= max_poor, f"UNBALANCED: Poor spike rate of {poor_pct}% is out of bounds!"

    print(f" -> [PASS] {test_name} Spike Quality Distribution is healthy and balanced.\n")


if __name__ == "__main__":
    print("=== STARTING SPIKE PHASE TESTS ===")

    tests = [
        ("Standard Spike Flow", test_standard_spike_flow),
        ("Exclusion Rules (Setter, Libero, Emergency Setter)", test_exclusion_rules),
        ("Attack Modifier Scaling", test_attack_modifier_scaling),
        ("Front-Row vs Back-Row Frequency", test_front_back_row_frequency),
        ("Early-Game Spike Distribution", lambda: run_spike_distribution_test("Early-Game", 200, (26.0, 35.0), (40.0, 52.0), (19.0, 28.0))),
        ("Mid-Game Spike Distribution", lambda: run_spike_distribution_test("Mid-Game", 600, (29.0, 38.0), (42.0, 53.0), (15.0, 23.0))),
        ("Endgame Spike Distribution", lambda: run_spike_distribution_test("Endgame", 1200, (32.0, 41.0), (46.0, 57.0), (9.0, 16.0))),
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
        print("=== SOME SPIKE TESTS FAILED ===")
        exit(1)
    else:
        print("=== ALL SPIKE TESTS PASSED SUCCESSFULLY ===")