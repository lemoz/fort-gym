from copy import deepcopy
import json
from pathlib import Path

import pytest

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.codex_transport import CodexTransportError
from fort_gym.bench.eval.campaign import read_campaign_progress
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, CampaignPreDispatchPause, reconciled_usage
from tests.test_campaign_codex_keyboard import Environment, agent, decision, start


def rejected(*args):
    result = decision(*args)
    raw = deepcopy(result["action"])
    raw["params"]["keys"] = ["BUILJOB_FARM_SPRING", "SELECT"]
    raw["memory_update"] = "This attempted action did not happen."
    raw["advance_ticks"] = 2000
    result.update(
        action=None,
        action_grammar_valid=False,
        native_action_dispatched=False,
        error="Keyboard keys must be supported native interface events",
    )
    result["transport_receipt"].update(
        response=raw, usage_complete=True, native_game_commands=0,
        timed_out=False, interrupted=False,
    )
    return result


def no_native_call(*args):
    pytest.fail("A rejected response must not invoke native input or clock, even with zero ticks")


def test_typo_is_recorded_without_correcting_keys_advancing_time_or_applying_memory(tmp_path):
    loop = start(tmp_path, rejected)
    loop.environment.apply = no_native_call
    loop.environment.advance = no_native_call
    row = loop.step()
    assert row["record_origin"] == "model_input_rejection/v1"
    assert row["action"]["params"]["keys"] == ["BUILJOB_FARM_SPRING", "SELECT"]
    assert row["execute"]["accepted"] is False
    assert row["execute"]["result"]["command_mutation"] == "not_attempted"
    assert row["execute"]["result"]["keys_confirmed"] == 0
    assert row["tick_advance"]["requested"] == 2000
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert row["tick_advance"]["clock_dispatched"] is False
    assert row["tick_advance"]["ok"] is False
    assert loop.agent.memory == ""
    assert loop.agent.usage["total_tokens"] == 100
    assert loop.agent.usage["accounted_responses"] == 1
    assert loop.agent.usage["total_cost_usd"] is None
    assert loop.next_step == 1 and loop.at_boundary and not loop.failed
    assert loop.history[-1]["outcome"] == "validation_rejected"
    assert read_campaign_progress(loop.trace)["elapsed_ticks"] == 0
    assert not (loop.output / "failures.jsonl").exists()


def test_checkpoint_resume_delivers_rejection_feedback_then_only_the_models_next_action(tmp_path):
    loop = start(tmp_path)
    loop.step()
    loop.agent.decision = rejected
    loop.step()
    assert loop.agent.memory == "x"
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="fixture")
    assert verify_checkpoint(checkpoint)["payload"]["next_step"] == 2
    calls = []

    def corrected(screen, memory, feedback):
        calls.append((screen, memory, feedback))
        return decision(screen, memory, feedback)

    environment = Environment()
    environment.tick = loop.environment.tick
    resumed = CampaignLoop.resume(
        checkpoint, agent=agent(corrected), environment=environment,
        output=tmp_path / "resumed", latest_usage_path=loop.journal,
    )
    assert environment.actions == []
    row = resumed.step()
    assert len(calls) == len(environment.actions) == 1
    assert row["action"]["params"]["keys"] == ["LEAVESCREEN"]
    _, memory, feedback = calls[0]
    assert memory == "x"
    assert feedback["accepted"] is False and feedback["keys_confirmed"] == 0
    assert "BUILJOB_FARM_SPRING" in feedback["reason"]
    assert "BUILDJOB_FARM_SPRING" not in feedback["reason"]
    assert feedback["simulation"]["clock_dispatched"] is False
    assert "hidden" not in json.dumps(calls)
    assert resumed.agent.memory == "xx"
    assert resumed.agent.usage["total_tokens"] == 300
    assert read_campaign_progress(resumed.trace)["elapsed_ticks"] == 20
    assert resumed.trace.read_bytes().startswith(loop.trace.read_bytes())


@pytest.mark.parametrize("field,value", [
    ("usage_complete", False), ("native_game_commands", 1), ("native_game_commands", False),
    ("timed_out", True), ("interrupted", True),
    ("model_requested", "wrong"), ("auth_mode", "apikey"),
])
def test_uncertain_transport_is_not_relabelled_as_input_rejection(tmp_path, field, value):
    def callback(*args):
        result = rejected(*args)
        result["transport_receipt"][field] = value
        return result

    loop = start(tmp_path, callback)
    with pytest.raises(CodexTransportError):
        loop.step()
    assert loop.failed and not loop.at_boundary
    assert loop.agent.usage["total_tokens"] == 100
    assert not loop.environment.actions


