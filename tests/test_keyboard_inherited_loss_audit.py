"""A recovered save retains lost usage across ordinary, non-restart windows."""

import hashlib
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_window_audit import settled_segment_spans
from tests.test_keyboard_restart import failed as failed
from tests.test_keyboard_runtime import CONDITION, policy, saved as saved
from tests.test_keyboard_segment_audit import (
    REVISION, audit as segment_audit, continuation_trial, modify, semantic_environment,
)
from tests.test_keyboard_window_checkpoint_audit import audit, window_fixture


@pytest.fixture(autouse=True)
def synthetic_budget(monkeypatch):
    # The fixture needs ten total responses, including two lost responses.
    # Set its condition before creating any synthetic campaign state.
    monkeypatch.setitem(CONDITION, "max_dispatches", 32)


@pytest.fixture
def inherited_trial(tmp_path, failed):
    checkpoint, source, declaration = failed
    game = semantic_environment()
    game.tick = int((checkpoint / "game/world.sav").read_text())
    output = tmp_path / "recovery"
    result = run_keyboard_segment(
        agent=policy(CONDITION), environment=game, snapshotter=game,
        output=output, condition=CONDITION, checkpoint=checkpoint,
        latest_usage=source / "segment-0/loop/usage.jsonl", steps=1,
        expected_cursor=1, revision=REVISION,
        restart_declaration=declaration, restart_source=source,
    )
    assert result["next_step"] == 2 and result["usage"]["accounted_responses"] == 4
    return continuation_trial(tmp_path, output / "checkpoint")


@pytest.mark.parametrize("paused", [False, True])
def test_ordinary_window_keeps_prior_loss_and_full_usage(inherited_trial, paused):
    parent = inherited_trial[1]
    original = (parent / "checkpoint.json").read_bytes()
    window, _ = window_fixture(inherited_trial, paused)
    assert window["continuation_from_next_step"] == 2
    assert window["accounted_responses_before_window"] == 4
    report = audit(inherited_trial, window)
    responses = 3 if paused else 6
    assert report["new_responses"] == responses
    assert report["next_step"] == 2 + responses
    assert report["usage"]["accounted_responses"] == 4 + responses
    assert report["new_tokens"] == 100 * responses
    assert report["saved_elapsed_ticks"] == 20 + 10 * responses
    assert report["new_saved_ticks"] == 10 * responses
    history = read(parent / "runner.json")["discontinuities"]
    assert len(history) == 1 and history[0]["lost_elapsed_ticks"] == 20
    assert report["inherited_discontinuities"] == history
    assert report["uninterrupted_campaign"] is False
    for segment in report["segments"]:
        assert segment["inherited_discontinuities"] == history
        assert segment["uninterrupted_campaign"] is False
    assert report["segments"][0]["final_fresh_reload_verified"] is True
    assert report["final_fresh_reload_verified"] is False
    assert (parent / "checkpoint.json").read_bytes() == original


@pytest.mark.parametrize("target", ["start_history", "result", "invalid_history"])
def test_ordinary_segment_cannot_erase_or_invent_loss(inherited_trial, target):
    native = inherited_trial[0]
    if target == "start_history":
        modify(native / "segment-0/history-before.json", ("discontinuities",), [])
    elif target == "result":
        modify(native / "segment-0/result.json", ("discontinuities",), [])
        modify(native / "runtime-0/result.json", ("experiment", "discontinuities"), [])
    else:
        history = read(native / "segment-0/history-before.json")["discontinuities"]
        history[0]["lost_elapsed_ticks"] += 1
        modify(native / "segment-0/history-before.json", ("discontinuities",), history)
    with pytest.raises(ValueError):
        segment_audit(inherited_trial)


def test_window_cannot_reset_accounted_responses_to_saved_cursor(inherited_trial):
    window, _ = window_fixture(inherited_trial)
    window["accounted_responses_before_window"] = window["continuation_from_next_step"]
    (inherited_trial[0] / "window.json").write_text(json.dumps(window))
    with pytest.raises(ValueError, match="actual prior usage"):
        audit(inherited_trial, window)


def test_span_checker_requires_explicit_parent_history(inherited_trial):
    window, result = window_fixture(inherited_trial)
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)
    history = read(inherited_trial[1] / "runner.json")["discontinuities"]
    assert len(settled_segment_spans(result, window, inherited_discontinuities=history)) == 2


@pytest.mark.parametrize("target", ["trace", "runner"])
def test_self_consistent_checkpoint_cannot_erase_inherited_loss(inherited_trial, target):
    segment = inherited_trial[0] / "segment-0"
    checkpoint = segment / "checkpoint"
    if target == "trace":
        rows = [json.loads(line) for line in (checkpoint / "trace.jsonl").read_text().splitlines()]
        rows[-1]["discontinuities"] = []
        content = "".join(json.dumps(row) + "\n" for row in rows)
        (checkpoint / "trace.jsonl").write_text(content)
        (segment / "loop/trace.jsonl").write_text(content)
    else:
        modify(checkpoint / "runner.json", ("discontinuities",), [])
    name = "trace.jsonl" if target == "trace" else "runner.json"
    manifest = read(checkpoint / "checkpoint.json")
    manifest["payload"][target + "_sha256"] = hashlib.sha256((checkpoint / name).read_bytes()).hexdigest()
    manifest["sha256"] = hashlib.sha256(
        json.dumps(manifest["payload"], sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()
    (checkpoint / "checkpoint.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inherited loss history"):
        segment_audit(inherited_trial)
