"""Server-Sent Event helpers."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Iterator

from fastapi import Request


def sse_event(event_type: str, data: Dict) -> str:
    """Serialize an SSE frame for the provided payload."""

    return f"event: {event_type}\n" f"data: {json.dumps(data)}\n\n"


async def stream_queue(
    request: Request,
    queue: asyncio.Queue[Dict[str, Any]],
    *,
    heartbeat: float = 5.0,
) -> AsyncGenerator[str, None]:
    """Yield frames from an asyncio queue until the client disconnects."""

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except asyncio.TimeoutError:
                yield sse_event("heartbeat", {"ts": datetime.utcnow().isoformat() + "Z"})
                continue

            event_type = item.get("t", "message")
            data = item.get("data", {})
            yield sse_event(event_type, data)
    except asyncio.CancelledError:
        pass


def ndjson_iter(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield JSON objects from a newline-delimited JSON file."""

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
