"""Typed rejection of a received keyboard response, never a replacement action."""

from __future__ import annotations

from copy import deepcopy

from ..env.native_key_catalog import NATIVE_PROFILE, keys_for_profile
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
