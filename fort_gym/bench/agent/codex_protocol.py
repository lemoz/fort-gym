"""Decode Codex exec events without treating diagnostics as game actions.

This is a transport receipt, not evidence that a returned action was executed.
Retain usage even when a later event or malformed final answer rejects the turn.
"""

from __future__ import annotations

import json
from typing import Any

TRANSPORT = "codex-exec-chatgpt/v1"
CODE_MODE_DISABLED = (
    "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; "
    "enable `features.code_mode_host` and install `codex-code-mode-host`."
)


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def _usage_valid(usage: object) -> bool:
    if not isinstance(usage, dict):
        return False
    fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in fields):
        return False
    reasoning = usage.get("reasoning_output_tokens", 0)
    return (
        usage["cached_input_tokens"] <= usage["input_tokens"]
        and type(reasoning) is int
        and reasoning >= 0
    )


def decode_events(raw: str, *, exit_code: int | None, timed_out: bool = False) -> dict:
    messages: list[str] = []
    usages: list[Any] = []
    diagnostics: list[str] = []
    errors: list[str] = []
    started, completed, finished = 0, 0, False
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, parse_constant=_reject_nonfinite)
        except (ValueError, TypeError):
            errors.append("invalid_event_json")
            continue
        if not isinstance(event, dict):
            errors.append("invalid_event_shape")
            continue
        kind = event.get("type")
        if kind == "turn.started":
            if started or finished:
                errors.append("invalid_turn_order")
            started += 1
        elif kind == "turn.completed":
            if started != 1 or finished:
                errors.append("invalid_turn_order")
            completed += 1
            finished = True
            usages.append(event.get("usage"))
        elif kind in {"turn.failed", "error"}:
            errors.append("codex_turn_error")
        elif isinstance(kind, str) and kind.startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict):
                errors.append("invalid_item_shape")
                continue
            item_type = item.get("type")
            if item_type == "error" and item.get("message") == CODE_MODE_DISABLED and not started:
                diagnostics.append(CODE_MODE_DISABLED)
            elif item_type not in {"agent_message", "reasoning"}:
                errors.append("unexpected_codex_item")
            elif finished or started != 1:
                errors.append("item_after_turn_completion")
            elif item_type == "agent_message" and kind == "item.completed":
                message = item.get("text")
                if isinstance(message, str):
                    messages.append(message)
                else:
                    errors.append("invalid_message_text")
        elif kind != "thread.started":
            errors.append("unexpected_codex_event")
    if exit_code != 0 or timed_out:
        errors.append("codex_timeout" if timed_out else "codex_exit_error")
    if started != 1 or completed != 1:
        errors.append("expected_one_completed_turn")
    if len(usages) != 1 or not all(_usage_valid(usage) for usage in usages):
        errors.append("missing_or_invalid_usage")
    response = None
    try:
        response = json.loads(messages[-1], parse_constant=_reject_nonfinite)
        if not isinstance(response, dict):
            errors.append("final_response_not_object")
            response = None
    except (ValueError, TypeError, IndexError):
        errors.append("missing_or_invalid_final_response")
    return {
        "transport": TRANSPORT,
        "accepted": not errors,
        "response": response,
        "usage": usages,
        "usage_complete": len(usages) == 1 and all(_usage_valid(usage) for usage in usages),
        "total_tokens": (
            sum(usage["input_tokens"] + usage["output_tokens"] for usage in usages)
            if usages and all(_usage_valid(usage) for usage in usages)
            else None
        ),
        "diagnostics": diagnostics,
        "errors": sorted(set(errors)),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "cost_basis": "chatgpt_subscription",
        "reported_charge_usd": None,
        "charge_status": "not_reported_by_exec",
        "native_game_commands": 0,
    }
