"""LLM policy on the DFHack-governed legal action surface.

One OpenRouter chat-completion call per step (default ``z-ai/glm-5.2``), forced
through a single ``submit_action`` tool restricted to DIG/BUILD/ORDER/WAIT.
``MemoryManager`` carries the plan, POIs, and failed attempts across steps.

This module intentionally contains no gameplay heuristics: the model plus the
run loop must solve gameplay. The only local logic is schema normalization and
a safe WAIT fallback when the model call or its payload is unusable, so a bad
step degrades to "let the simulation run" instead of crashing the run.
"""

from __future__ import annotations

import json
import os
import re
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..env.actions import parse_action
from .base import Agent, register_agent
from .memory import MemoryManager

GOVERNED_ACTION_TYPES = ("DIG", "BUILD", "ORDER", "WAIT")
DEFAULT_ADVANCE_TICKS = 1000

_MEMORY_PATH_ENV_VAR = "FORT_GYM_GOVERNED_MEMORY_PATH"
_MEMORY_PATH_DISABLE_VALUES = {"off", "0"}

GOVERNED_SYSTEM_PROMPT = """You are the overseer of a live Dwarf Fortress fortress. You play by issuing \
exactly one bounded, legal overseer command per step, then the real simulation runs and you observe \
what actually changed. Your score comes only from real observed fortress state: dug rooms, working \
workshops, production, wealth, and dwarves staying alive.

Legal actions (the only four types accepted):
- DIG: params {"area": [x, y, z], "size": [w, h, 1]}. Designates a dig rectangle (max 30x30, one \
z-level). Only WALL tiles can be dug; DF silently drops designations on floor/shrub/other tiles. \
Miners with the mining labor must then reach the walls and dig them out over time.
- BUILD: params {"kind": "CarpenterWorkshop", "x": X, "y": Y, "z": Z}. Places a 3x3 carpenter \
workshop whose footprint must fit fully on open floor inside your work area. The observation's work \
metrics include a `carpenter_build_site` when a legal spot is visible. After placement a dwarf must \
construct it (watch the workshop's construction stage in the crew/jobs section).
- ORDER: params {"job": <item>, "quantity": 1-5}. Queues production to any BUILT carpenter workshop \
(construction stage complete), wherever it stands. Items: bed, door, table, chair, barrel, bin. \
Dwarves then do the work.
- WAIT: params {}. Issues nothing and lets the simulation run.

Every action must include "advance_ticks" (how many game ticks to run after the command, up to \
2000; around 1000 is a typical step). Nothing in the fortress changes unless time advances.

The observation gives you the recorded game screen text plus derived work metrics (the `work` \
fields): target/connector/workshop-room rectangles, wall vs floor tile counts, dig designations, \
active jobs, workshop counts and usability, and manager order counts. Read them to see whether \
your previous command actually worked before issuing the next one. A == MEMORY == section carries \
your own plan, POIs, and failed attempts from earlier steps.

With each action also submit:
- "intent": one sentence on what this command does.
- "objective": the fortress goal this action advances (used as your persistent plan objective).
- "plan_step": which step of your plan this is.
- "expected_simulation_result": what the real simulation should show afterwards if it worked.
- "memory_update" (optional): a fact worth remembering, as "label @ x,y,z: note" if it has a \
location.

Be honest: if the metrics show your last action did nothing, say so in your next intent and adapt. \
Repeating an identical failing action wastes the run and is scored against you."""


def _submit_action_tool() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_action",
            "description": "Submit exactly one legal governed fortress action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(GOVERNED_ACTION_TYPES)},
                    "params": {"type": "object"},
                    "intent": {"type": "string"},
                    "objective": {"type": "string"},
                    "plan_step": {"type": "string"},
                    "expected_simulation_result": {"type": "string"},
                    "memory_update": {"type": "string"},
                    "advance_ticks": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 2000,
                        "description": "Game ticks to run after the command (~1000 typical).",
                    },
                },
                "required": ["type", "params", "intent", "advance_ticks"],
            },
        },
    }


_LAST_ACTION_LINE = re.compile(r"^Last Action:.*$", re.MULTILINE)
_MEMORY_UPDATE_POI = re.compile(
    r"^(?P<label>[^@]{1,80})@\s*(?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\s*,\s*(?P<z>-?\d+)\s*:?\s*(?P<note>.*)$"
)


