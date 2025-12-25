"""Action schema definitions and validation utilities for fort-gym."""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, Annotated, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError


def _dump_model(model: BaseModel) -> Dict[str, Any]:
    """Return a JSON-ready representation supporting both Pydantic v1/v2."""

    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True)  # type: ignore[call-arg]
    return model.dict(by_alias=True)


class DigParams(BaseModel):
    """Parameters for DIG actions targeting rectangular designations."""

    area: tuple[int, int, int] = Field(..., description="(x, y, z) coordinates for the dig start.")
    size: tuple[int, int, int] = Field(..., description="(width, height, depth) of the designation.")


class BuildParams(BaseModel):
    """Parameters for BUILD actions."""

    kind: Optional[str] = None
    structure: Optional[Literal["workshop", "furnace", "stockpile"]] = None
    material: Optional[str] = None
    location: Optional[tuple[int, int, int]] = None
    x: Optional[int] = None
    y: Optional[int] = None
    z: int = 0


class OrderParams(BaseModel):
    """Parameters for manager ORDER actions."""

    job: str
    quantity: int = Field(..., ge=1)
    at: Optional[str] = None


class KeystrokeParams(BaseModel):
    """Parameters for KEYSTROKE actions - raw keyboard input."""

    keys: list[str] = Field(..., description="List of interface_key names to send")

    class Config:
        extra = "forbid"


class BaseAction(BaseModel):
    """Base set of properties available across all actions."""

    type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    intent: Optional[str] = Field(default=None, description="Optional short rationale provided by the agent.")
    advance_ticks: int = Field(
        default=0,
        ge=0,
        le=2000,
        description="Number of game ticks to advance after executing this action. 0 = no time passes (stay paused).",
    )

    model_config = {
        "extra": "ignore",
        "populate_by_name": True,
        "use_enum_values": True,
    }


class DigAction(BaseAction):
    type: Literal["DIG"]
    params: DigParams


class BuildAction(BaseAction):
    type: Literal["BUILD"]
    params: BuildParams


class OrderAction(BaseAction):
    type: Literal["ORDER"]
    params: OrderParams


class ZoneAction(BaseAction):
    type: Literal["ZONE"]


class StockpileAction(BaseAction):
    type: Literal["STOCKPILE"]


class AssignAction(BaseAction):
    type: Literal["ASSIGN"]


class AlertAction(BaseAction):
    type: Literal["ALERT"]


class NoteAction(BaseAction):
    type: Literal["NOTE"]


class KeystrokeAction(BaseAction):
    """Raw keystroke input action for direct game control."""
    type: Literal["KEYSTROKE"]
    params: KeystrokeParams


ActionUnion = Annotated[
    Union[
        DigAction,
        BuildAction,
        ZoneAction,
        StockpileAction,
        OrderAction,
        AssignAction,
        AlertAction,
        NoteAction,
        KeystrokeAction,
    ],
    Field(discriminator="type"),
]


class ActionModel(BaseModel):
    action: ActionUnion


ALLOWED_TYPES = {"DIG", "BUILD", "ZONE", "STOCKPILE", "ORDER", "ASSIGN", "ALERT", "NOTE", "KEYSTROKE"}


def parse_action(obj_or_str: Dict[str, Any] | str) -> Dict[str, Any]:
    """Parse raw action payload from JSON string or dict and validate it."""
    if isinstance(obj_or_str, str):
        try:
            payload = json.loads(obj_or_str)
        except JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON action: {exc}") from exc
    elif isinstance(obj_or_str, dict):
        payload = obj_or_str
    else:
        raise TypeError("Action must be JSON string or dict")

    try:
        model = ActionModel(action=payload)
    except ValidationError as exc:
        raise ValueError(exc.errors(include_url=False)) from exc

    normalized = _dump_model(model.action)
    return normalized


def validate_action(state: Dict[str, Any], action: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Lightweight validation ensuring required fields exist before execution."""
    action_type = action.get("type")
    params = action.get("params", {})

    if action_type not in ALLOWED_TYPES:
        return False, f"Unsupported action type: {action_type}"

    if action_type == "DIG":
        if "area" not in params or "size" not in params:
            return False, "DIG action requires area and size"
    if action_type == "BUILD":
        if "kind" in params:
            if any(key not in params for key in ("kind", "x", "y")):
                return False, "BUILD action missing coordinates"
        elif {"structure", "material", "location"} - params.keys():
            return False, "BUILD action missing required fields"
    if action_type == "ORDER":
        if "job" not in params or "quantity" not in params:
            return False, "ORDER action requires job and quantity"
    if action_type == "KEYSTROKE":
        keys = params.get("keys")
        if not keys:
            return False, "KEYSTROKE action requires non-empty keys list"
        if not isinstance(keys, list):
            return False, "KEYSTROKE keys must be a list"
        if len(keys) > 100:
            return False, "KEYSTROKE keys list too long (max 100)"

    map_bounds = state.get("map_bounds")
    location = params.get("location")
    if map_bounds and location:
        if any(coord < 0 for coord in location):
            return False, "Location coordinates must be non-negative"
        if len(map_bounds) == 3 and any(coord >= bound for coord, bound in zip(location, map_bounds)):
            return False, "Location outside map bounds"

    return True, None


def schema_json() -> str:
    """Return the JSON Schema representing the action model."""
    schema = ActionModel.model_json_schema(mode="validation")
    return json.dumps(schema, indent=2)


ACTION_TOOL_SPEC = {
    "name": "submit_action",
    "description": "Emit exactly one fortress action as JSON.",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["DIG", "BUILD", "ZONE", "STOCKPILE", "ORDER", "ASSIGN", "ALERT", "NOTE"],
            },
            "params": {"type": "object"},
            "intent": {"type": "string"},
            "advance_ticks": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2000,
                "default": 0,
                "description": "Game ticks to advance after action. 0 = stay paused.",
            },
        },
        "required": ["type", "params"],
    },
}


system_prompt_v1 = """You are the fortress overseer. One action per step. Never return multiple actions or plans.\nWhen unsure, prefer small, safe actions.\nExamples:\n- DIG: {"type":"DIG","params":{"area":[60,18,0],"size":[5,5,1]}}\n- BUILD: {"type":"BUILD","params":{"kind":"CarpenterWorkshop","x":65,"y":22,"z":0}}\n- ORDER: {"type":"ORDER","params":{"at":"Still","job":"BrewDrink","qty":10}}"""


__all__ = [
    "ActionModel",
    "ACTION_TOOL_SPEC",
    "ALLOWED_TYPES",
    "parse_action",
    "schema_json",
    "system_prompt_v1",
    "validate_action",
]
