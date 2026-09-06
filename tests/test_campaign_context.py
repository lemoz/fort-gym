"""Prompt projection tests; no native game or inference calls."""

import json
from copy import deepcopy

import pytest

from fort_gym.bench.agent.campaign_context import pack_messages, project_observation
from fort_gym.bench.agent.memory import MemoryManager
from fort_gym.bench.env.campaign_encoder import (
    encode_campaign_observation,
    render_campaign_observation,
)


def observation():
    _, result = encode_campaign_observation(
        {
            "year": 30,
            "year_tick": 12,
            "population": 0,
            "stocks": {"food": None},
            "fort": {"ok": False, "error": "unavailable", "map_rows": [".# "]},
        },
        screen_text="native dialog must remain exact",
        action_history=[
            {
                "step": i,
                "action_type": "DIG",
                "params": {"area": [i, 2, 3]},
                "accepted": False,
                "error": "native rejection",
                "actual_ticks": 0,
                "result_details": {"large": "details"},
                "failed_targets": [[i, 2, 3]],
            }
            for i in range(12)
        ],
        last_action_result={
            "accepted": False,
            "why": "native rejection",
            "result": {"large": "latest details"},
        },
    )
    return result


def extract(messages):
    return json.loads(messages[1]["content"].split("Native facts and recent commands:\n", 1)[1])


def test_projection_preserves_current_facts_and_latest_result_without_mutation():
    full = observation()
    before = deepcopy(full)
    projected = project_observation(full, 2)
    for key in full.keys() - {"action_history"}:
        assert projected[key] == full[key]
    assert [row["step"] for row in projected["action_history"]] == [10, 11]
    assert projected["action_history"][0]["params"] == {"area": [10, 2, 3]}
    assert "result_details" not in projected["action_history"][0]
    assert projected["prompt_projection"]["history_rows_omitted"] == 10
    projected["fort"]["map_rows"].append("changed copy")
    assert full == before


def test_packing_selects_largest_fitting_newest_suffix_without_fabricating_actions():
    full = observation()
    messages = pack_messages(
        full,
        system_prompt="test policy",
        memory_context="Persistent model note",
        fits=lambda candidate: len(extract(candidate)["action_history"]) <= 2,
    )
    assert messages is not None
    projected = extract(messages)
    assert len(projected["action_history"]) == 2
    assert projected["prompt_projection"]["history_rows_retained"] == 2
    assert "Persistent model note" in messages[1]["content"]
    assert projected["population"] == 0 and projected["stocks"]["food"] is None
    assert projected["screen_text"] == full["screen_text"]


def test_irreducible_snapshot_is_never_truncated_to_force_a_fit():
    full = observation()
    attempts = []

    def reject(messages):
        projected = extract(messages)
        assert projected["last_action_result"] == full["last_action_result"]
        assert projected["fort"] == full["fort"]
        attempts.append(projected)
        return False

    assert pack_messages(full, system_prompt="test", memory_context="note", fits=reject) is None
    assert [item["prompt_projection"]["history_rows_retained"] for item in attempts] == list(
        range(12, -1, -1)
    )


def test_legacy_rendering_and_compact_rendering_share_identical_facts():
    full = observation()
    legacy = render_campaign_observation(full)
    compact = render_campaign_observation(full, compact=True)
    assert len(compact) < len(legacy)
    assert json.loads(legacy.split("Native facts and recent commands:\n")[1]) == full
    assert json.loads(compact.split("Native facts and recent commands:\n")[1]) == full
    assert legacy.splitlines()[:4] == compact.splitlines()[:4]


def test_persistent_memory_notes_survive_duplicate_recent_text_omission():
    memory = MemoryManager()
    memory.add_step("native state", {"type": "WAIT"}, "accepted")
    memory.remember_poi(label="model's own long-term note")
    before = memory.export_checkpoint()
    assert "Recent Steps:" in memory.get_context()
    assert "Recent Steps:" not in memory.get_context(include_recent=False)
    assert "model's own long-term note" in memory.get_context(include_recent=False)
    assert memory.export_checkpoint() == before


@pytest.mark.parametrize("keep", [-1, 13, True])
def test_invalid_projection_bounds_are_rejected(keep):
    with pytest.raises(ValueError):
        project_observation(observation(), keep)
