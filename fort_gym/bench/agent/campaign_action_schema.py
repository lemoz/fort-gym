"""Opt-in typed response grammar, without selecting or executing gameplay actions.

Historical conditions keep their loose parameter schema. This profile makes the
documented parameter types visible to constrained decoders and requires an explicit
DIG mode. Native execution and its legality checks remain authoritative.
"""

from __future__ import annotations

from copy import deepcopy

LEGACY = "loose_parameters/v1"
TYPED = "typed_native_parameters/v1"


def validate_schema_profile(profile: object) -> str:
    if not isinstance(profile, str) or profile not in {LEGACY, TYPED}:
        raise ValueError("Unsupported local action schema profile")
    return profile


def action_tool(legacy: dict, profile: object = LEGACY, *, allow_view: bool = False) -> dict:
    """Return independent legacy or per-action typed tool definitions."""
    selected = validate_schema_profile(profile)
    tool = deepcopy(legacy)
    if selected == LEGACY:
        return tool
    integer = {"type": "integer"}
    string = {"type": "string"}
    triple = {"type": "array", "items": integer, "minItems": 3, "maxItems": 3}
    params: dict[str, dict] = {
        "DIG": {
            "area": triple,
            "size": triple,
            "kind": {"type": "string", "enum": ["dig", "channel", "chop", "gather"]},
        },
        "BUILD": {"kind": string, **{key: integer for key in ("x", "y", "z", "x2", "y2")}},
        "ORDER": {"job": string, "quantity": {"type": "integer", "minimum": 1, "maximum": 5}},
        "UNSUSPEND": {"area": triple, "size": triple},
        "FARM": {
            "building_id": integer,
            "crop": string,
            "seasons": {
                "type": "array",
                "items": {"type": "string", "enum": ["spring", "summer", "autumn", "winter"]},
            },
        },
        "LABOR": {"unit_id": integer, "labor": string, "enable": {"type": "boolean"}},
        "WAIT": {},
        "INTERACT": {
            "operation": {
                "type": "string",
                "enum": [
                    "confirm",
                    "cancel",
                    "up",
                    "down",
                    "left",
                    "right",
                    "finish_topic_meeting",
                    *[f"topic_option_{letter}" for letter in "abcdefgh"],
                ],
            }
        },
    }
    optional = {"BUILD": {"x2", "y2"}, "FARM": {"seasons"}}
    if allow_view:
        params["VIEW"] = {
            "origin": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
                "minItems": 3,
                "maxItems": 3,
            },
            "size": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 34},
                "minItems": 2,
                "maxItems": 2,
            },
        }
    original = tool["function"]["parameters"]
    kinds = original["properties"]["type"]["enum"]
    if set(kinds) != set(params):
        raise ValueError("Typed schema must cover exactly the existing campaign controls")
    variants = []
    for kind in kinds:
        branch = deepcopy(original)
        branch["properties"]["type"] = {"type": "string", "enum": [kind]}
        branch["properties"]["params"] = {
            "type": "object",
            "properties": deepcopy(params[kind]),
            "required": [key for key in params[kind] if key not in optional.get(kind, set())],
            "additionalProperties": False,
        }
        if kind in {"INTERACT", "VIEW"}:
            branch["properties"]["advance_ticks"]["maximum"] = 0
        variants.append(branch)
    tool["function"]["parameters"] = {"oneOf": variants}
    return tool
