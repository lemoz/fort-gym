"""Declared, non-strategic projection of redundant campaign prompt history.

Current native facts and the latest command result are never shortened. Raw traces
and checkpoint memory stay unchanged. Only older per-action details and duplicate
recent-memory text are omitted, with the projection visible to the model.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

from ..env.campaign_encoder import PROFILE, render_campaign_observation

PACKING = "bounded_history/v1"
OMITTED_HISTORY_FIELDS = ("result_details", "failed_targets", "placed_targets")


def project_observation(observation: dict, keep: int) -> dict:
    history = observation.get("action_history")
    if observation.get("observation_profile") != PROFILE or not isinstance(history, list):
        raise ValueError("Prompt packing requires a factual campaign observation")
    if any(not isinstance(row, dict) for row in history):
        raise ValueError("Prompt history contains an invalid action record")
    if type(keep) is not int or not 0 <= keep <= min(len(history), 12):
        raise ValueError("Invalid retained prompt history count")
    result = deepcopy(observation)
    result["action_history"] = [
        {key: value for key, value in row.items() if key not in OMITTED_HISTORY_FIELDS}
        for row in (result["action_history"][-keep:] if keep else [])
    ]
    result["prompt_projection"] = {
        "schema_version": "fortgym.campaign-prompt-projection/v1",
        "packing": PACKING,
        "history_rows_available": len(history),
        "history_rows_retained": keep,
        "history_rows_omitted": len(history) - keep,
        "prior_action_fields_omitted": list(OMITTED_HISTORY_FIELDS),
        "duplicate_recent_memory_text_omitted": True,
        "current_native_facts_preserved": True,
        "latest_command_result_preserved": True,
        "full_trace_and_checkpoint_memory_retained": True,
    }
    return result


def pack_messages(
    observation: dict,
    *,
    system_prompt: str,
    memory_context: str,
    fits: Callable[[list[dict]], bool],
) -> list[dict] | None:
    """Keep the largest newest history suffix fitting the caller's exact request.

    Never shorten the current snapshot to manufacture a fitting prompt. None
    means its irreducible facts do not fit; the caller must pause before dispatch.
    """
    history = observation.get("action_history")
    if not isinstance(history, list):
        raise ValueError("Prompt packing requires explicit action history")
    for keep in range(min(len(history), 12), -1, -1):
        selected = project_observation(observation, keep)
        text = render_campaign_observation(selected, compact=True)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{memory_context}\n\n{text}" if memory_context else text},
        ]
        if fits(messages):
            return messages
    return None
