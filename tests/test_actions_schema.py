from __future__ import annotations

from fort_gym.bench.env.actions import (
    ACTION_TOOL_SPEC,
    parse_action,
    system_prompt_v1,
    validate_action,
)


def test_action_tool_spec_structure() -> None:
    assert ACTION_TOOL_SPEC["name"] == "submit_action"
    params = ACTION_TOOL_SPEC["parameters"]
    assert params["type"] == "object"
    assert "type" in params["properties"]
    assert set(params["required"]) == {"type", "params"}


def test_keystroke_action_preserves_agent_perception_metadata() -> None:
    action = parse_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN"]},
            "intent": "recover to main view",
            "screen_read": {
                "mode": "building_menu",
                "evidence": ["visible building menu"],
                "cursor_or_selection": "workshop category",
                "confidence": "medium",
            },
            "last_action_review": {
                "worked": False,
                "evidence": ["recent outcome changed=none"],
                "mismatch_reason": "expected workshop placement but menu did not advance",
                "should_retry_same_path": False,
            },
            "advance_ticks": 0,
        }
    )

    assert action["screen_read"]["mode"] == "building_menu"
    assert action["last_action_review"]["worked"] is False


def test_keystroke_validation_rejects_empty_key_name() -> None:
    action = parse_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["D_DESIGNATE", ""]},
            "intent": "malformed key sequence",
            "advance_ticks": 0,
        }
    )

    valid, reason = validate_action({}, action)

    assert valid is False
    assert reason == "KEYSTROKE keys must be non-empty strings"


def test_keystroke_validation_rejects_z_level_spam() -> None:
    action = parse_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["CURSOR_UP_Z"] * 11},
            "intent": "overshoot z-level navigation",
            "advance_ticks": 0,
        }
    )

    valid, reason = validate_action({}, action)

    assert valid is False
    assert reason == "KEYSTROKE z-level navigation too long (max 10 per action)"


def test_system_prompt_mentions_single_action() -> None:
    assert "one action per step" in system_prompt_v1.lower()
