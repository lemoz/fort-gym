"""Action schema definitions and validation utilities for fort-gym."""

from __future__ import annotations

import hashlib
import json
import re
from json import JSONDecodeError
from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator


def _dump_model(model: BaseModel) -> Dict[str, Any]:
    """Return a JSON-ready representation supporting both Pydantic v1/v2."""

    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True)  # type: ignore[call-arg]
    return model.dict(by_alias=True)


class DigParams(BaseModel):
    """Parameters for DIG actions targeting rectangular designations."""

    area: tuple[int, int, int] = Field(..., description="(x, y, z) coordinates for the dig start.")
    size: tuple[int, int, int] = Field(
        ..., description="(width, height, depth) of the designation."
    )
    kind: Literal["dig", "channel", "chop", "gather"] = Field(
        default="dig",
        description=(
            "Designation kind: 'dig'/'channel' designate the rect; 'chop' designates map "
            "trees inside the rect for felling so woodcutters produce logs over time; "
            "'gather' designates shrub tiles inside the rect for plant gathering so a "
            "dwarf with the herbalism labor collects plants over time."
        ),
    )


class BuildParams(BaseModel):
    """Parameters for BUILD actions."""

    kind: Optional[str] = None
    structure: Optional[Literal["workshop", "furnace", "stockpile"]] = None
    material: Optional[str] = None
    location: Optional[tuple[int, int, int]] = None
    x: Optional[int] = None
    y: Optional[int] = None
    z: int = 0
    x2: Optional[int] = None
    y2: Optional[int] = None


class OrderParams(BaseModel):
    """Parameters for manager ORDER actions."""

    job: str
    quantity: int = Field(..., ge=1)
    at: Optional[str] = None


class UnsuspendParams(BaseModel):
    """Parameters for UNSUSPEND actions targeting a bounded rect."""

    area: tuple[int, int, int] = Field(..., description="(x, y, z) coordinates for the rect start.")
    size: tuple[int, int, int] = Field(
        ..., description="(width, height, 1) of the rect, one z-level, max 10x10."
    )


class LaborParams(BaseModel):
    """Parameters for LABOR actions: flip one labor on one citizen."""

    unit_id: int = Field(..., description="id of the citizen whose labor to flip.")
    labor: str = Field(..., description="Whitelisted labor name, e.g. 'brewing', 'mine'.")
    enable: bool = Field(..., description="True enables the labor, False disables it.")


class FarmParams(BaseModel):
    """Parameters for FARM actions setting a farm plot's seasonal crop.

    ``crop`` is a plant raw token (e.g. "RADISH") or the literal "clear" to
    reset the selected seasons to no crop. ``seasons`` is optional; omitted
    means all four seasons.
    """

    building_id: int = Field(..., description="Farm plot building id to set crops on.")
    crop: str = Field(..., description="Plant raw token or 'clear'.")
    seasons: Optional[list[Literal["spring", "summer", "autumn", "winter"]]] = Field(
        default=None,
        description="Seasons to set; omitted means all four.",
    )


class KeystrokeParams(BaseModel):
    """Parameters for KEYSTROKE actions - raw keyboard input."""

    keys: list[str] = Field(..., description="List of interface_key names to send")

    class Config:
        extra = "forbid"


class InteractParams(BaseModel):
    """Parameters for one bounded paused-interface interaction."""

    operation: Literal[
        "confirm",
        "cancel",
        "up",
        "down",
        "left",
        "right",
        "finish_topic_meeting",
        "topic_option_a",
        "topic_option_b",
        "topic_option_c",
        "topic_option_d",
        "topic_option_e",
        "topic_option_f",
        "topic_option_g",
        "topic_option_h",
    ]

    model_config = {"extra": "forbid"}


class BaseAction(BaseModel):
    """Base set of properties available across all actions."""

    type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    intent: Optional[str] = Field(
        default=None, description="Optional short rationale provided by the agent."
    )
    objective: Optional[str] = Field(
        default=None,
        description="Current gameplay objective this action is meant to advance.",
    )
    expected_visible_result: Optional[str] = Field(
        default=None,
        description="Expected immediate screen, menu, cursor, or map result after the keys are sent.",
    )
    expected_simulation_result: Optional[str] = Field(
        default=None,
        description="Expected dwarf/world result after advancing ticks, if any.",
    )
    screen_read: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Agent's own interpretation of the current DF screen before acting. "
            "This is perception/debug metadata, not gameplay execution."
        ),
    )
    last_action_review: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Agent's own comparison of the previous action intent against the current "
            "screen/state before acting. This is verification metadata, not gameplay execution."
        ),
    )
    memory_update: Optional[str] = Field(
        default=None,
        description="Memory or POI update the agent made or will make around this action.",
    )
    plan_step: Optional[str] = Field(
        default=None,
        description="Current agent-maintained plan step this action is meant to advance.",
    )
    plan_review: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Agent-authored plan review metadata, or a legacy brief summary, used before "
            "this action. This is audit metadata, not gameplay execution."
        ),
    )
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


