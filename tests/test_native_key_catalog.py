"""Versioned native keys: full capability without an oversized provider enum."""

import json
from pathlib import Path

import pytest

from fort_gym.bench.agent import keyboard_decision
from fort_gym.bench.agent.standard_input import parse_response, response_schema
from fort_gym.bench.env import campaign_keyboard
from fort_gym.bench.env.native_key_catalog import (
    LEGACY_PROFILE,
    NATIVE_KEYS,
    NATIVE_PROFILE,
    catalog_instructions,
    keys_for_profile,
)
from fort_gym.bench.run.campaign_environment import NativeCampaignEnvironment


def action(keys):
    return dict(
        type="KEYSTROKE", params={"keys": keys}, advance_ticks=0, intent="", memory_update=""
    )


def test_pinned_catalog_is_complete_and_legacy_is_unchanged():
    assert len(NATIVE_KEYS) == 1613
    assert {"D_PAUSE", "HOTKEY_BUILDING_WORKSHOP_CARPENTER", "BUILDJOB_ADD"} <= NATIVE_KEYS
    assert {"STRING_A000", "STRING_A255"} <= NATIVE_KEYS
    assert not {"NONE", "KEYBINDING_COMPLETE", "PAUSE", "BUILDJOB_BED"} & NATIVE_KEYS
    assert len(keys_for_profile(LEGACY_PROFILE)) == 358
    assert "PAUSE" in keys_for_profile(LEGACY_PROFILE)
    assert "D_PAUSE" not in keys_for_profile(LEGACY_PROFILE)
    assert set(catalog_instructions().split()[-1613:]) == NATIVE_KEYS
    with pytest.raises(ValueError):
        keys_for_profile("unknown")


def test_schema_avoids_enum_limit_but_all_native_keys_validate_locally():
    schema = response_schema(max_advance_ticks=2000, control_profile=NATIVE_PROFILE)
    assert schema["properties"]["params"]["properties"]["keys"]["items"] == {"type": "string"}
    for key in NATIVE_KEYS:
        payload = action([key])
        assert (
            parse_response(payload, max_advance_ticks=2000, control_profile=NATIVE_PROFILE)
            == payload
        )


@pytest.mark.parametrize(
    "keys",
    [
        ["PAUSE"],
        ["BUILDJOB_BED"],
        ["NONE"],
        ["KEYBINDING_COMPLETE"],
        ["SELECT", "invalid"],
        [True],
        [["SELECT"]],
        ["SELECT"] * 101,
    ],
)
def test_v2_rejects_wrong_keys_without_repair(keys):
    with pytest.raises(ValueError, match="supported native"):
        parse_response(action(keys), max_advance_ticks=2000, control_profile=NATIVE_PROFILE)


def test_decision_declares_catalog_and_new_profile_without_dispatch(tmp_path, monkeypatch):
    calls = []

    def request(prompt, schema, **kwargs):
        calls.append((prompt, schema))
        return {"response": action(["D_PAUSE"]), "run_directory": str(tmp_path)}

    monkeypatch.setattr(keyboard_decision, "request_decision", request)
    result = keyboard_decision.request_keyboard_decision(
        {"width": 1, "height": 1, "tiles": [[32, 7, 0]]},
        executable=Path("/unused"),
        artifact_root=tmp_path,
        allowance_check=lambda: {},
        control_profile=NATIVE_PROFILE,
    )
    assert result["control_profile"] == NATIVE_PROFILE
    assert result["action"] == action(["D_PAUSE"])
    assert result["native_action_dispatched"] is False
    assert calls[0][0].count("HOTKEY_BUILDING_WORKSHOP_CARPENTER") == 1
    assert "D_PAUSE" not in json.dumps(calls[0][1])


def test_v2_invalid_key_is_rejected_before_native_contact(monkeypatch):
    monkeypatch.setattr(
        campaign_keyboard, "run_lua_file", lambda *a, **k: pytest.fail("native contact")
    )
    for key in ("PAUSE", "BUILDJOB_BED", "NONE", "KEYBINDING_COMPLETE"):
        result = campaign_keyboard.execute_campaign_keys(
            [key],
            expected_dfroot=Path("/unused"),
            year=30,
            year_tick=123,
            control_profile=NATIVE_PROFILE,
        )
        assert result["accepted"] is False
        assert result["result"]["command_mutation"] == "not_attempted"


def test_environment_preserves_v2_profile_on_dispatch(monkeypatch):
    from fort_gym.bench.run import campaign_environment

    env = NativeCampaignEnvironment.__new__(NativeCampaignEnvironment)
    env.control_profile = NATIVE_PROFILE
    env.expected_dfroot = Path("/unused")
    env._verify_runtime = lambda: None
    calls = []
    monkeypatch.setattr(
        campaign_environment,
        "execute_campaign_keys",
        lambda keys, **kwargs: calls.append((keys, kwargs)) or {"accepted": True},
    )
    assert env.apply(action(["D_PAUSE"]), {"year": 30, "year_tick": 123})["accepted"]
    assert calls[0][0] == ["D_PAUSE"]
    assert calls[0][1]["control_profile"] == NATIVE_PROFILE
    assert not env.apply({"type": "BUILD"}, {})["accepted"]
