"""Synthetic controller tests. No model client, DF process, VM or gameplay proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.eval.campaign import TICKS_PER_YEAR, read_campaign_progress
from fort_gym.bench.run.campaign_config import (
    decision_time_reserve,
    load_segment_config,
)
from fort_gym.bench.run.campaign_save import save_inventory
from scripts import campaign_run
from scripts.campaign_development import load_config
from scripts.campaign_segment import run_segment
from tests.test_campaign_segment import SegmentAgent
from tests.test_campaign_loop import TestEnvironment

CONFIG = Path(__file__).resolve().parents[1] / "experiments/campaigns/endurance_autonomous_v1.json"
MODEL = "qwen/qwen3.8-flash"
REVISION = "d" * 40


class EndurancePolicy(SegmentAgent):
    def decide(self, text, observation):
        action = super().decide(text, observation)
        action["advance_ticks"] = 2000
        return action


class CalendarEnvironment(TestEnvironment):
    def advance(self, ticks, state):
        self.state["year_tick"] += ticks
        years, self.state["year_tick"] = divmod(self.state["year_tick"], TICKS_PER_YEAR)
        self.state["year"] += years
        return self.observe(), {"ok": True, "ticks_advanced": ticks}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign_run.subprocess, "check_output", lambda *a, **k: REVISION)
    snapshot = tmp_path / "start"
    snapshot.mkdir()
    env = CalendarEnvironment()
    receipt = env.capture(snapshot / "native-snapshot")
    native = {"paused": True, "year": env.state["year"], "year_tick": env.state["year_tick"]}
    result = {
        "schema_version": "fortgym.native-save-smoke/v1",
        "native_snapshot_verified": True,
        "before": native,
        "after": native,
        "snapshot": {"files": receipt["files"]},
    }
    path = snapshot / "result.json"
    path.write_text(json.dumps(result))
    return SimpleNamespace(
        config=CONFIG,
        model=MODEL,
        campaign_id="synthetic-campaign",
        source=tmp_path / "source",
        output=tmp_path / "run",
        snapshot=snapshot,
        snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        resume=False,
        segments=2,
        port=5501,
        public_campaign_dir=None,
    )


class FakeLauncher:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def __call__(self, args, config):
        assert not self.calls or self.calls[-1]["cleaned"] is True
        env = CalendarEnvironment()
        if args.checkpoint is not None:
            env.state = json.loads((args.checkpoint / "game/world.sav").read_text())
        args.output.mkdir()
        result = run_segment(
            agent=EndurancePolicy(),
            environment=env,
            snapshotter=env,
            output=args.output,
            config=config,
            campaign_id=args.campaign_id,
            model=args.model,
            revision=REVISION,
            checkpoint=args.checkpoint,
            latest_usage=args.latest_usage,
        )
        receipt = {
            "schema_version": "fortgym.isolated-experiment-runtime/v1",
            "code_revision": REVISION,
            "native_load_verified": True,
            "cleanup_verified": True,
        }
        if args.checkpoint is None:
            receipt["source_snapshot_receipt_sha256"] = args.snapshot_sha256
        else:
            receipt["source_checkpoint_file_sha256"] = hashlib.sha256(
                (args.checkpoint / "checkpoint.json").read_bytes()
            ).hexdigest()
        (args.output / "result.json").write_text(json.dumps(receipt))
        if self.mutate is not None:
            self.mutate(args.output, result, receipt)
        self.calls.append(
            {"output": args.output, "port": args.port, "cleaned": True, "result": result}
        )
        return receipt


def condition(inputs, **updates):
    config = {**load_segment_config(CONFIG, MODEL), **updates}
    path = inputs.output.parent / "test-condition.json"
    path.write_text(json.dumps(config))
    inputs.config = path
    return config


def test_endurance_has_a_distinct_schema_and_keeps_old_probe_bounds():
    config = load_segment_config(CONFIG, MODEL)
    assert config["max_dispatches"] > 403200 // config["max_advance_ticks"]
    assert decision_time_reserve(config) < config["segment_time_budget_seconds"]
    with pytest.raises(ValueError, match="Unsupported development"):
        load_config(CONFIG, MODEL)
    old = load_segment_config(CONFIG.with_name("development_autonomous_v1.json"), MODEL)
    assert old["max_dispatches"] == 8 and old["max_steps"] == 3


def test_controller_verifies_periodic_siblings_before_next_runtime(inputs):
    model = "fort-gym-qwen35-9b-q4-03b74727a860"
    config = load_segment_config(CONFIG.with_name("local_native_llama_long_v1.json"), model)
    config.update(max_steps=4, max_dispatches=8)
    config["checkpoint_policy"]["interval_steps"] = 2
    inputs.model = model
    path = inputs.output.parent / "periodic-condition.json"
    path.write_text(json.dumps(config))
    inputs.config = path
    launcher = FakeLauncher()
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "budget_limited_pause"
    assert result["next_step"] == 8 and len(launcher.calls) == 2
    assert [x["result"]["periodic_checkpoints"][0]["next_step"] for x in launcher.calls] == [2, 6]


def test_missing_periodic_index_blocks_controller_handoff(inputs):
    model = "fort-gym-qwen35-9b-q4-03b74727a860"
    config = load_segment_config(CONFIG.with_name("local_native_llama_long_v1.json"), model)
    config.update(max_steps=4, max_dispatches=8)
    config["checkpoint_policy"]["interval_steps"] = 2
    inputs.model = model
    path = inputs.output.parent / "periodic-condition.json"
    path.write_text(json.dumps(config))
    inputs.config = path
    launcher = FakeLauncher(
        mutate=lambda root, segment, runtime: (root / "periodic-checkpoints.jsonl").unlink()
    )
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "requires_reconciliation"
    assert result["next_step"] == 0 and len(launcher.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_cost_usd", True),
        ("max_cost_usd", 21),
        ("max_cost_usd", float("nan")),
        ("max_dispatches", 4097),
        ("max_segments", 513),
        ("max_total_tokens", 20000001),
        ("segment_time_budget_seconds", 100),
        ("schema_attempts", True),
    ],
)
def test_endurance_configuration_rejects_invalid_bounds(inputs, field, value):
    condition(inputs, **{field: value})
    with pytest.raises(ValueError):
        load_segment_config(inputs.config, MODEL)


def test_serial_continuation_crosses_anniversary_and_preserves_usage_and_actions(inputs):
    inputs.segments = 6
    launcher = FakeLauncher()
    first = campaign_run.run_campaign(inputs, launch=launcher)
    assert first["status"] == "invocation_limited_pause" and first["next_step"] == 96
    inputs.resume, inputs.segments = True, 8
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "invocation_limited_pause"
    assert result["next_step"] == result["usage"]["dispatched_requests"] == 224
    assert result["usage"]["total_tokens"] == 2240
    assert result["year_two_gameplay_verified"] is False
    trace = inputs.output / "segments/segment-000014/campaign/trace.jsonl"
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [row["step"] for row in rows] == list(range(224))
    progress = read_campaign_progress(trace)
    assert progress["elapsed_ticks"] == 448000
    assert len(launcher.calls) == 14
    assert [call["port"] for call in launcher.calls] == list(range(5501, 5515))
    assert all(call["result"]["new_checkpoint_verified"] for call in launcher.calls)
    assert save_inventory(inputs.snapshot / "native-snapshot")


def test_cumulative_dispatch_cap_stops_without_allocating_another_runtime(inputs):
    condition(inputs, max_dispatches=32)
    inputs.segments = 6
    launcher = FakeLauncher()
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "budget_limited_pause"
    assert result["usage"]["dispatched_requests"] == 32 and len(launcher.calls) == 2
    inputs.resume = True
    with pytest.raises(ValueError, match="reconciliation"):
        campaign_run.run_campaign(inputs, launch=launcher)
    assert len(launcher.calls) == 2


def test_segment_limit_does_not_reset_with_another_invocation(inputs):
    condition(inputs, max_segments=2)
    launcher = FakeLauncher()
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "segment_limit_pause" and len(launcher.calls) == 2
    inputs.resume = True
    with pytest.raises(ValueError, match="reconciliation"):
        campaign_run.run_campaign(inputs, launch=launcher)


@pytest.mark.parametrize(
    "tamper", ["cleanup", "model", "source", "checkpoint", "usage", "zero_steps"]
)
def test_invalid_handoff_never_launches_a_second_segment(inputs, tamper):
    def mutate(root, result, receipt):
        if tamper == "cleanup":
            receipt["cleanup_verified"] = False
        elif tamper == "source":
            receipt["source_snapshot_receipt_sha256"] = "0" * 64
        elif tamper == "model":
            result["model"] = "foreign/model"
        elif tamper == "checkpoint":
            (root / "checkpoint/game/world.sav").write_text("changed")
        elif tamper == "usage":
            (root / "campaign/usage.jsonl").write_text("changed")
        else:
            result["segment_committed_steps"] = 0
        (root / "result.json").write_text(json.dumps(receipt))
        (root / "campaign-segment.json").write_text(json.dumps(result))

    launcher = FakeLauncher(mutate)
    result = campaign_run.run_campaign(inputs, launch=launcher)
    assert result["status"] == "requires_reconciliation"
    assert len(launcher.calls) == 1
    inputs.resume = True
    with pytest.raises(ValueError, match="reconciliation"):
        campaign_run.run_campaign(inputs, launch=launcher)


def test_failure_is_not_retried_or_relabelled_as_fortress_collapse(inputs):
    calls = []

    def fail(args, config):
        calls.append(args)
        raise OSError("synthetic runtime failure")

    result = campaign_run.run_campaign(inputs, launch=fail)
    assert result["status"] == "requires_reconciliation" and len(calls) == 1
    assert result["error_type"] == "OSError" and result["usage"] is None
    assert result["year_two_gameplay_verified"] is False


@pytest.mark.parametrize("port", [5000, 4900, 65535, 1000])
def test_invalid_rpc_range_rejected_before_any_runtime_or_run_directory(inputs, port):
    inputs.port = port
    launcher = FakeLauncher()
    with pytest.raises(ValueError, match="port range"):
        campaign_run.run_campaign(inputs, launch=launcher)
    assert not inputs.output.exists() and launcher.calls == []


def test_changed_condition_and_later_usage_are_rejected_before_resume(inputs):
    launcher = FakeLauncher()
    campaign_run.run_campaign(inputs, launch=launcher)
    inputs.resume = True
    condition(inputs, max_dispatches=2049)
    with pytest.raises(ValueError, match="identity changed"):
        campaign_run.run_campaign(inputs, launch=launcher)
    inputs.config = CONFIG
    journal = inputs.output / "segments/segment-000002/campaign/usage.jsonl"
    with journal.open("a") as stream:
        stream.write('{"type":"decision_started","step":32}\n')
    with pytest.raises(ValueError, match="boundary or usage has changed"):
        campaign_run.run_campaign(inputs, launch=launcher)
    assert len(launcher.calls) == 2


def test_resume_requires_the_exact_checkpoint_file_digest(inputs):
    launcher = FakeLauncher()
    campaign_run.run_campaign(inputs, launch=launcher)
    inputs.resume = True
    path = inputs.output / "segments/segment-000002/checkpoint/checkpoint.json"
    path.write_text(json.dumps(json.loads(path.read_text()), indent=4))
    with pytest.raises(ValueError, match="boundary or usage has changed"):
        campaign_run.run_campaign(inputs, launch=launcher)
    assert len(launcher.calls) == 2


def test_failed_later_segment_marks_previous_usage_as_stale_not_zero(inputs):
    launcher = FakeLauncher()

    def fail_second(args, config):
        if launcher.calls:
            raise OSError("synthetic transport interruption")
        return launcher(args, config)

    result = campaign_run.run_campaign(inputs, launch=fail_second)
    assert result["status"] == "requires_reconciliation"
    assert result["usage"]["dispatched_requests"] == 16
    assert result["usage_status"] == "last_verified_boundary_only"


def test_concurrent_controller_cannot_enter_the_same_campaign(inputs):
    launcher = FakeLauncher()
    inputs.segments = 1

    def launch_with_contender(args, config):
        contender = SimpleNamespace(**vars(inputs))
        contender.resume = True
        with pytest.raises(BlockingIOError):
            campaign_run.run_campaign(contender, launch=launcher)
        return launcher(args, config)

    result = campaign_run.run_campaign(inputs, launch=launch_with_contender)
    assert result["status"] == "invocation_limited_pause"
    assert len(launcher.calls) == 1


def test_time_slice_yields_before_a_new_decision_and_preserves_checkpoint(inputs, monkeypatch):
    from scripts import campaign_segment

    clock_values = iter([0, 0, 151])
    monkeypatch.setattr(campaign_segment.time, "monotonic", lambda: next(clock_values))
    inputs.segments = 1
    launcher = FakeLauncher()
    result = campaign_run.run_campaign(inputs, launch=launcher)
    segment = launcher.calls[0]["result"]
    assert segment["status"] == "bounded_segment_complete"
    assert segment["segment_stop_reason"] == "time_slice"
    assert segment["segment_committed_steps"] == 1
    assert result["next_step"] == 1 and result["status"] == "invocation_limited_pause"
