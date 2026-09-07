"""Typed rejection of a received keyboard response, never a replacement action."""

from __future__ import annotations

from copy import deepcopy

from ..env.native_key_catalog import NATIVE_PROFILE, keys_for_profile
from ..env.screen_observation import TEXT_PROFILE
from .codex_protocol import TRANSPORT
from .codex_transport import MODEL, REASONING_EFFORT
from .standard_input import parse_envelope


class KeyboardInputRejected(ValueError):
    """A shape-valid response has unsupported keys and must not reach the game."""

    def __init__(self, payload: object, *, max_advance_ticks: int) -> None:
        self.action = parse_envelope(
            payload, max_advance_ticks=max_advance_ticks, control_profile=NATIVE_PROFILE
        )
        allowed = keys_for_profile(NATIVE_PROFILE)
        self.invalid_keys = sorted({key for key in self.action["params"]["keys"] if key not in allowed})
        if not self.invalid_keys:
            raise ValueError("A keyboard rejection requires unsupported native key names")
        super().__init__(
            "Unsupported native keyboard keys: " + ", ".join(self.invalid_keys)
            + ". Entire response rejected; no keys or simulation ticks were executed."
        )


def rejected_receipt(result: dict, *, screen_sha256: str, max_advance_ticks: int) -> KeyboardInputRejected:
    """Validate a complete rejection receipt, without invoking any transport."""
    receipt = result.get("transport_receipt")
    if not isinstance(receipt, dict) or (
        result.get("control_profile") != NATIVE_PROFILE
        or result.get("observation_profile") != TEXT_PROFILE
        or result.get("screen_sha256") != screen_sha256
        or result.get("action_grammar_valid") is not False
        or result.get("action") is not None
        or result.get("native_action_dispatched") is not False
        or result.get("error") != "Keyboard keys must be supported native interface events"
        or receipt.get("accepted") is not True
        or receipt.get("dispatched") is not True
        or receipt.get("model_requested") != MODEL
        or receipt.get("reasoning_effort_requested") != REASONING_EFFORT
        or receipt.get("auth_mode") != "chatgpt"
        or receipt.get("transport") != TRANSPORT
        or receipt.get("reported_charge_usd") is not None
        or receipt.get("usage_complete") is not True
        or type(receipt.get("total_tokens")) is not int
        or receipt["total_tokens"] < 0
        or not receipt.get("usage")
        or type(receipt.get("native_game_commands")) is not int
        or receipt["native_game_commands"] != 0
        or receipt.get("timed_out") is not False
        or receipt.get("interrupted") is not False
    ):
        raise ValueError("Keyboard rejection lacks complete identity and non-execution proof")
    return KeyboardInputRejected(receipt.get("response"), max_advance_ticks=max_advance_ticks)


def validate_rejection_state(previous: dict, current: dict) -> None:
    """Only fully counted model usage may change; attempted memory is not applied."""
    before, after = deepcopy(previous), deepcopy(current)
    old_usage, usage = before.pop("usage"), after.pop("usage")
    if before != after:
        raise ValueError("Rejected keyboard input changed memory or campaign configuration")
    if any(usage[key] != old_usage[key] + 1 for key in (
        "dispatched_requests", "returned_responses", "accounted_responses",
    )) or usage["total_tokens"] < old_usage["total_tokens"]:
        raise ValueError("Rejected keyboard input has unresolved model usage")
