from copy import deepcopy

from fort_gym.bench.env.campaign_encoder import encode_campaign_observation


def encode(state, **kwargs):
    return encode_campaign_observation(
        state,
        screen_text="native test screen",
        action_history=kwargs.get("history", []),
        last_action_result=kwargs.get("result"),
    )


def test_factual_campaign_observation_preserves_native_maps_and_unknowns():
    state = {
        "year": 30,
        "year_tick": 123,
        "population": 0,
        "stocks": {"food": 0, "drink": None},
        "fort": {
            "ok": True,
            "spaces_truncated": True,
            "map_origin": [2, 3, 4],
            "map_rows": ["#. "],
        },
        "crew": {"ok": False, "error": "test unavailable", "citizens": {"list_truncated": True}},
    }
    original = deepcopy(state)
    text, observed = encode(state)
    assert observed["population"] == 0 and observed["stocks"] == {"food": 0, "drink": None}
    assert observed["crew"] == state["crew"] and observed["fort"] == state["fort"]
    assert '"drink": null' in text and "Blank=hidden/unreadable" in text
    assert observed["screen_text"] == "native test screen"
    observed["fort"]["map_rows"].append("x")
    assert state == original


def test_no_benchmark_targets_strategy_or_productivity_verdicts_are_added():
    state = {
        "population": 7,
        "reminders": ["prescribed build order"],
        "agent_plan_control": {"review_due": True},
        "g7_fact_snapshot": {"score": 3},
        "work": {
            "ok": True,
            "observation_scope": "global",
            "active_jobs": 2,
            "fortress_plan_name": "two_room_workshop",
            "target_rect": [1, 2, 3],
        },
    }
    history = [
        {
            "step": 4,
            "action_type": "DIG",
            "params": {"area": [1, 2, 3]},
            "objective": "model's own plan",
            "actual_ticks": 0,
            "accepted": False,
            "plan_review": {"decision": "revise"},
            "productive_reasons": ["reward"],
            "outcome": "action_effect_observed",
        }
    ]
    text, observed = encode(state, history=history)
    for excluded in (
        "agent_plan_control",
        "g7_fact_snapshot",
        "prescribed build order",
        "two_room_workshop",
        "target_rect",
        "plan_review",
        "productive_reasons",
        "action_effect_observed",
    ):
        assert excluded not in text
    assert observed["action_history"][0]["objective"] == "model's own plan"
    assert observed["work"]["active_jobs"] == 2


def test_missing_fields_stay_missing_and_history_has_a_declared_bound():
    text, observed = encode({}, history=[{"step": i} for i in range(20)])
    assert "population" not in observed and "stocks" not in observed and "fort" not in observed
    assert "Population: unknown" in text and "Stocks: null" in text
    assert observed["action_history"] == [{"step": i} for i in range(8, 20)]


def test_memory_feedback_does_not_misread_false_rejection_flag():
    text, observed = encode({}, result={"accepted": True, "validation_rejected": False})
    line = next(line for line in text.splitlines() if line.startswith("Last Action:"))
    assert line == "Last Action: ACCEPTED"
    assert observed["last_action_result"]["validation_rejected"] is False
    text, _ = encode({}, result={"accepted": False, "why": "native blocked tile"})
    assert 'Last Action: REJECTED; "native blocked tile"' in text
