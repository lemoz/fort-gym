import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.codex_transport import CodexTransportError
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import digest, publish, read
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_config import load_window, validate_condition
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from scripts.campaign_keyboard_native import publish_response, run_window


def test_post_rejection_window_preserves_condition_and_declares_larger_allowance():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    condition, window = load_window(
        root / "experiments/campaign_astra_keyboard_20260907.json",
        root / "experiments/campaign_astra_keyboard_window_20260907d.json",
    )
    assert condition["model"] == "gpt-6-astra" and condition["reasoning_effort"] == "medium"
    assert condition["screen_size"] == [120, 40] and condition["api_fallback"] is False
    assert window["continuation_from_next_step"] == 184
    assert window["steps_per_segment"] == 16 and window["max_segments"] == 4
    assert window["budget_extension"] == {"max_dispatches": 1024, "max_total_tokens": 40000000}
    assert window["reset_memory"] is window["reset_usage"] is window["strategy_intervention"] is False
from tests.test_campaign_codex_keyboard import Environment, decision, admission_denied

PROJECT = Path(__file__).resolve().parents[1]
CONDITION = json.loads((PROJECT / "experiments/campaign_astra_keyboard_20260907.json").read_text())


def environment():
    value = Environment()
    value.screen_capture = lambda: {"width": 120, "height": 40, "tiles": [[32, 7, 0]] * 4800}
    return value


def policy(config, callback=decision):
    return CodexKeyboardAgent(
        decision=callback,
        max_dispatches=config["max_dispatches"],
        max_total_tokens=config["max_total_tokens"],
        max_advance_ticks=config["max_advance_ticks"],
    )


@pytest.fixture
def saved(tmp_path):
    env = environment()
    loop = CampaignLoop(
        campaign_id="runtime-test",
        agent=policy(CONDITION),
        environment=env,
        output=tmp_path / "original",
        observation_profile=CONDITION["observation_profile"],
        advance_policy=CONDITION["advance_policy"],
    )
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=env, code_revision="fixture")
    return checkpoint, loop.journal, env.tick


def run(tmp_path, saved, callback=decision, **kwargs):
    checkpoint, usage, tick = saved
    env = environment()
    env.tick = tick
    agent = policy(CONDITION, callback)
    output = tmp_path / "segment"
    result = run_keyboard_segment(
        agent=agent,
        environment=env,
        snapshotter=env,
        output=output,
        condition=CONDITION,
        checkpoint=checkpoint,
        latest_usage=usage,
        steps=3,
        expected_cursor=1,
        revision="fixture",
        **kwargs,
    )
    return result, env, agent, output


def test_public_segment_resumes_without_new_strategy_or_usage_reset(tmp_path, saved):
    result, env, agent, output = run(tmp_path, saved)
    assert result["status"] == "bounded_segment_complete" and result["checkpoint_verified"]
    assert result["next_step"] == 4 and result["committed_elapsed_ticks"] == 40
    assert agent.usage["dispatched_requests"] == 4 and agent.usage["total_tokens"] == 400
    assert len(env.actions) == 3
    assert (output / "loop/usage.jsonl").read_bytes().startswith(saved[1].read_bytes())
    assert read(output / "result.json") == result


def test_public_segment_retains_extension_with_original_condition(tmp_path, saved):
    result, _, agent, _ = run(
        tmp_path,
        saved,
        budget_extension={"max_dispatches": 16, "max_total_tokens": 1000000},
    )
    assert result["checkpoint_verified"]
    assert agent.configuration["max_dispatches"] == 8
    assert agent.budget_extensions[-1]["limits"]["max_dispatches"] == 16


def test_admission_denial_produces_clean_native_checkpoint(tmp_path, saved):
    result, env, agent, output = run(tmp_path, saved, admission_denied)
    assert result["status"] == "bounded_segment_complete"
    assert result["stop_reason"] == "budget_limited_pause"
    assert result["checkpoint_verified"] and result["next_step"] == 1
    assert not env.actions and agent.usage["dispatched_requests"] == 1
    assert (output / "loop/pauses.jsonl").exists()


