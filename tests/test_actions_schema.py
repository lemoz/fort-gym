from __future__ import annotations

import pytest

from fort_gym.bench.env.actions import (
    ACTION_TOOL_SPEC,
    DigParams,
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


def test_dig_schema_describes_chop_as_rect_bounded() -> None:
    description = DigParams.model_json_schema()["properties"]["kind"]["description"]

    assert "trees inside the rect" in description
    assert "not rect-bounded" not in description


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


def test_action_schema_preserves_structured_plan_review() -> None:
    action = parse_action(
        {
            "type": "WAIT",
            "params": {},
            "objective": "Keep the current shelter plan.",
            "plan_step": "Observe construction progress.",
            "plan_review": {
                "request_id": "5:periodic_5",
                "decision": "continue",
                "prior_objective": "Keep the current shelter plan.",
                "objective": "Keep the current shelter plan.",
                "evidence": ["Fort structure: functional_rooms=1"],
                "reason": "Construction is still moving.",
                "next_step": "Observe construction progress.",
            },
            "advance_ticks": 1000,
        }
    )

    assert action["plan_review"]["decision"] == "continue"
    assert action["plan_review"]["request_id"] == "5:periodic_5"


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


def test_interact_schema_accepts_only_a_semantic_operation_with_zero_ticks() -> None:
    action = parse_action(
        {
            "type": "INTERACT",
            "params": {"operation": "confirm"},
            "intent": "confirm the visible dialog",
            "advance_ticks": 0,
        }
    )

    assert action["params"] == {"operation": "confirm"}
    assert validate_action({}, action) == (True, None)

    topic_action = parse_action(
        {
            "type": "INTERACT",
            "params": {"operation": "finish_topic_meeting"},
            "advance_ticks": 0,
        }
    )
    assert topic_action["params"] == {"operation": "finish_topic_meeting"}
    assert validate_action({}, topic_action) == (True, None)

    visible_option_action = parse_action(
        {
            "type": "INTERACT",
            "params": {"operation": "topic_option_a"},
            "advance_ticks": 0,
        }
    )
    assert visible_option_action["params"] == {"operation": "topic_option_a"}
    assert validate_action({}, visible_option_action) == (True, None)


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (
            {"type": "INTERACT", "params": {"operation": "confirm"}, "advance_ticks": 1},
            "INTERACT action requires advance_ticks == 0",
        ),
        (
            {
                "type": "INTERACT",
                "params": {"operation": "confirm"},
                "advance_ticks": False,
            },
            "INTERACT action requires advance_ticks == 0",
        ),
        (
            {"type": "INTERACT", "params": {"operation": "confirm", "keys": ["SELECT"]}},
            "INTERACT params must contain only operation",
        ),
    ],
)
def test_interact_validation_rejects_time_and_arbitrary_keys(action, reason) -> None:
    assert validate_action({}, action) == (False, reason)


def test_interact_schema_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="operation"):
        parse_action({"type": "INTERACT", "params": {"operation": "escape"}})


@pytest.mark.parametrize("advance_ticks", [None, False, "0", 1])
def test_interact_schema_requires_an_explicit_strict_integer_zero(advance_ticks) -> None:
    payload = {"type": "INTERACT", "params": {"operation": "confirm"}}
    if advance_ticks is not None:
        payload["advance_ticks"] = advance_ticks

    with pytest.raises(ValueError, match="advance_ticks"):
        parse_action(payload)


def test_system_prompt_mentions_single_action() -> None:
    assert "one action per step" in system_prompt_v1.lower()


def test_action_tool_spec_includes_unsuspend_type() -> None:
    assert "UNSUSPEND" in ACTION_TOOL_SPEC["parameters"]["properties"]["type"]["enum"]


def test_action_tool_spec_includes_interact_type() -> None:
    assert "INTERACT" in ACTION_TOOL_SPEC["parameters"]["properties"]["type"]["enum"]


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
    valid, reason = validate_action({}, {"type": "UNSUSPEND", "params": {"area": [101, 98, 177]}})

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
