"""Exploratory campaign decisions without the historical benchmark review gate.

Reuse provider transport, returned-usage accounting, and checkpointable memory.
Only the action grammar is enforced here; the native executor judges legality.
No model error becomes an agent-selected WAIT or a scripted gameplay repair.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..env.actions import parse_action
from .governed_llm import DFHackGovernedLLMAgent, GOVERNED_ACTION_TYPES, GovernedDecisionError

CAMPAIGN_SYSTEM_PROMPT = """You manage a live Dwarf Fortress fortress over a long campaign.
Choose your own strategy to keep it viable, develop it, and respond to what happens.
One full elapsed game year is a milestone, not a command to stop. There is no scalar
score, mandatory build order, required review wording, or rule forcing you to revise
a plan after a fixed number of steps. Outcomes and costs are recorded for research.

Submit one action through submit_action, with type, params and advance_ticks.
Intent, objective, plan_step and memory_update are optional notes for your own use.
The next observation shows the command result and actual simulation progress.
An accepted command may only designate or queue work; native dwarves perform it
over time. Read the resulting state to decide your next action. You can make mistakes
and attempt recovery. A provider or malformed-command failure is not gameplay.

The current interface exposes these controls, not every Dwarf Fortress feature:
DIG: params {area:[x,y,z],size:[width,height,1],kind:"dig"|"channel"|"chop"|"gather"}.
Coordinates must refer to observed terrain. Eligibility and accessibility are checked
by the existing native controls; a designation does not itself complete digging.
BUILD: params {kind,x,y,z}, optionally x2,y2. Kinds are CarpenterWorkshop, Still,
FarmPlot, Bed, Door, Table, Chair, Wall, Floor. Workshops use a 3x3 footprint;
FarmPlot rectangles are at most 5x5. Wall/Floor rectangles are filled, at most 10
tiles. Placement is within 24 tiles of a citizen or existing building. Native
material, terrain, construction, and furnishing requirements still apply.
ORDER: params {job,quantity}, quantity 1-5. bed,door,table,chair,barrel,bin use a
built CarpenterWorkshop; brew uses a built Still. Native inputs and workers are needed.
UNSUSPEND: params {area:[x,y,z],size:[width,height,1]}, at most 10x10. Re-enables
suspended building jobs in the rectangle; it does not complete them or fix paths.
FARM: params {building_id,crop}, optionally seasons:["spring","summer","autumn","winter"].
Use a crop token offered by that completed plot, or "clear". A crop setting is not
planting or harvesting. The observation reports the native plot and crop facts.
LABOR: params {unit_id,labor,enable:true|false}. Use a labor-eligible citizen.
Supported names: mine, woodcutting, carpentry, masonry, farming, herbalism, brewing,
fishing, construction, cooking. This changes a labor setting, not a unit's position.
WAIT: params {}. Advances simulation by your requested ticks without another command.
INTERACT: params {operation}, with advance_ticks exactly 0. Operations: confirm,
cancel, up, down, left, right, finish_topic_meeting, topic_option_a through topic_option_h.
The observed paused dialog determines legality; topic options require a visible matching
letter. This is not arbitrary command or shell execution.