def test_uncertain_model_tail_is_forensic_not_resumable(tmp_path, saved):
    result, env, agent, output = run(tmp_path, saved, lambda *args: {})
    assert result["status"] == "failed"
    assert result["stop_reason"] == "unsettled_failure"
    assert result["recovery_requires_reconciliation"]
    assert not result["checkpoint_verified"] and not (output / "checkpoint").exists()
    assert result["unreconciled_native_snapshot_retained"] and not env.actions
    assert agent.usage["dispatched_requests"] == 2


def request():
    return {
        "schema_version": "fortgym.keyboard-exchange-request/v1",
        "request_id": "a" * 32,
        "screen": environment().screen_capture(),
        "memory": "retained model memory",
        "feedback": {"accepted": True},
        "control_profile": CONDITION["control_profile"],
        "observation_profile": CONDITION["observation_profile"],
        "max_advance_ticks": CONDITION["max_advance_ticks"],
    }


def test_courier_binds_once_and_passes_unchanged_policy_inputs(tmp_path):
    calls = []
    def guard():
        return {"allowed": True, "basis": "offline"}

    def callback(screen, **options):
        calls.append((screen, options))
        assert options["allowance_check"] is guard
        assert options["memory"] == request()["memory"]
        return decision(screen, options["memory"], options["feedback"])

    response, summary = answer_request(
        request(),
        directory=tmp_path,
        condition=CONDITION,
        executable=Path("/fixture/codex"),
        decision=callback,
        allowance_check=guard,
    )
    assert response["request_sha256"] == digest(request())
    assert summary["model_dispatched"] and summary["reported_charge_usd"] is None
    assert read(tmp_path / "response.json") == response
    with pytest.raises(FileExistsError):
        answer_request(
            request(),
            directory=tmp_path,
            condition=CONDITION,
            executable=Path("/fixture/codex"),
            decision=callback,
            allowance_check=guard,
        )
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["denied", "unknown"])
def test_courier_retains_rejection_or_unknown_without_retry(tmp_path, kind):
    def callback(*args, **kwargs):
        if kind == "denied":
            raise CodexTransportError("not admitted", admission_denied()["transport_receipt"])
        raise OSError("synthetic uncertain callback failure")

    response, summary = answer_request(
        request(),
        directory=tmp_path,
        condition=CONDITION,
        executable=Path("/fixture/codex"),
        decision=callback,
    )
    assert summary["model_dispatched"] is (False if kind == "denied" else None)
    assert response["result"]["action_grammar_valid"] is False


def test_game_user_publication_verifies_digest_and_is_single_use(tmp_path):
    directory = tmp_path / request()["request_id"]
    directory.mkdir()
    publish(directory / "request.json", request())
    value = {"request_sha256": digest(request()), "result": {"receipt": "test"}}
    with pytest.raises(ValueError):
        publish_response(tmp_path, "../escape", value)
    with pytest.raises(ValueError):
        publish_response(tmp_path, request()["request_id"], {**value, "request_sha256": "bad"})
    publish_response(tmp_path, request()["request_id"], value)
    assert read(directory / "response.json") == value
    with pytest.raises(FileExistsError):
        publish_response(tmp_path, request()["request_id"], value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "other"),
        ("api_fallback", True),
        ("automatic_credit_purchase", 0),
        ("automatic_reset_consumption", True),
        ("actual_charge_usd", 0),
        ("max_dispatches", True),
        ("max_total_tokens", 0),
        ("maximum_included_usage_percent", 100),
        ("screen_size", [0, 40]),
        ("exchange_timeout_seconds", 180),
    ],
)
def test_invalid_conditions_fail_before_runtime_or_model(key, value):
    with pytest.raises(ValueError):
        validate_condition({**CONDITION, key: value})


def test_window_rejects_old_save_or_changed_identity_before_launch(tmp_path, saved):
    config_path, window_path = tmp_path / "condition.json", tmp_path / "window.json"
    publish(config_path, CONDITION)
    window = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "condition_id": "test",
        "original_condition": config_path.name,
        "continuation_from_next_step": 1,
        "steps_per_segment": 16,
        "max_segments": 8,
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
    }
    publish(window_path, window)
    assert load_window(config_path, window_path) == (CONDITION, window)
    latest = tmp_path / "later-usage.jsonl"
    latest.write_bytes(saved[1].read_bytes() + b"extra journal bytes\n")
    args = SimpleNamespace(
        condition=config_path,
        window=window_path,
        checkpoint=saved[0],
        latest_usage=latest,
        port=5530,
        output=tmp_path / "never-created",
    )
    with pytest.raises(ValueError, match="latest checkpoint"):
        run_window(args)
    assert not args.output.exists()


