"""Do not turn the observed load-log exception into a blanket changed-file allowance."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments/keyboard_binding_reload_20260911/review_log_delta.py"
)
spec = importlib.util.spec_from_file_location("binding_reload_log_delta", PATH)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def row(name, raw):
    return {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def example():
    before = b"original log\n"
    prefix = b"[2026-09-11T08:58:03+0000] DFHack 0.47.05-r8-0-gfed9f763 on Linux; cwd md5: 5abf9e8477; save: campaign-resume; "
    after = before + b"".join(
        prefix + event + b"; game type DWARF_MAIN (0)\n"
        for event in (b"SC_WORLD_LOADED", b"SC_MAP_LOADED")
    )
    return (
        [row("world.sav", b"world"), row(review.LOG, before)],
        [row("world.sav", b"world"), row(review.LOG, after)],
        before,
        after,
    )


def test_only_exact_load_events_are_accepted_with_original_prefix():
    result = review.verify_delta(*example())
    assert result["appended_bytes"] == 304
    assert result["non_log_files_byte_identical"] == 1
    assert result["whole_copied_save_tree_byte_identical"] is False
    assert result["appended_events"] == ["SC_WORLD_LOADED", "SC_MAP_LOADED"]


@pytest.mark.parametrize(
    "change",
    ["world", "extra", "missing", "prefix", "third_line", "different_event", "wrong_order", "hash"],
)
def test_any_unexplained_delta_is_rejected(change):
    expected, actual, before, after = deepcopy(example())
    if change == "world":
        actual[0] = row("world.sav", b"changed")
    elif change == "extra":
        actual.append(row("another.log", b"new"))
    elif change == "missing":
        actual = actual[1:]
    elif change == "prefix":
        after = b"CHANGED" + after[len(before) :]
    elif change == "third_line":
        after += b"unexpected activity\n"
    elif change == "different_event":
        after = after.replace(b"SC_MAP_LOADED", b"SC_GAMEPLAY_X")
    elif change == "wrong_order":
        lines = after[len(before) :].splitlines(keepends=True)
        after = before + b"".join(reversed(lines))
    elif change == "hash":
        actual[-1]["sha256"] = "0" * 64
    if change in {"prefix", "third_line", "different_event", "wrong_order"}:
        actual[-1] = row(review.LOG, after)
    with pytest.raises(ValueError):
        review.verify_delta(expected, actual, before, after)
