"""OpenAI function-calling agent adapter."""

from __future__ import annotations

import json
import time
from importlib import import_module
from typing import Any, Dict, Optional

from .base import Agent, register_agent
from ..config import get_settings
from ..env.actions import ACTION_TOOL_SPEC, parse_action, system_prompt_v1


class OpenAIActionAgent(Agent):
    """Calls OpenAI's Chat Completions API with the submit_action tool."""

    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self._client = None
        self._last_call = 0.0

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

    def _client_instance(self):
        if self._client is None:
            try:
                openai_mod = import_module("openai")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("openai package not installed") from exc
            client_cls = getattr(openai_mod, "OpenAI", None)
            if client_cls is None:
                raise RuntimeError("openai.OpenAI client not available")
            self._client = client_cls(api_key=self._settings.OPENAI_API_KEY)
        return self._client

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt_v1},
            {
                "role": "user",
                "content": f"{obs_text}\n\nState JSON:\n{json.dumps(obs_json)}",
            },
        ]

        last_error: Optional[Exception] = None
        for _ in range(3):
            self._rate_limit()
            client = self._client_instance()
            response = client.chat.completions.create(
                model=self._settings.OPENAI_MODEL,
                messages=messages,
                tools=[{"type": "function", "function": ACTION_TOOL_SPEC}],
                tool_choice="auto",
                temperature=self._settings.LLM_TEMP,
                max_tokens=self._settings.LLM_MAX_TOKENS,
            )
            choice = response.choices[0]
            tool_call = None
            if choice.message and getattr(choice.message, "tool_calls", None):
                tool_call = choice.message.tool_calls[0]
            if not tool_call:
                last_error = ValueError("Model did not call submit_action")
                continue
            try:
                arguments = tool_call.function.arguments or "{}"
                payload = json.loads(arguments)
                return parse_action(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                messages.append(
                    {
                        "role": "system",
                        "content": f"Previous response invalid ({exc}); emit exactly one action.",
                    }
                )
        raise RuntimeError(f"OpenAI agent failed to produce action: {last_error}")


register_agent("openai", lambda: OpenAIActionAgent())


__all__ = ["OpenAIActionAgent"]