def test_window_runs_serial_checkpoints_on_distinct_ports(tmp_path, saved, monkeypatch):
    from scripts import campaign_keyboard_native as native

    condition_path, window_path = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition_path, CONDITION)
    publish(
        window_path,
        {
            "schema_version": "fortgym.codex-keyboard-window/v1",
            "condition_id": "test",
            "original_condition": condition_path.name,
            "continuation_from_next_step": 1,
            "steps_per_segment": 2,
            "max_segments": 2,
            "reset_memory": False,
            "reset_usage": False,
            "strategy_intervention": False,
        },
    )
    args = SimpleNamespace(
        condition=condition_path,
        window=window_path,
        checkpoint=saved[0],
        latest_usage=saved[1],
        port=5530,
        output=tmp_path / "window-output",
        source=tmp_path / "assets",
        revision="fixture",
    )
    calls = []

    def isolated(**options):
        index = len(calls)
        calls.append(options)
        env = environment()
        env.tick = int((options["snapshot"] / "game/world.sav").read_text())
        previous = saved[1] if index == 0 else args.output / "segment-0/loop/usage.jsonl"
        result = run_keyboard_segment(
            agent=policy(CONDITION),
            environment=env,
            snapshotter=env,
            output=args.output / f"segment-{index}",
            condition=CONDITION,
            checkpoint=options["snapshot"],
            latest_usage=previous,
            steps=2,
            expected_cursor=1 + index * 2,
            revision="fixture",
        )
        return {"experiment": result, "cleanup_verified": True}

    monkeypatch.setattr(native, "run_isolated", isolated)
    result = run_window(args)
    assert result["status"] == "completed"
    assert result["original_checkpoint_unchanged"] and result["runtime_cleanup_verified"]
    assert [call["port"] for call in calls] == [5530, 5531]
    assert [segment["next_step"] for segment in result["segments"]] == [3, 5]
    assert all(call["screen_size"] == (120, 40) for call in calls)
    assert calls[1]["snapshot"] == args.output / "segment-0/checkpoint"


def test_window_retains_failed_worker_outcome_and_verified_cleanup(tmp_path, saved, monkeypatch):
    import subprocess
    from scripts import campaign_keyboard_native as native

    condition, window = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    publish(window, {
        "schema_version": "fortgym.codex-keyboard-window/v1", "condition_id": "failure",
        "original_condition": condition.name, "continuation_from_next_step": 1,
        "steps_per_segment": 2, "max_segments": 2, "reset_memory": False,
        "reset_usage": False, "strategy_intervention": False,
    })
    args = SimpleNamespace(
        condition=condition, window=window, checkpoint=saved[0], latest_usage=saved[1],
        port=5530, output=tmp_path / "output", source=tmp_path / "assets", revision="fixture",
    )
    failure = {
        "schema_version": "fortgym.keyboard-segment/v1", "source_revision": "fixture",
        "campaign_id": "runtime-test", "first_step": 1, "next_step": 1,
        "status": "failed", "checkpoint_verified": False,
        "stop_reason": "unsettled_failure", "recovery_requires_reconciliation": True,
    }

    def worker(command, **kwargs):
        segment = args.output / "segment-0"
        segment.mkdir()
        publish(segment / "result.json", failure)
        raise subprocess.CalledProcessError(1, command)

    def isolated(**options):
        return {
            "experiment": options["work"](args.source, {}, {}), "cleanup_verified": True,
        }

    monkeypatch.setattr(native, "run_worker", worker)
    monkeypatch.setattr(native, "run_isolated", isolated)
    result = run_window(args)
    assert result["status"] == "failed" and result["segments"] == [failure]
    assert result["runtime_cleanup_verified"] and result["original_checkpoint_unchanged"]
    assert not (args.output / "segment-1").exists()
