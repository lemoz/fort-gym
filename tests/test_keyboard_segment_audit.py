"""Real checkpoint/journal mechanics with deterministic fake game/runtime data."""

import hashlib
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.eval.campaign_profile import metrics_from_state
from fort_gym.bench.run.campaign_checkpoint import CampaignCheckpointError
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_segment_audit import (
    verify_save_boundary,
    verify_saved_segment,
)
from fort_gym.bench.run.keyboard_window_audit import SegmentSpan
from tests.test_keyboard_runtime import CONDITION, environment, policy
from tests.test_campaign_codex_keyboard import admission_denied, decision

REVISION = "a" * 40


def semantic_environment():
    env = environment()
    capture = env.capture
    observe = env.observe

    def observation():
        return {
            **observe(),
            "campaign_observation_quality": {
                "schema_version": "fortgym.campaign-observation-quality/v1",
                "native_population_resources_validated": True,
            },
        }

    env.observe = observation

    def snapshot(path):
        return {
            **capture(path),
            "snapshot_profile": "native_menu_preserving_save/v4",
            "screen_sha256": "a" * 64,
            "screen_after_sha256": "a" * 64,
            "screen_unchanged": True,
            "ui_identity_unchanged": True,
            "world_observations_unchanged": True,
        }

    env.capture = snapshot
    return env


@pytest.fixture
def trial(tmp_path):
    env = semantic_environment()
    loop = CampaignLoop(
        campaign_id="runtime-test",
        agent=policy(CONDITION),
        environment=env,
        output=tmp_path / "original",
        observation_profile=CONDITION["observation_profile"],
        advance_policy=CONDITION["advance_policy"],
    )
    loop.step()
    initial = tmp_path / "checkpoint"
    loop.checkpoint(initial, snapshotter=env, code_revision=REVISION)
    native = tmp_path / "native"
    native.mkdir()

    def run(index, parent, callback=decision):
        game = semantic_environment()
        game.tick = int((parent / "game/world.sav").read_text())
        before = game.observe()
        cursor = read(parent / "checkpoint.json")["payload"]["next_step"]
        result = run_keyboard_segment(
            agent=policy(CONDITION, callback),
            environment=game,
            snapshotter=game,
            output=native / f"segment-{index}",
            condition=CONDITION,
            checkpoint=parent,
            latest_usage=parent / "usage.jsonl",
            steps=3,
            expected_cursor=cursor,
            revision=REVISION,
        )
        runtime = native / f"runtime-{index}"
        runtime.mkdir()
        publish(
            runtime / "result.json",
            {
                "experiment": result,
                "code_revision": REVISION,
                "source_checkpoint_file_sha256": hashlib.sha256(
                    (parent / "checkpoint.json").read_bytes()
                ).hexdigest(),
                "native_load_verified": True,
                "cleanup_verified": True,
                "listener_closed": True,
                "remaining_live_processes": [],
                "loaded": {
                    "year": before["year"],
                    "year_tick": before["year_tick"],
                    "paused": True,
                },
            },
        )
        span = SegmentSpan(index, cursor, result["next_step"])
        return span, metrics_from_state(before)

    span, metrics = run(0, initial)
    return native, initial, span, metrics, run


def audit(trial):
    native, parent, span, metrics, _ = trial
    return verify_saved_segment(
        native,
        parent,
        span,
        campaign_id="runtime-test",
        revision=REVISION,
        expected_initial_metrics=metrics,
    )


def modify(path, keys, value):
    data = read(path)
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    path.write_text(json.dumps(data))


def test_two_segments_extend_own_inventory_memory_usage_and_calendar(trial):
    native, parent, span, metrics, run = trial
    first = audit(trial)
    next_parent = native / "segment-0/checkpoint"
    second_span, second_metrics = run(1, next_parent)
    second = audit((native, next_parent, second_span, second_metrics, run))
    assert first["new_responses"] == second["new_responses"] == 3
    assert first["new_tokens"] == second["new_tokens"] == 300
    assert first["new_saved_ticks"] == second["new_saved_ticks"] == 30
    assert second["usage"]["accounted_responses"] == 7
    assert second["usage"]["total_tokens"] == 700
    assert second["prior_checkpoint_sha256"] == first["checkpoint_sha256"]
    assert second["source_checkpoint_fresh_load_verified"] is True
    assert second["final_fresh_reload_verified"] is False
    assert read(native / "segment-1/checkpoint/agent.json")["memory"] == "x" * 7


