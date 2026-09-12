"""A later clock recovery retains an earlier lost branch and all its usage."""

import json
import shutil

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest, publish, read
from fort_gym.bench.eval.campaign import read_campaign_progress
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_clock import WORKSHOP_JOB_FOCUS
from fort_gym.bench.run.keyboard_recovery import inspect_recovery_source, reconcile_loaded_tail
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_recovery import NativeFixture
from tests.test_keyboard_restart import failed as failed
from tests.test_keyboard_runtime import CONDITION, environment, policy, saved as saved


@pytest.fixture
def later_failure(tmp_path, failed):
    checkpoint, lost, declaration = failed
    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    restarted = tmp_path / "restarted"
    result = run_keyboard_segment(
        agent=policy(CONDITION),
        environment=env,
        snapshotter=env,
        output=restarted,
        condition=CONDITION,
        checkpoint=checkpoint,
        latest_usage=lost / "segment-0/loop/usage.jsonl",
        steps=1,
        expected_cursor=1,
        revision="b" * 40,
        restart_declaration=declaration,
        restart_source=lost,
    )
    assert result["checkpoint_verified"] is True
    parent = restarted / "checkpoint"
    exchange = tmp_path / "exchange"
    exchange.mkdir()

    def captured(screen, memory, feedback):
        response = decision(screen, memory, feedback)
        request = {
            "schema_version": "fortgym.keyboard-exchange-request/v1",
            "request_id": "a" * 32,
            "screen": screen,
            "memory": memory,
            "feedback": feedback,
            "control_profile": CONDITION["control_profile"],
            "observation_profile": CONDITION["observation_profile"],
            "max_advance_ticks": 2000,
        }
        publish(exchange / "request.json", request)
        publish(exchange / "response.json", {"request_sha256": digest(request), "result": response})
        return response

    class Workshop(NativeFixture):
        def apply(self, action, state):
            result = super().apply(action, state)
            for receipt in result["result"]["native_receipts"]:
                for key in ("before", "after"):
                    receipt[key]["focus"] = WORKSHOP_JOB_FOCUS
            return result

    native = Workshop()
    native.tick = env.tick
    native.screen_capture = environment().screen_capture
    native.advance = native.fail_clock
    segment = tmp_path / "clock-failed"
    result = run_keyboard_segment(
        agent=policy(CONDITION, captured),
        environment=native,
        snapshotter=native,
        output=segment,
        condition=CONDITION,
        checkpoint=parent,
        latest_usage=restarted / "loop/usage.jsonl",
        steps=1,
        expected_cursor=2,
        revision="c" * 40,
    )
    assert result["status"] == "failed" and result["usage"]["returned_responses"] == 5
    return {"parent": parent, "segment": segment, "exchange": exchange}


def test_workshop_clock_recovery_keeps_the_prior_loss_through_resume(tmp_path, later_failure):
    plan = inspect_recovery_source(**later_failure)
    assert plan["schema_version"] == "fortgym.keyboard-failure-recovery/v2"
    assert plan["source_focus"] == WORKSHOP_JOB_FOCUS
    assert plan["next_step"] == 3 and plan["usage"]["returned_responses"] == 5
    inherited = read(later_failure["parent"] / "runner.json")["discontinuities"]
    assert plan["inherited_discontinuities"] == inherited
    original = {
        p: p.read_bytes() for root in later_failure.values() for p in root.rglob("*") if p.is_file()
    }
    env = NativeFixture()
    env.tick = read(later_failure["segment"] / "native-after.json")["year_tick"]
    env.expected_dfroot = env.dfroot = tmp_path / "loaded"
    target = env.dfroot / "data/save/campaign-resume"
    target.parent.mkdir(parents=True)
    shutil.copytree(later_failure["segment"] / "unreconciled-native-save", target)
    env.apply = lambda *args: pytest.fail("No recovery input")
    env.advance = lambda *args: pytest.fail("No recovery time")
    output = tmp_path / "recovered"
    result = reconcile_loaded_tail(
        **later_failure,
        plan=plan,
        agent=policy(CONDITION, lambda *args: pytest.fail("No model call")),
        environment=env,
        snapshotter=env,
        output=output,
        revision="d" * 40,
    )
    assert (
        result["model_calls"]
        == result["native_input_commands"]
        == result["native_ticks_requested"]
        == 0
    )
    checkpoint = output / "checkpoint"
    assert verify_checkpoint(checkpoint)["payload"]["next_step"] == 3
    assert read(checkpoint / "agent.json") == read(later_failure["segment"] / "agent-after.json")
    assert read(checkpoint / "runner.json")["discontinuities"] == inherited
    row = json.loads((output / "trace.jsonl").read_text().splitlines()[-1])
    assert row["discontinuities"] == inherited and row["tick_advance"]["timeout"] is True
    assert all(path.read_bytes() == data for path, data in original.items())
    next_env = environment()
    next_env.tick = env.tick
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=policy(CONDITION),
        environment=next_env,
        output=tmp_path / "continued",
        latest_usage_path=output / "usage.jsonl",
    )
    resumed.step()
    assert (
        resumed.agent.usage["returned_responses"] == 6
        and resumed.agent.usage["total_tokens"] == 600
    )
    assert resumed.discontinuities == inherited
    progress = read_campaign_progress(resumed.trace)
    assert progress["discarded_native_ticks"] == 20 and progress["native_save_loss_restarts"] == 1
    assert progress["elapsed_ticks"] == 30 and progress["uninterrupted_campaign"] is False


def test_recovery_refuses_a_source_that_drops_its_inherited_loss(later_failure):
    path = later_failure["segment"] / "result.json"
    result = read(path)
    result["discontinuities"] = []
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="unchanged keyboard campaign"):
        inspect_recovery_source(**later_failure)
