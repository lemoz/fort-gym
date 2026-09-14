"""The predeclared completed-segment audit cannot relabel short work as 64 replies."""

import importlib.util
from pathlib import Path

import pytest

PLAN = (
    Path(__file__).resolve().parents[1]
    / "experiments/keyboard_binding_comparison_20260911"
)


@pytest.fixture
def review():
    spec = importlib.util.spec_from_file_location(
        "comparison_review", PLAN / "terminal_review.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "status,count,reason",
    [
        ("completed", 64, "segment_limit"),
        ("paused", 1, "budget_limited_pause"),
        ("paused", 63, "budget_limited_pause"),
    ],
)
def test_valid_bounded_result_shape(review, status, count, reason):
    segment = {
        "status": "bounded_segment_complete",
        "first_step": 0,
        "next_step": count,
        "stop_reason": reason,
    }
    assert review.verify_shape({"status": status, "segment": segment}) == segment


@pytest.mark.parametrize(
    "status,count,reason",
    [
        ("completed", 32, "segment_limit"),
        ("completed", 65, "segment_limit"),
        ("completed", 64, "budget_limited_pause"),
        ("paused", 64, "budget_limited_pause"),
        ("paused", 0, "budget_limited_pause"),
        ("failed", 10, "error"),
    ],
)
def test_incomplete_or_failed_attempt_is_not_certified_as_completed(
    review, status, count, reason
):
    with pytest.raises(AssertionError):
        review.verify_shape(
            {
                "status": status,
                "segment": {
                    "status": "bounded_segment_complete",
                    "first_step": 0,
                    "next_step": count,
                    "stop_reason": reason,
                },
            }
        )


def test_teardown_requires_observed_stopped_state(review):
    evidence = {
        "guest_poweroff_returncode": 255,
        "vm_stop_returncode": 0,
        "vm_observed_stopped": True,
    }
    assert review.verify_teardown(evidence)["guest_command_warning"] is True
    evidence["vm_observed_stopped"] = False
    with pytest.raises(AssertionError):
        review.verify_teardown(evidence)