def test_zero_response_pause_in_second_segment_preserves_first_segment(trial):
    native, _, _, _, run = trial
    first = audit(trial)
    parent = native / "segment-0/checkpoint"
    span, metrics = run(1, parent, admission_denied)
    paused = audit((native, parent, span, metrics, run))
    assert paused["next_step"] == first["next_step"] == 4
    assert (
        paused["new_responses"]
        == paused["new_tokens"]
        == paused["new_saved_ticks"]
        == 0
    )
    assert paused["usage"] == first["usage"]
    assert paused["prior_checkpoint_sha256"] == first["checkpoint_sha256"]


@pytest.mark.parametrize(
    "keys,value",
    [
        (("source_checkpoint_file_sha256",), "b" * 64),
        (("native_load_verified",), False),
        (("cleanup_verified",), 1),
        (("listener_closed",), False),
        (("remaining_live_processes",), [123]),
        (("loaded", "year_tick"), 0),
        (("loaded", "paused"), False),
        (("code_revision",), "other"),
        (("experiment", "next_step"), 5),
    ],
)
def test_broken_load_and_cleanup_receipts_are_rejected(trial, keys, value):
    modify(trial[0] / "runtime-0/result.json", keys, value)
    with pytest.raises(ValueError):
        audit(trial)


@pytest.mark.parametrize(
    "filename,keys,value",
    [
        ("agent-before.json", ("memory",), "borrowed"),
        ("agent-after.json", ("usage", "total_tokens"), 0),
        ("native-before.json", ("population",), 0),
        ("native-before.json", ("year_tick",), True),
        ("native-after.json", ("year_tick",), 0),
        ("native-after.json", ("pause_state",), False),
    ],
)
def test_saved_state_disagreement_is_rejected(trial, filename, keys, value):
    modify(trial[0] / "segment-0" / filename, keys, value)
    with pytest.raises(ValueError):
        audit(trial)


def test_final_save_inventory_tampering_fails(trial):
    (trial[0] / "segment-0/checkpoint/game/world.sav").write_text("tampered")
    with pytest.raises(CampaignCheckpointError):
        audit(trial)


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_sha256", "b" * 64),
        ("next_step", True),
        ("campaign_id", "borrowed"),
        ("code_revision", "different"),
    ],
)
def test_self_consistent_manifest_cannot_borrow_another_parent_or_cursor(
    trial, field, value
):
    path = trial[0] / "segment-0/checkpoint/checkpoint.json"
    data = read(path)
    data["payload"][field] = value
    data["sha256"] = hashlib.sha256(
        json.dumps(
            data["payload"], sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        audit(trial)


def test_second_segment_cannot_resume_initial_save_again(trial):
    native, initial, _, _, run = trial
    parent = native / "segment-0/checkpoint"
    span, metrics = run(1, parent)
    with pytest.raises(ValueError):
        audit((native, initial, span, metrics, run))


@pytest.mark.parametrize(
    "index,first,last", [(True, 1, 4), (-1, 1, 4), (16, 1, 4), (0, True, 4), (0, 1, 66)]
)
def test_invalid_span_is_rejected_before_reading_files(trial, index, first, last):
    native, parent, _, metrics, run = trial
    with pytest.raises(ValueError, match="Invalid declared segment span"):
        audit((native, parent, SegmentSpan(index, first, last), metrics, run))


@pytest.mark.parametrize(
    "field,value",
    [
        ("screen_sha256", "g" * 64),
        ("screen_after_sha256", None),
        ("screen_unchanged", 1),
        ("screen_unchanged", False),
        ("ui_identity_unchanged", False),
        ("world_observations_unchanged", 1),
        ("paused", 1),
        ("year", True),
    ],
)
def test_semantic_save_receipt_uses_strict_identity_and_calendar_types(field, value):
    save = {
        "snapshot_profile": "native_menu_preserving_save/v4",
        "screen_sha256": "a" * 64,
        "screen_after_sha256": "a" * 64,
        "screen_unchanged": True,
        "ui_identity_unchanged": True,
        "world_observations_unchanged": True,
        "paused": True,
        "year": 30,
        "year_tick": 50,
    }
    save[field] = value
    with pytest.raises(ValueError):
        verify_save_boundary(save, {"pause_state": True, "year": 30, "year_tick": 50})
