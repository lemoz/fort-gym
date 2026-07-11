"""Evaluation protocol validation shared by run entry points."""

from __future__ import annotations

import re


# Stable, URL-safe protocol labels such as ``fort-eval-v1`` or ``suite.2026-07``.
EVALUATION_PROTOCOL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


def validate_evaluation_protocol(value: str | None) -> str | None:
    """Return a valid optional protocol label or raise ``ValueError``."""

    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(EVALUATION_PROTOCOL_PATTERN, value) is None:
        raise ValueError(
            "evaluation_protocol must be a 1-64 character token containing only "
            "letters, digits, '.', '_', or '-'"
        )
    return value


__all__ = ["EVALUATION_PROTOCOL_PATTERN", "validate_evaluation_protocol"]
