from __future__ import annotations

from fort_gym.bench.eval.gates import FAIL, PASS, UNKNOWN, evaluate_g7


def _row(
    step: int,
    *,
    survival=None,
    dead: int = 0,
    drink: int = 80,
    completed_beds: int | None = 5,
    ticks_advanced: int = 403_200,
):
    survival_payload = dict(survival or {})
    survival_payload.setdefault("run_id", "g7-test")
    crew = {}
    if completed_beds is not None:
        crew["placed_furniture_completed"] = {"bed": completed_beds}
    state = {
        "population": 15,
        "dead": dead,
        "stocks": {"food": 80, "drink": drink},
        "crew": crew,
        "survival": survival_payload,
    }
    return {
        "run_id": "g7-test",
        "step": step,
        "action": {"type": "WAIT", "params": {}, "advance_ticks": ticks_advanced},
        "observation": state,
        "state_after_advance": state,
        "metrics": {"dead": dead, "fort_functional_rooms": 3},
        "execute": {"accepted": True, "provenance": "dfhack_governed"},
        "tick_advance": {"ticks_advanced": ticks_advanced},
        "screen_text": "DF screen",
        "gameplay_proof": {
            "ok": True,
            "source": "dfhack-map-and-state",
            "provenance": "dfhack_governed",
        },
        "events": [
            {
                "type": "tool_call",
                "data": {
                    "tool": "openrouter.chat.completions.create",
                    "input": {"model": "z-ai/glm-5v-turbo"},
                    "output": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            }
        ],
    }


def _summary(**overrides):
    value = {
        "duration_ticks": 403_200,
        "end_pop": 15,
        "fort_functional_rooms": 3,
        "total_score": 150,
        "score_version": 3,
        "rubric": {"rubric_score": 70, "blockers": []},
    }
    value.update(overrides)
    return value


def test_g7_pass_requires_every_ratified_fact() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }
    result = evaluate_g7([_row(0, survival=survival)], _summary())

    assert result["status"] == PASS
    assert all(item["status"] == PASS for item in result["criteria"].values())


def test_g7_failure_wins_over_unknown_evidence() -> None:
    result = evaluate_g7(
        [
            _row(
                0,
                dead=1,
                drink=0,
                completed_beds=None,
                ticks_advanced=199_691,
            )
        ],
        _summary(
            duration_ticks=199_691,
            fort_functional_rooms=0,
            total_score=209.44,
            rubric={"rubric_score": 63.79, "blockers": []},
        ),
    )
    assert result["status"] == FAIL
    assert result["criteria"]["duration"]["status"] == FAIL
    assert result["criteria"]["food_and_drink_loop"]["status"] == FAIL
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert result["criteria"]["installed_beds"]["status"] == UNKNOWN


def test_g7_death_without_cause_is_unknown_when_everything_else_passes() -> None:
    survival = {
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
    }
    result = evaluate_g7([_row(0, survival=survival, dead=1)], _summary())

    assert result["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN


def test_g7_zero_deaths_without_complete_run_scoped_evidence_is_unknown() -> None:
    result = evaluate_g7([_row(0)], _summary())

    assert result["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
    assert "run-scoped" in result["criteria"]["neglect_deaths"]["reason"]


def test_g7_duration_comes_from_trace_and_rejects_a_forged_summary() -> None:
    row = _row(
        0,
        ticks_advanced=1_000,
        survival={"death_evidence_complete": True},
    )

    result = evaluate_g7([row], _summary(duration_ticks=403_200))

    duration = result["criteria"]["duration"]
    assert duration["status"] == FAIL
    assert duration["observed"] == {
        "trace_ticks": 1_000,
        "summary_ticks": 403_200,
        "summary_consistent": False,
    }


def test_g7_missing_step_evidence_fails_closed() -> None:
    row = _row(0)
    row.pop("screen_text")
    result = evaluate_g7([row], _summary())

    assert result["status"] == FAIL
    assert result["criteria"]["evidence"]["status"] == FAIL


def test_g7_screen_capture_error_is_not_counted_as_evidence() -> None:
    row = _row(0)
    row["screen_text"] = "(screen capture failed)"

    result = evaluate_g7([row], _summary())

    assert result["criteria"]["evidence"]["status"] == FAIL


def test_g7_rejects_complete_survival_facts_from_another_run() -> None:
    survival = {
        "run_id": "stale-run",
        "food_produced_in_run": 21,
        "food_consumed_in_run": 20,
        "drink_produced_in_run": 31,
        "drink_consumed_in_run": 30,
        "flow_evidence_complete": True,
        "death_evidence_complete": True,
        "death_causes_known": True,
        "neglect_deaths": 0,
    }

    result = evaluate_g7([_row(0, survival=survival, dead=1)], _summary())

    assert result["criteria"]["food_and_drink_loop"]["status"] == UNKNOWN
    assert result["criteria"]["neglect_deaths"]["status"] == UNKNOWN
