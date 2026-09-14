"""A native dialog that remains after model input is feedback, not a fatal clock."""

from copy import deepcopy

import pytest

from fort_gym.bench.run import campaign_environment as adapter
from fort_gym.bench.run.keyboard_clock import (
    MODAL_SCHEMA, SCHEMA, deferral_schema, validate_menu_deferral,
)
from tests.test_campaign_codex_keyboard import decision, start
from tests.test_keyboard_clock import boundary, deferred, native_adapter, observed


def modal_boundary(view="topicmeeting", focus=None):
    return {
        **boundary(),
        "viewscreen_type": f"<type: viewscreen_{view}st>",
        "focus": focus or view,
    }


def modal_state(view="topicmeeting"):
    return {**observed(), "viewscreen_type": f"viewscreen_{view}st"}


def modal_receipt(view="topicmeeting"):
    return {
        **deferred(), "schema_version": MODAL_SCHEMA,
        "native_before": modal_boundary(view), "native_after": modal_boundary(view),
    }


@pytest.mark.parametrize("view", ["topicmeeting", "meeting", "textviewer", "layer_stockpile"])
def test_modal_baseline_returns_to_model_without_starting_clock(monkeypatch, view):
    env, calls = native_adapter(monkeypatch)
    env.observe = lambda: modal_state(view)

    def probe(keys, **kwargs):
        calls.append(("probe", keys))
        assert keys == [] and kwargs["year_tick"] == observed()["year_tick"]
        return {"accepted": True, "result": {"native_receipts": [
            {"after": modal_boundary(view)},
        ]}}

    monkeypatch.setattr(adapter, "execute_campaign_keys", probe)
    after, receipt = env.advance(10, modal_state(view))
    assert calls == [("probe", []), ("probe", [])]
    assert receipt == modal_receipt(view)
    assert validate_menu_deferral(
        receipt, requested_ticks=10, before=modal_state(view), after=after,
    ) is None


@pytest.mark.parametrize("view,focus", [
    ("unknown", "meeting"), ("<type: viewscreen>", "dfhack/menu"),
    (None, "meeting"), ([], "meeting"),
    ("<type: viewscreen_topicmeetingst>", ""),
    ("<type: viewscreen_topicmeetingst>", []),
])
def test_unidentified_view_is_not_assumed_to_be_a_modal(view, focus):
    assert deferral_schema({"viewscreen_type": view, "focus": focus}) is None


@pytest.mark.parametrize("field,value", [
    ("schema_version", SCHEMA), ("schema_version", []),
    ("clock_dispatched", True), ("ticks_advanced", 1), ("ticks_advanced", False),
    ("timeout", True), ("requested", True), ("requested", 9),
    ("deferred", False), ("ok", True),
])
def test_modal_receipt_cannot_relabel_an_attempted_clock(field, value):
    receipt = modal_receipt()
    receipt[field] = value
    assert validate_menu_deferral(
        receipt, requested_ticks=10, before=modal_state(), after=modal_state(),
    ) is not None


@pytest.mark.parametrize("field,value", [
    ("year_tick", 124), ("year_tick", True), ("paused", False),
    ("save_name", "other"), ("dfroot", "/other"),
    ("focus", "meeting"), ("viewscreen_type", "<type: viewscreen_meetingst>"),
])
def test_changed_modal_probe_never_commits(field, value):
    receipt = modal_receipt()
    receipt["native_after"][field] = value
    assert validate_menu_deferral(
        receipt, requested_ticks=10, before=modal_state(), after=modal_state(),
    ) is not None


@pytest.mark.parametrize("field,value", [
    ("pause_state", False), ("year_tick", 124), ("year_tick", True),
    ("viewscreen_type", "viewscreen_dwarfmodest"),
])
def test_model_observation_must_match_native_modal_boundary(field, value):
    state = modal_state()
    state[field] = value
    assert validate_menu_deferral(
        modal_receipt(), requested_ticks=10, before=modal_state(), after=state,
    ) is not None


def test_same_screen_key_still_commits_and_next_model_decision_owns_recovery(tmp_path):
    feedback = []

    def callback(screen, memory, previous):
        feedback.append(deepcopy(previous))
        result = decision(screen, memory, previous)
        result["action"]["params"]["keys"] = ["CUSTOM_A"] if not memory else ["OPTION1"]
        return result

    loop = start(tmp_path, callback)
    loop.environment.observe = modal_state
    loop.environment.advance = lambda *args: (modal_state(), modal_receipt())
    first = loop.step()
    assert first["execute"]["accepted"] is True
    assert first["tick_advance"]["clock_dispatched"] is False
    assert loop.at_boundary and not loop.failed
    assert loop.committed_elapsed_ticks == 0 and loop.next_step == 1
    loop.step()
    assert [a["params"]["keys"] for a in loop.environment.actions] == [["CUSTOM_A"], ["OPTION1"]]
    assert feedback[1]["simulation"] == {
        "requested_ticks": 10, "ticks_advanced": 0,
        "deferred": True, "reason": "blocking_native_menu",
    }
    assert loop.agent.usage["dispatched_requests"] == 2
    assert loop.agent.usage["total_tokens"] == 200


def test_historical_baseline_failure_remains_failed(tmp_path):
    loop = start(tmp_path)
    loop.environment.observe = modal_state
    loop.environment.advance = lambda *args: (modal_state(), {
        "ok": False, "requested": 10, "ticks_advanced": 0,
        "error": "interrupt_baseline_invalid", "interrupt_safety_error": True,
    })
    with pytest.raises(ValueError, match="did not finish"):
        loop.step()
    assert loop.failed and not loop.at_boundary
