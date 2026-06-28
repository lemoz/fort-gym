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
        return [
            _submit_action_tool(require_perception_review=self._require_perception_review),
            *[_openai_tool(spec) for spec in self._tool_manager.tool_specs()],
        ]

    def _create_completion(self, messages: List[Dict[str, Any]]) -> Any:
        max_attempts = max(1, self._settings.OPENROUTER_MAX_ATTEMPTS)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self._client_instance().chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools(),
                    tool_choice="auto",
                    temperature=self._settings.LLM_TEMP,
                    max_tokens=self._settings.LLM_MAX_TOKENS,
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
                content_payload = self._json_payload_from_text(getattr(message, "content", None))
                if content_payload is not None:
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
