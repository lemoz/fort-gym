from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.campaign_segment import load_segment_config, run_segment, worker
from tests.test_campaign_loop import TestAgent, TestEnvironment

CONFIG = (
    Path(__file__).resolve().parents[1] / "experiments/campaigns/development_continuation_v1.json"
)
MODEL = "qwen/qwen3.8-flash"


class SegmentAgent(TestAgent):
    """Synthetic policy/usage only; no transport or model client is constructed."""

    def __init__(self):
        super().__init__()
        self.dispatches = 0

    def _pre_dispatch_gate(self):
        return None

    def decide(self, text, observation):
        self.dispatches += 1
        return super().decide(text, observation)

    def export_campaign_state(self):
        state = super().export_campaign_state()
        state["usage"]["dispatched_requests"] = self.dispatches
        return state

    def restore_campaign_state(self, state, *, campaign_id):
        super().restore_campaign_state(state, campaign_id=campaign_id)
        self.dispatches = state["usage"]["dispatched_requests"]


def segment(tmp_path, name="first", **kwargs):
    output = tmp_path / name
    output.mkdir()
    agent = kwargs.pop("agent", SegmentAgent())
    environment = kwargs.pop("environment", TestEnvironment())
    result = run_segment(
        agent=agent,
        environment=environment,
        snapshotter=kwargs.pop("snapshotter", environment),
        output=output,
        config=kwargs.pop("config", load_segment_config(CONFIG, MODEL)),
        campaign_id=kwargs.pop("campaign_id", "test-campaign"),
        model=MODEL,
        revision="test-only-revision",
        **kwargs,
    )
    assert json.loads((output / "campaign-segment.json").read_text()) == result
    return result, output, agent


def test_old_probe_condition_is_not_silently_run_on_new_loop():
    with pytest.raises(ValueError, match="runner condition"):
        load_segment_config(CONFIG.with_name("development_probe_v1.json"), MODEL)


@pytest.mark.parametrize(
    "model", ["z-ai/glm-5.3-flash", "qwen/qwen3.8-flash", "deepseek/deepseek-v4-flash-0731"]
)
def test_segment_condition_declares_each_supported_model(model):
    assert load_segment_config(CONFIG, model)["runner"] == "campaign-loop/v1"


def test_completed_model_segment_checkpoints_and_resumes_at_next_action(tmp_path):
    first, first_output, first_agent = segment(tmp_path)
    assert first["status"] == "bounded_segment_complete"
    assert first["segment_committed_steps"] == 3 and first["next_step"] == 3
    assert first["new_checkpoint_verified"] is True
    assert first["recovery_requires_reconciliation"] is False
    checkpoint = Path(first["checkpoint"])
    environment = TestEnvironment()
    environment.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed, resumed_output, agent = segment(
        tmp_path,
        "resumed",
        environment=environment,
        checkpoint=checkpoint,
        latest_usage=first_output / "campaign/usage.jsonl",
    )
    assert resumed["status"] == "bounded_segment_complete"
    assert resumed["first_step"] == 3 and resumed["next_step"] == 6
    assert resumed["usage"]["dispatched_requests"] == 6
    assert resumed["usage"]["total_tokens"] == 60
    assert agent.count == 6 and first_agent.count == 3
    assert environment.actions == ["test decision 4", "test decision 5", "test decision 6"]
    rows = [
        json.loads(row)
        for row in (resumed_output / "campaign/trace.jsonl").read_text().splitlines()
    ]
    assert [row["step"] for row in rows] == list(range(6))
    assert rows[3]["observation"]["agent_plan_control"]["previous_step"] == 2
    assert resumed["year_two_gameplay_verified"] is False


def test_budget_pause_checkpoints_last_boundary_and_does_not_reset_on_resume(tmp_path):
    config = {**load_segment_config(CONFIG, MODEL), "max_dispatches": 1}
    first, output, _ = segment(tmp_path, config=config)
    assert first["status"] == "budget_limited_pause"
    assert first["segment_committed_steps"] == 1
    assert first["new_checkpoint_verified"] is True
    assert first["recovery_requires_reconciliation"] is False
    checkpoint = Path(first["checkpoint"])
    env = TestEnvironment()
    env.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed, _, agent = segment(
        tmp_path,
        "resumed",
        config=config,
        environment=env,
        checkpoint=checkpoint,
        latest_usage=output / "campaign/usage.jsonl",
    )
    assert resumed["status"] == "budget_limited_pause"
    assert resumed["segment_committed_steps"] == 0
    assert resumed["checkpoint"] == str(checkpoint)
    assert resumed["recovery_requires_reconciliation"] is False
    assert resumed["usage"] == first["usage"] and agent.prompts == []


