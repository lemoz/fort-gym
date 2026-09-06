from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

import pytest

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from fort_gym.bench.run.campaign_save import save_inventory


class TestAgent(Agent):
    __test__ = False

    def __init__(self):
        self.count = 0
        self.prompts = []
        self.campaign_id = None
        self.cost = Decimal(0)
        self.usage_calls = 0

    def set_campaign_context(self, *, campaign_id):
        self.campaign_id = campaign_id

    def decide(self, text, observation):
        self.prompts.append((text, deepcopy(observation)))
        self.count += 1
        self.usage_calls += 1
        self.cost += Decimal("0.0000000000001")
        return {
            "type": "WAIT",
            "params": {},
            "advance_ticks": 200,
            "intent": f"test decision {self.count}",
            "objective": "test continuity",
        }

    def export_campaign_state(self):
        return {
            "campaign_id": self.campaign_id,
            "configuration": {"model": "test-only"},
            "memory": {"count": self.count},
            "usage": {
                "total_tokens": self.usage_calls * 10,
                "returned_responses": self.usage_calls,
                "accounted_responses": self.usage_calls,
                "total_cost_usd": str(self.cost),
            },
        }

    def restore_campaign_state(self, state, *, campaign_id):
        assert self.campaign_id == campaign_id
        self.count = state["memory"]["count"]
        self.usage_calls = state["usage"]["returned_responses"]
        self.cost = Decimal(state["usage"]["total_cost_usd"])


class TestEnvironment:
    """Deterministic test double, not real DF or autonomous gameplay evidence."""

    __test__ = False

    def __init__(self):
        self.state = {
            "year": 30,
            "year_tick": 19309,
            "pause_state": True,
            "population": 7,
            "stocks": {"food": 45, "drink": 60},
        }
        self.actions = []

    def observe(self):
        return deepcopy(self.state)

    def screen(self):
        return "test-only screen"

    def apply(self, action, state):
        self.actions.append(action["intent"])
        return {"accepted": True, "test_feedback": action["intent"]}

    def advance(self, ticks, state):
        self.state["year_tick"] += ticks
        return self.observe(), {"ok": True, "ticks_advanced": ticks}

    def capture(self, directory):
        directory.mkdir()
        (directory / "world.sav").write_text(json.dumps(self.state))
        return {
            "schema_version": "fortgym.native-save-snapshot/v1",
            "save_name": "test-save",
            "year": self.state["year"],
            "year_tick": self.state["year_tick"],
            "paused": True,
            "files": save_inventory(directory),
        }


def start(tmp_path, name="first"):
    return CampaignLoop(
        campaign_id="test-campaign",
        agent=TestAgent(),
        environment=TestEnvironment(),
        output=tmp_path / name,
    )


def test_checkpoint_resume_matches_next_uninterrupted_decision(tmp_path):
    uninterrupted = start(tmp_path)
    uninterrupted.step()
    checkpoint = tmp_path / "checkpoint"
    uninterrupted.checkpoint(
        checkpoint, snapshotter=uninterrupted.environment, code_revision="test"
    )
    environment = TestEnvironment()
    environment.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=TestAgent(),
        environment=environment,
        output=tmp_path / "second",
        latest_usage_path=uninterrupted.journal,
    )
    expected = uninterrupted.step()
    actual = resumed.step()
    assert actual == expected
    assert resumed.agent.prompts[-1] == uninterrupted.agent.prompts[-1]
    assert environment.actions == ["test decision 2"]
    assert actual["step"] == 1
    assert actual["observation"]["agent_plan_control"]["previous_step"] == 0
    assert resumed.history == uninterrupted.history
    assert resumed.last_result == uninterrupted.last_result
    assert resumed.agent.export_campaign_state() == uninterrupted.agent.export_campaign_state()
    second = tmp_path / "checkpoint-two"
    final = resumed.checkpoint(second, snapshotter=environment, code_revision="test")
    assert final["payload"]["parent_sha256"] == verify_checkpoint(checkpoint)["sha256"]
    assert final["payload"]["next_step"] == 2


def test_resume_retains_later_charges_without_replaying_later_actions(tmp_path):
    loop = start(tmp_path)
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="test")
    loop.step()  # A decision after the selected game checkpoint was charged.
    env = TestEnvironment()
    env.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=TestAgent(),
        environment=env,
        output=tmp_path / "resumed",
        latest_usage_path=loop.journal,
    )
    assert resumed.agent.count == 1  # Game-era memory, not future gameplay memory.
    assert resumed.agent.cost == Decimal("0.0000000000002")  # All returned charges.
    assert resumed.agent.usage_calls == 2
    assert env.actions == []
    resumed.step()
    assert resumed.agent.cost == Decimal("0.0000000000003")
    assert env.actions == ["test decision 2"]


def test_failed_execution_cannot_produce_a_checkpoint(tmp_path, monkeypatch):
    loop = start(tmp_path)

    def fail(action, state):
        raise OSError("test runtime vanished after dispatch")

    monkeypatch.setattr(loop.environment, "apply", fail)
    with pytest.raises(OSError):
        loop.step()
    with pytest.raises(ValueError, match="committed"):
        loop.checkpoint(tmp_path / "bad", snapshotter=loop.environment, code_revision="test")
    assert not (tmp_path / "bad").exists()
    with pytest.raises(RuntimeError, match="checkpoint recovery"):
        loop.step()


