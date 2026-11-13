def create_dummy_team(serve_val=100, receive_val=100, set_val=100, spike_val=100):
    """Helper to quickly spin up a team with flat stats for edge testing."""
    return {
        "setter": {"name": "TestSetter", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "opposite": {"name": "TestOpposite", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "wing_spiker_1": {"name": "TestWS1", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "wing_spiker_2": {"name": "TestWS2", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "middle_blocker_1": {"name": "TestMB1", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "middle_blocker_2": {"name": "TestMB2", "serve": serve_val, "receive": receive_val, "set": set_val, "spike": spike_val},
        "libero": {"name": "TestLibero", "serve": 0, "receive": receive_val, "set": set_val, "spike": 0}
    }


def create_asymmetric_team(base_serve=100, base_receive=200, base_set=100, base_spike=100, carry_position="setter", carry_serve=900, carry_receive=900, carry_set=900, carry_spike=900):
    """Helper to spin up a team where one specific player has hyper-stats to test rotation shifts or stat mismatches."""
    team = create_dummy_team(serve_val=base_serve, receive_val=base_receive, set_val=base_set, spike_val=base_spike)

    # Override whichever position you pass into carry_position
    team[carry_position] = {
        "name": f"God{carry_position.capitalize()}",
        "serve": carry_serve,
        "receive": carry_receive,
        "set": carry_set,
        "spike": carry_spike
    }

    return team