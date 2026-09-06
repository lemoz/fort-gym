"""Output-limit recovery with synthetic policy/native doubles, never live gameplay."""

import hashlib
import json
from pathlib import Path

import pytest

from fort_gym.bench.agent.campaign_local import LocalOutputLimitPause
from fort_gym.bench.run.campaign_checkpoint import (
    CampaignCheckpointError,
    verify_checkpoint,
)
from fort_gym.bench.run.campaign_loop import (
    CampaignLoop,
    CampaignNoActionPause,
    reconciled_usage,
)
from scripts import campaign_run
from tests.test_campaign_loop import TestEnvironment
from tests.test_campaign_run import FakeLauncher, condition
from tests.test_campaign_run import inputs as inputs
from tests.test_campaign_segment import SegmentAgent, segment


class PausingAgent(SegmentAgent):
    def __init__(self, fail_at=1):
        super().__init__()
        self.fail_at = fail_at

    def decide(self, text, observation):
        action = super().decide(text, observation)
        if self.count == self.fail_at:
            raise LocalOutputLimitPause("synthetic accounted output limit")
        return action


@pytest.mark.parametrize("before_pause", [0, 2])
def test_output_pause_checkpoints_all_usage_and_resumes_without_replaying(tmp_path, before_pause):
    env = TestEnvironment()
    result, output, _ = segment(tmp_path, agent=PausingAgent(before_pause + 1), environment=env)
    assert result["status"] == "inference_output_limited_pause"
    assert result["segment_stop_reason"] == "output_token_limit"
    assert result["new_checkpoint_verified"] is True
    assert result["recovery_requires_reconciliation"] is False
    assert result["segment_committed_steps"] == result["next_step"] == before_pause
    assert len(env.actions) == before_pause
    assert env.state["year_tick"] == 19309 + before_pause * 200
    checkpoint = Path(result["checkpoint"])
    manifest = verify_checkpoint(checkpoint)
    assert manifest["schema_version"] == "fortgym.campaign-checkpoint/v3"
    assert manifest["payload"]["last_committed_step"] == before_pause - 1
    assert manifest["payload"]["next_step"] == before_pause
    state = json.loads((checkpoint / "agent.json").read_text())
    assert state["usage"]["accounted_responses"] == before_pause + 1
    assert reconciled_usage(state, (checkpoint / "usage.jsonl").read_bytes()) == state["usage"]
    pauses = [
        json.loads(x) for x in (checkpoint / "decision-pauses.jsonl").read_text().splitlines()
    ]
    assert pauses[-1]["native_action_dispatched"] is False
    assert not (output / "campaign/failures.jsonl").exists()

    resumed_env = TestEnvironment()
    resumed_env.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed, resumed_output, agent = segment(
        tmp_path,
        "resumed",
        agent=PausingAgent(before_pause + 1),
        environment=resumed_env,
        checkpoint=checkpoint,
        latest_usage=output / "campaign/usage.jsonl",
    )
    assert resumed["status"] == "bounded_segment_complete"
    assert resumed["next_step"] == before_pause + 3
    assert agent.dispatches == before_pause + 4
    assert resumed_env.actions == [
        f"test decision {n}" for n in range(before_pause + 2, before_pause + 5)
    ]
    rows = [
        json.loads(x) for x in (resumed_output / "campaign/trace.jsonl").read_text().splitlines()
    ]
    assert [r["step"] for r in rows] == list(range(before_pause + 3))
    assert (
        verify_checkpoint(Path(resumed["checkpoint"]))["payload"]["parent_sha256"]
        == manifest["sha256"]
    )


