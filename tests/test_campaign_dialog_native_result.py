"""Read-only published fixture checks and deterministic meeting-cascade regression."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fort_gym.bench.run.campaign_advance import MODEL_REQUESTED
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from fort_gym.bench.tick_receipt import validate_clean_interruption_receipt
from tests.test_campaign_loop import TestAgent

EVIDENCE = Path(__file__).resolve().parents[1] / "experiments/evidence"


def evidence():
    return json.loads((EVIDENCE / "local_native_dialog_feedback_20260907.json").read_text())


def test_native_stage_evidence_does_not_rewrite_failed_fixture_as_passing():
    row = evidence()
    declaration = EVIDENCE / "local_native_dialog_feedback_declaration_20260907.json"
    assert hashlib.sha256(declaration.read_bytes()).hexdigest() == row["declaration_sha256"]
    assert row["declared_fixture_passed"] is row["original_operator_verified_flag"] is False
    assert row["status"] == "fixture_assertion_failed_after_verified_dialog_feedback"
    parts = row["component_evidence"]
    assert parts["natural_liaison_dialog_reproduced"] is True
    assert parts["invalid_wait_rejected_without_command_or_clock"] is True
    assert parts["rejection_visible_to_next_decision"] is True
    assert parts["one_scripted_confirm_executed"] is True
    assert parts["subsequent_native_time_advanced"] == 19
    assert parts["subsequent_meeting_interruption_validated"] is True
    assert parts["campaign_loop_failed"] is False
    assert parts["meeting_completed"] is parts["autonomous_model_recovery"] is False
    assert [s["actual_ticks"] for s in row["scripted_steps"]] == [2500, 2500, 2500, 624, 0, 0, 19]
    assert (
        sum(s["actual_ticks"] for s in row["scripted_steps"]) == row["total_scripted_ticks"] == 8143
    )
    assert row["container_exit_code"] == 1
    assert row["native_load_verified"] is row["native_cleanup_verified"] is True
    assert row["owned_container_stopped"] is row["owned_vm_stopped"] is True
    assert row["original_checkpoint_still_verifies"] is True
    assert row["provider_calls"] == row["total_tokens"] == row["cloud_vms_created"] == 0
    assert row["metered_provider_charge_usd"] == "0"
    assert row["hardware_energy_and_app_cost_usd"] is None
    for key in (
        "autonomous_gameplay",
        "year_two_gameplay_verified",
        "model_ranking_evidence",
        "original_campaign_resumed",
        "original_evidence_rewritten",
        "production_deployed",
    ):
        assert row[key] is False


def test_real_meeting_cascade_receipt_remains_a_clean_interruption_then_feedback(tmp_path):
    receipt = evidence()["final_interruption_receipt"]
    before = {
        "year": 30,
        "year_tick": 220925,
        "time": 220925,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
        "population": 9,
        "stocks": {},
    }
    after = {
        **before,
        "year_tick": 220944,
        "time": 220944,
        "viewscreen_type": "viewscreen_topicmeetingst",
    }
    assert (
        validate_clean_interruption_receipt(
            receipt, requested_ticks=100, state_after_apply=before, state_after_advance=after
        )
        is None
    )
    corrupted = {**receipt, "ticks_advanced": 100}
    assert (
        validate_clean_interruption_receipt(
            corrupted, requested_ticks=100, state_after_apply=before, state_after_advance=after
        )
        is not None
    )

    class ScriptedInputs(TestAgent):
        def decide(self, text, observation):
            action = super().decide(text, observation)
            action["advance_ticks"] = 100 if self.count == 1 else 2500
            return action

    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env._verify_runtime = lambda: None
    env.max_advance_ticks = 2500
    state, calls = deepcopy(before), []
    env.observe = lambda: deepcopy(state)
    env.screen = lambda: "Deterministic double of recorded meeting transition"
    env.executor = SimpleNamespace(apply=lambda *a, **k: {"accepted": True})

    def advance(ticks, **kwargs):
        calls.append(ticks)
        assert len(calls) == 1 and ticks == 100
        state.update(after)
        client.last_tick_info = deepcopy(receipt)

    client = SimpleNamespace(advance=advance)
    env.client = client
    loop = CampaignLoop(
        campaign_id="recorded-meeting-cascade-test",
        agent=ScriptedInputs(),
        environment=env,
        output=tmp_path / "campaign",
        observation_profile="campaign_state/v1",
        advance_policy=MODEL_REQUESTED,
        max_advance_ticks=2500,
    )
    interrupted = loop.step()
    assert interrupted["tick_advance"]["ok"] is False
    assert interrupted["tick_advance"]["ticks_advanced"] == 19
    assert loop.at_boundary and not loop.failed
    rejected = loop.step()
    assert rejected["action"]["advance_ticks"] == 2500
    assert rejected["execute"]["accepted"] is False
    assert rejected["tick_advance"]["ticks_advanced"] == 0
    assert calls == [100] and loop.next_step == 2 and loop.committed_elapsed_ticks == 19
    assert loop.at_boundary and not loop.failed
    assert not (loop.output / "failures.jsonl").exists()
    agent = loop.agent.export_campaign_state()
    assert reconciled_usage(agent, loop.journal.read_bytes()) == agent["usage"]
    assert agent["usage"]["returned_responses"] == 2
