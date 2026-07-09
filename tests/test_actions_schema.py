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


def test_keystroke_validation_allows_empty_keys_with_positive_ticks() -> None:
    action = parse_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": []},
            "intent": "let dwarves work without pressing another UI key",
            "advance_ticks": 1500,
        }
    )

    valid, reason = validate_action({}, action)

    assert valid is True
    assert reason is None


def test_keystroke_validation_rejects_empty_keys_without_ticks() -> None:
    action = parse_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": []},
            "intent": "empty UI action",
            "advance_ticks": 0,
        }
    )

    valid, reason = validate_action({}, action)

    assert valid is False
    assert reason == "KEYSTROKE action requires keys unless advance_ticks > 0"


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


def test_action_tool_spec_includes_unsuspend_type() -> None:
    assert "UNSUSPEND" in ACTION_TOOL_SPEC["parameters"]["properties"]["type"]["enum"]


def test_parse_action_accepts_unsuspend_area_and_size() -> None:
    action = parse_action(
        {
            "type": "UNSUSPEND",
            "params": {"area": [101, 98, 177], "size": [1, 1, 1]},
            "intent": "clear the suspended ConstructBuilding job",
            "advance_ticks": 500,
        }
    )

    assert action["type"] == "UNSUSPEND"
    assert action["params"]["area"] == [101, 98, 177]
    assert action["params"]["size"] == [1, 1, 1]


def test_validate_action_rejects_unsuspend_missing_area_or_size() -> None:
    valid, reason = validate_action(
        {}, {"type": "UNSUSPEND", "params": {"area": [101, 98, 177]}}
    )

    assert valid is False
    assert reason == "UNSUSPEND action requires area and size"


def test_action_tool_spec_includes_labor_type() -> None:
    assert "LABOR" in ACTION_TOOL_SPEC["parameters"]["properties"]["type"]["enum"]


def test_parse_action_accepts_labor_unit_labor_enable() -> None:
    action = parse_action(
        {
            "type": "LABOR",
            "params": {"unit_id": 243, "labor": "brewing", "enable": True},
            "intent": "enable brewing so the starved brew job gets taken",
            "advance_ticks": 2000,
        }
    )

    assert action["type"] == "LABOR"
    assert action["params"]["unit_id"] == 243
    assert action["params"]["labor"] == "brewing"
    assert action["params"]["enable"] is True


def test_validate_action_rejects_labor_missing_fields() -> None:
    valid, reason = validate_action(
        {}, {"type": "LABOR", "params": {"unit_id": 243, "labor": "brewing"}}
    )

    assert valid is False
    assert reason == "LABOR action requires unit_id, labor, and enable"


def test_action_tool_spec_includes_farm_type() -> None:
    assert "FARM" in ACTION_TOOL_SPEC["parameters"]["properties"]["type"]["enum"]


def test_parse_action_accepts_farm_with_seasons() -> None:
    action = parse_action(
        {
            "type": "FARM",
            "params": {"building_id": 34, "crop": "RADISH", "seasons": ["spring", "summer"]},
            "intent": "grow radishes in the warm seasons",
            "advance_ticks": 1000,
        }
    )

    assert action["type"] == "FARM"
    assert action["params"]["building_id"] == 34
    assert action["params"]["crop"] == "RADISH"
    assert action["params"]["seasons"] == ["spring", "summer"]


def test_parse_action_accepts_farm_without_seasons() -> None:
    action = parse_action(
        {"type": "FARM", "params": {"building_id": 34, "crop": "clear"}, "advance_ticks": 0}
    )

    assert action["type"] == "FARM"
    assert action["params"]["seasons"] is None


def test_validate_action_rejects_farm_missing_crop() -> None:
    valid, reason = validate_action({}, {"type": "FARM", "params": {"building_id": 34}})

    assert valid is False
    assert reason == "FARM action requires building_id and crop"
