from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run.storage import RunRegistry


def _create_run(registry: RunRegistry, run_id: str = "outbox-run") -> None:
    registry.create(
        backend="mock",
        model="random",
        max_steps=4,
        ticks_per_step=10,
        run_id=run_id,
    )


def test_two_registry_roles_share_monotonic_per_run_events(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    api_registry = RunRegistry(db_path=db_path)
    _create_run(api_registry)
    assert api_registry.claim_pending_run(
        "outbox-run",
        started_at=datetime.now(UTC),
    )
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)

    worker_registry.append_event(
        "outbox-run", {"t": "state", "data": {"source": "worker", "n": 1}}
    )
    api_registry.append_event(
        "outbox-run", {"t": "step", "data": {"source": "api", "n": 2}}
    )
    worker_registry.append_event(
        "outbox-run", {"t": "terminal", "data": {"source": "worker", "n": 3}}
    )

    for registry in (api_registry, worker_registry):
        events = registry.read_events_since("outbox-run")
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.payload["data"]["n"] for event in events] == [1, 2, 3]
        assert registry.get("outbox-run").status == "running"

    _create_run(api_registry, "other-run")
    worker_registry.append_event(
        "other-run", {"t": "state", "data": {"per_run": True}}
    )
    assert worker_registry.read_events_since("other-run")[0].sequence == 1


def test_concurrent_registry_writers_allocate_contiguous_sequences(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    owner = RunRegistry(db_path=db_path)
    _create_run(owner)
    first = RunRegistry(db_path=db_path, recover_interrupted=False)
    second = RunRegistry(db_path=db_path, recover_interrupted=False)
    assert first.get("outbox-run") is not None
    assert second.get("outbox-run") is not None
    barrier = threading.Barrier(2)

    def append_batch(registry: RunRegistry, source: str) -> None:
        barrier.wait()
        for index in range(10):
            registry.append_event(
                "outbox-run",
                {"t": "message", "data": {"source": source, "index": index}},
            )

    threads = [
        threading.Thread(target=append_batch, args=(first, "first")),
        threading.Thread(target=append_batch, args=(second, "second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events = owner.read_events_since("outbox-run", limit=100)
    assert [event.sequence for event in events] == list(range(1, 21))
    assert {
        (event.payload["data"]["source"], event.payload["data"]["index"])
        for event in events
    } == {(source, index) for source in ("first", "second") for index in range(10)}


def test_event_append_commits_before_legacy_queue_push(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    owner = RunRegistry(db_path=db_path)
    _create_run(owner)
    observer = RunRegistry(db_path=db_path, recover_interrupted=False)
    pushed: list[dict[str, Any]] = []

    class InspectingQueue:
        def put_nowait(self, payload: dict[str, Any]) -> None:
            persisted = observer.read_events_since("outbox-run")
            assert persisted[-1].payload == payload
            pushed.append(payload)

        def get_nowait(self) -> dict[str, Any]:
            raise asyncio.QueueEmpty

    owner._queues["outbox-run"] = InspectingQueue()  # type: ignore[assignment]
    owner.append_event("outbox-run", {"t": "state", "data": {"durable": True}})

    assert pushed == [{"t": "state", "data": {"durable": True}}]


def test_restart_replays_persisted_events(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    first = RunRegistry(db_path=db_path)
    _create_run(first)
    first.append_event("outbox-run", {"t": "state", "data": {"before": 1}})
    first.append_event("outbox-run", {"t": "state", "data": {"before": 2}})

    restarted = RunRegistry(db_path=db_path, recover_interrupted=False)
    events = restarted.read_events_since("outbox-run")

    assert [event.sequence for event in events] == [1, 2]
    assert [event.payload["data"]["before"] for event in events] == [1, 2]


def test_existing_database_adds_outbox_without_relabeling_run(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    legacy_registry = RunRegistry(db_path=db_path)
    _create_run(legacy_registry)

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE run_events")

    migrated_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    migrated_registry.append_event(
        "outbox-run", {"t": "state", "data": {"migrated": True}}
    )

    assert migrated_registry.get("outbox-run").status == "pending"
    assert migrated_registry.read_events_since("outbox-run")[0].payload == {
        "t": "state",
        "data": {"migrated": True},
    }


def test_read_since_paginates_without_duplicates(tmp_path: Path) -> None:
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    _create_run(registry)
    for index in range(5):
        registry.append_event(
            "outbox-run", {"t": "message", "data": {"index": index}}
        )

    first = registry.read_events_since("outbox-run", limit=2)
    second = registry.read_events_since(
        "outbox-run", after_sequence=first[-1].sequence, limit=2
    )
    third = registry.read_events_since(
        "outbox-run", after_sequence=second[-1].sequence, limit=2
    )
    pages = [*first, *second, *third]

    assert [event.sequence for event in pages] == [1, 2, 3, 4, 5]
    assert len({event.sequence for event in pages}) == 5
    assert registry.read_events_since(
        "outbox-run", after_sequence=pages[-1].sequence
    ) == []
    with pytest.raises(ValueError, match="after_sequence"):
        registry.read_events_since("outbox-run", after_sequence=-1)
    with pytest.raises(ValueError, match="limit"):
        registry.read_events_since("outbox-run", limit=0)


def test_read_since_caps_oversized_pages(tmp_path: Path) -> None:
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    _create_run(registry)
    for index in range(1001):
        registry.append_event(
            "outbox-run", {"t": "message", "data": {"index": index}}
        )

    first = registry.read_events_since("outbox-run", limit=10_000)
    second = registry.read_events_since(
        "outbox-run", after_sequence=first[-1].sequence, limit=10_000
    )

    assert len(first) == 1000
    assert [event.sequence for event in second] == [1001]


def test_terminal_row_and_legacy_score_queue_remain_compatible(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    registry = RunRegistry(db_path=db_path)
    _create_run(registry)
    queue = registry.get_queue("outbox-run")
    assert queue is not None

    registry.append_event(
        "outbox-run",
        {
            "t": "score",
            "data": {"total_score": 7.5, "milestones": {"shelter": True}},
        },
    )
    assert queue.get_nowait() == {
        "t": "score",
        "data": {"total_score": 7.5, "milestones": {"shelter": True}},
    }
    assert registry.get("outbox-run").metadata == {
        "last_score": 7.5,
        "milestones": {"shelter": True},
    }

    terminal_reason = {"code": "synthetic_terminal", "detail": "preserved"}
    registry.record_terminal_failure(
        "outbox-run",
        terminal_reason=terminal_reason,
        step=3,
        ended_at=datetime.now(UTC),
    )
    registry.append_event(
        "outbox-run", {"t": "terminal", "data": terminal_reason}
    )

    reopened = RunRegistry(db_path=db_path)
    terminal = reopened.get("outbox-run")
    assert terminal is not None
    assert terminal.status == "failed"
    assert terminal.step == 3
    assert terminal.metadata["terminal_reason"] == terminal_reason
    assert [event.payload["t"] for event in reopened.read_events_since("outbox-run")] == [
        "score",
        "terminal",
    ]