advance_ticks must be an integer from 0 to the tool's stated maximum. Zero leaves the
simulation paused. Use only the supplied observations as world facts; missing data is
unknown, and stock counts do not by themselves prove production or consumption.
"""

PARAM_FIELDS = {
    "DIG": ("area", "size"),
    "BUILD": ("kind", "x", "y", "z"),
    "ORDER": ("job", "quantity"),
    "UNSUSPEND": ("area", "size"),
    "FARM": ("building_id", "crop"),
    "LABOR": ("unit_id", "labor", "enable"),
    "WAIT": (),
    "INTERACT": ("operation",),
}
OPTIONAL_NOTES = ("intent", "objective", "plan_step", "memory_update")
CAMPAIGN_JSON_INSTRUCTION = (
    "Return one JSON object for submit_action, without Markdown. "
    "Required fields: type, params, advance_ticks. Planning notes are optional."
)


class CampaignActionError(GovernedDecisionError):
    """A model did not produce an executable action grammar within its allowance."""

    terminal_code = "campaign_invalid_action"


class CampaignLLMAgent(DFHackGovernedLLMAgent):
    """Same governed native controls, with an independently versioned decision profile."""

    def __init__(self, *, schema_attempts: int = 3, **kwargs: Any) -> None:
        if type(schema_attempts) is not int or not 1 <= schema_attempts <= 3:
            raise ValueError("Campaign schema attempts must be between one and three")
        self._schema_attempts = schema_attempts
        super().__init__(**kwargs)

    def _action_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "submit_action",
                "description": "Choose one native fortress command and simulation advance.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": list(GOVERNED_ACTION_TYPES)},
                        "params": {
                            "type": "object",
                            "description": "Required fields by action: " + json.dumps(PARAM_FIELDS),
                        },
                        "advance_ticks": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": self._max_advance_ticks,
                            "description": "Native simulation ticks after the command. INTERACT requires 0.",
                        },
                        **{key: {"type": "string"} for key in OPTIONAL_NOTES},
                    },
                    "required": ["type", "params", "advance_ticks"],
                    "additionalProperties": False,
                },
            },
        }

    def _json_action_transport_instruction(self) -> str:
        return CAMPAIGN_JSON_INSTRUCTION

    def _checkpoint_configuration(self) -> dict:
        configuration = super()._checkpoint_configuration()
        configuration.update(
            decision_profile="campaign_action/v1",
            schema_attempts=self._schema_attempts,
            prompt_sha256=hashlib.sha256(CAMPAIGN_SYSTEM_PROMPT.encode()).hexdigest(),
            action_tool_sha256=hashlib.sha256(
                json.dumps(self._action_tool(), sort_keys=True).encode()
            ).hexdigest(),
        )
        return configuration

    def _campaign_action(self, payload: dict) -> dict:
        kind = str(payload.get("type") or "").strip().upper()
        if kind not in PARAM_FIELDS:
            raise ValueError("type must name one of the declared native controls")
        params = payload.get("params")
        if not isinstance(params, dict):
            raise ValueError("params must be an explicit object")
        missing = sorted(set(PARAM_FIELDS[kind]) - set(params))
        if missing:
            raise ValueError(f"{kind} params missing required fields: {', '.join(missing)}")
        ticks = payload.get("advance_ticks")
        if type(ticks) is not int or not 0 <= ticks <= self._max_advance_ticks:
            raise ValueError("advance_ticks must be an explicit integer within the declared limit")
        action = {"type": kind, "params": params, "advance_ticks": ticks}
        # Optional metadata cannot veto a valid native command. Preserve the raw
        # response in the private tool event, but only store supported text notes.
        action.update(
            {key: payload[key] for key in OPTIONAL_NOTES if isinstance(payload.get(key), str)}
        )
        return parse_action(action, max_advance_ticks=self._max_advance_ticks)

    def decide(self, obs_text: str, obs_json: dict) -> dict:
        self._record_previous_outcome(obs_text)
        memory = self._memory.get_context()
        messages = [
            {"role": "system", "content": CAMPAIGN_SYSTEM_PROMPT},
            {"role": "user", "content": f"{memory}\n\n{obs_text}" if memory else obs_text},
        ]
        last_error = "No action object returned"
        for attempt in range(self._schema_attempts):
            # Transport failures propagate. Never synthesize a WAIT decision.
            response = self._create_completion(messages)
            payload = self._extract_tool_payload(response)
            action = None
            if payload is not None:
                try:
                    action = self._campaign_action(payload)
                except (TypeError, ValueError) as error:
                    last_error = str(error)
            else:
                last_error = "No action object returned"
            self._tool_events.append(
                {
                    "tool": "campaign_agent.action_response",
                    "input": {"attempt": attempt + 1},
                    "output": {
                        "payload": payload,
                        "grammar_valid": action is not None,
                        "error": None if action is not None else last_error,
                    },
                }
            )
            if action is not None:
                self._apply_memory_fields(action)
                return self._store_pending(obs_text, action)
            if attempt + 1 < self._schema_attempts:
                messages.append(
                    {
                        "role": "user",
                        "content": "No game action was executed. Correct the action grammar: "
                        + last_error
                        + "\nYour submitted object: "
                        + json.dumps(payload)
                        + "\nReturn one submit_action. You choose the gameplay decision.",
                    }
                )
        raise CampaignActionError(last_error, schema_attempts=self._schema_attempts)
