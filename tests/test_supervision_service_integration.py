from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervision_service import (
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionService,
)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_provider_free_service_owns_one_external_mock_worker_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the concrete service/manager/supervisor/CLI/SQLite chain."""

    repo_root = Path(__file__).resolve().parents[1]
    run_id = "service-integration-run"
    artifacts_root = (tmp_path / "gameplay-artifacts").resolve()
    control_root = (tmp_path / "parent-control").resolve()
    db_path = (tmp_path / "shared.sqlite3").resolve()
    dfroot = (tmp_path / "unused-dfroot").resolve()
    dfroot.mkdir()

    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-openrouter-must-not-reach-child")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-must-not-reach-child")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic-must-not-reach-child")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    config = ServiceConfig(
        db_path=db_path,
        artifacts_root=artifacts_root,
        control_root=control_root,
        repo_root=repo_root,
        python_executable=Path(sys.executable),
        entrypoint_path=(repo_root / "infra/m1b/runtime_entrypoint.sh").resolve(),
        dfroot=dfroot,
        code_sha256="a" * 64,
        timeout_seconds=30.0,
        term_grace_seconds=1.0,
        poll_interval_seconds=0.01,
    )
    registry = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    )
    service = SupervisionService(
        registry=registry,
        config=config,
        id_factory=lambda: run_id,
        nonce_factory=lambda: "b" * 32,
    )

    results = service.run_blocking(
        SupervisedRunRequest(
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=1,
        )
    )

    assert set(results) == {run_id}
    result = results[run_id]
    assert result.run_id == run_id
    assert result.status == "completed"
    assert result.finalized is True
    assert result.returncode == 0
    assert result.reason == {
        "code": "external_worker_completed",
        "returncode": 0,
        "late_stop_observed": False,
    }

    run_control = control_root / run_id
    attempt_dir = run_control / "attempts" / "attempt-0001"
    gameplay_dir = artifacts_root / run_id
    assert result.control_dir == run_control
    assert not run_control.is_relative_to(artifacts_root)
    assert not gameplay_dir.is_relative_to(control_root)
    assert (run_control / "manager-terminal.json").is_file()
    assert (run_control / "supervision-observed.json").is_file()
    assert (attempt_dir / "terminal.json").is_file()
    assert (attempt_dir / "attempt-journal.jsonl").is_file()
    assert not (gameplay_dir / "terminal.json").exists()
    assert not (gameplay_dir / "manager-terminal.json").exists()

    attempt_events = [
        row["event"] for row in _json_lines(attempt_dir / "attempt-journal.jsonl")
    ]
    assert attempt_events.index("runtime_prepare_completed") < attempt_events.index(
        "child_started"
    )
    assert attempt_events.index("child_started") < attempt_events.index(
        "cleanup_recorded"
    )
    assert attempt_events.index("cleanup_recorded") < attempt_events.index(
        "terminal_pending"
    )

    manager_records = _json_lines(run_control / "manager-journal.jsonl")
    manager_events = [row["event"] for row in manager_records]
    assert manager_events.index("cleanup_completion_recorded") < manager_events.index(
        "registry_terminal_recorded"
    )
    supervision_started = next(
        row for row in manager_records if row["event"] == "supervision_started"
    )
    argv = supervision_started["argv"]
    assert argv.count("--external-run-id") == 1
    assert argv[-2:] == ["--external-run-id", run_id]

    supervisor_terminal = json.loads(
        (attempt_dir / "terminal.json").read_text(encoding="utf-8")
    )
    assert supervisor_terminal["run_id"] == run_id
    assert supervisor_terminal["terminal_class"] == "completed"
    assert supervisor_terminal["cleanup"]["ok"] is True
    assert supervisor_terminal["budget"]["calls"] == 0
    assert supervisor_terminal["budget"]["total_cost_usd"] == 0
    callback_cleanup = next(
        stage
        for stage in supervisor_terminal["cleanup"]["stages"]
        if stage["stage"] == "callback"
    )
    assert callback_cleanup == {
        "stage": "callback",
        "ok": True,
        "details": {
            "ok": True,
            "backend": "mock",
            "runtime": "none",
            "container_absent": True,
            "listener_absent": True,
        },
    }
    assert supervisor_terminal["environment_identity"]["run_id"] == run_id
    assert supervisor_terminal["environment_identity"]["provider"]["enabled"] is False

    worker_output = (attempt_dir / "child.stdout.log").read_text(encoding="utf-8")
    worker_payloads = [
        json.loads(line) for line in worker_output.splitlines() if line.startswith("{")
    ]
    worker_terminal = next(
        payload
        for payload in worker_payloads
        if payload.get("schema") == "fortgym.external-worker-outcome/v1"
    )
    assert worker_terminal == {
        "schema": "fortgym.external-worker-outcome/v1",
        "run_id": run_id,
        "outcome": "completed",
        "terminal_reason": None,
    }
    for secret in (
        "ambient-openrouter-must-not-reach-child",
        "ambient-openai-must-not-reach-child",
        "ambient-anthropic-must-not-reach-child",
    ):
        assert secret not in worker_output
        assert secret not in (attempt_dir / "child.stderr.log").read_text(
            encoding="utf-8"
        )

    summary_path = gameplay_dir / "summary.json"
    trace_path = gameplay_dir / "trace.jsonl"
    assert summary_path.is_file()
    assert trace_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trace = _json_lines(trace_path)
    assert summary["run_id"] == run_id
    assert summary["usage"]["calls"] == 0
    assert summary["usage"]["cost_usd"] == 0
    assert trace
    assert {row["run_id"] for row in trace} == {run_id}

    reopened = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    )
    persisted = reopened.get(run_id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.ended_at is not None
    assert "cleanup_completed_at" in persisted.metadata
    assert persisted.latest_summary == summary
    assert [record.run_id for record in reopened.list()] == [run_id]

    outbox = reopened.read_events_since(run_id, limit=1_000)
    assert outbox
    assert [event.sequence for event in outbox] == list(range(1, len(outbox) + 1))
    assert any(event.payload["t"] == "score" for event in outbox)
    assert all(event.run_id == run_id for event in outbox)
    assert all(
        event.payload["data"].get("run_id", run_id) == run_id for event in outbox
    )