class UnsuspendAction(BaseAction):
    type: Literal["UNSUSPEND"]
    params: UnsuspendParams


class LaborAction(BaseAction):
    type: Literal["LABOR"]
    params: LaborParams


class FarmAction(BaseAction):
    type: Literal["FARM"]
    params: FarmParams


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


class WaitAction(BaseAction):
    type: Literal["WAIT"]


class KeystrokeAction(BaseAction):
    """Raw keystroke input action for direct game control."""

    type: Literal["KEYSTROKE"]
    params: KeystrokeParams


class InteractAction(BaseAction):
    """One semantic input for a paused interface or dialog."""

    type: Literal["INTERACT"]
    params: InteractParams
    advance_ticks: StrictInt = Field(
        ...,
        description="INTERACT is paused interface input and must explicitly request zero ticks.",
    )

    @field_validator("advance_ticks")
    @classmethod
    def require_zero_ticks(cls, value: int) -> int:
        if value != 0:
            raise ValueError("INTERACT requires advance_ticks == 0")
        return value


ActionUnion = Annotated[
    Union[
        DigAction,
        BuildAction,
        ZoneAction,
        StockpileAction,
        OrderAction,
        UnsuspendAction,
        LaborAction,
        FarmAction,
        AssignAction,
        AlertAction,
        NoteAction,
        WaitAction,
        KeystrokeAction,
        InteractAction,
    ],
    Field(discriminator="type"),
]


class ActionModel(BaseModel):
    action: ActionUnion


ALLOWED_TYPES = {
    "DIG",
    "BUILD",
    "ZONE",
    "STOCKPILE",
    "ORDER",
    "UNSUSPEND",
    "LABOR",
    "FARM",
    "ASSIGN",
    "ALERT",
    "NOTE",
    "WAIT",
    "KEYSTROKE",
    "INTERACT",
}

INTERACT_ALLOWED_VIEWSCREEN_TYPES = frozenset(
    {
        "viewscreen_textviewerst",
        "viewscreen_meetingst",
        "viewscreen_requestagreementst",
        "viewscreen_topicmeeting_fill_land_holder_positionsst",
        "viewscreen_topicmeeting_takerequestsst",
        "viewscreen_topicmeetingst",
        "viewscreen_storesst",
    }
)

BLOCKING_VIEWSCREEN_INTERACT_OPERATIONS = {
    "viewscreen_storesst": frozenset({"cancel"}),
}

FINISH_TOPIC_MEETING_OPTION_TEXT = "a - Finish peeking in on conversation"
TOPIC_MEETING_OPTION_OPERATIONS = frozenset(
    f"topic_option_{letter}" for letter in "abcdefgh"
)


