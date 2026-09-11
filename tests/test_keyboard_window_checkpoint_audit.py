"""Synthetic two-segment windows exercise real checkpoint/journal verification."""

import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.eval.campaign import read_campaign_progress
from fort_gym.bench.run.keyboard_window_checkpoint_audit import (
    verify_window_checkpoints,
)
from tests.test_campaign_codex_keyboard import admission_denied, decision
from tests.test_keyboard_runtime import CONDITION
from tests.test_keyboard_segment_audit import REVISION, modify, trial as trial


def window_fixture(trial, paused=False):
    native, parent, _, metrics, run = trial
    run(1, native / "segment-0/checkpoint", admission_denied if paused else decision)
    cursor = read(parent / "checkpoint.json")["payload"]["next_step"]
    usage = read(parent / "agent.json")["usage"]
    window = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "continuation_from_next_step": cursor,
        "steps_per_segment": 3,
        "max_segments": 2,
        "window_end_decision": cursor + 6,
        "source_native_revision": REVISION,
        "expected_campaign_id": "runtime-test",
        "continuation_checkpoint_sha256": read(parent / "checkpoint.json")["sha256"],
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        "accounted_responses_before_window": usage["accounted_responses"],
        "returned_tokens_before_window": usage["total_tokens"],
        "saved_elapsed_ticks_before_window": read_campaign_progress(parent / "trace.jsonl")["elapsed_ticks"],
    }
    result = {
        "schema_version": "fortgym.keyboard-window-result/v1",
        "source_revision": REVISION,
        "campaign_id": "runtime-test",
        "status": "paused" if paused else "completed",
        "original_checkpoint_unchanged": True,
        "runtime_cleanup_verified": True,
        "segments": [read(native / f"segment-{i}/result.json") for i in range(2)],
    }
    publish(native / "condition.json", CONDITION)
    publish(native / "window.json", window)
    publish(native / "result.json", result)
    return window, result


def audit(trial, window):
    return verify_window_checkpoints(
        trial[0], trial[1], condition=CONDITION, window=window, initial_metrics=trial[3]
    )


@pytest.mark.parametrize("paused", [False, True])
def test_whole_window_reconciles_saved_segments_and_exact_intermediate_reload(
    trial, paused
):
    window, _ = window_fixture(trial, paused)
    report = audit(trial, window)
    responses = 3 if paused else 6
    assert report["new_responses"] == responses
    assert report["new_tokens"] == responses * 100
    assert report["new_saved_ticks"] == responses * 10
    assert report["saved_elapsed_ticks"] == 10 + responses * 10
    assert report["usage"]["accounted_responses"] == 1 + responses
    assert report["status"] == ("paused" if paused else "completed")
    assert [row["final_fresh_reload_verified"] for row in report["segments"]] == [
        True,
        False,
    ]
    assert report["final_fresh_reload_verified"] is False
    assert report["segments"][-1]["checkpoint_sha256"] == report["checkpoint_sha256"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("accounted_responses_before_window", 0),
        ("accounted_responses_before_window", True),
        ("returned_tokens_before_window", False),
        ("saved_elapsed_ticks_before_window", True),
        ("returned_tokens_before_window", 99),
        ("saved_elapsed_ticks_before_window", 0),
        ("continuation_checkpoint_sha256", "b" * 64),
    ],
)
def test_window_cannot_misstate_its_baseline(trial, field, value):
    window, _ = window_fixture(trial)
    window[field] = value
    (trial[0] / "window.json").write_text(json.dumps(window))
    with pytest.raises(ValueError):
        audit(trial, window)


def test_window_cannot_drop_a_saved_middle_segment(trial):
    window, result = window_fixture(trial)
    result["segments"] = result["segments"][1:]
    (trial[0] / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        audit(trial, window)


def test_second_runtime_must_identify_the_first_segments_actual_checkpoint_file(trial):
    window, _ = window_fixture(trial)
    modify(
        trial[0] / "runtime-1/result.json", ("source_checkpoint_file_sha256",), "b" * 64
    )
    with pytest.raises(ValueError):
        audit(trial, window)


def test_window_summary_must_match_each_segments_actual_result(trial):
    window, result = window_fixture(trial)
    result["segments"][-1]["usage"]["total_tokens"] += 1
    (trial[0] / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Window summary differs"):
        audit(trial, window)
