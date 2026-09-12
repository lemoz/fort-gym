"""A failed native clock can settle forward; original failure evidence stays."""

import json
import shutil
from copy import deepcopy

import pytest

from fort_gym.bench.agent.keyboard_exchange import digest, publish, read
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_clock import BLOCKING_FOCUS, NATIVE_VIEW
from fort_gym.bench.run.keyboard_recovery import (
    inspect_recovery_source,
    reconcile_loaded_tail,
)
from tests.test_campaign_codex_keyboard import Environment, agent, decision, start


class NativeFixture(Environment):
    def observe(self):
        return {
            **super().observe(),
            "time": self.tick,
            "viewscreen_type": "viewscreen_dwarfmodest",
        }

    def apply(self, action, state):
        self.actions.append(deepcopy(action))
        before = {
            "dfroot": "/native/fixture",
            "save_name": "campaign-resume",
            "year": 30,
            "year_tick": self.tick,
            "paused": True,
            "viewscreen_type": NATIVE_VIEW,
            "focus": BLOCKING_FOCUS,
        }
        keys = action["params"]["keys"]
        receipts = [
            {
                "schema_version": "fortgym.campaign-keyboard-native/v1",
                "ok": True,
                "mode": "probe" if i == 0 else "key",
                "command_mutation": "not_attempted" if i == 0 else "completed",
                "keys_sent": int(i > 0),
                "before": before,
                "after": before,
                **({"key": key} if i else {}),
            }
            for i, key in enumerate([None, *keys])
        ]
        return {
            "accepted": True,
            "result": {
                "ok": True,
                "command_mutation": "completed",
                "keys_confirmed": len(keys),
                "keys_sent": len(keys),
                "native_receipts": receipts,
            },
        }

    def fail_clock(self, ticks, state):
        return self.observe(), {
            "ok": False,
            "requested": ticks,
            "ticks_advanced": 0,
            "start_year": 30,
            "start_tick": self.tick,
            "end_year": 30,
            "end_tick": self.tick,
            "timeout": True,
            "error": "timeout_waiting_for_ticks",
            "paused_before": True,
            "paused_after": True,
            "repause_requested": True,
            "repause_effective": True,
            "final_pause_state": True,
            "interrupt_safety_error": False,
            "calendar_safety_error": False,
            "final_viewscreen_type": "viewscreen_dwarfmodest",
            "repause": {
                "ok": True,
                "paused": True,
                "attempts": 1,
                "attempt_records": [
                    {"attempt": 1, "nopause_disabled": True, "paused": True}
                ],
            },
        }


@pytest.fixture
def source(tmp_path):
    first = start(tmp_path)
    first.step()
    parent = tmp_path / "parent"
    first.checkpoint(parent, snapshotter=first.environment, code_revision="first")
    segment, exchange = tmp_path / "failed", tmp_path / "exchange"
    segment.mkdir()
    exchange.mkdir()

    def captured(screen, memory, feedback):
        response = decision(screen, memory, feedback)
        request = {
            "schema_version": "fortgym.keyboard-exchange-request/v1",
            "request_id": "a" * 32,
            "screen": screen,
            "memory": memory,
            "feedback": feedback,
            "control_profile": "native_keyboard/v2",
            "observation_profile": "native_screen_text/v1",
            "max_advance_ticks": 2000,
        }
        publish(exchange / "request.json", request)
        publish(
            exchange / "response.json",
            {"request_sha256": digest(request), "result": response},
        )
        return response

    env = NativeFixture()
    env.tick = first.environment.tick
    loop = CampaignLoop.resume(
        parent,
        agent=agent(captured),
        environment=env,
        output=segment / "loop",
        latest_usage_path=first.journal,
    )
    publish(segment / "agent-before.json", loop.agent.export_campaign_state())
    env.advance = env.fail_clock
    with pytest.raises(ValueError, match="did not finish"):
        loop.step()
    env.capture(segment / "unreconciled-native-save")
    publish(segment / "agent-after.json", loop.agent.export_campaign_state())
    publish(segment / "native-after.json", env.observe())
    publish(
        segment / "result.json",
        {
            "schema_version": "fortgym.keyboard-segment/v1",
            "status": "failed",
            "stop_reason": "unsettled_failure",
            "first_step": 1,
            "next_step": 1,
            "checkpoint_verified": False,
            "recovery_requires_reconciliation": True,
            "unreconciled_native_snapshot_retained": True,
            "committed_elapsed_ticks": 10,
            "usage": loop.agent.export_campaign_state()["usage"],
        },
    )
    return {"parent": parent, "segment": segment, "exchange": exchange}


