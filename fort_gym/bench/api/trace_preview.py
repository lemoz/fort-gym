"""Bounded public preview extraction for completed run traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator


MAX_PREVIEW_TAIL_BYTES = 4 * 1024 * 1024
MAX_SCREEN_TEXT_CHARS = 128 * 1024


def _tail_lines(path: Path, *, max_bytes: int) -> Iterator[bytes]:
    """Yield complete tail lines newest-first without loading the whole trace."""

    size = path.stat().st_size
    read_size = min(size, max(1, int(max_bytes)))
    start = size - read_size
    with path.open("rb") as handle:
        handle.seek(start)
        payload = handle.read(read_size)
    if start > 0:
        newline = payload.find(b"\n")
        payload = payload[newline + 1 :] if newline >= 0 else b""
    yield from reversed(payload.splitlines())


def _screen_text(record: Dict[str, Any]) -> str | None:
    candidates = [
        # When a completed interaction records both sides of the transition,
        # the preview must show the resulting screen rather than the modal the
        # action just closed.
        record.get("screen_text_after_action"),
        record.get("screen_text_after_interaction"),
        record.get("screenTextAfterInteraction"),
        record.get("screen_text"),
        record.get("screenText"),
        (record.get("observation") or {}).get("screen_text")
        if isinstance(record.get("observation"), dict)
        else None,
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value[:MAX_SCREEN_TEXT_CHARS].replace("\r", "")

    observation_text = record.get("observation_text")
    if not isinstance(observation_text, str):
        return None
    screen_marker = "== SCREEN =="
    status_marker = "== STATUS =="
    start = observation_text.find(screen_marker)
    if start < 0:
        return None
    content_start = start + len(screen_marker)
    end = observation_text.find(status_marker, content_start)
    value = observation_text[content_start : end if end >= 0 else None].strip("\r\n")
    return value[:MAX_SCREEN_TEXT_CHARS].replace("\r", "") if value.strip() else None


def read_trace_preview(
    path: Path, *, max_bytes: int = MAX_PREVIEW_TAIL_BYTES
) -> Dict[str, Any]:
    """Return the latest recorded screen in a bounded trace tail.

    Derived map snapshots are intentionally ignored. A missing recorded screen
    remains an explicit evidence gap instead of being replaced with observer data.
    """

    if not path.is_file():
        raise FileNotFoundError(path)

    latest_step: int | None = None
    inspected_records = 0
    for raw_line in _tail_lines(path, max_bytes=max_bytes):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        inspected_records += 1
        step = record.get("step")
        if latest_step is None and isinstance(step, int) and not isinstance(step, bool):
            latest_step = step
        screen_text = _screen_text(record)
        if screen_text is not None:
            return {
                "step": step if isinstance(step, int) and not isinstance(step, bool) else latest_step,
                "screen_text": screen_text,
                "screen_status": "recorded",
                "inspected_records": inspected_records,
            }

    return {
        "step": latest_step,
        "screen_text": None,
        "screen_status": "not_reported",
        "inspected_records": inspected_records,
    }


__all__ = ["MAX_PREVIEW_TAIL_BYTES", "read_trace_preview"]