class DFHackGovernedLLMAgent(Agent):
    """OpenRouter-backed policy for governed DIG/BUILD/ORDER/WAIT gameplay.

    ``memory_path`` controls disk persistence of POIs, failed attempts, plan,
    and summary across runs (runs on the same seed save share the same map,
    so this state stays valid run to run). ``"auto"`` (the default) resolves
    a path from ``FORT_GYM_GOVERNED_MEMORY_PATH`` (set to ``"off"``/``"0"``
    to disable) or falls back to ``<ARTIFACTS_DIR>/governed_llm_memory.json``.
    Pass ``None`` to disable persistence entirely, or an explicit path string.
    """

    def __init__(
        self,
        *,
        model_override: str | None = None,
        api_key: str | None = None,
        max_attempts: int | None = None,
        memory_path: str | None = "auto",
    ) -> None:
        self._settings = get_settings()
        self._api_key = api_key if api_key is not None else self._settings.OPENROUTER_API_KEY
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY not configured")
        self._model = model_override or self._settings.OPENROUTER_MODEL
        self._max_attempts = (
            self._settings.OPENROUTER_MAX_ATTEMPTS if max_attempts is None else max_attempts
        )
        self._client = None
        self._last_call = 0.0
        self._memory = MemoryManager(window_size=self._settings.MEMORY_WINDOW)
        self._tool_events: List[Dict[str, Any]] = []
        self._pending: Optional[Dict[str, Any]] = None
        self._memory_path = self._resolve_memory_path(memory_path)
        self._load_memory()

    # -- memory persistence ------------------------------------------------

    def _resolve_memory_path(self, memory_path: str | None) -> Path | None:
        if memory_path is None:
            return None
        if memory_path != "auto":
            return Path(memory_path)
        env_value = os.getenv(_MEMORY_PATH_ENV_VAR)
        if env_value is not None and env_value.strip():
            if env_value.strip().lower() in _MEMORY_PATH_DISABLE_VALUES:
                return None
            return Path(env_value.strip())
        return Path(self._settings.ARTIFACTS_DIR) / "governed_llm_memory.json"

    def _load_memory(self) -> None:
        if self._memory_path is None:
            return
        try:
            if not self._memory_path.is_file():
                return
            data = json.loads(self._memory_path.read_text(encoding="utf-8"))
            self._memory.load_dict(data if isinstance(data, dict) else {})
        except Exception as exc:
            self._tool_events.append(
                {
                    "tool": "governed_llm.load_memory",
                    "input": {"path": str(self._memory_path)},
                    "output": {"error": type(exc).__name__, "message": str(exc)},
                }
            )

    def _save_memory(self) -> None:
        if self._memory_path is None:
            return
        try:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._memory_path.with_name(self._memory_path.name + ".tmp")
            tmp_path.write_text(json.dumps(self._memory.to_dict()), encoding="utf-8")
            os.replace(tmp_path, self._memory_path)
        except Exception as exc:
            self._tool_events.append(
                {
                    "tool": "governed_llm.save_memory",
                    "input": {"path": str(self._memory_path)},
                    "output": {"error": type(exc).__name__, "message": str(exc)},
                }
            )

    # -- transport -------------------------------------------------------

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
                api_key=self._api_key,
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
        wait = interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _create_completion(self, messages: List[Dict[str, Any]]) -> Any:
        request_kwargs: Dict[str, Any] = {
            "tools": [_submit_action_tool()],
            "tool_choice": {"type": "function", "function": {"name": "submit_action"}},
        }
        if self._settings.OPENROUTER_DISABLE_REASONING:
            request_kwargs["extra_body"] = {"reasoning": {"enabled": False, "exclude": True}}
        max_attempts = max(1, self._max_attempts)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                self._rate_limit()
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
                        "input": {"model": self._model, "attempt": attempt + 1},
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
            f"openrouter request failed after {max_attempts} attempts"
        ) from last_exc

    # -- memory ----------------------------------------------------------

    def _record_previous_outcome(self, obs_text: str) -> None:
        if self._pending is None:
            return
        match = _LAST_ACTION_LINE.search(obs_text or "")
        result = match.group(0) if match else ""
        self._memory.add_step(
            observation=self._pending.get("observation_digest", ""),
            action=self._pending.get("action", {}),
            result=result,
        )
        if result and "REJECTED" in result.upper():
            action = self._pending.get("action", {})
            self._memory.remember_failed_attempt(
                label=f"{action.get('type', 'unknown')} rejected",
                reason=result,
            )
        self._pending = None

    def _apply_memory_fields(self, action: Dict[str, Any]) -> None:
        objective = str(action.get("objective") or "").strip()
        if objective:
            self._memory.write_gameplay_plan(
                objective=objective,
                current_step=str(action.get("plan_step") or "").strip(),
            )
        update = str(action.get("memory_update") or "").strip()
        if update:
            poi = _MEMORY_UPDATE_POI.match(update)
            if poi:
                self._memory.remember_poi(
                    label=poi.group("label").strip(),
                    x=poi.group("x"),
                    y=poi.group("y"),
                    z=poi.group("z"),
                    evidence=poi.group("note").strip(),
                )
            else:
                self._memory.remember_poi(label=update)

    # -- action handling ---------------------------------------------------

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(payload)
        params = normalized.get("params")
        normalized["params"] = dict(params) if isinstance(params, dict) else {}
        if normalized.get("type") == "ORDER":
            order = normalized["params"]
            if "quantity" not in order and "qty" in order:
                order["quantity"] = order.pop("qty")
        if "advance_ticks" not in normalized:
            normalized["advance_ticks"] = DEFAULT_ADVANCE_TICKS
        return normalized

    def _fallback_wait(self, reason: str) -> Dict[str, Any]:
        self._tool_events.append(
            {"tool": "governed_llm.fallback_wait", "input": {}, "output": {"reason": reason}}
        )
        self._memory.remember_failed_attempt(label="llm step fallback", reason=reason[:180])
        return parse_action(
            {
                "type": "WAIT",
                "params": {},
                "intent": f"fallback wait: {reason[:140]}",
                "objective": "Keep the simulation advancing despite a failed policy step.",
                "expected_simulation_result": "Existing jobs progress while the policy recovers.",
                "advance_ticks": DEFAULT_ADVANCE_TICKS,
            }
        )

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self._record_previous_outcome(obs_text)

        memory_context = self._memory.get_context()
        user_content = obs_text if not memory_context else f"{memory_context}\n\n{obs_text}"
        messages = [
            {"role": "system", "content": GOVERNED_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = self._create_completion(messages)
        except Exception as exc:
            return self._store_pending(obs_text, self._fallback_wait(f"llm call failed: {exc}"))

        payload = self._extract_tool_payload(response)
        if payload is None:
            return self._store_pending(
                obs_text, self._fallback_wait("model returned no submit_action tool call")
            )

        action_type = str(payload.get("type") or "").upper()
        if action_type not in GOVERNED_ACTION_TYPES:
            return self._store_pending(
                obs_text, self._fallback_wait(f"illegal action type: {action_type or 'missing'}")
            )

        try:
            action = parse_action(self._normalize_payload(payload))
        except (TypeError, ValueError) as exc:
            return self._store_pending(
                obs_text, self._fallback_wait(f"invalid action payload: {exc}")
            )

        self._apply_memory_fields(action)
        return self._store_pending(obs_text, action)

    def _store_pending(self, obs_text: str, action: Dict[str, Any]) -> Dict[str, Any]:
        digest = (obs_text or "").strip().splitlines()
        self._pending = {
            "observation_digest": " | ".join(line for line in digest[:3] if line),
            "action": action,
        }
        self._save_memory()
        return action

    def _extract_tool_payload(self, response: Any) -> Optional[Dict[str, Any]]:
        try:
            choices = getattr(response, "choices", None) or []
            message = getattr(choices[0], "message", None)
            tool_calls = getattr(message, "tool_calls", None) or []
        except (IndexError, AttributeError):
            return None
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._tool_events.append(
                {
                    "tool": "openrouter.chat.completions.create",
                    "input": {"model": self._model},
                    "output": {
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                    },
                }
            )
        for call in tool_calls:
            function = getattr(call, "function", None)
            if getattr(function, "name", "") != "submit_action":
                continue
            try:
                arguments = json.loads(getattr(function, "arguments", "") or "{}")
            except json.JSONDecodeError:
                return None
            return arguments if isinstance(arguments, dict) else None
        return None

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = self._tool_events
        self._tool_events = []
        return events


register_agent("dfhack-governed-llm", lambda: DFHackGovernedLLMAgent())


__all__ = ["DFHackGovernedLLMAgent", "GOVERNED_ACTION_TYPES", "GOVERNED_SYSTEM_PROMPT"]
