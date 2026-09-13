"""Replay offsets are not a reset of saved campaign time or usage."""

import pytest

from scripts.export_displayed_key_recording import reviewed_window


@pytest.fixture
def continuation():
    return {
        "schema_version": "fortgym.private-matched-window-terminal-review/v1",
        "passed": True,
        "status": "completed",
        "native_cleanup_verified": True,
        "vm_teardown_verified": True,
        "human_gameplay_rescue": False,
        "responses": 128,
        "first_step": 64,
        "next_step": 128,
        "new_responses": 64,
        "new_saved_elapsed_ticks": 116000,
        "saved_elapsed_ticks": 120200,
        "source_checkpoint_fresh_load_verified": True,
    }


def test_own_save_replay_preserves_offset_and_counts_only_new_elapsed_time(continuation):
    assert reviewed_window(continuation) == (64, 128, 116000, "native_keyboard_bindings/v1")


def test_fresh_export_keeps_its_original_boundary(continuation):
    continuation.update(
        schema_version="fortgym.private-binding-trial-terminal-review/v1",
        responses=64,
        saved_elapsed_ticks=4200,
        control_profile="native_keyboard_bindings/v1",
    )
    assert reviewed_window(continuation) == (0, 64, 4200, "native_keyboard_bindings/v1")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "unknown"),
        ("passed", False),
        ("status", "paused"),
        ("native_cleanup_verified", False),
        ("vm_teardown_verified", False),
        ("human_gameplay_rescue", True),
        ("source_checkpoint_fresh_load_verified", False),
        ("source_checkpoint_fresh_load_verified", 1),
        ("first_step", 0),
        ("first_step", True),
        ("new_responses", 128),
        ("next_step", 64),
        ("responses", 127),
        ("responses", True),
        ("saved_elapsed_ticks", 115999),
        ("new_saved_elapsed_ticks", -1),
        ("new_saved_elapsed_ticks", None),
        ("new_saved_elapsed_ticks", True),
    ],
)
def test_incomplete_or_rebased_continuations_are_not_exported(continuation, field, value):
    continuation[field] = value
    with pytest.raises(ValueError):
        reviewed_window(continuation)
