from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.run.process_supervisor import RunSpec
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import SupervisedRunManager
from infra.m1b.diagnostics import capture_run_diagnostics


class _NoopRuntimeController:
    def prepare(self) -> dict[str, Any]:
        return {"ok": True, "backend": "mock", "runtime": "none"}

    def cleanup(self) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": "mock",
            "runtime": "none",
            "container_absent": True,
            "listener_absent": True,
        }


def test_two_workers_survive_target_kill_and_export_evidence_before_teardown(tmp_path: Path) -> None:
    """Real OS processes and SIGKILL, but mock runtime: not real-DF acceptance."""
    root = tmp_path.resolve()
    control = root / "control"
    artifacts = root / "artifacts"
    registry = RunRegistry(db_path=root / "registry.sqlite3", artifacts_root=artifacts)
    run_ids = ("target", "peer")
    for run_id in run_ids:
        registry.create(run_id=run_id, backend="mock", model="fake", max_steps=2, ticks_per_step=10)
        (artifacts / run_id).mkdir(parents=True)
    config = root / "mock.yaml"
    config.write_text(
        "name: two-worker-failure\nbase_config:\n  backend: mock\n"
        "  max_steps: 2\n  model: fake\n  ticks_per_step: 10\n"
        "variants:\n  - name: fixed\n    memory_window: 0\nruns_per_variant: 1\n"
    )

    def contract(record, attempt_dir, _controller):
        return RunSpec(
            run_id=record.run_id,
            argv=(sys.executable, "-m", "fort_gym.bench.cli", "experiment", str(config),
                  "--external-run-id", record.run_id),
            cwd=Path(__file__).resolve().parents[1],
            env={"ARTIFACTS_DIR": str(artifacts), "FORT_GYM_DB_PATH": str(root / "registry.sqlite3")},
            env_allowlist=("ARTIFACTS_DIR", "FORT_GYM_DB_PATH"),
            trace_path=artifacts / record.run_id / "trace.jsonl",
            artifact_dir=attempt_dir, scripted=True, timeout_seconds=10,
            term_grace_seconds=0.2, poll_interval_seconds=0.01,
            environment_identity={
                "schema": "fortgym.m1b-runtime-contract/v1",
                "backend": "mock",
                "run_id": record.run_id,
                "contract_sha256": hashlib.sha256(record.run_id.encode()).hexdigest(),
                "rpc": {"port": None, "nonce": f"{run_ids.index(record.run_id) + 1:032x}"},
                "classification": "local_mock_engineering_only",
            },
            cotenancy={"peer_run_ids": [name for name in run_ids if name != record.run_id]},
            runtime_cleanup_required=True,
        )

    manager = SupervisedRunManager(
        registry=registry, control_root=control,
        runtime_controller_factory=lambda _record, _dir: _NoopRuntimeController(),
        contract_factory=contract,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(manager.run, name) for name in run_ids}
        paused: dict[str, int] = {}
        try:
            deadline = time.monotonic() + 5
            while len(paused) < 2:
                assert time.monotonic() < deadline, "workers did not become ready"
                for name in run_ids:
                    if name in paused:
                        continue
                    journal = control / name / "attempts/attempt-0001/attempt-journal.jsonl"
                    if journal.exists():
                        try:
                            rows = [json.loads(line) for line in journal.read_text().splitlines()]
                        except json.JSONDecodeError:
                            continue  # writer is between append and fsync
                        for row in rows:
                            if row.get("event") == "child_started":
                                os.kill(row["child_pid"], signal.SIGSTOP)
                                paused[name] = row["child_pid"]
                                break
                time.sleep(0.01)
            target_pid, peer_pid = paused["target"], paused["peer"]
            assert target_pid != peer_pid
            os.kill(target_pid, signal.SIGKILL)
            target = futures["target"].result(timeout=5)
            assert target.status == "failed" and target.finalized is True
            assert futures["peer"].done() is False
            os.kill(peer_pid, 0)
        finally:
            # Unblock every still-running test worker even when an assertion fails.
            for pid in paused.values():
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
        peer = futures["peer"].result(timeout=5)
    assert peer.status == "completed" and peer.finalized is True

    export = root / "evidence"
    export.mkdir()
    for name in run_ids:
        snapshot = capture_run_diagnostics(control_root=control, artifacts_root=artifacts, run_id=name)
        assert snapshot["capture_ok"] is True
        assert snapshot["terminal_evidence_present"] is True
        terminal = next(
            record for record in snapshot["files"]
            if record["area"] == "control" and record["path"] == "attempts/attempt-0001/terminal.json"
        )
        evidence = json.loads(terminal["content"])
        assert evidence["cleanup"]["ok"] is True
        assert evidence["budget"]["calls"] == 0
        assert evidence["child_signal"] == (signal.SIGKILL if name == "target" else None)
        with pytest.raises(ProcessLookupError):
            os.kill(evidence["child_pid"], 0)
        (export / f"{name}.json").write_text(json.dumps(snapshot))
    archive = root / "remote-evidence.tar"
    with tarfile.open(archive, "w") as handle:
        handle.add(export, arcname="fortgym-m1b/evidence/local-two-worker/diagnostics")
    # Only test-owned temporary runtime trees are removed, after export.
    shutil.rmtree(control)
    shutil.rmtree(artifacts)
    with tarfile.open(archive) as handle:
        for name in run_ids:
            member = handle.extractfile(f"fortgym-m1b/evidence/local-two-worker/diagnostics/{name}.json")
            assert member is not None
            restored = json.load(member)
            assert restored["run_id"] == name and restored["terminal_evidence_present"] is True


