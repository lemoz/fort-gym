from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api.server import app
from fort_gym.bench.api import routes_step
from fort_gym.bench.run.storage import RUN_REGISTRY


@dataclass
class _StubDFHackClient:
    host: str | None = None
    port: int | None = None

    def __post_init__(self) -> None:
        self._ticks = 0
        self._tick_info: Dict[str, Any] = {}

    def connect(self) -> None:  # pragma: no cover - stub
        return

    def close(self) -> None:  # pragma: no cover - stub
        return

    def pause(self) -> None:  # pragma: no cover - stub
        return

    def get_state(self) -> Dict[str, Any]:
        return {
            "time": self._ticks,
            "population": 0,
            "stocks": {"food": 0, "drink": 0, "wood": 0, "stone": 0, "wealth": 0},
            "risks": [],
            "reminders": [],
            "recent_events": [],
            "hostiles": False,
            "dead": 0,
            "map_bounds": (100, 100, 10),
        }

    def advance(self, ticks: int) -> Dict[str, Any]:
        self._ticks += ticks
        self._tick_info = {"ok": True, "requested": ticks, "ticks_advanced": ticks}
        return self.get_state()

    def designate_rect(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": True}

    def queue_manager_order(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": True}

    @property
    def last_tick_info(self) -> Dict[str, Any]:
        return self._tick_info


@pytest.fixture(autouse=True)
def _clean_state():
    with RUN_REGISTRY._lock:  # type: ignore[attr-defined]
        RUN_REGISTRY._runs.clear()  # type: ignore[attr-defined]
        RUN_REGISTRY._shares.clear()  # type: ignore[attr-defined]
        RUN_REGISTRY._shares_by_run.clear()  # type: ignore[attr-defined]
    routes_step._reset_step_contexts_for_tests()
    yield
    with RUN_REGISTRY._lock:  # type: ignore[attr-defined]
        RUN_REGISTRY._runs.clear()  # type: ignore[attr-defined]
        RUN_REGISTRY._shares.clear()  # type: ignore[attr-defined]
        RUN_REGISTRY._shares_by_run.clear()  # type: ignore[attr-defined]
    routes_step._reset_step_contexts_for_tests()


@pytest.fixture
def client(tmp_path, monkeypatch):
    stub_settings = SimpleNamespace(
        DFHACK_ENABLED=True,
        DFHACK_HOST="127.0.0.1",
        DFHACK_PORT=5000,
        TICKS_PER_STEP=200,
        ARTIFACTS_DIR=str(tmp_path),
    )
    monkeypatch.setattr(routes_step, "get_settings", lambda: stub_settings)
    monkeypatch.setattr("fort_gym.bench.config.get_settings", lambda: stub_settings)
    monkeypatch.setattr(routes_step, "DFHackClient", _StubDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_designate_rect",
        lambda *args, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_queue_manager_order",
        lambda *args, **kwargs: {"ok": True},
    )
    return TestClient(app)


def _register_run(max_steps: int = 5) -> str:
    run_id = uuid.uuid4().hex
    RUN_REGISTRY.create(
        backend="dfhack",
        model="fake",
        max_steps=max_steps,
        ticks_per_step=500,
        run_id=run_id,
    )
    return run_id


def test_step_enforces_rate_limit(client: TestClient):
    run_id = _register_run()
    payload = {
        "run_id": run_id,
        "action": {"type": "DIG", "params": {"area": [0, 0, 0], "size": [1, 1, 1]}},
        "min_step_period_ms": 1000,
        "max_ticks": 100,
    }

    first = client.post("/step", json=payload)
    assert first.status_code == 200

    second = client.post("/step", json=payload)
    assert second.status_code == 429


def test_step_updates_artifacts_and_sse(client: TestClient, tmp_path):
    run_id = _register_run()
    payload = {
        "run_id": run_id,
        "action": {"type": "DIG", "params": {"area": [0, 0, 0], "size": [1, 1, 1]}},
        "min_step_period_ms": 200,
        "max_ticks": 100,
    }

    response = client.post("/step", json=payload)
    assert response.status_code == 200

    body = response.json()
    assert body["reward"] == pytest.approx(body["info"]["reward_cum"])
    assert body["done"] is False
    assert body["info"]["tick_advance"]["ok"] is True
    assert body["info"]["tick_advance"]["ticks_advanced"] == 100

    summary_path = tmp_path / run_id / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["steps"] == 1
    assert "reward_cum" in summary

    trace_path = tmp_path / run_id / "trace.jsonl"
    assert trace_path.exists()
    with trace_path.open() as handle:
        lines = handle.readlines()
    assert len(lines) == 1

    queue = RUN_REGISTRY.get_queue(run_id)
    assert queue is not None
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert any(evt.get("t") == "step" for evt in events)
    assert any(
        evt.get("t") == "advance" and "tick_advance" in evt.get("data", {})
        for evt in events
    )