@pytest.mark.parametrize("fault", ["unaccounted", "dispatch_gap", "clock", "unpaused", "screen"])
def test_typed_output_exception_is_not_enough_when_its_boundary_is_uncertain(tmp_path, fault):
    env = TestEnvironment()

    class BrokenPause(PausingAgent):
        def decide(self, text, observation):
            try:
                return super().decide(text, observation)
            finally:
                if fault == "dispatch_gap":
                    self.dispatches += 1
                elif fault == "clock":
                    env.state["year_tick"] += 1
                elif fault == "unpaused":
                    env.state["pause_state"] = False
                elif fault == "screen":
                    env.state["viewscreen_type"] = "different-screen"

        def export_campaign_state(self):
            state = super().export_campaign_state()
            if fault == "unaccounted" and self.count:
                state["usage"]["accounted_responses"] = 0
            return state

    result, output, _ = segment(tmp_path, agent=BrokenPause(), environment=env)
    assert result["status"] == "failed" and result["new_checkpoint_verified"] is False
    assert result["recovery_requires_reconciliation"] is True
    assert not env.actions and not (output / "checkpoint").exists()


def test_typed_output_exception_during_native_execution_is_still_uncertain(tmp_path):
    class BrokenNative(TestEnvironment):
        def apply(self, action, state):
            raise LocalOutputLimitPause("not from the decision phase")

    result, _, _ = segment(tmp_path, environment=BrokenNative())
    assert result["status"] == "failed"
    assert result["recovery_requires_reconciliation"] is True
    assert result["new_checkpoint_verified"] is False


def test_output_pause_receipt_is_digest_bound(tmp_path):
    result, _, _ = segment(tmp_path, agent=PausingAgent())
    checkpoint = Path(result["checkpoint"])
    (checkpoint / "decision-pauses.jsonl").write_text("{}\n")
    with pytest.raises(CampaignCheckpointError, match="receipt digest"):
        verify_checkpoint(checkpoint)


def test_historical_failed_decision_is_not_reclassified_by_new_usage_reader(tmp_path):
    result, _, _ = segment(tmp_path, agent=PausingAgent())
    checkpoint = Path(result["checkpoint"])
    state = json.loads((checkpoint / "agent.json").read_text())
    rows = [json.loads(x) for x in (checkpoint / "usage.jsonl").read_text().splitlines()]
    del rows[-1]["outcome"]
    with pytest.raises(ValueError, match="unresolved provider usage"):
        reconciled_usage(state, ("\n".join(json.dumps(x) for x in rows) + "\n").encode())


def test_inconsistent_receipt_never_publishes_a_checkpoint_manifest(tmp_path):
    loop = CampaignLoop(
        campaign_id="test",
        agent=PausingAgent(),
        environment=TestEnvironment(),
        output=tmp_path / "loop",
    )
    with pytest.raises(CampaignNoActionPause):
        loop.step()
    receipt = loop.output / "pauses.jsonl"
    row = json.loads(receipt.read_text())
    row["native_action_dispatched"] = True
    receipt.write_text(json.dumps(row) + "\n")
    destination = tmp_path / "checkpoint"
    with pytest.raises(CampaignCheckpointError, match="receipt or usage boundary"):
        loop.checkpoint(destination, snapshotter=loop.environment, code_revision="test-only")
    assert not (destination / "checkpoint.json").exists()
    assert (destination / "game/world.sav").exists()  # Retained diagnostics, not silently deleted.


def test_controller_pauses_once_then_resumes_the_same_cursor_and_usage(inputs, monkeypatch):
    from tests import test_campaign_run as doubles

    condition(inputs, max_steps=3, max_segments=3)
    monkeypatch.setattr(doubles, "EndurancePolicy", PausingAgent)
    launcher = FakeLauncher()
    first = campaign_run.run_campaign(inputs, launch=launcher)
    assert first["status"] == "inference_output_limited_pause"
    assert first["next_step"] == 0 and first["segments_completed"] == 1
    assert first["usage"]["accounted_responses"] == 1
    assert len(launcher.calls) == 1  # No hidden retry or forced gameplay.
    inputs.resume = True
    inputs.segments = 1
    second = campaign_run.run_campaign(inputs, launch=launcher)
    assert second["status"] == "invocation_limited_pause"
    assert second["next_step"] == 3 and second["usage"]["accounted_responses"] == 4
    assert second["segments_started"] == second["segments_completed"] == 2


