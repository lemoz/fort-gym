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
    ) -> None:
        self._settings = get_settings()
        if not self._settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not configured")
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

    def _client_instance(self):
        if self._client is None:
            try:
                openai_mod = import_module("openai")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("openai package not installed") from exc
            client_cls = getattr(openai_mod, "OpenAI", None)
            if client_cls is None:
                raise RuntimeError("openai.OpenAI client not available")
            self._client = client_cls(
                api_key=self._settings.OPENROUTER_API_KEY,
                base_url=self._settings.OPENROUTER_BASE_URL,
                max_retries=0,
                timeout=self._settings.OPENROUTER_TIMEOUT_SECONDS,
            )
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

    def _create_completion(self, messages: List[Dict[str, Any]]) -> Any:
        max_attempts = max(1, self._settings.OPENROUTER_MAX_ATTEMPTS)
        last_exc: Exception | None = None
        request_kwargs: Dict[str, Any] = {}
        if self._settings.OPENROUTER_DISABLE_REASONING:
            request_kwargs["extra_body"] = {
                "reasoning": {"enabled": False, "exclude": True}
            }
        for attempt in range(max_attempts):
            try:
                return self._client_instance().chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools(),
                    tool_choice=(
                        {"type": "function", "function": {"name": "submit_action"}}
                        if self._submit_action_only
                        else "auto"
                    ),
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
                            "timeout_seconds": self._settings.OPENROUTER_TIMEOUT_SECONDS,
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
        raise RuntimeError(f"OpenRouter request failed after {max_attempts} attempts") from last_exc

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
        if advance_ticks > 0:
            return None

        params = tool_payload.get("params") if isinstance(tool_payload.get("params"), dict) else {}
        keys = params.get("keys") if isinstance(params, dict) else []
        keys = keys if isinstance(keys, list) else []
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
        if cls._zero_tick_action_says_time_should_pass(tool_payload) or (
            scroll_only and "advance" in action_text
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
        if not self._submit_action_only:
            return None
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
                    f"{repaired_advance_ticks} during action-only OpenRouter "
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

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        messages = self._messages(obs_text, obs_json)
        called_tool_names: set[str] = set()
        last_error: Exception | str | None = None

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
                    content_payload = self._repair_missing_keystroke_type(content_payload)
                    content_payload = self._repair_menu_loop_recovery_action(
                        content_payload,
                        obs_json,
                    )
                    contract_error = self._advance_ticks_contract_error(content_payload)
                    if contract_error:
                        repaired = self._repair_action_only_contract(
                            content_payload,
                            contract_error,
                        )
                        if repaired is None:
                            last_error = ValueError(contract_error)
                            messages.append(
                                {
                                    "role": "user",
                                    "content": contract_error,
                                }
                            )
                            continue
                        content_payload = repaired
                    try:
                        action = parse_action(content_payload)
                    except ValueError as exc:
                        last_error = exc
                    else:
                        self._tool_events.append(
                            {
                                "tool": "openrouter.content_action",
                                "input": content_payload,
                                "output": "accepted",
                            }
                        )
                        self._completed_actions += 1
                        return action
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
                if not tool_input:
                    fallback_payload = self._json_payload_from_text(
                        getattr(message, "content", None)
                    )
                    if fallback_payload is not None:
                        tool_input = fallback_payload
                tool_input = self._repair_missing_keystroke_type(tool_input)
                tool_input = self._repair_menu_loop_recovery_action(tool_input, obs_json)
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
                contract_error = self._advance_ticks_contract_error(tool_input)
                if contract_error:
                    repaired = self._repair_action_only_contract(
                        tool_input,
                        contract_error,
                    )
                    if repaired is None:
                        last_error = ValueError(contract_error)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": contract_error,
                            }
                        )
                        continue
                    tool_input = repaired
                try:
                    action = parse_action(tool_input)
                except ValueError as exc:
                    last_error = exc
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": f"Invalid submit_action payload: {exc}",
                        }
                    )
                    continue
                self._tool_events.append(
                    {"tool": "submit_action", "input": tool_input, "output": "accepted"}
                )
                self._completed_actions += 1
                return action

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
