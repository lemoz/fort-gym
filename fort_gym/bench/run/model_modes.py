"""Shared model-mode classification for DFHack control surfaces."""

from __future__ import annotations


GOVERNED_DFHACK_MODELS = frozenset(
    {
        "dfhack-governed-scripted",
        "dfhack-governed-llm",
        "dfhack-governed-llm-glm52",
        "dfhack-governed-llm-deepseek-v4",
        "dfhack-governed-llm-gpt55",
        "dfhack-governed-llm-fable5",
        "dfhack-governed-llm-gpt56-sol",
        "dfhack-governed-llm-glm5v",
        "dfhack-governed-llm-gpt55-vision",
        "dfhack-governed-llm-kimi-vision",
        "dfhack-governed-llm-minimax-vision",
        "dfhack-governed-llm-minimax-canary",
    }
)


def is_governed_dfhack_model(model: str) -> bool:
    """Return whether a model must use the serialized governed runner."""

    return str(model or "").lower() in GOVERNED_DFHACK_MODELS


__all__ = ["GOVERNED_DFHACK_MODELS", "is_governed_dfhack_model"]