def test_native_calendar_mismatch_rejects_resume_before_output_creation(tmp_path):
    loop = start(tmp_path)
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="test")
    with pytest.raises(ValueError, match="calendar"):
        CampaignLoop.resume(
            checkpoint,
            agent=TestAgent(),
            environment=TestEnvironment(),
            output=tmp_path / "bad",
            latest_usage_path=loop.journal,
        )
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("name", ["runner.json", "usage.jsonl"])
def test_runner_and_usage_bytes_are_bound_to_manifest(tmp_path, name):
    loop = start(tmp_path)
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="test")
    (checkpoint / name).write_text("tampered")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        verify_checkpoint(checkpoint)


def test_interrupted_decision_and_partial_journal_do_not_restore_free_spending(tmp_path):
    loop = start(tmp_path)
    loop.step()
    state = loop.agent.export_campaign_state()
    raw = loop.journal.read_bytes()
    for suffix in (b'{"type":"decision_started","step":1}\n', b'{"type":'):
        with pytest.raises(ValueError):
            reconciled_usage(state, raw + suffix)


def test_cross_campaign_usage_is_rejected(tmp_path):
    loop = start(tmp_path)
    loop.step()
    state = loop.agent.export_campaign_state()
    state["campaign_id"] = "other"
    with pytest.raises(ValueError, match="configuration"):
        reconciled_usage(state, loop.journal.read_bytes())


def test_partial_tick_advance_counts_actual_time_not_requested_ticks(tmp_path, monkeypatch):
    loop = start(tmp_path)

    def partial(ticks, state):
        loop.environment.state["year_tick"] += 17
        return loop.environment.observe(), {"ok": True, "ticks_advanced": 17, "interrupted": True}

    monkeypatch.setattr(loop.environment, "advance", partial)
    row = loop.step()
    assert row["action"]["advance_ticks"] == 200
    assert row["tick_advance"]["ticks_advanced"] == 17
    assert row["tick_advance"]["end_tick"] - row["tick_advance"]["start_tick"] == 17


def test_tick_receipt_mismatch_cannot_be_committed(tmp_path, monkeypatch):
    loop = start(tmp_path)
    monkeypatch.setattr(
        loop.environment, "advance", lambda ticks, state: (state, {"ticks_advanced": ticks})
    )
    with pytest.raises(ValueError, match="disagrees"):
        loop.step()
    assert not loop.trace.exists()
    assert loop.failed


def test_bounded_native_repause_overshoot_is_counted_not_discarded(tmp_path, monkeypatch):
    loop = start(tmp_path)

    def advance(ticks, state):
        loop.environment.state["year_tick"] += ticks + 2
        return loop.environment.observe(), {"ok": True, "ticks_advanced": ticks + 2}

    monkeypatch.setattr(loop.environment, "advance", advance)
    row = loop.step()
    assert row["tick_advance"]["ticks_advanced"] == 202


def test_failed_native_tick_receipt_is_not_a_clean_boundary(tmp_path, monkeypatch):
    loop = start(tmp_path)
    monkeypatch.setattr(
        loop.environment,
        "advance",
        lambda ticks, state: (state, {"ok": False, "ticks_advanced": 0, "error": "timeout"}),
    )
    with pytest.raises(ValueError, match="cleanly"):
        loop.step()
    assert loop.failed and not loop.at_boundary


def test_model_decision_failure_retains_usage_but_requires_reconciliation(tmp_path, monkeypatch):
    loop = start(tmp_path)

    def fail(text, state):
        loop.agent.cost = Decimal("0.12")
        raise OSError("provider interrupted")

    monkeypatch.setattr(loop.agent, "decide", fail)
    with pytest.raises(OSError):
        loop.step()
    usage = json.loads(loop.journal.read_text().splitlines()[-1])
    assert usage["usage"]["total_cost_usd"] == "0.12"
    assert usage["decision_returned"] is False
    with pytest.raises(ValueError, match="unresolved"):
        reconciled_usage(loop.agent.export_campaign_state(), loop.journal.read_bytes())


def test_campaign_trace_remains_readable_by_existing_usage_and_replay_surfaces(
    tmp_path, monkeypatch
):
    from fort_gym.bench.eval.gates import _model_usage

    loop = start(tmp_path)
    monkeypatch.setattr(
        loop.agent,
        "pop_tool_events",
        lambda: [
            {
                "tool": "openrouter.chat.completions.create",
                "input": {"model": "test-only"},
                "output": {
                    "resolved_model": "test-only",
                    "generation_id": "test-generation",
                    "cost": 0.12,
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 10,
                },
            }
        ],
    )
    row = loop.step()
    assert row["screen_text"] == "test-only screen"
    assert row["events"][0]["type"] == "tool_call"
    assert row["events"][0]["data"]["run_id"] == "test-campaign"
    assert _model_usage([row])["cost_usd"] == 0.12
    assert _model_usage([row])["calls"] == 1
