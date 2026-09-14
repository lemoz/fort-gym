"""The progress reader never materializes the complete growing campaign trace."""

import json
import tracemalloc

import pytest

from scripts.campaign_trace_summary import MAX_LINE_BYTES, summarize


def record(step, ticks=100, **extra):
    return (
        json.dumps(
            {
                "step": step,
                "tick_advance": {"ticks_advanced": ticks},
                "state_after_advance": {"population": 12, "dead": 0},
                **extra,
            }
        ).encode()
        + b"\n"
    )


def test_summary_is_committed_progress_not_a_checkpoint(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(record(0) + record(1, 0) + record(2, 300))
    result = summarize(path, starting_step=1)
    assert result["committed_decisions"] == 2
    assert result["committed_ticks"] == 300
    assert result["trace_next_step"] == 3
    assert result["last_population"] == 12
    assert result["checkpoint_verified"] is False
    assert result["game_calls"] == result["model_calls"] == 0


def test_partial_last_record_is_not_promoted(tmp_path):
    path = tmp_path / "trace.jsonl"
    tail = b'{"step": 1'
    path.write_bytes(record(0) + tail)
    result = summarize(path)
    assert result["committed_decisions"] == 1
    assert result["ignored_incomplete_tail_bytes"] == len(tail)


@pytest.mark.parametrize(
    "content",
    [
        record(0) + record(2),
        record(True),
        record(-1),
        record(0, -1),
        record(0, True),
        b"{}\n",
        b"[]\n",
        b"not json\n",
        record(0, state_after_advance=[]),
        record(0, discontinuities={}),
    ],
)
def test_malformed_committed_records_fail(tmp_path, content):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        summarize(path)


@pytest.mark.parametrize("starting_step", [-1, True, 1.5])
def test_invalid_start_fails(tmp_path, starting_step):
    with pytest.raises(ValueError):
        summarize(tmp_path / "unused", starting_step=starting_step)


def test_oversized_record_fails_before_json_allocation(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(b"x" * (MAX_LINE_BYTES + 1))
    with pytest.raises(ValueError, match="bounded diagnostic limit"):
        summarize(path)


def test_empty_trace_has_no_cursor(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(b"")
    result = summarize(path)
    assert result["trace_next_step"] is None
    assert result["committed_decisions"] == result["committed_ticks"] == 0


def test_memory_does_not_scale_with_file_length(tmp_path):
    path = tmp_path / "trace.jsonl"
    with path.open("wb") as stream:
        for step in range(2500):
            stream.write(record(step, screen_padding="x" * 16384))
    assert path.stat().st_size > 40_000_000
    tracemalloc.start()
    try:
        result = summarize(path, starting_step=2400)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["committed_decisions"] == 100
    assert peak < 2_000_000
