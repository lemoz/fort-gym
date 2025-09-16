"""Anthropic tool-use agent adapter."""

from __future__ import annotations

import json
import time
from importlib import import_module
from typing import Any, Dict, Optional

from .base import Agent, register_agent
from ..config import get_settings
from ..env.actions import ACTION_TOOL_SPEC, parse_action, system_prompt_v1


ANTHROPIC_TOOL = {
    "name": ACTION_TOOL_SPEC["name"],
    "description": ACTION_TOOL_SPEC["description"],
    "input_schema": ACTION_TOOL_SPEC["parameters"],
}


class AnthropicActionAgent(Agent):
    """Calls Anthropic Messages API with tool-use for submit_action."""

    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
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
                anthropic_mod = import_module("anthropic")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("anthropic package not installed") from exc
            client_cls = getattr(anthropic_mod, "Anthropic", None)
            if client_cls is None:
                raise RuntimeError("anthropic.Anthropic client not available")
            self._client = client_cls(api_key=self._settings.ANTHROPIC_API_KEY)
        return self._client

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        content = f"{obs_text}\n\nState JSON:\n{json.dumps(obs_json)}"
        last_error: Optional[Exception] = None

        for _ in range(3):
            self._rate_limit()
            client = self._client_instance()
            response = client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_output_tokens=self._settings.LLM_MAX_TOKENS,
                temperature=self._settings.LLM_TEMP,
                system=system_prompt_v1,
                tools=[ANTHROPIC_TOOL],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            )

            tool_payload = None
            for item in response.content:
                if item.type == "tool_use" and item.name == ACTION_TOOL_SPEC["name"]:
                    tool_payload = item.input
                    break
            if tool_payload is None:
                last_error = ValueError("Model did not use submit_action tool")
                continue
            try:
                return parse_action(tool_payload)
            except ValueError as exc:
                last_error = exc
                content += f"\n\nPrevious response invalid ({exc}). Provide one action."

        raise RuntimeError(f"Anthropic agent failed to produce action: {last_error}")


register_agent("anthropic", lambda: AnthropicActionAgent())


__all__ = ["AnthropicActionAgent"]
