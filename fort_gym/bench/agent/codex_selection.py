"""Explicit subscription model identity, not an account-availability catalog."""

from __future__ import annotations

import re

MODEL = "gpt-6-astra"
REASONING_EFFORT = "medium"
EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})


def validate_selection(model: object, reasoning_effort: object) -> None:
    """Validate literal CLI values; the provider must still support the pair.

    This route never chooses a replacement model or a different provider. An
    unavailable selection is an inference failure, not permission to fall back.
    """
    if (
        not isinstance(model, str)
        or len(model) > 128
        or re.fullmatch(r"gpt-[a-z0-9]+(?:[.-][a-z0-9]+)*", model) is None
        or not isinstance(reasoning_effort, str)
        or reasoning_effort not in EFFORTS
    ):
        raise ValueError("Invalid explicit Codex model or reasoning effort")
