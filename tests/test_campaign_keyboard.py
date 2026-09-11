from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.env import campaign_keyboard as module
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment


def receipt(mode, key=None):
    state = {
        "dfroot": "/isolated",
        "year": 30,
        "year_tick": 123,
        "save_name": "fixture",
        "paused": True,
    }
    return {
        "schema_version": module.NATIVE_SCHEMA,
        "ok": True,
        "mode": mode,
        "key": key,
        "before": state,
        "after": deepcopy(state),
        "keys_sent": 0 if mode == "probe" else 1,
        "command_mutation": "not_attempted" if mode == "probe" else "completed",
    }


def install(monkeypatch, responses=None):
    calls = []
    responses = iter(responses) if responses is not None else None

    def invoke(hook, mode, root, year, tick, save, *keys, **kwargs):
        calls.append((mode, root, year, tick, save, keys))
        result = (
            next(responses)
            if responses is not None
            else receipt(mode, keys[0] if mode == "key" else None)
        )
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(module, "run_lua_file", invoke)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return calls


def execute(keys):
    return module.execute_campaign_keys(
        keys, expected_dfroot=Path("/isolated"), year=30, year_tick=123
    )


def test_sequence_is_prevalidated_then_each_exact_key_is_dispatched_once(monkeypatch):
    calls = install(monkeypatch)
    result = execute(["SELECT", "PAUSE", "LEAVESCREEN"])
    assert result["accepted"] is True
    assert [call[0] for call in calls] == ["probe", "key", "key", "key"]
    assert calls[0][-1] == ("SELECT", "PAUSE", "LEAVESCREEN")
    assert [call[-1] for call in calls[1:]] == [("SELECT",), ("PAUSE",), ("LEAVESCREEN",)]
    assert all(call[4] == "fixture" for call in calls[1:])
    assert result["result"]["keys_confirmed"] == 3
    assert result["result"]["frame_freshness"] == "not_verified"


def test_empty_keys_only_probe_and_do_not_pick_a_game_action(monkeypatch):
    calls = install(monkeypatch)
    result = execute([])
    assert result["accepted"] and len(calls) == 1
    assert result["result"]["command_mutation"] == "not_attempted"


@pytest.mark.parametrize("keys", [None, "SELECT", [False], ["invented"], ["SELECT"] * 101])
def test_invalid_keys_do_not_contact_runtime(monkeypatch, keys):
    calls = install(monkeypatch)
    assert execute(keys)["accepted"] is False
    assert not calls


def test_unsupported_native_probe_never_sends_first_key(monkeypatch):
    rejection = {**receipt("probe"), "ok": False, "error": "unsupported_native_key"}
    calls = install(monkeypatch, [rejection])
    result = execute(["SELECT", "PAUSE"])
    assert not result["accepted"] and len(calls) == 1
    assert result["result"]["command_mutation"] == "not_attempted"


def test_timeout_after_confirmed_prefix_is_unknown_not_retried(monkeypatch):
    calls = install(
        monkeypatch, [receipt("probe"), receipt("key", "SELECT"), module.DFHackError("timeout")]
    )
    result = execute(["SELECT", "PAUSE", "LEAVESCREEN"])
    assert len(calls) == 3 and not result["accepted"]
    assert result["result"]["keys_confirmed"] == 1
    assert result["result"]["keys_sent"] is None
    assert result["result"]["command_mutation"] == "unknown"


def test_rejection_after_confirmed_prefix_is_partial_not_no_action(monkeypatch):
    rejected = {
        **receipt("key", "PAUSE"),
        "ok": False,
        "command_mutation": "not_attempted",
        "keys_sent": 0,
    }
    install(monkeypatch, [receipt("probe"), receipt("key", "SELECT"), rejected])
    result = execute(["SELECT", "PAUSE"])
    assert result["result"]["keys_confirmed"] == 1
    assert result["result"]["command_mutation"] == "partial"


def test_contradictory_no_dispatch_receipt_remains_unknown(monkeypatch):
    rejected = {**receipt("key", "SELECT"), "ok": False, "command_mutation": "not_attempted"}
    install(monkeypatch, [receipt("probe"), rejected])
    result = execute(["SELECT"])
    assert not result["accepted"]
    assert result["result"]["command_mutation"] == "unknown"
    assert result["result"]["keys_sent"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "probe"},
        {"keys_sent": True},
        {"key": "PAUSE"},
        {"before": None},
        {"after": {"year_tick": 124}},
        {"command_mutation": "not_attempted"},
    ],
)
def test_malformed_key_receipt_is_unknown(monkeypatch, change):
    install(monkeypatch, [receipt("probe"), {**receipt("key", "SELECT"), **change}])
    result = execute(["SELECT"])
    assert not result["accepted"]
    assert result["result"]["command_mutation"] == "unknown"


def test_keyboard_environment_allows_dialog_input_but_not_shortcuts(monkeypatch):
    from fort_gym.bench.run import campaign_environment as env_module

    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env.control_profile = module.KEYBOARD_CONTROL_PROFILE
    env.expected_dfroot = Path("/isolated")
    env._verify_runtime = lambda: None
    calls = []
    monkeypatch.setattr(
        env_module,
        "execute_campaign_keys",
        lambda keys, **kw: calls.append(keys) or {"accepted": True},
    )
    state = {
        "pause_state": True,
        "viewscreen_type": "viewscreen_topicmeetingst",
        "year": 30,
        "year_tick": 123,
    }
    assert env.apply({"type": "KEYSTROKE", "params": {"keys": ["OPTION1"]}}, state)["accepted"]
    assert not env.apply({"type": "ORDER", "params": {"job": "bed"}}, state)["accepted"]
    assert calls == [["OPTION1"]]