def normalized_action_fingerprint(action: Dict[str, Any]) -> str:
    """Return a stable identifier for an action's execution contract only."""

    params = action.get("params")
    canonical = json.dumps(
        {
            "type": str(action.get("type") or "").strip().upper(),
            "params": params if isinstance(params, dict) else {},
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalized_objective(value: Any) -> str:
    """Normalize model-authored objective identity for continuity checks."""

    return " ".join(str(value or "").split()).casefold()


def visible_topic_meeting_option(operation: str, screen_text: str) -> bool:
    """Return whether the requested lettered topic option is visibly present."""

    if operation not in TOPIC_MEETING_OPTION_OPERATIONS:
        return False
    letter = operation.rsplit("_", 1)[-1]
    return bool(re.search(rf"(?m)^[# ]*{re.escape(letter)}\s*-\s+\S", screen_text or ""))


def blocking_viewscreen_action_reason(
    state: Dict[str, Any], action: Dict[str, Any]
) -> str | None:
    """Require the single attested exit action while a blocking UI is open."""

    viewscreen_type = str(state.get("viewscreen_type") or "unknown")
    allowed_operations = BLOCKING_VIEWSCREEN_INTERACT_OPERATIONS.get(viewscreen_type)
    if allowed_operations is None:
        return None

    params = action.get("params")
    operation = params.get("operation") if isinstance(params, dict) else None
    if (
        action.get("type") == "INTERACT"
        and operation in allowed_operations
        and type(action.get("advance_ticks")) is int
        and action.get("advance_ticks") == 0
    ):
        return None

    operations = " or ".join(sorted(allowed_operations))
    return (
        f"DF viewscreen {viewscreen_type!r} blocks simulation; submit only INTERACT "
        f"{operations} with advance_ticks=0 and wait for a fresh observation"
    )


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
    if action_type == "UNSUSPEND":
        if "area" not in params or "size" not in params:
            return False, "UNSUSPEND action requires area and size"
    if action_type == "LABOR":
        if "unit_id" not in params or "labor" not in params or "enable" not in params:
            return False, "LABOR action requires unit_id, labor, and enable"
    if action_type == "FARM":
        if "building_id" not in params or "crop" not in params:
            return False, "FARM action requires building_id and crop"
        seasons = params.get("seasons")
        if seasons is not None:
            if not isinstance(seasons, list) or any(
                season not in {"spring", "summer", "autumn", "winter"} for season in seasons
            ):
                return False, "FARM seasons must be a list of season names"
    if action_type == "KEYSTROKE":
        keys = params.get("keys")
        if not isinstance(keys, list):
            return False, "KEYSTROKE keys must be a list"
        if not keys:
            advance_ticks = action.get("advance_ticks") or 0
            try:
                advance_ticks_int = int(advance_ticks)
            except (TypeError, ValueError):
                advance_ticks_int = 0
            if advance_ticks_int <= 0:
                return False, "KEYSTROKE action requires keys unless advance_ticks > 0"
            return True, None
        if any(not isinstance(key, str) or not key.strip() for key in keys):
            return False, "KEYSTROKE keys must be non-empty strings"
        if len(keys) > 100:
            return False, "KEYSTROKE keys list too long (max 100)"
        z_level_keys = {"CURSOR_UP_Z", "CURSOR_DOWN_Z"}
        z_level_count = sum(1 for key in keys if str(key) in z_level_keys)
        if z_level_count > 10:
            return False, "KEYSTROKE z-level navigation too long (max 10 per action)"
    if action_type == "INTERACT":
        if not isinstance(params, dict):
            return False, "INTERACT params must be an object"
        if set(params) != {"operation"}:
            return False, "INTERACT params must contain only operation"
        if params.get("operation") not in {
            "confirm",
            "cancel",
            "up",
            "down",
            "left",
            "right",
            "finish_topic_meeting",
            *TOPIC_MEETING_OPTION_OPERATIONS,
        }:
            return False, (
                "INTERACT operation must be confirm, cancel, up, down, left, right, "
                "finish_topic_meeting, or topic_option_a through topic_option_h"
            )
        advance_ticks = action.get("advance_ticks")
        if type(advance_ticks) is not int or advance_ticks != 0:
            return False, "INTERACT action requires advance_ticks == 0"

    map_bounds = state.get("map_bounds")
    location = params.get("location")
    if map_bounds and location:
        if any(coord < 0 for coord in location):
            return False, "Location coordinates must be non-negative"
        if len(map_bounds) == 3 and any(
            coord >= bound for coord, bound in zip(location, map_bounds)
        ):
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
                "enum": [
                    "DIG",
                    "BUILD",
                    "ZONE",
                    "STOCKPILE",
                    "ORDER",
                    "UNSUSPEND",
                    "LABOR",
                    "FARM",
                    "ASSIGN",
                    "ALERT",
                    "NOTE",
                    "WAIT",
                    "INTERACT",
                ],
            },
            "params": {"type": "object"},
            "intent": {"type": "string"},
            "objective": {"type": "string"},
            "expected_visible_result": {"type": "string"},
            "expected_simulation_result": {"type": "string"},
            "screen_read": {"type": "object"},
            "last_action_review": {"type": "object"},
            "memory_update": {"type": "string"},
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


system_prompt_v1 = """You are the fortress overseer. One action per step. Never return multiple actions or plans.\nWhen unsure, prefer small, safe actions.\nExamples:\n- DIG: {"type":"DIG","params":{"area":[50,35,0],"size":[5,5,1]}}\n- BUILD: {"type":"BUILD","params":{"kind":"CarpenterWorkshop","x":65,"y":22,"z":0}}\n- ORDER: {"type":"ORDER","params":{"at":"Still","job":"BrewDrink","qty":10}}"""


__all__ = [
    "ActionModel",
    "ACTION_TOOL_SPEC",
    "ALLOWED_TYPES",
    "BLOCKING_VIEWSCREEN_INTERACT_OPERATIONS",
    "FINISH_TOPIC_MEETING_OPTION_TEXT",
    "INTERACT_ALLOWED_VIEWSCREEN_TYPES",
    "blocking_viewscreen_action_reason",
    "parse_action",
    "schema_json",
    "system_prompt_v1",
    "validate_action",
]
