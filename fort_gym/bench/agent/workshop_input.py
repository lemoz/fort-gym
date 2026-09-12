"""Selected-workshop response contract; historical keyboard contracts stay intact."""

from copy import deepcopy

from ..env.display_key_catalog import BINDING_PROFILE
from ..env.workshop_job_profile import ACTION_TYPE, ITEMS, MAX_QUANTITY
from . import standard_input


def response_schema(*, max_advance_ticks: int) -> dict:
    schema = standard_input.response_schema(
        max_advance_ticks=max_advance_ticks, control_profile=BINDING_PROFILE
    )
    props = schema["properties"]
    props["type"]["enum"].append(ACTION_TYPE)
    props["params"] = {"anyOf": [
        props["params"],
        {
            "type": "object",
            "properties": {
                "item": {"type": "string", "enum": list(ITEMS)},
                "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_QUANTITY},
            },
            "required": ["item", "quantity"],
            "additionalProperties": False,
        },
    ]}
    return schema


def parse_envelope(payload: object, *, max_advance_ticks: int) -> dict:
    if isinstance(payload, dict) and payload.get("type") == "KEYSTROKE":
        return standard_input.parse_envelope(
            payload, max_advance_ticks=max_advance_ticks, control_profile=BINDING_PROFILE
        )
    schema = response_schema(max_advance_ticks=max_advance_ticks)
    if (
        not isinstance(payload, dict) or set(payload) != set(schema["required"])
        or payload.get("type") != ACTION_TYPE
        or not isinstance(payload.get("params"), dict)
        or set(payload["params"]) != {"item", "quantity"}
        or not isinstance(payload["params"].get("item"), str)
        or payload["params"]["item"] not in ITEMS
        or type(payload["params"].get("quantity")) is not int
        or not 1 <= payload["params"]["quantity"] <= MAX_QUANTITY
        or type(payload.get("advance_ticks")) is not int
        or not 0 <= payload["advance_ticks"] <= max_advance_ticks
        or any(not isinstance(payload.get(key), str) for key in ("intent", "memory_update"))
    ):
        raise ValueError("Invalid selected-workshop job response")
    return deepcopy(payload)


def parse_response(payload: object, *, max_advance_ticks: int) -> dict:
    action = parse_envelope(payload, max_advance_ticks=max_advance_ticks)
    if action["type"] == "KEYSTROKE":
        return standard_input.parse_response(
            action, max_advance_ticks=max_advance_ticks, control_profile=BINDING_PROFILE
        )
    return action
