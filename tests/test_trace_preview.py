from __future__ import annotations

import json
from pathlib import Path

import pytest

from fort_gym.bench.api.trace_preview import read_trace_preview


def _write_rows(path: Path, *rows: dict) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_trace_preview_returns_latest_recorded_screen(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_rows(
        path,
        {"step": 1, "screen_text": "old frame"},
        {"step": 2, "map_snapshot": {"ok": True}},
        {"step": 3, "observation": {"screen_text": "new frame\r\n"}},
    )

    assert read_trace_preview(path) == {
        "step": 3,
        "screen_text": "new frame\n",
        "screen_status": "recorded",
        "inspected_records": 1,
    }


def test_trace_preview_prefers_post_interaction_screen(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_rows(
        path,
        {
            "step": 173,
            "screen_text": "announcement before cancel",
            "screen_text_after_interaction": "fortress map after cancel\r\n",
        },
    )

    assert read_trace_preview(path) == {
        "step": 173,
        "screen_text": "fortress map after cancel\n",
        "screen_status": "recorded",
        "inspected_records": 1,
    }


def test_trace_preview_never_substitutes_a_derived_map(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_rows(path, {"step": 8, "map_snapshot": {"ok": True, "tiles": [{"char": "W"}]}})

    assert read_trace_preview(path) == {
        "step": 8,
        "screen_text": None,
        "screen_status": "not_reported",
        "inspected_records": 1,
    }


def test_trace_preview_discards_partial_first_tail_line(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_rows(
        path,
        {"step": 1, "screen_text": "x" * 4000},
        {"step": 2, "screen_text": "bounded latest"},
    )

    assert read_trace_preview(path, max_bytes=200)["screen_text"] == "bounded latest"


def test_trace_preview_supports_legacy_observation_text(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_rows(
        path,
        {"step": 4, "observation_text": "== SCREEN ==\nframe text\n== STATUS ==\nstatus"},
    )

    assert read_trace_preview(path)["screen_text"] == "frame text"


def test_trace_preview_requires_existing_trace(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_trace_preview(tmp_path / "missing.jsonl")
