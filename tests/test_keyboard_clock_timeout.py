from copy import deepcopy

import pytest

from fort_gym.bench.run import campaign_environment as adapter
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_clock import WORKSHOP_JOB_FOCUS, validate_menu_deferral
from fort_gym.bench.run.keyboard_clock_timeout import SCHEMA, validate_clock_unavailable
from tests.test_campaign_codex_keyboard import Environment, agent, decision, start
from tests.test_keyboard_clock import boundary, native_adapter, observed
from tests.test_keyboard_recovery import NativeFixture


def timeout_receipt(ticks=10):
    env = NativeFixture()
    env.tick = 123
    return env.fail_clock(ticks, observed())[1]


def unavailable():
    return {
        **timeout_receipt(),
        "schema_version": SCHEMA,
        "clock_unavailable": True,
        "clock_dispatched": True,
        "native_before": {**boundary(), "focus": "dwarfmode/UnseenMenu"},
        "native_after": {**boundary(), "focus": "dwarfmode/UnseenMenu"},
    }


def test_workshop_job_menu_defers_without_time_dispatch_or_a_harness_key(monkeypatch):
    env, calls = native_adapter(monkeypatch, WORKSHOP_JOB_FOCUS)
    after, receipt = env.advance(10, observed())
    assert calls == [("probe", []), ("probe", [])]
    assert (
        validate_menu_deferral(receipt, requested_ticks=10, before=observed(), after=after) is None
    )
    assert receipt["clock_dispatched"] is False and receipt["timeout"] is False


def test_unknown_focus_retains_original_timeout_and_matches_two_read_only_probes(monkeypatch):
    env, calls = native_adapter(monkeypatch, "dwarfmode/UnseenMenu")
    original = timeout_receipt()
    env.client.last_tick_info = deepcopy(original)
    after, receipt = env.advance(10, observed())
    assert calls == [("probe", []), ("clock", (10,)), ("probe", [])]
    assert all(receipt[key] == value for key, value in original.items())
    assert receipt["ok"] is False and receipt["clock_dispatched"] is True
    assert (
        validate_clock_unavailable(receipt, requested_ticks=10, before=observed(), after=after)
        is None
    )
    assert env.client.last_tick_info == original


def test_unknown_or_partial_timeout_is_not_promoted(monkeypatch):
    env, calls = native_adapter(monkeypatch, "dwarfmode/UnseenMenu")
    original = {**timeout_receipt(), "ticks_advanced": 1}
    env.client.last_tick_info = original
    assert env.advance(10, observed())[1] == original
    assert calls == [("probe", []), ("clock", (10,))]


def test_changed_post_timeout_probe_fails_without_replaying(monkeypatch):
    env, calls = native_adapter(monkeypatch, "dwarfmode/UnseenMenu")
    env.client.last_tick_info = timeout_receipt()
    original = adapter.execute_campaign_keys

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(calls) == 3:
            result["result"]["native_receipts"][0]["after"]["save_name"] = "different"
        return result

    monkeypatch.setattr(adapter, "execute_campaign_keys", changed)
    with pytest.raises(RuntimeError, match="boundary_changed"):
        env.advance(10, observed())
    assert calls == [("probe", []), ("clock", (10,)), ("probe", [])]


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "unknown"),
        ("clock_unavailable", 1),
        ("clock_dispatched", False),
        ("ok", True),
        ("timeout", 1),
        ("error", "other"),
        ("ticks_advanced", False),
        ("ticks_advanced", 1),
        ("requested", 11),
        ("requested", True),
        ("start_tick", True),
        ("end_tick", 124),
        ("paused_before", False),
        ("paused_after", False),
        ("repause_effective", False),
        ("repause_requested", False),
        ("final_pause_state", False),
        ("final_viewscreen_type", "unknown"),
        ("interrupt_safety_error", True),
        ("calendar_safety_error", True),
        ("tick_deadline_error", "failed"),
        ("resume_error", "failed"),
        ("repause_error", "failed"),
        ("nopause_enable_error", "failed"),
        ("intermediate_probe_error", "missing sample"),
        ("interrupted", True),
        ("repause", {}),
        ("deferred", False),
        ("native_after", {}),
    ],
)
def test_clock_feedback_never_hides_unknown_or_partial_execution(tmp_path, field, value):
    loop = start(tmp_path)
    loop.environment.observe = observed
    receipt = unavailable()
    receipt[field] = value
    loop.environment.advance = lambda *args: (observed(), receipt)
    with pytest.raises(ValueError):
        loop.step()
    assert loop.failed and not loop.at_boundary
    assert loop.agent.usage["accounted_responses"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("year_tick", 124),
        ("year", True),
        ("paused", False),
        ("focus", ""),
        ("dfroot", ""),
        ("save_name", ""),
        ("viewscreen_type", "other"),
    ],
)
def test_missing_native_identity_cannot_attest_timeout(field, value):
    receipt = unavailable()
    for key in ("native_before", "native_after"):
        receipt[key][field] = value
    assert validate_clock_unavailable(
        receipt, requested_ticks=10, before=observed(), after=observed()
    )


def test_attested_timeout_checkpoints_and_the_model_selects_the_next_input(tmp_path):
    feedbacks = []

    def callback(screen, memory, feedback):
        feedbacks.append(deepcopy(feedback))
        return decision(screen, memory, feedback)

    loop = start(tmp_path, callback)
    loop.environment.observe = observed
    loop.environment.advance = lambda *args: (observed(), unavailable())
    row = loop.step()
    assert loop.at_boundary and not loop.failed and loop.next_step == 1
    assert row["tick_advance"]["ok"] is False and row["tick_advance"]["timeout"] is True
    assert row["tick_advance"]["ticks_advanced"] == 0
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="fixture")
    assert verify_checkpoint(checkpoint)["payload"]["next_step"] == 1
    env = Environment()
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=agent(callback),
        environment=env,
        output=tmp_path / "resume",
        latest_usage_path=loop.journal,
    )
    assert env.actions == []
    resumed.step()
    assert [action["params"]["keys"] for action in env.actions] == [["LEAVESCREEN"]]
    assert feedbacks[-1]["simulation"] == {
        "requested_ticks": 10,
        "ticks_advanced": 0,
        "deferred": True,
        "reason": "timeout_waiting_for_ticks",
    }
    assert resumed.agent.usage["accounted_responses"] == 2
