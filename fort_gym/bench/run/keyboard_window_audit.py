"""Validate terminal window segment structure before private evidence auditing.

This is not a native-save, provider-receipt or teardown verifier. It determines
which declared segments a full auditor must inspect, including a final pause.
"""

from dataclasses import dataclass
import re

from .keyboard_config import positive
from .keyboard_restart import validate_discontinuities


@dataclass(frozen=True)
class SegmentSpan:
    index: int
    first_step: int
    next_step: int

    @property
    def responses(self) -> int:
        return self.next_step - self.first_step


def settled_segment_spans(
    result: dict, window: dict, *, inherited_discontinuities: list[dict] | None = None,
) -> tuple[SegmentSpan, ...]:
    """Reject gaps or new loss; the caller must bind history to a verified parent."""
    history = validate_discontinuities(
        [] if inherited_discontinuities is None else inherited_discontinuities
    )
    start = positive(window.get("continuation_from_next_step"), "continuation cursor")
    steps = positive(window.get("steps_per_segment"), "segment size", maximum=64)
    maximum = positive(window.get("max_segments"), "segment count", maximum=16)
    revision, identity = (
        window.get("source_native_revision"),
        window.get("expected_campaign_id"),
    )
    if (
        window.get("schema_version") != "fortgym.codex-keyboard-window/v1"
        or not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or not isinstance(identity, str)
        or not identity
        or any(
            window.get(k) is not False
            for k in ("reset_memory", "reset_usage", "strategy_intervention")
        )
        or {"restart", "prompt_change", "budget_extension"} & window.keys()
        or type(window.get("window_end_decision")) is not int
        or window["window_end_decision"] != start + steps * maximum
    ):
        raise ValueError("An unchanged declared endurance window is required")
    segments = result.get("segments")
    if (
        result.get("schema_version") != "fortgym.keyboard-window-result/v1"
        or result.get("source_revision") != revision
        or result.get("campaign_id") != identity
        or result.get("status") not in {"completed", "paused"}
        or result.get("original_checkpoint_unchanged") is not True
        or result.get("runtime_cleanup_verified") is not True
        or "error_type" in result
        or "error" in result
        or not isinstance(segments, list)
        or not 1 <= len(segments) <= maximum
    ):
        raise ValueError("Window is not a settled completed or paused segment sequence")
    spans = []
    for index, segment in enumerate(segments):
        first = start + index * steps
        if not isinstance(segment, dict):
            raise ValueError("Malformed native segment")
        end, reason = segment.get("next_step"), segment.get("stop_reason")
        if (
            segment.get("schema_version") != "fortgym.keyboard-segment/v1"
            or segment.get("campaign_id") != identity
            or segment.get("source_revision") != revision
            or segment.get("status") != "bounded_segment_complete"
            or type(segment.get("first_step")) is not int
            or segment["first_step"] != first
            or type(end) is not int
            or not first <= end <= first + steps
            or segment.get("checkpoint_verified") is not True
            or segment.get("recovery_requires_reconciliation") is not False
            or segment.get("discontinuities", []) != history
            or any(k.endswith("error") or k.endswith("error_type") for k in segment)
        ):
            raise ValueError(
                "Native segment has a gap, changed identity or unsettled checkpoint"
            )
        if reason == "segment_limit":
            if end != first + steps:
                raise ValueError(
                    "A completed segment must retain every declared response"
                )
        elif reason == "budget_limited_pause":
            if (
                end == first + steps
                or index != len(segments) - 1
                or result["status"] != "paused"
            ):
                raise ValueError(
                    "Only the final incomplete segment may be an admission pause"
                )
        else:
            raise ValueError("Failure is not an admission pause or a completed segment")
        spans.append(SegmentSpan(index, first, end))
    if result["status"] == "completed":
        if len(segments) != maximum or segments[-1]["stop_reason"] != "segment_limit":
            raise ValueError(
                "A completed window must contain its entire declared segment sequence"
            )
    elif segments[-1]["stop_reason"] != "budget_limited_pause":
        raise ValueError(
            "A paused window must retain its final admission-pause segment"
        )
    return tuple(spans)
