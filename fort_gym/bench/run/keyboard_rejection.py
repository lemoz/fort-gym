"""Commit an unsupported-key response as feedback with no native action or clock."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from ..agent.keyboard_rejection import KeyboardInputRejected

if TYPE_CHECKING:
    from .campaign_loop import CampaignLoop


def commit_rejection(
    loop: CampaignLoop,
    rejection: KeyboardInputRejected,
    *,
    before: dict,
    after: dict,
    observation: dict,
    text: str,
    screen: str,
) -> dict:
    from .campaign_loop import _append, reconciled_usage
    from .runner import _action_history_entry

    current = loop.agent.export_campaign_state()
    if reconciled_usage(current, loop.journal.read_bytes()) != current["usage"]:
        raise ValueError("Rejected keyboard usage does not reconcile")
    row = rejection_record(
        campaign_id=loop.campaign_id, step=loop.next_step, rejection=rejection,
        before=before, after=after, observation=observation, text=text, screen=screen,
        events=loop.agent.pop_tool_events(),
    )
    history = _action_history_entry(
        step=loop.next_step, action=row["action"],
        requested_ticks=row["action"]["advance_ticks"],
        tick_info=row["tick_advance"], execute_result=row["execute"], state_before=before,
        advance_state=after, metrics_snapshot={},
    )
    _append(loop.trace, row)
    loop.history = (loop.history + [history])[-12:]
    loop.last_result = row["execute"]
    loop.next_step += 1
    loop.at_boundary = True
    return row


def rejection_record(
    *, campaign_id: str, step: int, rejection: KeyboardInputRejected, before: dict,
    after: dict, observation: dict, text: str, screen: str, events: list[dict],
) -> dict:
    """Build factual rejection evidence, shared by live and historical handling."""
    action = deepcopy(rejection.action)
    tick_info = {
        "schema_version": "fortgym.no-native-dispatch/v1",
        "ok": False,
        "error": "unsupported_native_keys",
        "requested": action["advance_ticks"],
        "ticks_advanced": 0,
        "clock_dispatched": False,
        "start_year": before["year"],
        "start_tick": before["year_tick"],
        "end_year": after["year"],
        "end_tick": after["year_tick"],
        "paused_before": True,
        "paused_after": True,
    }
    execution = {
        "accepted": False,
        "validation_rejected": True,
        "why": str(rejection),
        "result": {
            "ok": False,
            "command_mutation": "not_attempted",
            "keys_sent": 0,
            "keys_confirmed": 0,
            "native_action_dispatched": False,
            "invalid_keys": rejection.invalid_keys,
        },
        "tick_feedback": {
            "requested_ticks": action["advance_ticks"],
            "ticks_advanced": 0,
            "deferred": False,
            "clock_dispatched": False,
            "reason": "unsupported_native_keys",
        },
    }
    return {
        "run_id": campaign_id,
        "step": step,
        "campaign_mode": True,
        "record_origin": "model_input_rejection/v1",
        "observation": observation,
        "observation_text": text,
        "screen_text": screen,
        "action": action,
        "execute": execution,
        "state_after_advance": after,
        "tick_advance": tick_info,
        "events": [{"type": "tool_call", "data": {
            **event, "run_id": campaign_id, "step": step,
        }} for event in events],
    }