def loaded_fixture(tmp_path, source):
    env = NativeFixture()
    env.tick = 133
    env.expected_dfroot = env.dfroot = tmp_path / "loaded"
    loaded = env.dfroot / "data/save/campaign-resume"
    loaded.parent.mkdir(parents=True)
    shutil.copytree(source["segment"] / "unreconciled-native-save", loaded)
    env.apply = lambda *a: pytest.fail("Recovery must not replay any native key")
    env.advance = lambda *a: pytest.fail("Recovery must not request game time")
    return env


def test_recovery_checkpoint_preserves_original_failure_and_never_replays(
    tmp_path, source
):
    plan = inspect_recovery_source(**source)
    assert plan["failed_step"] == 1 and plan["next_step"] == 2
    assert plan["usage"]["total_tokens"] == 200 and plan["replay_allowed"] is False
    originals = {
        p: p.read_bytes()
        for root in source.values()
        for p in root.rglob("*")
        if p.is_file()
    }
    env = loaded_fixture(tmp_path, source)
    output = tmp_path / "recovery"
    policy = agent(lambda *a: pytest.fail("Recovery must not make a model call"))
    result = reconcile_loaded_tail(
        **source,
        plan=plan,
        agent=policy,
        environment=env,
        snapshotter=env,
        output=output,
        revision="recovery-fixture",
    )
    assert result["checkpoint_verified"] and result["next_step"] == 2
    assert (
        result["model_calls"]
        == result["native_input_commands"]
        == result["native_ticks_requested"]
        == 0
    )
    assert result["original_failure_reclassified_as_success"] is False
    assert result["elapsed_ticks"] == 10
    assert all(path.read_bytes() == original for path, original in originals.items())
    checkpoint = verify_checkpoint(output / "checkpoint")
    assert checkpoint["payload"]["parent_sha256"] == plan["parent_checkpoint_sha256"]
    rows = [
        json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()
    ]
    assert [row["step"] for row in rows] == [0, 1]
    assert rows[-1]["record_origin"] == "verified_failure_reconciliation/v1"
    assert (
        rows[-1]["tick_advance"]["ok"] is False
        and rows[-1]["tick_advance"]["timeout"] is True
    )
    assert rows[-1]["reconciliation"]["original_failure"]["step"] == 1
    assert read(output / "checkpoint/agent.json") == read(
        source["segment"] / "agent-after.json"
    )
    next_env = NativeFixture()
    next_env.tick = 133
    observations = []

    def next_decision(screen, memory, feedback):
        observations.append((memory, feedback))
        return decision(screen, memory, feedback)

    resumed = CampaignLoop.resume(
        output / "checkpoint",
        agent=agent(next_decision),
        environment=next_env,
        output=tmp_path / "next",
        latest_usage_path=output / "usage.jsonl",
    )
    assert next_env.actions == []
    resumed.step()
    assert len(next_env.actions) == 1 and resumed.next_step == 3
    assert observations[0][0] == "xx"
    assert observations[0][1]["simulation"]["failure_reconciled"] is True
    assert observations[0][1]["simulation"]["runtime_reloaded"] is True
    assert resumed.agent.usage["total_tokens"] == 300


def mutate(source, filename, change):
    path = source["segment"] / filename
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value) + "\n")


@pytest.mark.parametrize(
    "kind", ["partial", "ticks", "pause", "clock", "count", "native"]
)
def test_unproven_failed_tail_is_not_recoverable(source, kind):
    def change(failure):
        if kind == "partial":
            failure["execute"]["result"]["command_mutation"] = "partial"
        elif kind == "ticks":
            failure["tick_receipt"]["ticks_advanced"] = 1
        elif kind == "pause":
            failure["tick_receipt"]["repause_effective"] = False
        elif kind == "clock":
            failure["native_after"]["year_tick"] += 1
        elif kind == "count":
            failure["execute"]["result"]["keys_confirmed"] = 0
        else:
            failure["execute"]["result"]["native_receipts"][-1]["after"]["focus"] = (
                "unknown"
            )

    mutate(source, "loop/failures.jsonl", change)
    with pytest.raises(ValueError):
        inspect_recovery_source(**source)