def test_loop_exposes_pause_without_applying_a_partial_action(tmp_path):
    env = TestEnvironment()
    loop = CampaignLoop(
        campaign_id="test", agent=PausingAgent(), environment=env, output=tmp_path / "loop"
    )
    with pytest.raises(CampaignNoActionPause):
        loop.step()
    assert loop.at_boundary and not loop.failed and loop.next_step == 0
    assert not env.actions


def test_repeated_output_pauses_consume_allowances_without_fabricating_steps(inputs, monkeypatch):
    from tests import test_campaign_run as doubles

    class AlwaysPause(PausingAgent):
        def decide(self, text, observation):
            self.fail_at = self.count + 1
            return super().decide(text, observation)

    condition(inputs, max_steps=3, max_segments=2)
    monkeypatch.setattr(doubles, "EndurancePolicy", AlwaysPause)
    launcher = FakeLauncher()
    first = campaign_run.run_campaign(inputs, launch=launcher)
    assert first["status"] == "inference_output_limited_pause"
    inputs.resume = True
    second = campaign_run.run_campaign(inputs, launch=launcher)
    assert second["status"] == "inference_output_limited_pause"
    assert second["next_step"] == 0 and second["segments_completed"] == 2
    assert second["usage"]["accounted_responses"] == 2
    third = campaign_run.run_campaign(inputs, launch=launcher)
    assert third["status"] == "segment_limit_pause"
    assert len(launcher.calls) == 2 and third["usage"] == second["usage"]


def test_pause_receipt_write_failure_requires_reconciliation(tmp_path, monkeypatch):
    from fort_gym.bench.run import campaign_loop

    append = campaign_loop._append

    def fail_receipt(path, value):
        if path.name == "pauses.jsonl":
            raise OSError("synthetic receipt write failure")
        append(path, value)

    monkeypatch.setattr(campaign_loop, "_append", fail_receipt)
    result, _, _ = segment(tmp_path, agent=PausingAgent())
    assert result["status"] == "failed"
    assert result["recovery_requires_reconciliation"] is True
    assert result["new_checkpoint_verified"] is False


@pytest.mark.parametrize(
    "fault", ["cursor", "empty_trace", "trace_boundary", "receipt_boundary", "usage_outcome"]
)
def test_no_action_checkpoint_rejects_internally_inconsistent_rehashed_files(tmp_path, fault):
    result, _, _ = segment(tmp_path, agent=PausingAgent(2))
    checkpoint = Path(result["checkpoint"])
    manifest = json.loads((checkpoint / "checkpoint.json").read_text())
    payload = manifest["payload"]

    def replace_file(name, key, data):
        (checkpoint / name).write_bytes(data)
        payload[key] = hashlib.sha256(data).hexdigest()

    if fault == "cursor":
        payload["next_step"] += 1
    elif fault == "empty_trace":
        replace_file("trace.jsonl", "trace_sha256", b"")
    elif fault == "trace_boundary":
        row = json.loads((checkpoint / "trace.jsonl").read_text())
        row["tick_advance"]["end_tick"] += 1
        replace_file("trace.jsonl", "trace_sha256", (json.dumps(row) + "\n").encode())
    elif fault == "receipt_boundary":
        row = json.loads((checkpoint / "decision-pauses.jsonl").read_text())
        row["native_boundary"]["year_tick"] += 1
        replace_file(
            "decision-pauses.jsonl", "decision_pauses_sha256", (json.dumps(row) + "\n").encode()
        )
    elif fault == "usage_outcome":
        rows = [json.loads(line) for line in (checkpoint / "usage.jsonl").read_text().splitlines()]
        del rows[-1]["outcome"]
        replace_file(
            "usage.jsonl", "usage_sha256", ("\n".join(map(json.dumps, rows)) + "\n").encode()
        )
    manifest["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()
    (checkpoint / "checkpoint.json").write_text(json.dumps(manifest))
    with pytest.raises((CampaignCheckpointError, ValueError)):
        verify_checkpoint(checkpoint)