def test_eight_mock_worker_processes_share_registry_without_cross_talk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Prove eight parent-managed mock workers share SQLite without cross-talk."""

    artifacts_root = tmp_path / "artifacts"
    control_root = tmp_path / "control"
    db_path = artifacts_root / "fort_gym.sqlite3"
    repo_root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "one-run-mock.yaml"
    config_path.write_text(
        """
name: m1b-local-mock-worker
description: Local process plumbing only; not a DF acceptance run
base_config:
  backend: mock
  max_steps: 2
  model: fake
  ticks_per_step: 10
variants:
  - name: fixed
    memory_window: 0
runs_per_variant: 1
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    api_registry = RunRegistry(db_path=db_path)
    run_ids = [f"m1b-local-mock-{index:02d}" for index in range(8)]
    for run_id in run_ids:
        api_registry.create(
            run_id=run_id,
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
        )

    def contract(record, attempt_dir: Path, _controller) -> RunSpec:
        run_id = record.run_id
        peers = tuple(peer for peer in run_ids if peer != run_id)
        return RunSpec(
            run_id=run_id,
            argv=(
                sys.executable,
                "-m",
                "fort_gym.bench.cli",
                "experiment",
                str(config_path),
                "--external-run-id",
                run_id,
            ),
            artifact_dir=attempt_dir,
            cwd=repo_root,
            env={
                "ARTIFACTS_DIR": str(artifacts_root),
                "FORT_GYM_DB_PATH": str(db_path),
            },
            env_allowlist=("ARTIFACTS_DIR", "FORT_GYM_DB_PATH"),
            scripted=True,
            timeout_seconds=30.0,
            term_grace_seconds=1.0,
            poll_interval_seconds=0.02,
            trace_path=artifacts_root / run_id / "trace.jsonl",
            environment_identity={
                "schema": "fortgym.m1b-runtime-contract/v1",
                "run_id": run_id,
                "contract_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
                "rpc": {
                    "host": "127.0.0.1",
                    "port": None,
                    "nonce": f"{run_ids.index(run_id) + 1:032x}",
                },
                "classification": "local_mock_engineering_only",
                "backend": "mock",
                "seed_attestation": "mock-fixed-seed",
            },
            cotenancy={"slot": run_ids.index(run_id), "peer_run_ids": peers},
            runtime_cleanup_required=True,
        )

    manager = SupervisedRunManager(
        registry=api_registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: _NoopRuntimeController(),
        contract_factory=contract,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(manager.run, run_ids))

    assert [result.status for result in results] == ["completed"] * 8
    assert all(result.finalized for result in results)
    assert [result.returncode for result in results] == [0] * 8
    assert api_registry.list_public() == []

    child_pids: set[int] = set()
    for run_id, result in zip(run_ids, results, strict=True):
        record = api_registry.get(run_id)
        assert record is not None and record.status == "completed"
        assert record.ended_at is not None
        assert "cleanup_completed_at" in record.metadata
        assert result.control_dir == control_root / run_id
        assert not result.control_dir.is_relative_to(artifacts_root)

        attempt_dir = result.control_dir / "attempts" / "attempt-0001"
        supervisor_terminal = json.loads(
            (attempt_dir / "terminal.json").read_text(encoding="utf-8")
        )
        assert isinstance(supervisor_terminal["child_pid"], int)
        child_pids.add(supervisor_terminal["child_pid"])
        assert supervisor_terminal["environment_identity"]["classification"] == (
            "local_mock_engineering_only"
        )
        assert supervisor_terminal["cotenancy"]["peer_run_ids"] == [
            peer for peer in run_ids if peer != run_id
        ]
        assert supervisor_terminal["budget"]["calls"] == 0
        assert supervisor_terminal["budget"]["total_cost_usd"] == 0
        assert supervisor_terminal["cleanup"]["ok"] is True

        manager_journal = [
            json.loads(line)
            for line in (result.control_dir / "manager-journal.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        manager_events = [event["event"] for event in manager_journal]
        assert manager_events.index("cleanup_completion_recorded") < (
            manager_events.index("registry_terminal_recorded")
        )
        assert (result.control_dir / "manager-terminal.json").is_file()

        summary_path = artifacts_root / run_id / "summary.json"
        trace_path = artifacts_root / run_id / "trace.jsonl"
        assert summary_path.is_file()
        assert trace_path.is_file()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["run_id"] == run_id
        assert summary["usage"]["calls"] == 0
        assert summary["usage"]["cost_usd"] == 0
        assert not (artifacts_root / run_id / "terminal.json").exists()
        assert not (artifacts_root / run_id / "manager-terminal.json").exists()
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            assert event["run_id"] == run_id

    assert len(child_pids) == len(run_ids)
    reopened = RunRegistry(db_path=db_path, recover_interrupted=False)
    for run_id in run_ids:
        events = reopened.read_events_since(run_id, limit=1_000)
        assert events
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert all(event.run_id == run_id for event in events)
        assert all(
            event.payload["data"].get("run_id", run_id) == run_id for event in events
        )

    get_settings.cache_clear()  # type: ignore[attr-defined]
