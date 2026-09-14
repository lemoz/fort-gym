"""Synthetic structure checks, not native gameplay or checkpoint acceptance."""

import copy

import pytest

from fort_gym.bench.run.keyboard_window_audit import settled_segment_spans


def fixture(start=128, segments=2, pause=None):
    window = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "continuation_from_next_step": start,
        "steps_per_segment": 64,
        "max_segments": segments,
        "window_end_decision": start + 64 * segments,
        "expected_campaign_id": "synthetic-campaign",
        "source_native_revision": "a" * 40,
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
    }
    result = {
        "schema_version": "fortgym.keyboard-window-result/v1",
        "campaign_id": window["expected_campaign_id"],
        "source_revision": window["source_native_revision"],
        "status": "completed" if pause is None else "paused",
        "original_checkpoint_unchanged": True,
        "runtime_cleanup_verified": True,
        "segments": [],
    }
    for index in range(segments):
        count = 64 if pause is None or index < segments - 1 else pause
        result["segments"].append(
            {
                "schema_version": "fortgym.keyboard-segment/v1",
                "campaign_id": result["campaign_id"],
                "source_revision": result["source_revision"],
                "status": "bounded_segment_complete",
                "first_step": start + index * 64,
                "next_step": start + index * 64 + count,
                "stop_reason": "segment_limit"
                if count == 64
                else "budget_limited_pause",
                "checkpoint_verified": True,
                "recovery_requires_reconciliation": False,
            }
        )
    return result, window


@pytest.mark.parametrize(
    "start,count", [(64, 1), (128, 2), (256, 4), (512, 8), (1024, 4)]
)
def test_all_declared_stages_are_structurally_supported(start, count):
    result, window = fixture(start, count)
    original = copy.deepcopy((result, window))
    spans = settled_segment_spans(result, window)
    assert len(spans) == count and sum(s.responses for s in spans) == count * 64
    assert spans[0].first_step == start and spans[-1].next_step == start + count * 64
    assert (result, window) == original


@pytest.mark.parametrize("responses", [0, 1, 31, 63])
def test_pause_in_second_segment_retains_completed_prefix_and_exact_cursor(responses):
    result, window = fixture(pause=responses)
    spans = settled_segment_spans(result, window)
    assert [s.responses for s in spans] == [64, responses]
    assert spans[-1].next_step == 192 + responses


def test_pause_in_first_segment_does_not_require_unstarted_later_segments():
    result, window = fixture(pause=0)
    result["segments"] = [result["segments"][0]]
    result["segments"][0].update(next_step=128, stop_reason="budget_limited_pause")
    assert settled_segment_spans(result, window)[0].responses == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("first_step", 193),
        ("first_step", True),
        ("next_step", True),
        ("next_step", 257),
        ("next_step", 191),
        ("next_step", 255),
        ("checkpoint_verified", 1),
        ("recovery_requires_reconciliation", True),
        ("status", "failed"),
        ("campaign_id", "borrowed"),
        ("source_revision", "b" * 40),
        ("stop_reason", "provider_failure"),
        ("error_type", "TimeoutError"),
        ("discontinuities", [{"kind": "save_loss"}]),
    ],
)
def test_bad_last_segment_cannot_be_promoted(field, value):
    result, window = fixture()
    result["segments"][-1][field] = value
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("status", "paused"),
        ("segments", []),
        ("original_checkpoint_unchanged", 1),
        ("runtime_cleanup_verified", False),
        ("campaign_id", "borrowed"),
        ("source_revision", "b" * 40),
        ("error", "failure"),
    ],
)
def test_unsettled_window_cannot_be_promoted(field, value):
    result, window = fixture()
    result[field] = value
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)


def test_completed_window_cannot_omit_or_repeat_segment():
    result, window = fixture()
    result["segments"].pop()
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)
    result["segments"] *= 3
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)


def test_no_work_is_allowed_after_an_admission_pause():
    result, window = fixture(pause=1)
    result["segments"][0].update(next_step=129, stop_reason="budget_limited_pause")
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_segments", True),
        ("max_segments", 17),
        ("steps_per_segment", 65),
        ("continuation_from_next_step", 0),
        ("window_end_decision", 257),
        ("window_end_decision", True),
        ("reset_memory", True),
        ("budget_extension", {}),
    ],
)
def test_invalid_or_changed_window_is_rejected(field, value):
    result, window = fixture()
    window[field] = value
    with pytest.raises(ValueError):
        settled_segment_spans(result, window)
