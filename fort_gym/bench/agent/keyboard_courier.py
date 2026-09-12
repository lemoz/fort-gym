"""Reusable host-side decision courier; no game controls or VM ownership."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..run.keyboard_config import validate_condition
from .codex_allowance import read_allowance
from .codex_transport import CodexTransportError
from .keyboard_decision import request_keyboard_decision
from .keyboard_exchange import digest, publish, request_selection
from .keyboard_prompt import BASE_PROMPT


def answer_request(
    request: dict,
    *,
    directory: Path,
    condition: dict,
    executable: Path,
    decision: Callable = request_keyboard_decision,
    allowance_check: Callable | None = None,
) -> tuple[dict, dict]:
    """Answer once, retaining intent and usage even when delivery later fails.

    The owner creates a unique existing directory and transports the returned
    response to the game user. A second call at that directory cannot re-infer.
    """
    validate_condition(condition)
    model, reasoning_effort = request_selection(request)
    version = condition["schema_version"].rsplit("/", 1)[1]
    if (
        request["schema_version"] != f"fortgym.keyboard-exchange-request/{version}"
        or model != condition["model"]
        or reasoning_effort != condition["reasoning_effort"]
        or request.get("prompt_profile", BASE_PROMPT) != condition.get("prompt_profile", BASE_PROMPT)
        or request["control_profile"] != condition["control_profile"]
        or request.get("bindings_sha256") != condition.get("bindings_sha256")
    ):
        raise ValueError("Request model differs from its declared condition")
    if request["max_advance_ticks"] != condition["max_advance_ticks"]:
        raise ValueError("Request tick bound differs from its declared condition")
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("Courier requires an existing private request directory")
    publish(
        directory / "claim.json",
        {
            "schema_version": "fortgym.keyboard-courier-claim/v1",
            "request_sha256": digest(request),
            "dispatch_outcome": "unknown_until_response",
        },
    )
    try:
        result = decision(
            request["screen"],
            memory=request["memory"],
            feedback=request["feedback"],
            executable=executable,
            artifact_root=directory,
            allowance_check=allowance_check
            or (
                lambda: read_allowance(
                    executable,
                    maximum_used_percent=condition["maximum_included_usage_percent"],
                )
            ),
            max_advance_ticks=condition["max_advance_ticks"],
            timeout_seconds=condition["model_timeout_seconds"],
            control_profile=condition["control_profile"],
            observation_profile=condition["observation_profile"],
            model=model,
            reasoning_effort=reasoning_effort,
            **({"prompt_profile": condition["prompt_profile"]} if version in ("v3", "v4") else {}),
        )
    except CodexTransportError as error:
        result = error.receipt
        if "transport_receipt" not in result:
            result = {
                "transport_receipt": result,
                "action_grammar_valid": False,
                "error": str(error),
            }
    except Exception as error:
        result = {
            "transport_receipt": {"accepted": False, "dispatched": None},
            "action_grammar_valid": False,
            "error_type": type(error).__name__,
        }
    response = {"request_sha256": digest(request), "result": result}
    publish(directory / "response.json", response)
    receipt = result.get("transport_receipt", {})
    summary = {
        "request_id": request["request_id"],
        "model_dispatched": receipt.get("dispatched"),
        "action_grammar_valid": result.get("action_grammar_valid"),
        "total_tokens": receipt.get("total_tokens"),
        "reported_charge_usd": receipt.get("reported_charge_usd"),
    }
    publish(directory / "courier-summary.json", summary)
    return response, summary