def test_changed_memory_and_response_cannot_be_substituted(source):
    mutate(
        source, "agent-after.json", lambda value: value.update(memory="operator rescue")
    )
    with pytest.raises(ValueError, match="memory"):
        inspect_recovery_source(**source)


def test_plan_does_not_authorize_a_different_loaded_game(tmp_path, source):
    plan = inspect_recovery_source(**source)
    env = loaded_fixture(tmp_path, source)
    (env.dfroot / "data/save/campaign-resume/world.sav").write_text("wrong-fortress")
    output = tmp_path / "recovery"
    with pytest.raises(ValueError, match="Loaded game files"):
        reconcile_loaded_tail(
            **source,
            plan=plan,
            agent=agent(),
            environment=env,
            snapshotter=env,
            output=output,
            revision="fixture",
        )
    assert not output.exists()


def test_source_mutation_during_capture_cannot_publish_checkpoint(tmp_path, source):
    plan = inspect_recovery_source(**source)
    env = loaded_fixture(tmp_path, source)
    original = env.capture

    def capture(path):
        receipt = original(path)
        mutate(source, "agent-after.json", lambda value: value.update(memory="changed"))
        return receipt

    env.capture = capture
    output = tmp_path / "recovery"
    with pytest.raises(ValueError):
        reconcile_loaded_tail(
            **source,
            plan=plan,
            agent=agent(),
            environment=env,
            snapshotter=env,
            output=output,
            revision="fixture",
        )
    assert not (output / "checkpoint/checkpoint.json").exists()


def test_changed_request_cannot_be_bound_to_the_failed_response(source):
    path = source["exchange"] / "request.json"
    request = read(path)
    request["memory"] = "different memory"
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match="bound"):
        inspect_recovery_source(**source)


def test_failed_response_cost_cannot_be_discarded(source):
    def change(state):
        state["usage"]["total_tokens"] -= 100
    mutate(source, "agent-after.json", change)
    with pytest.raises(ValueError, match="accounted"):
        inspect_recovery_source(**source)


@pytest.mark.parametrize("append_only", [True, False])
def test_loaded_dfhack_log_may_only_append(tmp_path, source, append_only):
    old = source["segment"] / "unreconciled-native-save/events-dfhack.log"
    old.write_text("original load event\n")
    plan = inspect_recovery_source(**source)
    env = loaded_fixture(tmp_path, source)
    log = env.dfroot / "data/save/campaign-resume/events-dfhack.log"
    log.write_text(("original load event\n" if append_only else "") + "new load event\n")
    arguments = dict(
        **source, plan=plan, agent=agent(), environment=env, snapshotter=env,
        output=tmp_path / "recovery", revision="fixture",
    )
    if append_only:
        assert reconcile_loaded_tail(**arguments)["checkpoint_verified"]
    else:
        with pytest.raises(ValueError, match="log"):
            reconcile_loaded_tail(**arguments)


def test_native_clock_diagnostic_is_not_campaign_performance():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    record = read(root / "experiments/evidence/local_native_keyboard_clock_20260907.json")
    assert record["executed_source_revision"] == "9d09f69615faf03e151ee2b8d8b43bac6eab172e"
    assert record["native_clock_correction_verified"] is True
    assert record["ordinary_requested_ticks"] == record["ordinary_observed_ticks"] == 100
    assert record["blocked_requested_ticks"] == 2000 and record["blocked_observed_ticks"] == 0
    assert record["blocked_clock_dispatched"] is False
    assert record["latest_forensic_native_load_verified"] is True
    assert record["campaign_gameplay"] is record["campaign_recovery_verified"] is False
    assert record["provider_calls"] == record["cloud_vms_created"] == 0
    assert record["teardown"]["container_running"] is False
    assert record["teardown"]["owned_vm_stopped"] is True