@pytest.mark.parametrize("mutation", ["dispatched", "no_unknown_keys", "wrong_type", "ticks"])
def test_inconsistent_rejection_evidence_remains_a_failure(tmp_path, mutation):
    def callback(*args):
        result = rejected(*args)
        raw = result["transport_receipt"]["response"]
        if mutation == "dispatched":
            result["native_action_dispatched"] = True
        elif mutation == "no_unknown_keys":
            raw["params"]["keys"] = ["SELECT"]
        elif mutation == "wrong_type":
            raw["type"] = "ORDER"
        else:
            raw["advance_ticks"] = True
        return result

    loop = start(tmp_path, callback)
    with pytest.raises((ValueError, CodexTransportError)):
        loop.step()
    assert loop.failed and not loop.environment.actions


def test_rejection_cannot_hide_native_calendar_drift(tmp_path):
    loop = start(tmp_path, rejected)
    observe = loop.environment.observe
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        if calls > 1:
            loop.environment.tick += 1
        return observe()

    loop.environment.observe = drift
    with pytest.raises(ValueError, match="Native boundary changed"):
        loop.step()
    assert loop.failed and not loop.at_boundary


def test_rejection_cannot_change_retained_memory(tmp_path):
    class BrokenAgent(CodexKeyboardAgent):
        def decide(self, *args):
            try:
                return super().decide(*args)
            finally:
                self.memory = "invented state"

    loop = start(tmp_path, rejected)
    broken = BrokenAgent(decision=rejected, max_dispatches=8, max_total_tokens=10000)
    broken.set_campaign_context(campaign_id=loop.campaign_id)
    loop.agent = broken
    with pytest.raises(ValueError, match="changed memory"):
        loop.step()
    assert loop.failed and not loop.environment.actions


def test_repeated_rejections_consume_the_existing_budget(tmp_path):
    loop = start(tmp_path, rejected, limit=2)
    loop.environment.apply = no_native_call
    loop.environment.advance = no_native_call
    loop.step()
    loop.step()
    with pytest.raises(CampaignPreDispatchPause):
        loop.step()
    assert loop.next_step == 2 and loop.at_boundary and not loop.failed
    assert loop.agent.usage["dispatched_requests"] == 2
    assert loop.agent.usage["total_tokens"] == 200


@pytest.mark.parametrize("mutation", ["unknown_dispatch", "historical_failure", "missing_boundary"])
def test_rejection_journal_requires_explicit_non_execution(tmp_path, mutation):
    loop = start(tmp_path, rejected)
    loop.step()
    records = [json.loads(line) for line in loop.journal.read_text().splitlines()]
    final = records[-1]
    assert final["outcome"] == "model_input_rejected/v1"
    if mutation == "unknown_dispatch":
        final["native_action_dispatched"] = None
    elif mutation == "historical_failure":
        final["decision_returned"] = False
    else:
        del final["native_boundary"]
    raw = "".join(json.dumps(row) + "\n" for row in records).encode()
    with pytest.raises(ValueError):
        reconciled_usage(loop.agent.export_campaign_state(), raw)


def test_published_rejection_keeps_original_failure_and_all_usage():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / "experiments/evidence/astra_native_keyboard_rejection_20260907.json").read_text())
    progress, usage = record["progress"], record["usage"]
    assert progress["returned_model_decisions"] == progress["committed_decisions"] + 1 == 184
    assert progress["failed_tail_key_events_confirmed"] == 0
    assert progress["latest_verified_checkpoint_cursor"] == 181
    assert progress["uncheckpointed_committed_decisions"] == 2
    assert usage["rejected_response_tokens_included"] == 32731
    assert usage["all_attempt_tokens"] == usage["campaign_tokens"] + usage["historical_failed_delivery_tokens"]
    assert usage["reported_charge_usd"] is None
    assert record["historical_run_reclassified_as_success"] is False
    assert record["forensic_save_is_resumable_checkpoint"] is False
    assert record["recovery_requires_reconciliation"] is True
