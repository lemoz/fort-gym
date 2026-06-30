"""OpenRouter keystroke agent adapter."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from importlib import import_module
from typing import Any, Dict, List

from .base import Agent, register_agent
from .llm_anthropic import (
    KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
    KEYSTROKE_SYSTEM_PROMPT,
    KEYSTROKE_TOOL_SPEC,
)
from .memory import MemoryManager
from .tools import ToolManager
from ..config import get_settings
from ..env.actions import parse_action

_DEFAULT_TOOLS = object()
_DEFAULT_BASE_URL = object()

PRODUCTION_SCREEN_COMPATIBLE_MODES = {
    "job_list": {
        "job_list",
        "jobs",
        "jobs_screen",
    },
    "manager_required": {
        "manager_required",
        "manager_orders",
        "orders_menu",
        "job_list",
    },
    "nobles_administrators": {
        "nobles_administrators",
        "nobles",
        "nobles_menu",
    },
    "manager_orders": {
        "manager_orders",
        "orders_menu",
        "job_list",
    },
    "manager_new_order_search": {
        "manager_new_order_search",
        "manager_orders",
        "orders_menu",
    },
    "carpenter_workshop_selected": {
        "carpenter_workshop_selected",
        "workshop_menu",
        "workshop_task_menu",
    },
    "carpenter_workshop_construction_pending": {
        "carpenter_workshop_construction_pending",
        "workshop_construction_pending",
        "workshop_menu",
    },
    "workshop_placement": {
        "workshop_placement",
        "building_menu",
    },
    "workshop_material_selection": {
        "workshop_material_selection",
        "material_selection",
    },
    "workshop_add_task_list": {
        "workshop_add_task_list",
        "workshop_task_menu",
        "workshop_menu",
    },
    "building_workshop_type_menu": {
        "building_workshop_type_menu",
        "building_menu",
    },
}

ESCAPE_THEN_ACT_MENU_MODES = {
    "job_list",
    "manager_required",
    "manager_orders",
    "manager_new_order_search",
    "nobles_administrators",
    "carpenter_workshop_selected",
    "carpenter_workshop_construction_pending",
    "workshop_placement",
    "workshop_material_selection",
    "workshop_add_task_list",
    "building_workshop_type_menu",
}


def _openai_tool(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "parameters": spec.get("input_schema") or spec.get("parameters") or {},
        },
    }


def _submit_action_tool(*, require_perception_review: bool) -> Dict[str, Any]:
    tool_spec = deepcopy(KEYSTROKE_TOOL_SPEC)
    if require_perception_review:
        required = list(tool_spec["parameters"].get("required", []))
        for field in (
            "screen_read",
            "last_action_review",
            "advance_ticks",
            "objective",
            "expected_visible_result",
        ):
            if field not in required:
                required.append(field)
        tool_spec["parameters"]["required"] = required
    return _openai_tool(tool_spec)


def _usage_payload(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    payload: Dict[str, int] = {}
    for src, dst in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, src, None)
        if value is not None:
            payload[dst] = int(value)
    return payload


class OpenRouterKeystrokeAgent(Agent):
    """OpenRouter/OpenAI-compatible agent for native DF keystroke gameplay."""

    def __init__(
        self,
        *,
        system_prompt: str = KEYSTROKE_SYSTEM_PROMPT,
        require_memory_review: bool = False,
        require_plan_review: bool = False,
        require_perception_review: bool = False,
        model_override: str | None = None,
        api_key: str | None = None,
        api_key_name: str = "OPENROUTER_API_KEY",
        base_url: str | None | object = _DEFAULT_BASE_URL,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        disable_reasoning: bool | None = None,
        provider_label: str = "openrouter",
    ) -> None:
        self._settings = get_settings()
        self._api_key = api_key if api_key is not None else self._settings.OPENROUTER_API_KEY
        if not self._api_key:
            raise RuntimeError(f"{api_key_name} not configured")
        self._base_url = (
            self._settings.OPENROUTER_BASE_URL if base_url is _DEFAULT_BASE_URL else base_url
        )
        self._timeout_seconds = (
            self._settings.OPENROUTER_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )
        self._max_attempts = (
            self._settings.OPENROUTER_MAX_ATTEMPTS if max_attempts is None else max_attempts
        )
        self._disable_reasoning = (
            self._settings.OPENROUTER_DISABLE_REASONING
            if disable_reasoning is None
            else disable_reasoning
        )
        self._provider_label = provider_label
        self._system_prompt = system_prompt
        self._model = model_override or self._settings.OPENROUTER_MODEL
        self._require_memory_review = require_memory_review
        self._require_plan_review = require_plan_review
        self._require_perception_review = require_perception_review
        self._submit_action_only = not (
            require_memory_review or require_plan_review or require_perception_review
        )
        self._completed_actions = 0
        self._client = None
        self._last_call = 0.0
        self._memory = MemoryManager(window_size=self._settings.MEMORY_WINDOW)
        enabled_tools = ["df_wiki", "remember_poi", "remember_failed_attempt", "query_memory"]
        if require_plan_review:
            enabled_tools.extend(["write_gameplay_plan", "review_gameplay_plan"])
        if require_perception_review:
            enabled_tools.extend(["record_screen_read", "review_last_action"])
        self._tool_manager = ToolManager(enabled_tools, memory=self._memory)
        self._tool_events: List[Dict[str, Any]] = []
        self._last_plain_json_error: str | None = None

    def _client_instance(self):
        if self._client is None:
            try:
                openai_mod = import_module("openai")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("openai package not installed") from exc
            client_cls = getattr(openai_mod, "OpenAI", None)
            if client_cls is None:
                raise RuntimeError("openai.OpenAI client not available")
            client_kwargs: Dict[str, Any] = {
                "api_key": self._api_key,
                "max_retries": 0,
                "timeout": self._timeout_seconds,
            }
            if self._base_url is not None:
                client_kwargs["base_url"] = self._base_url
            self._client = client_cls(**client_kwargs)
        return self._client

    def _rate_limit(self) -> None:
        limit = self._settings.LLM_RATE_LIMIT_TPS
        if limit <= 0:
            return
        interval = 1.0 / limit
        now = time.monotonic()
        wait = interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _tools(self) -> List[Dict[str, Any]]:
        submit_tool = _submit_action_tool(
            require_perception_review=self._require_perception_review
        )
        if self._submit_action_only:
            return [submit_tool]
        return [submit_tool, *[_openai_tool(spec) for spec in self._tool_manager.tool_specs()]]

    def _create_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Dict[str, Any]] | None | object = _DEFAULT_TOOLS,
        tool_choice: Any = _DEFAULT_TOOLS,
    ) -> Any:
        max_attempts = max(1, self._max_attempts)
        last_exc: Exception | None = None
        request_kwargs: Dict[str, Any] = {}
        if self._disable_reasoning:
            request_kwargs["extra_body"] = {
                "reasoning": {"enabled": False, "exclude": True}
            }
        if tools is _DEFAULT_TOOLS:
            request_kwargs["tools"] = self._tools()
        elif tools is not None:
            request_kwargs["tools"] = tools
        if tool_choice is _DEFAULT_TOOLS:
            request_kwargs["tool_choice"] = (
                {"type": "function", "function": {"name": "submit_action"}}
                if self._submit_action_only
                else "auto"
            )
        elif tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice
        for attempt in range(max_attempts):
            try:
                return self._client_instance().chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._settings.LLM_TEMP,
                    max_tokens=self._settings.LLM_MAX_TOKENS,
                    **request_kwargs,
                )
            except Exception as exc:
                last_exc = exc
                will_retry = attempt + 1 < max_attempts
                self._tool_events.append(
                    {
                        "tool": "openrouter.chat.completions.create",
                        "input": {
                            "model": self._model,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "timeout_seconds": self._timeout_seconds,
                        },
                        "output": {
                            "error": type(exc).__name__,
                            "message": str(exc),
                            "retrying": will_retry,
                        },
                    }
                )
                if will_retry:
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
        raise RuntimeError(
            f"{self._provider_label} request failed after {max_attempts} attempts"
        ) from last_exc

    def _gate_error(self, called_tool_names: set[str]) -> str | None:
        if self._require_memory_review and "query_memory" not in called_tool_names:
            return (
                "Mandatory pre-action review missing: call query_memory before "
                "submit_action."
            )
        if self._require_plan_review and self._completed_actions == 0:
            if "write_gameplay_plan" not in called_tool_names:
                return (
                    "Mandatory gameplay plan missing: call write_gameplay_plan before "
                    "the first submit_action."
                )
        if (
            self._require_plan_review
            and self._completed_actions > 0
            and self._completed_actions % 5 == 0
            and "review_gameplay_plan" not in called_tool_names
        ):
            return "Mandatory gameplay plan review missing: call review_gameplay_plan."
        if self._require_perception_review and "record_screen_read" not in called_tool_names:
            return "Mandatory record_screen_read missing before submit_action."
        if self._require_perception_review and "review_last_action" not in called_tool_names:
            return "Mandatory review_last_action missing before submit_action."
        return None

    def _messages(self, obs_text: str, obs_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        memory_context = self._memory.get_context()
        user_text = f"{obs_text}\n\nState JSON:\n{json.dumps(obs_json)}"
        if memory_context:
            user_text += f"\n\nAgent memory:\n{memory_context}"
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_text},
        ]

    @staticmethod
    def _tool_args(tool_call: Any) -> Dict[str, Any]:
        raw = getattr(getattr(tool_call, "function", None), "arguments", None) or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _normalize_action_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        nested = payload.get("action")
        if not isinstance(nested, dict):
            return payload
        if not nested:
            return payload

        normalized = dict(nested)
        for field in (
            "intent",
            "objective",
            "expected_visible_result",
            "expected_simulation_result",
            "screen_read",
            "last_action_review",
            "memory_update",
            "plan_step",
            "plan_review",
            "advance_ticks",
        ):
            if field in payload and field not in normalized:
                normalized[field] = payload[field]
        self._tool_events.append(
            {
                "tool": "action_contract_repaired",
                "input": {"wrapped": "action", "keys": sorted(payload.keys())},
                "output": (
                    "Unwrapped nested submit_action.action into the top-level "
                    "KEYSTROKE action payload expected by fort-gym."
                ),
            }
        )
        return normalized

    @staticmethod
    def _empty_nested_action_error(payload: Dict[str, Any]) -> str | None:
        nested = payload.get("action")
        if isinstance(nested, dict) and not nested:
            return (
                "Invalid submit_action payload: action was an empty object. "
                "Do not wrap the action. Submit a top-level KEYSTROKE payload like "
                '{"type":"KEYSTROKE","params":{"keys":["LEAVESCREEN"]},'
                '"intent":"...","advance_ticks":0}.'
            )
        return None

    @staticmethod
    def _json_payload_from_text(content: Any) -> Dict[str, Any] | None:
        if not isinstance(content, str) or not content.strip():
            return None
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1]).strip()
        decoder = json.JSONDecoder()
        candidates = [text]
        for idx, char in enumerate(text):
            if char == "{":
                candidates.append(text[idx:])
        for candidate in candidates:
            try:
                parsed, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                action = parsed.get("action")
                if isinstance(action, dict):
                    return action
                return parsed
        return None

    @staticmethod
    def _zero_tick_action_says_time_should_pass(tool_payload: Dict[str, Any]) -> bool:
        action_text = " ".join(
            str(tool_payload.get(field) or "")
            for field in (
                "intent",
                "objective",
                "expected_simulation_result",
                "plan_step",
                "plan_review",
                "memory_update",
            )
        ).lower()
        if "advance" in action_text and any(
            marker in action_text
            for marker in (
                "time",
                "tick",
                "large block",
                "significant",
                "dwarf",
                "miner",
                "carpenter",
                "woodcutter",
                "work",
            )
        ):
            return True
        return any(
            phrase in action_text
            for phrase in (
                "advance time",
                "advance simulation",
                "advance ticks",
                "resume time",
                "simulation time",
                "time passes",
                "let dwarves",
                "let woodcutters",
                "let miners",
                "let carpenter",
                "let production",
                "give dwarves time",
                "dwarves work",
                "produce beds",
                "production happen",
                "works the queued",
                "execute existing",
            )
        )

    @classmethod
    def _advance_ticks_repair_for_action_only(
        cls,
        tool_payload: Dict[str, Any],
        contract_error: str,
    ) -> int | None:
        if "pure LEAVESCREEN" in contract_error:
            return 0
        if "completes a dig/chop/stair designation" in contract_error:
            return 500
        if cls._zero_tick_action_says_time_should_pass(tool_payload):
            return 500
        return None

    @classmethod
    def _advance_ticks_contract_error(cls, tool_payload: Dict[str, Any]) -> str | None:
        try:
            advance_ticks = int(tool_payload.get("advance_ticks", 0))
        except (TypeError, ValueError):
            return None

        params = tool_payload.get("params") if isinstance(tool_payload.get("params"), dict) else {}
        keys = params.get("keys") if isinstance(params, dict) else []
        keys = keys if isinstance(keys, list) else []
        if keys and all(str(key) == "LEAVESCREEN" for key in keys):
            if advance_ticks > 0:
                return (
                    "Action contract mismatch: pure LEAVESCREEN menu recovery "
                    "must use advance_ticks 0. Escaping screens is UI navigation, "
                    "not simulation time."
                )
            return None
        if advance_ticks > 0:
            return None
        if any(str(key) == "STRING_A032" for key in keys):
            return (
                "Action contract mismatch: STRING_A032 with advance_ticks 0 "
                "does not advance simulation time in this runner. If you need "
                "dwarves to work, set advance_ticks to a positive value such "
                "as 500, 1000, or 2000; for UI-only actions, remove STRING_A032."
            )

        action_text = " ".join(
            str(tool_payload.get(field) or "")
            for field in (
                "intent",
                "objective",
                "expected_simulation_result",
                "plan_step",
                "plan_review",
                "memory_update",
            )
        ).lower()
        scroll_only = bool(keys) and all(str(key).startswith("STANDARDSCROLL") for key in keys)
        expected_simulation_text = str(
            tool_payload.get("expected_simulation_result") or ""
        ).lower()
        explicitly_ui_only = any(
            phrase in expected_simulation_text
            for phrase in (
                "no simulation",
                "no simulation time",
                "no time passes",
                "ui navigation",
                "ui mode",
                "menu navigation",
                "mode change",
            )
        )
        if not explicitly_ui_only and (
            cls._zero_tick_action_says_time_should_pass(tool_payload)
            or (scroll_only and "advance" in action_text)
        ):
            return (
                "Action contract mismatch: the action says to advance time or let "
                "dwarves work, but advance_ticks is 0. Set advance_ticks to a "
                "positive value such as 200, 500, 1000, or 2000; viewport scroll "
                "keys do not advance simulation time."
            )

        designation_keys = {
            "DESIGNATE_DIG",
            "DESIGNATE_CHOP",
            "DESIGNATE_CHANNEL",
            "DESIGNATE_STAIR_DOWN",
            "DESIGNATE_STAIR_UP",
            "DESIGNATE_STAIR_UPDOWN",
            "DESIGNATE_RAMP",
            "DESIGNATE_PLANTS",
        }
        completed_work_designation = (
            (
                any(str(key) in designation_keys for key in keys)
                or (
                    any(
                        phrase in action_text
                        for phrase in (
                            "designate",
                            "dig room",
                            "dig area",
                            "chop",
                            "stair",
                            "mine",
                            "mining",
                        )
                    )
                    and len(keys) >= 3
                )
            )
            and sum(1 for key in keys if str(key) == "SELECT") >= 2
            and any(str(key) == "LEAVESCREEN" for key in keys)
        )
        if completed_work_designation:
            return (
                "Action contract mismatch: this key sequence completes a dig/chop/stair "
                "designation while the game is paused, but advance_ticks is 0. Set "
                "advance_ticks to 500+ so dwarves can act on the new designation before "
                "your next decision."
            )
        return None

    def _repair_missing_keystroke_type(
        self,
        tool_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if tool_payload.get("type") is not None:
            return tool_payload
        params = tool_payload.get("params")
        keys = params.get("keys") if isinstance(params, dict) else None
        if keys is None and isinstance(tool_payload.get("keys"), list):
            keys = tool_payload.get("keys")
        if not isinstance(keys, list) or not keys:
            repaired_escape = self._repair_review_only_escape_action(tool_payload)
            if repaired_escape is None:
                return tool_payload
            return repaired_escape
        repaired = dict(tool_payload)
        repaired.pop("keys", None)
        repaired["type"] = "KEYSTROKE"
        repaired["params"] = {"keys": keys}
        self._tool_events.append(
            {
                "tool": "action_contract_repaired",
                "input": {
                    "missing": "type",
                    "inferred_type": "KEYSTROKE",
                    "keys": keys[:10],
                },
                "output": (
                    "Inserted type=KEYSTROKE because the payload contained "
                    "params.keys and otherwise matched the keystroke action contract."
                ),
            }
        )
        return repaired

    def _repair_review_only_escape_action(
        self,
        tool_payload: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        """Recover when a model submits a review but omits executable keys.

        GLM sometimes correctly diagnoses that it is stuck in a menu, then
        returns only review fields instead of the required KEYSTROKE action.
        If the stated intent is a conservative screen escape back to the main
        map, we can safely turn it into LEAVESCREEN presses instead of ending
        the run.
        """

        intent_text = " ".join(
            str(tool_payload.get(field) or "")
            for field in (
                "intent",
                "objective",
                "expected_visible_result",
                "expected_simulation_result",
                "memory_update",
            )
        ).lower()
        review = tool_payload.get("last_action_review")
        if isinstance(review, dict):
            intent_text += " " + " ".join(
                str(review.get(field) or "")
                for field in ("mismatch_reason", "worked", "should_retry_same_path")
            ).lower()
            evidence = review.get("evidence")
            if isinstance(evidence, list):
                intent_text += " " + " ".join(str(item) for item in evidence).lower()

        wants_escape = any(
            phrase in intent_text
            for phrase in (
                "exit the current",
                "exit current",
                "return to the main map",
                "get back to the main map",
                "back to main map",
                "leave the unit info",
                "unit info screen",
            )
        )
        if not wants_escape:
            return None

        repaired = dict(tool_payload)
        repaired["type"] = "KEYSTROKE"
        repaired["params"] = {"keys": ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]}
        repaired["advance_ticks"] = 0
        self._tool_events.append(
            {
                "tool": "action_contract_repaired",
                "input": {
                    "missing": "type_and_keys",
                    "intent": tool_payload.get("intent"),
                },
                "output": (
                    "Inserted a conservative LEAVESCREEN recovery action because "
                    "the payload diagnosed a stuck menu/unit-info screen but "
                    "omitted executable keystroke keys."
                ),
            }
        )
        return repaired

    def _repair_action_only_contract(
        self,
        tool_payload: Dict[str, Any],
        contract_error: str,
    ) -> Dict[str, Any] | None:
        repaired_advance_ticks = self._advance_ticks_repair_for_action_only(
            tool_payload,
            contract_error,
        )
        if repaired_advance_ticks is None:
            return None
        repaired = dict(tool_payload)
        repaired["advance_ticks"] = repaired_advance_ticks
        self._tool_events.append(
            {
                "tool": "advance_ticks_contract_repaired",
                "input": {"contract_error": contract_error},
                "output": (
                    "Set advance_ticks="
                    f"{repaired_advance_ticks} during OpenRouter "
                    "recovery to match the model's stated turn intent."
                ),
            }
        )
        return repaired

    def _repair_menu_loop_recovery_action(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        recent = obs_json.get("recent_progress_summary")
        if not isinstance(recent, dict):
            return tool_payload
        if not recent.get("do_not_repeat_menu_path"):
            return tool_payload
        if recent.get("escape_recovery_attempted"):
            return tool_payload

        params = tool_payload.get("params") if isinstance(tool_payload.get("params"), dict) else {}
        keys = params.get("keys") if isinstance(params, dict) else []
        if isinstance(keys, list) and keys and all(str(key) == "LEAVESCREEN" for key in keys):
            return tool_payload

        repaired = dict(tool_payload)
        repaired["type"] = "KEYSTROKE"
        repaired["params"] = {"keys": ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]}
        repaired["advance_ticks"] = 0
        repaired["intent"] = (
            "Recover from repeated no-progress menu loop by escaping to a "
            "verified main-map screen before choosing another route."
        )
        self._tool_events.append(
            {
                "tool": "menu_loop_recovery_repaired",
                "input": {
                    "repeated_menu_family": recent.get("repeated_menu_family"),
                    "repeated_key_fingerprint": recent.get("repeated_key_fingerprint"),
                    "submitted_keys": keys,
                },
                "output": (
                    "Replaced compound menu action with LEAVESCREEN-only recovery "
                    "because do_not_repeat_menu_path was true and no clean escape "
                    "observation had happened yet."
                ),
            }
        )
        return repaired

    def _repair_metadata_dict_fields(
        self,
        tool_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        repaired: Dict[str, Any] | None = None
        repaired_fields: Dict[str, str] = {}
        for field in ("screen_read", "last_action_review"):
            value = tool_payload.get(field)
            if value is None or isinstance(value, dict):
                continue
            if repaired is None:
                repaired = dict(tool_payload)
            repaired[field] = {"evidence": [str(value)]}
            repaired_fields[field] = type(value).__name__

        if repaired is None:
            return tool_payload

        self._tool_events.append(
            {
                "tool": "action_contract_repaired",
                "input": {"metadata_fields": repaired_fields},
                "output": (
                    "Converted non-dict perception/review metadata into evidence "
                    "dictionaries so malformed debug metadata does not discard "
                    "an otherwise valid keystroke action."
                ),
            }
        )
        return repaired

    @staticmethod
    def _keystroke_keys(tool_payload: Dict[str, Any]) -> List[Any]:
        params = (
            tool_payload.get("params")
            if isinstance(tool_payload.get("params"), dict)
            else {}
        )
        keys = params.get("keys") if isinstance(params, dict) else []
        return keys if isinstance(keys, list) else []

    @classmethod
    def _screen_read_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        expected_mode = str(screen_state.get("mode") or "").strip().lower()
        if not expected_mode or str(screen_state.get("confidence") or "") != "high":
            return None

        allowed = PRODUCTION_SCREEN_COMPATIBLE_MODES.get(expected_mode)
        if not allowed:
            return None

        keys = cls._keystroke_keys(tool_payload)
        if keys and all(str(key) == "LEAVESCREEN" for key in keys):
            return None

        screen_read = (
            tool_payload.get("screen_read")
            if isinstance(tool_payload.get("screen_read"), dict)
            else {}
        )
        submitted_mode = str(screen_read.get("mode") or "").strip().lower()
        if submitted_mode in allowed:
            return None

        return (
            "Screen-read contract mismatch: observation classified the visible "
            f"screen as {expected_mode}, but submit_action.screen_read.mode was "
            f"{submitted_mode or 'missing'}. Before sending non-escape keys from "
            "manager/workshop production screens, set screen_read.mode to the "
            "visible screen you are acting from and cite screen evidence. If you "
            "disagree with the classifier, explain the stronger visible evidence "
            "in screen_read.evidence."
        )

    def _repair_missing_screen_read_from_classifier(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return tool_payload

        expected_mode = str(screen_state.get("mode") or "").strip().lower()
        if (
            not expected_mode
            or str(screen_state.get("confidence") or "") != "high"
            or expected_mode not in PRODUCTION_SCREEN_COMPATIBLE_MODES
        ):
            return tool_payload

        keys = self._keystroke_keys(tool_payload)
        if keys and all(str(key) == "LEAVESCREEN" for key in keys):
            return tool_payload

        existing_screen_read = tool_payload.get("screen_read")
        if isinstance(existing_screen_read, dict) and str(
            existing_screen_read.get("mode") or ""
        ).strip():
            return tool_payload

        repaired_screen_read = (
            dict(existing_screen_read) if isinstance(existing_screen_read, dict) else {}
        )
        repaired_screen_read["mode"] = expected_mode
        repaired_screen_read.setdefault("confidence", "high")
        evidence = screen_state.get("evidence")
        if isinstance(evidence, list) and evidence and not repaired_screen_read.get(
            "evidence"
        ):
            repaired_screen_read["evidence"] = [str(item) for item in evidence[:5]]
        highlighted = screen_state.get("highlighted")
        if highlighted and not repaired_screen_read.get("cursor_or_selection"):
            repaired_screen_read["cursor_or_selection"] = str(highlighted)

        repaired = dict(tool_payload)
        repaired["screen_read"] = repaired_screen_read
        self._tool_events.append(
            {
                "tool": "screen_read_contract_repaired",
                "input": {
                    "screen_state": screen_state,
                    "submitted_keys": self._keystroke_keys(tool_payload),
                },
                "output": (
                    "Inserted missing submit_action.screen_read from the "
                    "high-confidence observation classifier; keystroke keys were "
                    "left unchanged."
                ),
            }
        )
        return repaired

    def _log_screen_read_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        screen_state = obs_json.get("screen_state")
        screen_read = (
            tool_payload.get("screen_read")
            if isinstance(tool_payload.get("screen_read"), dict)
            else {}
        )
        self._tool_events.append(
            {
                "tool": "screen_read_contract_rejected",
                "input": {
                    "screen_state": screen_state,
                    "screen_read_mode": screen_read.get("mode"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                },
                "output": error,
            }
        )

    @classmethod
    def _compound_menu_escape_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        expected_mode = str(screen_state.get("mode") or "").strip().lower()
        if (
            not expected_mode
            or expected_mode not in ESCAPE_THEN_ACT_MENU_MODES
            or str(screen_state.get("confidence") or "") != "high"
        ):
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        if not keys:
            return None

        saw_escape = False
        for key in keys:
            if key == "LEAVESCREEN":
                saw_escape = True
                continue
            if saw_escape:
                return (
                    "Compound menu escape contract mismatch: observation classified "
                    f"the visible screen as {expected_mode}. From a high-confidence "
                    "production/menu screen, do not combine LEAVESCREEN with a "
                    "later non-escape command in one turn. First submit only "
                    "LEAVESCREEN keys with advance_ticks=0, then wait for the next "
                    "observation to confirm the screen before pressing D_NOBLES, "
                    "D_JOBLIST, D_BUILDJOB, D_BUILDING, cursor keys, or SELECT."
                )
        return None

    def _log_compound_menu_escape_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "compound_menu_escape_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                },
                "output": error,
            }
        )

    @staticmethod
    def _int_value(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _selected_workshop_wait_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        mode = str(screen_state.get("mode") or "").strip().lower()
        if mode != "carpenter_workshop_selected":
            return None
        if str(screen_state.get("confidence") or "") != "high":
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        if "BUILDJOB_ADD" in keys:
            return None

        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        waits = advance_ticks > 0 or any(key == "STRING_A032" for key in keys)
        if not waits:
            return None

        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        has_queued_or_active_work = any(
            cls._int_value(work.get(field)) > 0
            for field in (
                "manager_orders_count",
                "manager_orders_amount_left",
                "active_jobs",
            )
        )
        if has_queued_or_active_work:
            return None

        return (
            "Selected-workshop contract mismatch: the visible screen is an "
            "existing Carpenter's Workshop, but no manager order, workshop job, "
            "or active job is queued. Do not leave the workshop and wait. From "
            "this screen, use BUILDJOB_ADD with advance_ticks=0 to open the "
            "native add-task list, then select a concrete visible task before "
            "advancing time."
        )

    def _log_selected_workshop_wait_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "selected_workshop_wait_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "work": obs_json.get("work"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @classmethod
    def _workshop_select_transition_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        mode = str(screen_state.get("mode") or "").strip().lower()
        if mode not in {"workshop_placement", "workshop_material_selection"}:
            return None
        if str(screen_state.get("confidence") or "") != "high":
            return None

        target_setup = obs_json.get("ui_target_setup")
        recommended_keys = []
        if isinstance(target_setup, dict):
            raw_recommended = target_setup.get("recommended_keys")
            if isinstance(raw_recommended, list):
                recommended_keys = [str(key) for key in raw_recommended]
        should_force_select = recommended_keys == ["SELECT"]

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        if keys != ["SELECT"]:
            if not should_force_select:
                return None
            return (
                "Workshop select transition contract mismatch: the visible "
                f"screen is {mode} and the current workshop target recommends "
                "SELECT. Do not leave this ready placement/material screen or "
                "open another menu. Submit SELECT with advance_ticks=0."
            )
        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        if advance_ticks == 0:
            return None

        return (
            "Workshop select transition contract mismatch: the visible screen "
            f"is {mode}, where SELECT is still a paused UI/menu transition. "
            "Submit SELECT with advance_ticks=0. Let time pass only after a "
            "later observation proves a workshop construction job, usable "
            "workshop, task job, manager order, or active job exists."
        )

    def _log_workshop_select_transition_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "workshop_select_transition_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @classmethod
    def _workshop_add_task_list_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        mode = str(screen_state.get("mode") or "").strip().lower()
        if mode != "workshop_add_task_list":
            return None
        if str(screen_state.get("confidence") or "") != "high":
            return None

        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        has_queued_or_active_work = any(
            cls._int_value(work.get(field)) > 0
            for field in (
                "carpenter_workshop_task_jobs",
                "manager_orders_count",
                "manager_orders_amount_left",
                "active_carpenter_jobs",
                "active_jobs",
            )
        )
        if has_queued_or_active_work:
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        key_set = set(keys)
        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0

        blocked_keys = {
            "BUILDJOB_ADD",
            "D_BUILDJOB",
            "D_BUILDING",
            "D_JOBLIST",
            "D_NOBLES",
            "UNITJOB_MANAGER",
            "MANAGER_NEW_ORDER",
            "LEAVESCREEN",
            "STRING_A097",
        }
        if (
            advance_ticks == 0
            and "SELECT" in key_set
            and not key_set.intersection(blocked_keys)
        ):
            return None

        return (
            "Workshop add-task-list contract mismatch: the visible screen is "
            "the Carpenter's Workshop task list and no workshop task, manager "
            "order, or active job is queued yet. Do not press BUILDJOB_ADD, raw "
            "letter keys such as STRING_A097, job/manager routes, LEAVESCREEN, "
            "or wait from this screen. Submit SELECT with advance_ticks=0 to "
            "choose the highlighted visible task row; use only STANDARDSCROLL "
            "keys before SELECT if the current screen_read evidence names a "
            "different highlighted row you need."
        )

    def _log_workshop_add_task_list_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "workshop_add_task_list_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "work": obs_json.get("work"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @classmethod
    def _pending_workshop_construction_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        mode = str(screen_state.get("mode") or "").strip().lower()
        if mode != "carpenter_workshop_construction_pending":
            return None
        if str(screen_state.get("confidence") or "") != "high":
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        if "BUILDJOB_ADD" in keys:
            return (
                "Pending-workshop construction contract mismatch: the visible "
                "Carpenter's Workshop screen says construction is still pending. "
                "BUILDJOB_ADD only works on a usable workshop task menu; it will "
                "not queue production from a Waiting for construction / Needs "
                "Carpentry screen. First solve or record the construction blocker "
                "using visible evidence, or exit with LEAVESCREEN before choosing "
                "another route."
            )

        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        waits = advance_ticks > 0 or any(key == "STRING_A032" for key in keys)
        if not waits:
            return None

        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        construction_jobs = cls._int_value(work.get("carpenter_workshop_construction_jobs"))
        active_construct_jobs = cls._int_value(work.get("active_construct_building_jobs"))
        active_jobs = cls._int_value(work.get("active_jobs"))
        if construction_jobs > 0 or active_construct_jobs > 0 or active_jobs > 0:
            return None

        return (
            "Pending-workshop construction contract mismatch: this screen is "
            "waiting for construction, but work metrics show no construction job "
            "or active job to wait on. Do not blindly advance time from here; "
            "record the blocker, inspect jobs/labors if visible, or exit to a "
            "verified main-map screen and choose another productive route."
        )

    @classmethod
    def _queued_workshop_construction_route_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        planned = cls._int_value(work.get("carpenter_workshops_planned"))
        if planned <= 0:
            planned = cls._int_value(work.get("carpenter_workshops"))
        usable = cls._int_value(work.get("carpenter_workshops_usable"))
        task_jobs = cls._int_value(work.get("carpenter_workshop_task_jobs"))
        construction_jobs = cls._int_value(work.get("carpenter_workshop_construction_jobs"))
        active_construct_jobs = cls._int_value(work.get("active_construct_building_jobs"))
        if (
            planned <= 0
            or usable > 0
            or task_jobs > 0
            or (construction_jobs <= 0 and active_construct_jobs <= 0)
        ):
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        screen_state = obs_json.get("screen_state")
        mode = (
            str(screen_state.get("mode") or "").strip().lower()
            if isinstance(screen_state, dict)
            else ""
        )

        if keys and all(key == "LEAVESCREEN" for key in keys) and advance_ticks == 0:
            return None
        if not keys and advance_ticks >= 1000:
            return None
        if "D_BUILDJOB" in keys:
            return None
        if mode in ESCAPE_THEN_ACT_MENU_MODES:
            return (
                "Queued-workshop construction route mismatch: a Carpenter's "
                "Workshop construction job is already queued, and the visible "
                f"screen is {mode}. Do not combine this menu with another route. "
                "Submit only LEAVESCREEN with advance_ticks=0, then wait for "
                "the next observation."
            )
        return (
            "Queued-workshop construction route mismatch: a Carpenter's Workshop "
            "construction job is already queued. Do not dig, chop, open D_BUILDING, "
            "D_NOBLES, manager orders, or place another workshop. From the main "
            "map, use a KEYSTROKE action with params.keys=[] and advance_ticks "
            ">= 1000 so the carpenter can build it; use D_BUILDJOB only if you "
            "are explicitly inspecting the placed workshop after time fails."
        )

    def _log_queued_workshop_construction_route_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "queued_workshop_construction_route_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "work": obs_json.get("work"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @classmethod
    def _queued_workshop_task_route_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        task_jobs = cls._int_value(work.get("carpenter_workshop_task_jobs"))
        usable = cls._int_value(work.get("carpenter_workshops_usable"))
        manager_orders = cls._int_value(work.get("manager_orders_count"))
        if task_jobs <= 0 or usable <= 0 or manager_orders > 0:
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        key_set = set(keys)
        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        screen_state = obs_json.get("screen_state")
        mode = (
            str(screen_state.get("mode") or "").strip().lower()
            if isinstance(screen_state, dict)
            else ""
        )
        target_setup = (
            obs_json.get("ui_target_setup")
            if isinstance(obs_json.get("ui_target_setup"), dict)
            else {}
        )
        target_mode = str(target_setup.get("target_mode") or "").strip().lower()

        if keys and all(key == "LEAVESCREEN" for key in keys) and advance_ticks == 0:
            return None
        if mode == "main_map" and not keys and advance_ticks == 0:
            return None
        if mode == "main_map" and not keys and advance_ticks >= 1000:
            return None
        if mode == "main_map" and keys == ["D_JOBLIST"] and advance_ticks == 0:
            return None
        if (
            mode == "main_map"
            and "D_BUILDJOB" in key_set
            and target_mode == "existing_workshop"
            and advance_ticks == 0
            and key_set.issubset({"D_BUILDJOB"})
        ):
            return None
        if mode == "job_list" and not keys and advance_ticks == 0:
            return None

        unrelated_keys = {
            "D_DESIGNATE",
            "DESIGNATE_DIG",
            "DESIGNATE_CHOP",
            "D_BUILDING",
            "HOTKEY_BUILDING_WORKSHOP",
            "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
            "D_NOBLES",
            "UNITJOB_MANAGER",
            "MANAGER_NEW_ORDER",
            "D_STOCKPILES",
            "D_CIVZONE",
        }
        duplicate_task_keys = {"BUILDJOB_ADD", "SELECT"}
        if key_set.intersection(unrelated_keys | duplicate_task_keys) or advance_ticks < 1000:
            return (
                "Queued-workshop-task route mismatch: a real carpenter workshop "
                "task is already queued on a usable workshop, but no produced item "
                "or active carpenter job has been proven yet. Keep the run anchored "
                "to the existing workshop/task state. From the main map, either use "
                "params.keys=[] with advance_ticks >= 1000 to let dwarves work, use "
                "D_JOBLIST to inspect job/cancellation evidence, or use D_BUILDJOB "
                "only when ui_target_setup.target_mode is existing_workshop. Do not "
                "dig/chop, open D_BUILDING, D_NOBLES, manager orders, BUILDJOB_ADD, "
                "or SELECT another task until this queued task starts, completes, "
                "or shows a visible blocker."
            )
        return None

    def _log_queued_workshop_task_route_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "queued_workshop_task_route_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "ui_target_setup": obs_json.get("ui_target_setup"),
                    "work": obs_json.get("work"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @classmethod
    def _existing_workshop_production_route_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        target_setup = (
            obs_json.get("ui_target_setup")
            if isinstance(obs_json.get("ui_target_setup"), dict)
            else {}
        )
        target_mode = str(target_setup.get("target_mode") or "").strip().lower()
        if target_mode != "existing_workshop":
            return None

        work = obs_json.get("work") if isinstance(obs_json.get("work"), dict) else {}
        stocks = obs_json.get("stocks") if isinstance(obs_json.get("stocks"), dict) else {}
        usable = cls._int_value(work.get("carpenter_workshops_usable"))
        wood = cls._int_value(stocks.get("wood"))
        if usable <= 0 or wood <= 0:
            return None

        already_working = any(
            cls._int_value(work.get(field)) > 0
            for field in (
                "carpenter_workshop_task_jobs",
                "active_carpenter_jobs",
                "active_jobs",
                "carpenter_workshop_construction_jobs",
                "manager_orders_count",
                "manager_orders_amount_left",
            )
        )
        if already_working:
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        key_set = set(keys)
        try:
            advance_ticks = int(tool_payload.get("advance_ticks") or 0)
        except (TypeError, ValueError):
            advance_ticks = 0
        screen_state = obs_json.get("screen_state")
        mode = (
            str(screen_state.get("mode") or "").strip().lower()
            if isinstance(screen_state, dict)
            else ""
        )

        if keys and all(key == "LEAVESCREEN" for key in keys) and advance_ticks == 0:
            return None
        if (
            mode == "main_map"
            and keys == ["D_BUILDJOB"]
            and advance_ticks == 0
        ):
            return None
        if (
            mode == "carpenter_workshop_selected"
            and keys == ["BUILDJOB_ADD"]
            and advance_ticks == 0
        ):
            return None
        if mode == "workshop_add_task_list":
            return None

        unrelated_keys = {
            "D_DESIGNATE",
            "DESIGNATE_DIG",
            "DESIGNATE_STAIR_DOWN",
            "DESIGNATE_CHOP",
            "D_BUILDING",
            "HOTKEY_BUILDING_WORKSHOP",
            "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
            "D_JOBLIST",
            "D_NOBLES",
            "UNITJOB_MANAGER",
            "MANAGER_NEW_ORDER",
            "D_STOCKPILES",
            "D_CIVZONE",
        }
        if key_set.intersection(unrelated_keys) or advance_ticks > 0:
            return (
                "Existing-workshop production route mismatch: a usable "
                "Carpenter's Workshop exists, wood is available, and no "
                "workshop task or active job is currently queued. Keep the "
                "run anchored to the existing_workshop target. From the main "
                "map, use D_BUILDJOB with advance_ticks=0; from the selected "
                "workshop, use BUILDJOB_ADD with advance_ticks=0; from the "
                "add-task list, select a concrete visible wooden task. Do not "
                "dig/chop, open D_BUILDING, D_JOBLIST, D_NOBLES, manager "
                "orders, stockpiles, or wait with positive ticks until a real "
                "task exists."
            )
        return None

    def _log_existing_workshop_production_route_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "existing_workshop_production_route_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "ui_target_setup": obs_json.get("ui_target_setup"),
                    "work": obs_json.get("work"),
                    "stocks": obs_json.get("stocks"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    def _log_pending_workshop_construction_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "pending_workshop_construction_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "work": obs_json.get("work"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @staticmethod
    def _nobles_evidence_names_manager_row(text: Any) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        if "manager is required" in normalized:
            return False
        if "nobles and administrators" in normalized:
            return False
        return "manager" in normalized

    @classmethod
    def _nobles_navigation_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        screen_state = obs_json.get("screen_state")
        if not isinstance(screen_state, dict):
            return None
        if str(screen_state.get("mode") or "").strip().lower() != "nobles_administrators":
            return None
        if str(screen_state.get("confidence") or "") != "high":
            return None

        keys = [str(key) for key in cls._keystroke_keys(tool_payload)]
        if not keys or all(key == "LEAVESCREEN" for key in keys):
            return None

        uses_standard_scroll = any(key.startswith("STANDARDSCROLL") for key in keys)
        selects = "SELECT" in keys
        fixed_cursor_select = (
            selects
            and (
                sum(1 for key in keys if key == "CURSOR_DOWN") >= 2
                or sum(1 for key in keys if key == "CURSOR_UP") >= 2
            )
        )

        screen_read = (
            tool_payload.get("screen_read")
            if isinstance(tool_payload.get("screen_read"), dict)
            else {}
        )
        evidence_values: List[Any] = [
            screen_state.get("highlighted"),
            screen_state.get("cursor_or_selection"),
            screen_read.get("cursor_or_selection"),
        ]
        for source in (screen_state.get("evidence"), screen_read.get("evidence")):
            if isinstance(source, list):
                evidence_values.extend(source)
            elif source:
                evidence_values.append(source)
        manager_row_visible = any(
            cls._nobles_evidence_names_manager_row(value) for value in evidence_values
        )
        highlighted = str(screen_state.get("highlighted") or "").strip().lower()
        highlighted_is_title = "nobles and administrators" in highlighted

        if uses_standard_scroll:
            return (
                "Nobles navigation contract mismatch: STANDARDSCROLL keys are not "
                "accepted on the Nobles and Administrators screen in this runner. "
                "They caused live DFHack timeouts in trace evidence. Use only "
                "visible highlighted-row evidence, or LEAVESCREEN with advance_ticks=0 "
                "to return to the map and choose another production route."
            )
        if selects and highlighted_is_title and not manager_row_visible:
            return (
                "Nobles navigation contract mismatch: the visible Nobles screen has "
                "only the title highlighted, not a selectable Manager row. Do not "
                "press SELECT from a title highlight or use fixed row counts. First "
                "produce screen evidence that the Manager row itself is highlighted, "
                "or escape with LEAVESCREEN and choose another real gameplay route."
            )
        if fixed_cursor_select and not manager_row_visible:
            return (
                "Nobles navigation contract mismatch: fixed CURSOR_UP/CURSOR_DOWN "
                "counts followed by SELECT are not allowed unless screen_read "
                "cites the visible Manager row as the current highlight. Use visible "
                "row evidence instead of counting from memory."
            )
        return None

    def _log_nobles_navigation_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        self._tool_events.append(
            {
                "tool": "nobles_navigation_contract_rejected",
                "input": {
                    "screen_state": obs_json.get("screen_state"),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                },
                "output": error,
            }
        )

    @classmethod
    def _material_target_contract_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        target_setup = obs_json.get("ui_target_setup")
        if not isinstance(target_setup, dict):
            return None
        if str(target_setup.get("target_mode") or "") != "material":
            return None
        if not target_setup.get("show_recommended_keys"):
            return None

        run_progress = obs_json.get("ui_run_progress")
        if isinstance(run_progress, dict) and int(run_progress.get("total_material_delta") or 0) > 0:
            return None

        recommended_keys_raw = target_setup.get("recommended_keys")
        if not isinstance(recommended_keys_raw, list) or not recommended_keys_raw:
            return None
        recommended_keys = [str(key) for key in recommended_keys_raw]
        submitted_keys = [str(key) for key in cls._keystroke_keys(tool_payload)]

        if submitted_keys == recommended_keys:
            try:
                advance_ticks = int(tool_payload.get("advance_ticks") or 0)
            except (TypeError, ValueError):
                advance_ticks = 0
            if "DESIGNATE_CHOP" in recommended_keys and advance_ticks < 1000:
                return (
                    "Material target contract mismatch: the fresh material target "
                    "is a tree-chop designation. Copying the target keys is correct, "
                    "but advance_ticks must be at least 1000 so woodcutters have "
                    "time to produce logs before the next decision."
                )
            return None

        return (
            "Material target contract mismatch: no usable material has been "
            "proven yet and fresh material recommended_keys are visible. Copy "
            "those recommended_keys exactly for this turn instead of opening "
            "building/unit/job/nobles menus or inventing manual z-level mining. "
            "If the visible screen is a blocked build/material menu, use only "
            "the visible escape keys supplied in recommended_keys."
        )

    def _log_material_target_contract_error(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        target_setup = obs_json.get("ui_target_setup")
        self._tool_events.append(
            {
                "tool": "material_target_contract_rejected",
                "input": {
                    "target_mode": (
                        target_setup.get("target_mode")
                        if isinstance(target_setup, dict)
                        else None
                    ),
                    "recommended_keys": (
                        target_setup.get("recommended_keys")
                        if isinstance(target_setup, dict)
                        else None
                    ),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                    "advance_ticks": tool_payload.get("advance_ticks"),
                },
                "output": error,
            }
        )

    @staticmethod
    def _material_target_recovery_hint(obs_json: Dict[str, Any]) -> str:
        target_setup = obs_json.get("ui_target_setup")
        if not isinstance(target_setup, dict):
            return ""
        if str(target_setup.get("target_mode") or "") != "material":
            return ""
        if not target_setup.get("show_recommended_keys"):
            return ""

        run_progress = obs_json.get("ui_run_progress")
        if (
            isinstance(run_progress, dict)
            and int(run_progress.get("total_material_delta") or 0) > 0
        ):
            return ""

        recommended_keys_raw = target_setup.get("recommended_keys")
        if not isinstance(recommended_keys_raw, list) or not recommended_keys_raw:
            return ""
        recommended_keys = [str(key) for key in recommended_keys_raw]
        hint = (
            "Fresh material target is visible. Use exactly these keys in "
            f"params.keys, with no inserted navigation: {json.dumps(recommended_keys)}."
        )
        if "DESIGNATE_CHOP" in recommended_keys:
            hint += (
                " Because this is DESIGNATE_CHOP, set advance_ticks to at least "
                "1000, such as 1500, so woodcutters can produce logs before the "
                "next decision."
            )
        return hint

    @classmethod
    def _submitted_action_family(cls, tool_payload: Dict[str, Any]) -> str:
        keys = cls._keystroke_keys(tool_payload)
        key_values = [str(key) for key in keys]
        key_set = set(key_values)
        intent = str(tool_payload.get("intent") or "").lower()

        if "D_DESIGNATE" in key_set:
            return "designation"
        if "D_BUILDING" in key_set:
            return "building_placement_menu"
        if "D_JOBLIST" in key_set or "UNITJOB_MANAGER" in key_set:
            return "job_manager_menu"
        if "D_NOBLES" in key_set or "nobles" in intent or "manager" in intent:
            return "manager_nobles_menu"
        if (
            "D_BUILDJOB" in key_set
            or "BUILDJOB_ADD" in key_set
            or "workshop task" in intent
            or "carpenter workshop" in intent
        ):
            return "workshop_task_menu"
        if any(key == "STRING_A032" for key in key_values):
            return "wait"
        navigation_keys = {
            "LEAVESCREEN",
            "SELECT",
            "CURSOR_UP",
            "CURSOR_DOWN",
            "CURSOR_LEFT",
            "CURSOR_RIGHT",
            "SECONDSCROLL_UP",
            "SECONDSCROLL_DOWN",
            "STANDARDSCROLL_UP",
            "STANDARDSCROLL_DOWN",
            "STANDARDSCROLL_PAGEUP",
            "STANDARDSCROLL_PAGEDOWN",
        }
        if key_values and all(key in navigation_keys for key in key_values):
            return "menu_navigation"
        return key_values[0] if key_values else "none"

    @staticmethod
    def _blocked_menu_group(family: Any) -> str:
        if family in {"building_placement_menu", "workshop_task_menu"}:
            return "workshop_build_menus"
        if family in {"manager_nobles_menu", "job_manager_menu"}:
            return "manager_menus"
        return str(family or "none")

    @classmethod
    def _blocked_menu_path_error(
        cls,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> str | None:
        recent = obs_json.get("recent_progress_summary")
        if not isinstance(recent, dict) or not recent.get("do_not_repeat_menu_path"):
            return None

        keys = cls._keystroke_keys(tool_payload)
        if keys and all(str(key) == "LEAVESCREEN" for key in keys):
            return None

        repeated_family = recent.get("repeated_menu_family")
        submitted_family = cls._submitted_action_family(tool_payload)
        if submitted_family in {"none", "designation", "wait"}:
            return None
        if cls._blocked_menu_group(repeated_family) != cls._blocked_menu_group(
            submitted_family
        ):
            return None

        return (
            "Blocked repeated menu action: recent_progress_summary."
            "do_not_repeat_menu_path is true for "
            f"{repeated_family}, and this action is another {submitted_family} "
            "route in the same failed menu group. Do not reopen that menu path "
            "after an escape. Choose a different route using current visible "
            "screen evidence, such as a new designation/material-acquisition "
            "branch, a verified main-map inspection, or a different non-menu "
            "plan step."
        )

    def _log_blocked_menu_path(
        self,
        tool_payload: Dict[str, Any],
        obs_json: Dict[str, Any],
        error: str,
    ) -> None:
        recent = obs_json.get("recent_progress_summary")
        repeated_family = (
            recent.get("repeated_menu_family") if isinstance(recent, dict) else None
        )
        self._tool_events.append(
            {
                "tool": "blocked_menu_path_rejected",
                "input": {
                    "repeated_menu_family": repeated_family,
                    "submitted_family": self._submitted_action_family(tool_payload),
                    "submitted_keys": self._keystroke_keys(tool_payload),
                },
                "output": error,
            }
        )

    @staticmethod
    def _is_menu_escape_fallback_error(error: Any) -> bool:
        message = str(error or "")
        return message.startswith("Blocked repeated menu action:") or message.startswith(
            "Nobles navigation contract mismatch:"
        )

    def _fallback_blocked_menu_escape(self, error: str) -> Dict[str, Any]:
        fallback = {
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]},
            "intent": (
                "Escape from a blocked or unsafe menu path after the model did "
                "not choose a valid evidence-backed alternate route."
            ),
            "advance_ticks": 0,
        }
        self._tool_events.append(
            {
                "tool": "blocked_menu_path_fallback",
                "input": {"error": error},
                "output": "Submitted LEAVESCREEN-only recovery instead of repeating the blocked menu path.",
            }
        )
        return parse_action(fallback)

    def _parse_candidate_payload(
        self,
        payload: Dict[str, Any],
        obs_json: Dict[str, Any],
    ) -> Dict[str, Any] | str:
        payload = self._normalize_action_payload(payload)
        empty_action_error = self._empty_nested_action_error(payload)
        if empty_action_error:
            return empty_action_error

        payload = self._repair_missing_keystroke_type(payload)
        payload = self._repair_menu_loop_recovery_action(payload, obs_json)
        payload = self._repair_metadata_dict_fields(payload)
        payload = self._repair_missing_screen_read_from_classifier(payload, obs_json)

        blocked_menu_error = self._blocked_menu_path_error(payload, obs_json)
        if blocked_menu_error:
            self._log_blocked_menu_path(payload, obs_json, blocked_menu_error)
            return blocked_menu_error

        screen_read_error = self._screen_read_contract_error(payload, obs_json)
        if screen_read_error:
            self._log_screen_read_contract_error(payload, obs_json, screen_read_error)
            return screen_read_error

        workshop_select_transition_error = (
            self._workshop_select_transition_contract_error(payload, obs_json)
        )
        if workshop_select_transition_error:
            self._log_workshop_select_transition_contract_error(
                payload,
                obs_json,
                workshop_select_transition_error,
            )
            return workshop_select_transition_error

        selected_workshop_wait_error = self._selected_workshop_wait_contract_error(
            payload,
            obs_json,
        )
        if selected_workshop_wait_error:
            self._log_selected_workshop_wait_contract_error(
                payload,
                obs_json,
                selected_workshop_wait_error,
            )
            return selected_workshop_wait_error

        pending_workshop_error = self._pending_workshop_construction_contract_error(
            payload,
            obs_json,
        )
        if pending_workshop_error:
            self._log_pending_workshop_construction_contract_error(
                payload,
                obs_json,
                pending_workshop_error,
            )
            return pending_workshop_error

        queued_workshop_construction_error = (
            self._queued_workshop_construction_route_error(payload, obs_json)
        )
        if queued_workshop_construction_error:
            self._log_queued_workshop_construction_route_error(
                payload,
                obs_json,
                queued_workshop_construction_error,
            )
            return queued_workshop_construction_error

        queued_workshop_task_error = self._queued_workshop_task_route_error(
            payload,
            obs_json,
        )
        if queued_workshop_task_error:
            self._log_queued_workshop_task_route_error(
                payload,
                obs_json,
                queued_workshop_task_error,
            )
            return queued_workshop_task_error

        existing_workshop_production_error = (
            self._existing_workshop_production_route_error(payload, obs_json)
        )
        if existing_workshop_production_error:
            self._log_existing_workshop_production_route_error(
                payload,
                obs_json,
                existing_workshop_production_error,
            )
            return existing_workshop_production_error

        add_task_list_error = self._workshop_add_task_list_contract_error(
            payload,
            obs_json,
        )
        if add_task_list_error:
            self._log_workshop_add_task_list_contract_error(
                payload,
                obs_json,
                add_task_list_error,
            )
            return add_task_list_error

        compound_escape_error = self._compound_menu_escape_contract_error(
            payload,
            obs_json,
        )
        if compound_escape_error:
            self._log_compound_menu_escape_contract_error(
                payload,
                obs_json,
                compound_escape_error,
            )
            return compound_escape_error

        nobles_navigation_error = self._nobles_navigation_contract_error(payload, obs_json)
        if nobles_navigation_error:
            self._log_nobles_navigation_contract_error(
                payload,
                obs_json,
                nobles_navigation_error,
            )
            return nobles_navigation_error

        material_target_error = self._material_target_contract_error(payload, obs_json)
        if material_target_error:
            self._log_material_target_contract_error(
                payload,
                obs_json,
                material_target_error,
            )
            return material_target_error

        contract_error = self._advance_ticks_contract_error(payload)
        if contract_error:
            repaired = self._repair_action_only_contract(payload, contract_error)
            if repaired is None:
                return contract_error
            payload = repaired

        try:
            return parse_action(payload)
        except ValueError as exc:
            return f"Invalid submit_action payload: {exc}"

    def _force_plain_json_action(
        self,
        messages: List[Dict[str, Any]],
        obs_json: Dict[str, Any],
        last_error: Exception | str | None,
    ) -> Dict[str, Any] | None:
        force_messages = list(messages)
        self._last_plain_json_error = None
        material_hint = self._material_target_recovery_hint(obs_json)
        recovery_error = last_error or "tool rounds ended without an accepted action"
        force_messages.append(
            {
                "role": "user",
                "content": (
                    "Tool calling produced an invalid action. Do not call any tools. "
                    "Reply with only one JSON object for a top-level KEYSTROKE action. "
                    "Do not include an action wrapper. Required shape: "
                    '{"type":"KEYSTROKE","params":{"keys":["..."]},'
                    '"intent":"...","advance_ticks":0}. '
                    f"{material_hint} "
                    f"Previous error: {recovery_error}"
                ),
            }
        )
        for _ in range(3):
            self._rate_limit()
            response = self._create_completion(
                force_messages,
                tools=None,
                tool_choice=None,
            )
            self._tool_events.append(
                {
                    "tool": "openrouter.chat.completions.create",
                    "input": {
                        "model": self._model,
                        "mode": "plain_json_action_recovery",
                        "max_tokens": self._settings.LLM_MAX_TOKENS,
                        "temperature": self._settings.LLM_TEMP,
                    },
                    "output": {"usage": _usage_payload(response)},
                }
            )
            message = response.choices[0].message
            payload = self._json_payload_from_text(getattr(message, "content", None))
            if payload is None:
                self._last_plain_json_error = "plain JSON recovery returned no JSON action"
                force_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Reply only with the JSON action object. No prose, "
                            "no markdown, no tool call, and no action wrapper."
                        ),
                    }
                )
                continue
            parsed = self._parse_candidate_payload(payload, obs_json)
            if isinstance(parsed, dict):
                self._tool_events.append(
                    {
                        "tool": "openrouter.plain_json_action",
                        "input": payload,
                        "output": "accepted",
                    }
                )
                return parsed
            self._tool_events.append(
                {
                    "tool": "openrouter.plain_json_action",
                    "input": payload,
                    "output": {"rejected": str(parsed)},
                }
            )
            self._last_plain_json_error = str(parsed)
            if self._is_menu_escape_fallback_error(parsed):
                return self._fallback_blocked_menu_escape(str(parsed))
            force_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"{parsed} {material_hint} Reply only with one valid top-level "
                        "KEYSTROKE JSON object."
                    ),
                }
            )
        return None

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        messages = self._messages(obs_text, obs_json)
        called_tool_names: set[str] = set()
        last_error: Exception | str | None = None
        last_blocked_menu_error: str | None = None

        max_tool_rounds = max(1, self._settings.OPENROUTER_MAX_TOOL_ROUNDS)
        for _ in range(max_tool_rounds):
            self._rate_limit()
            response = self._create_completion(messages)
            self._tool_events.append(
                {
                    "tool": "openrouter.chat.completions.create",
                    "input": {
                        "model": self._model,
                        "max_tokens": self._settings.LLM_MAX_TOKENS,
                        "temperature": self._settings.LLM_TEMP,
                    },
                    "output": {"usage": _usage_payload(response)},
                }
            )
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                message_content = getattr(message, "content", None)
                content_payload = self._json_payload_from_text(message_content)
                if content_payload is not None:
                    parsed = self._parse_candidate_payload(content_payload, obs_json)
                    if isinstance(parsed, dict):
                        self._tool_events.append(
                            {
                                "tool": "openrouter.content_action",
                                "input": content_payload,
                                "output": "accepted",
                            }
                        )
                        self._completed_actions += 1
                        return parsed

                    last_error = ValueError(parsed)
                    if self._is_menu_escape_fallback_error(parsed):
                        last_blocked_menu_error = parsed
                        messages.append(
                            {
                                "role": "user",
                                "content": parsed,
                            }
                        )
                        continue
                else:
                    content_snippet = (
                        message_content[:2000]
                        if isinstance(message_content, str)
                        else message_content
                    )
                    self._tool_events.append(
                        {
                            "tool": "openrouter.no_tool_response",
                            "input": {"model": self._model},
                            "output": {
                                "content": content_snippet,
                                "content_type": type(message_content).__name__,
                            },
                        }
                    )
                    last_error = "model did not call a tool"
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Call submit_action with a valid KEYSTROKE payload. "
                            "If tool calling fails, reply with only the JSON action object."
                        ),
                    }
                )
                continue

            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(message, "content", None) or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )

            submit_calls = []
            for call in tool_calls:
                name = call.function.name
                tool_input = self._tool_args(call)
                if name == "submit_action":
                    submit_calls.append((call, tool_input))
                    continue
                called_tool_names.add(name)
                output = self._tool_manager.handle(name, tool_input)
                self._tool_events.append(
                    {"tool": name, "input": tool_input, "output": output}
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": output,
                    }
                )

            for call, tool_input in submit_calls:
                called_tool_names.add("submit_action")
                if not tool_input or self._empty_nested_action_error(tool_input):
                    fallback_payload = self._json_payload_from_text(
                        getattr(message, "content", None)
                    )
                    if fallback_payload is not None:
                        tool_input = fallback_payload
                gate_error = self._gate_error(called_tool_names)
                if gate_error:
                    last_error = gate_error
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": gate_error,
                        }
                    )
                    continue

                parsed = self._parse_candidate_payload(tool_input, obs_json)
                if not isinstance(parsed, dict):
                    last_error = ValueError(parsed)
                    if self._is_menu_escape_fallback_error(parsed):
                        last_blocked_menu_error = parsed
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": parsed,
                        }
                    )
                    continue
                self._tool_events.append(
                    {"tool": "submit_action", "input": tool_input, "output": "accepted"}
                )
                self._completed_actions += 1
                return parsed

        if last_blocked_menu_error is not None:
            self._completed_actions += 1
            return self._fallback_blocked_menu_escape(last_blocked_menu_error)

        last_error = last_error or "tool rounds ended without an accepted action"
        action = self._force_plain_json_action(messages, obs_json, last_error)
        if action is not None:
            self._completed_actions += 1
            return action
        if self._last_plain_json_error:
            last_error = (
                f"{last_error}; plain JSON recovery failed: "
                f"{self._last_plain_json_error}"
            )

        raise RuntimeError(
            f"OpenRouter keystroke agent failed after {max_tool_rounds} tool rounds: {last_error}"
        )

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = list(self._tool_events)
        self._tool_events.clear()
        return events


register_agent("openrouter-keystroke", lambda: OpenRouterKeystrokeAgent())
register_agent(
    "openrouter-keystroke-perception-review",
    lambda: OpenRouterKeystrokeAgent(
        system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
        require_plan_review=True,
        require_perception_review=True,
    ),
)
register_agent(
    "openrouter-glm-5.2",
    lambda: OpenRouterKeystrokeAgent(
        system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
        require_memory_review=True,
        require_plan_review=True,
        require_perception_review=True,
        model_override="z-ai/glm-5.2",
    ),
)


__all__ = ["OpenRouterKeystrokeAgent"]
