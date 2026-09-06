from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fort_gym.bench.api import server
from fort_gym.bench.run.storage import RunRegistry


def _create_run(registry: RunRegistry, run_id: str = "relay-run") -> None:
    registry.create(
        backend="mock",
        model="fake",
        max_steps=4,
        ticks_per_step=10,
        run_id=run_id,
    )


def _terminalize(registry: RunRegistry, run_id: str = "relay-run") -> None:
    registry.record_terminal_failure(
        run_id,
        terminal_reason={"code": "synthetic_terminal"},
        step=3,
        ended_at=datetime.now(UTC),
    )


def _client(monkeypatch: Any, registry: RunRegistry) -> TestClient:
    monkeypatch.setenv("FORT_GYM_INSECURE_ADMIN", "1")
    monkeypatch.setenv("FORT_GYM_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setattr(server, "RUN_REGISTRY", registry)
    return TestClient(server.app)


def _parse_sse(body: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        frame: dict[str, Any] = {}
        for line in block.splitlines():
            field, value = line.split(": ", 1)
            frame[field] = json.loads(value) if field == "data" else value
        frames.append(frame)
    return frames


def test_private_stream_reads_events_from_independent_worker_registry(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    api_registry = RunRegistry(db_path=db_path)
    _create_run(api_registry)
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    worker_registry.append_event(
        "relay-run", {"t": "state", "data": {"source": "worker"}}
    )
    worker_registry.append_event(
        "relay-run", {"t": "terminal", "data": {"code": "done"}}
    )
    _terminalize(worker_registry)

    local_queue = api_registry.get_queue("relay-run")
    assert local_queue is not None
    assert local_queue.empty()

    response = _client(monkeypatch, api_registry).get(
        "/runs/relay-run/events/stream"
    )

    assert response.status_code == 200
    assert _parse_sse(response.text) == [
        {"id": "1", "event": "state", "data": {"source": "worker"}},
        {"id": "2", "event": "terminal", "data": {"code": "done"}},
    ]


def test_public_stream_reads_independent_worker_events(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "runs.sqlite3"
    api_registry = RunRegistry(db_path=db_path)
    _create_run(api_registry)
    share = api_registry.create_share("relay-run", scope=["live"])
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    worker_registry.append_event(
        "relay-run", {"t": "score", "data": {"total_score": 2.5}}
    )
    _terminalize(worker_registry)

    response = _client(monkeypatch, api_registry).get(
        f"/public/runs/{share.token}/events/stream"
    )

    assert response.status_code == 200
    assert _parse_sse(response.text) == [
        {"id": "1", "event": "score", "data": {"total_score": 2.5}}
    ]


def test_stream_replays_after_api_registry_restart(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "runs.sqlite3"
    first_api_registry = RunRegistry(db_path=db_path)
    _create_run(first_api_registry)
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    worker_registry.append_event(
        "relay-run", {"t": "state", "data": {"before_restart": 1}}
    )
    worker_registry.append_event(
        "relay-run", {"t": "action", "data": {"before_restart": 2}}
    )
    _terminalize(worker_registry)

    restarted_api_registry = RunRegistry(db_path=db_path)
    assert restarted_api_registry.get_queue("relay-run") is None
    response = _client(monkeypatch, restarted_api_registry).get(
        "/runs/relay-run/events/stream"
    )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert [frame["id"] for frame in frames] == ["1", "2"]
    assert [frame["data"]["before_restart"] for frame in frames] == [1, 2]


def test_stream_cursor_orders_without_duplicates(tmp_path: Path, monkeypatch: Any) -> None:
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    _create_run(registry)
    for index in range(1, 4):
        registry.append_event(
            "relay-run", {"t": "message", "data": {"index": index}}
        )
    _terminalize(registry)
    client = _client(monkeypatch, registry)

    query_resume = client.get(
        "/runs/relay-run/events/stream", params={"after_sequence": 1}
    )
    header_resume = client.get(
        "/runs/relay-run/events/stream",
        params={"after_sequence": 1},
        headers={"Last-Event-ID": "2"},
    )

    query_frames = _parse_sse(query_resume.text)
    header_frames = _parse_sse(header_resume.text)
    assert [frame["id"] for frame in query_frames] == ["2", "3"]
    assert [frame["data"]["index"] for frame in query_frames] == [2, 3]
    assert [frame["id"] for frame in header_frames] == ["3"]
    assert len({frame["id"] for frame in query_frames}) == 2


def test_terminal_stream_closes_without_synthetic_end_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    _create_run(registry)
    registry.append_event(
        "relay-run", {"t": "terminal", "data": {"status": "failed"}}
    )
    _terminalize(registry)

    response = _client(monkeypatch, registry).get(
        "/runs/relay-run/events/stream"
    )

    assert response.status_code == 200
    assert _parse_sse(response.text) == [
        {"id": "1", "event": "terminal", "data": {"status": "failed"}}
    ]
    assert "event: end" not in response.text


def test_terminal_boundary_performs_final_durable_read(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    registry = RunRegistry(db_path=db_path)
    _create_run(registry)
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    original_get = registry.get
    terminalized = False

    def get_after_worker_finishes(run_id: str):
        nonlocal terminalized
        if not terminalized:
            terminalized = True
            worker_registry.append_event(
                run_id, {"t": "terminal", "data": {"boundary": True}}
            )
            _terminalize(worker_registry, run_id)
        return original_get(run_id)

    monkeypatch.setattr(registry, "get", get_after_worker_finishes)
    monkeypatch.setattr(server, "RUN_REGISTRY", registry)

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def collect() -> list[str]:
        return [
            frame
            async for frame in server._stream_run_events(
                ConnectedRequest(),  # type: ignore[arg-type]
                "relay-run",
            )
        ]

    assert _parse_sse("".join(asyncio.run(collect()))) == [
        {"id": "1", "event": "terminal", "data": {"boundary": True}}
    ]


def test_stream_cancellation_remains_quiet(tmp_path: Path, monkeypatch: Any) -> None:
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    _create_run(registry)
    monkeypatch.setattr(server, "RUN_REGISTRY", registry)

    class CancelledRequest:
        async def is_disconnected(self) -> bool:
            raise asyncio.CancelledError

    async def collect() -> list[str]:
        return [
            frame
            async for frame in server._stream_run_events(
                CancelledRequest(),  # type: ignore[arg-type]
                "relay-run",
            )
        ]

    assert asyncio.run(collect()) == []