def test_failed_execution_retains_usage_and_never_claims_checkpoint_or_collapse(tmp_path):
    class BrokenEnvironment(TestEnvironment):
        def apply(self, action, state):
            raise OSError("test runtime disappeared")

    result, output, _ = segment(tmp_path, environment=BrokenEnvironment())
    assert result["status"] == "failed" and result["error_type"] == "OSError"
    assert result["segment_committed_steps"] == 0
    assert result["usage"]["dispatched_requests"] == 1
    assert result["new_checkpoint_verified"] is False
    assert result["recovery_requires_reconciliation"] is True
    assert (output / "campaign/failures.jsonl").is_file()
    assert not (output / "checkpoint").exists()


def test_checkpoint_failure_is_separate_from_completed_actions(tmp_path):
    class BrokenSnapshot:
        def capture(self, path):
            raise OSError("test snapshot failure")

    result, _, _ = segment(tmp_path, snapshotter=BrokenSnapshot())
    assert result["status"] == "checkpoint_failed"
    assert result["segment_committed_steps"] == 3
    assert result["new_checkpoint_verified"] is False
    assert result["checkpoint_error_type"] == "OSError"
    assert result["native_final"]["year_tick"] == 19909


def test_foreign_campaign_resume_fails_before_new_decision(tmp_path):
    first, output, _ = segment(tmp_path)
    result, _, agent = segment(
        tmp_path,
        "foreign",
        campaign_id="different",
        checkpoint=Path(first["checkpoint"]),
        latest_usage=output / "campaign/usage.jsonl",
    )
    assert result["status"] == "failed"
    assert "identity differs" in result["error"]
    assert agent.dispatches == 0


def test_worker_opts_into_dispatch_accounting_and_closes_its_connection(tmp_path, monkeypatch):
    from scripts import campaign_segment
    from fort_gym.bench.run import campaign_environment

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("DFROOT", str(runtime))
    events = []
    env = SimpleNamespace(close=lambda: events.append("closed"))
    monkeypatch.setattr(campaign_environment, "NativeCampaignEnvironment", lambda **kwargs: env)

    def make(config, model, journal, *, persist_dispatches):
        assert persist_dispatches is True
        return SegmentAgent()

    monkeypatch.setattr(campaign_segment, "make_agent", make)
    monkeypatch.setattr(
        campaign_segment.subprocess, "check_output", lambda *a, **k: "test-revision"
    )
    monkeypatch.setattr(campaign_segment, "run_segment", lambda **kwargs: {"test_only": True})
    result = worker(
        SimpleNamespace(
            output=tmp_path,
            model=MODEL,
            campaign_id="campaign",
            checkpoint=None,
            latest_usage=None,
        ),
        load_segment_config(CONFIG, MODEL),
    )
    assert result == {"test_only": True} and events == ["closed"]


def test_parent_routes_checkpoint_resume_to_isolated_worker(tmp_path, monkeypatch):
    from scripts import campaign_segment

    checkpoint, output = tmp_path / "checkpoint", tmp_path / "resumed"
    checkpoint.mkdir()
    (checkpoint / "checkpoint.json").write_text("{}")
    latest = tmp_path / "latest-usage.jsonl"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-inherit")
    monkeypatch.setattr(
        campaign_segment.sys,
        "argv",
        [
            "campaign_segment",
            "--config",
            str(CONFIG),
            "--model",
            MODEL,
            "--campaign-id",
            "campaign",
            "--output",
            str(output),
            "--source",
            str(tmp_path / "source"),
            "--checkpoint",
            str(checkpoint),
            "--latest-usage",
            str(latest),
            "--port",
            "5502",
        ],
    )
    monkeypatch.setattr(
        campaign_segment.subprocess,
        "check_output",
        lambda args, **kwargs: "test-revision" if args[1] == "rev-parse" else "",
    )
    workers = []

    def fake_worker(command, *, env, **kwargs):
        workers.append((command, env))
        assert env["DFROOT"] == str(output / "runtime")
        assert env["DFHACK_PORT"] == "5502"
        assert env["OPENROUTER_API_KEY"] == "test-only-placeholder"
        assert "ANTHROPIC_API_KEY" not in env
        (output / "campaign-segment.json").write_text(json.dumps({"status": "test-only"}))

    def isolated(**kwargs):
        assert kwargs["source_kind"] == "campaign_checkpoint"
        assert kwargs["snapshot"] == checkpoint
        assert kwargs["port"] == 5502
        output.mkdir()
        return kwargs["work"](output / "runtime", {"PATH": "/test-only"}, {})

    monkeypatch.setattr(campaign_segment.subprocess, "run", fake_worker)
    monkeypatch.setattr(campaign_segment, "run_isolated", isolated)
    campaign_segment.main()
    assert len(workers) == 1
    command = workers[0][0]
    assert command[command.index("--checkpoint") + 1] == str(checkpoint)
    assert command[command.index("--latest-usage") + 1] == str(latest)
