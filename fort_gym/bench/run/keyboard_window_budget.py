"""Checkpoint-bound budgets for portable continuation windows.

The original condition never changes. A v2 window declares the budget already
present in its parent and may append one increase at that exact checkpoint.
This is budget bookkeeping, not permission to spend, change runtimes or play.
"""

from copy import deepcopy
import re

from ..agent.campaign_budget import BUDGET_KEYS, effective_budget
from ..agent.campaign_keyboard import CodexKeyboardAgent

WINDOW_V2 = "fortgym.codex-keyboard-window/v2"


def limits(value: object) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != set(BUDGET_KEYS)
        or any(type(value[key]) is not int or value[key] < 1 for key in BUDGET_KEYS)
    ):
        raise ValueError("Window budgets need positive integer cumulative limits")
    return dict(value)


def declared_limits(window: dict) -> dict:
    """Validate v2's declaration; the owner must separately bind the parent."""
    checkpoint = window.get("continuation_checkpoint_sha256")
    if (
        window.get("schema_version") != WINDOW_V2
        or not isinstance(checkpoint, str)
        or re.fullmatch(r"[a-f0-9]{64}", checkpoint) is None
        or any(window.get(k) is not False for k in
               ("reset_memory", "reset_usage", "strategy_intervention"))
        or {"restart", "prompt_change"} & window.keys()
    ):
        raise ValueError("A budget window must preserve its exact parent and strategy")
    before = limits(window.get("budget_before"))
    if "budget_extension" not in window:
        return before
    after = limits(window["budget_extension"])
    if after == before or any(after[k] < before[k] for k in BUDGET_KEYS):
        raise ValueError("Declared budgets must increase without reducing another limit")
    return after


def appended_budget_state(state: dict, checkpoint_sha256: str, extension: dict | None) -> dict:
    """Return the exact state expected before play, without changing the parent."""
    if extension is None:
        return deepcopy(state)
    agent = CodexKeyboardAgent(
        decision=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Offline only")),
        **{key: state["configuration"][key] for key in
           ("model", "reasoning_effort", "control_profile", "max_dispatches",
            "max_total_tokens", "max_advance_ticks")},
    )
    agent.restore_campaign_state(state, campaign_id=state["campaign_id"])
    agent.extend_budget(checkpoint_sha256=checkpoint_sha256, **limits(extension))
    return agent.export_campaign_state()


def verify_checkpoint_budget(state: dict, window: dict, checkpoint_sha256: str) -> dict:
    """Bind declared limits and a possible append to verified, settled state."""
    after = declared_limits(window)
    before = effective_budget(
        state["configuration"], state.get("budget_extensions", []), state["usage"]
    )
    if (window["continuation_checkpoint_sha256"] != checkpoint_sha256
            or limits(window["budget_before"]) != before):
        raise ValueError("Declared budget differs from the exact parent checkpoint")
    expected = appended_budget_state(state, checkpoint_sha256, window.get("budget_extension"))
    actual = effective_budget(
        expected["configuration"], expected.get("budget_extensions", []), expected["usage"]
    )
    if actual != after:
        raise ValueError("Budget extension does not match its declared cumulative limits")
    return expected
