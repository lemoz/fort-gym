"""A paused build menu returns to the model, not a retrying clock controller."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.env.native_key_catalog import NATIVE_PROFILE
from fort_gym.bench.run import campaign_environment as adapter
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_clock import (
    BLOCKING_FOCUS,
    NATIVE_VIEW,
    SCHEMA,
    validate_menu_deferral,
)
from tests.test_campaign_codex_keyboard import Environment, agent, decision, start


def boundary():
    return {
        "dfroot": "/fixture/df",
        "save_name": "fixture",
        "year": 30,
        "year_tick": 123,
        "paused": True,
        "viewscreen_type": NATIVE_VIEW,
        "focus": BLOCKING_FOCUS,
    }


def observed():
    return {
        "year": 30,
        "year_tick": 123,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }


def deferred(ticks=10):
    return {
        "schema_version": SCHEMA,
        "ok": False,
        "deferred": True,
        "error": "blocking_native_menu",
        "requested": ticks,
        "ticks_advanced": 0,
        "clock_dispatched": False,
        "timeout": False,
        "native_before": boundary(),
        "native_after": boundary(),
    }


def native_adapter(monkeypatch, focus=BLOCKING_FOCUS):
    calls = []
    env = adapter.NativeCampaignEnvironment.__new__(adapter.NativeCampaignEnvironment)
    env.control_profile = NATIVE_PROFILE
    env.max_advance_ticks = 2000
    env.expected_dfroot = Path("/fixture/df")
    env.observe = observed
    env.client = SimpleNamespace(
        advance=lambda *args, **kwargs: calls.append(("clock", args)),
        last_tick_info={"ok": True, "ticks_advanced": 10},
    )

    def probe(keys, **kwargs):
        calls.append(("probe", keys))
        assert keys == [] and kwargs["expected_dfroot"] == env.expected_dfroot
        return {
            "accepted": True,
            "result": {
                "native_receipts": [
                    {"after": {**boundary(), "focus": focus}},
                ]
            },
        }

    monkeypatch.setattr(adapter, "execute_campaign_keys", probe)
    return env, calls


def test_native_build_menu_is_read_twice_without_clock_or_recovery_keys(monkeypatch):
    env, calls = native_adapter(monkeypatch)
    after, receipt = env.advance(10, observed())
    assert calls == [("probe", []), ("probe", [])]
    assert receipt == deferred()
    assert (
        validate_menu_deferral(
            receipt, requested_ticks=10, before=observed(), after=after
        )
        is None
    )


def test_other_focus_keeps_existing_clock_path(monkeypatch):
    env, calls = native_adapter(monkeypatch, "dwarfmode/Default")
    _, receipt = env.advance(10, observed())
    assert calls == [("probe", []), ("clock", (10,))]
    assert receipt == {"ok": True, "ticks_advanced": 10}


def test_zero_request_does_not_probe_or_advance(monkeypatch):
    env, calls = native_adapter(monkeypatch)
    assert env.advance(0, observed())[1] == {
        "ok": True,
        "ticks_advanced": 0,
        "skipped": True,
    }
    assert calls == []


@pytest.mark.parametrize("profile", ["native_keyboard/v1", "dfhack_shortcuts/v1"])
def test_historical_controls_keep_the_existing_clock_path(monkeypatch, profile):
    env, calls = native_adapter(monkeypatch)
    env.control_profile = profile
    env.advance(10, observed())
    assert calls == [("clock", (10,))]


def test_unknown_probe_never_starts_the_clock(monkeypatch):
    env, calls = native_adapter(monkeypatch)
    monkeypatch.setattr(
        adapter, "execute_campaign_keys", lambda *a, **kw: {"accepted": False}
    )
    with pytest.raises(RuntimeError, match="could not attest"):
        env.advance(10, observed())
    assert calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("ok", True),
        ("clock_dispatched", True),
        ("timeout", True),
        ("ticks_advanced", False),
        ("requested", 11),
        ("deferred", 1),
        ("schema_version", "unknown"),
        ("error", "timeout_waiting_for_ticks"),
    ],
)
def test_deferral_cannot_hide_timeout_or_unknown_clock(tmp_path, field, value):
    loop = start(tmp_path)
    loop.environment.observe = observed
    receipt = deferred()
    receipt[field] = value
    loop.environment.advance = lambda *args: (observed(), receipt)
    with pytest.raises(ValueError, match="menu deferral|Native time disagrees"):
        loop.step()
    assert loop.failed and not loop.at_boundary
    assert loop.agent.usage["dispatched_requests"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("year_tick", 124),
        ("year_tick", True),
        ("paused", False),
        ("focus", "dwarfmode/Default"),
        ("dfroot", "/another"),
        ("save_name", "other"),
        ("viewscreen_type", "viewscreen_textviewerst"),
    ],
)
def test_changed_native_boundary_is_not_deferred(field, value):
    receipt = deferred()
    receipt["native_after"][field] = value
    assert (
        validate_menu_deferral(
            receipt, requested_ticks=10, before=observed(), after=observed()
        )
        is not None
    )


def test_menu_result_can_checkpoint_and_model_alone_selects_recovery(tmp_path):
    feedbacks = []

    def callback(screen, memory, feedback):
        feedbacks.append(deepcopy(feedback))
        return decision(screen, memory, feedback)

    loop = start(tmp_path, callback)
    loop.environment.observe = observed
    loop.environment.advance = lambda *args: (observed(), deferred())
    row = loop.step()
    assert (
        row["action"]["advance_ticks"] == 10
        and row["tick_advance"]["ticks_advanced"] == 0
    )
    assert loop.at_boundary and not loop.failed and loop.next_step == 1
    assert loop.environment.actions[0]["params"]["keys"] == ["D_BUILDING"]
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=loop.environment, code_revision="fixture")
    assert verify_checkpoint(checkpoint)["payload"]["next_step"] == 1
    env = Environment()
    resumed = CampaignLoop.resume(
        checkpoint,
        agent=agent(callback),
        environment=env,
        output=tmp_path / "resumed",
        latest_usage_path=loop.journal,
    )
    assert env.actions == []
    resumed.step()
    assert [a["params"]["keys"] for a in env.actions] == [["LEAVESCREEN"]]
    assert feedbacks[-1]["simulation"] == {
        "requested_ticks": 10,
        "ticks_advanced": 0,
        "deferred": True,
        "reason": "blocking_native_menu",
    }
    assert feedbacks[-1]["accepted"] is True
    assert set(feedbacks[-1]) == {
        "accepted",
        "reason",
        "keys_confirmed",
        "command_mutation",
        "simulation",
    }
    assert resumed.agent.usage["dispatched_requests"] == 2
    assert resumed.agent.usage["total_tokens"] == 200


def test_historical_timeout_remains_a_failure(tmp_path):
    loop = start(tmp_path)
    loop.environment.advance = lambda *args: (
        loop.environment.observe(),
        {
            "ok": False,
            "requested": 10,
            "ticks_advanced": 0,
            "error": "timeout_waiting_for_ticks",
            "timeout": True,
            "paused_after": True,
            "repause_effective": True,
        },
    )
    with pytest.raises(ValueError, match="did not finish"):
        loop.step()
    assert loop.failed and not loop.at_boundary
