"""Saved gameplay followed by a pre-dispatch pause, not a completed window."""

from pathlib import Path

from .campaign_keyboard_presave import _matches, _read
from .campaign_keyboard_windows import _counts, saved_window

PAUSED_WINDOWS = ("astra_native_keyboard_paused_window_20260910aa.json",)


def paused_window(root: Path, filename: str, parents: list[dict]) -> dict:
    source = _read(root, filename)
    row = saved_window(root, filename, parents, paused=True)
    pause = source.get("pause")
    if not isinstance(pause, dict):
        raise ValueError("Saved-window pause must be an object")
    counts = _counts(pause, (
        "decision_limit", "unattempted_decisions", "denied_request_index",
        "denied_request_tokens_added", "undispatched_requests",
        "previous_included_usage_cutoff_percent", "included_usage_cutoff_percent",
    ))
    flags = {
        "reason": "included_usage_headroom_threshold",
        "denied_request_dispatched": False, "api_fallback_used": False,
        "operating_policy_changed": True,
    }
    _matches(pause, flags)
    decisions = row["progress"]["new_model_responses"]
    if (not decisions < counts["decision_limit"] <= 1024
            or counts["unattempted_decisions"] != counts["decision_limit"] - decisions
            or counts["denied_request_index"] != decisions
            or counts["denied_request_tokens_added"] != 0
            or counts["undispatched_requests"] != 1
            or not 0 < counts["previous_included_usage_cutoff_percent"]
            < counts["included_usage_cutoff_percent"] < 100):
        raise ValueError("Saved-window pause does not reconcile with dispatched decisions")
    return {**row, "pause": {**counts, **flags}}
