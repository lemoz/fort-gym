from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run.process_supervisor import RunSpec, validate_terminal_chain
from fort_gym.bench.run.residue_audit import (
    BatchResidueAuditor,
    ResidueExpectation,
)
from fort_gym.bench.run.storage import RunInfo, RunRegistry
from fort_gym.bench.run.supervised_manager import (
    ManagedRunResult,
    SupervisedRunManager,
)
from fort_gym.bench.run.supervision_service import (
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionService,
)

_RUN_ID = "orphan2-e2e"
_NONCE = "d" * 32
_CODE_SHA256 = "a" * 64
_IMAGE_MANIFEST_SHA256 = "1" * 64
_IMAGE_CONFIG_SHA256 = "2" * 64
_IMAGE_ARCHIVE_SHA256 = "3" * 64
_SEED_TREE_SHA256 = "4" * 64
_SEED_WORLD_SHA256 = "5" * 64


class _EphemeralRuntimeController:
    def __init__(self, *, run_id: str, runtime_temp: Path) -> None:
        self.run_id = run_id
        self.runtime_temp = runtime_temp

    @property
    def marker(self) -> Path:
        return self.runtime_temp / "owner.json"

    def prepare(self) -> Mapping[str, Any]:
        self.runtime_temp.mkdir(parents=True, exist_ok=False)
        self.marker.write_text(
            json.dumps({"run_id": self.run_id}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "runtime": "test-process-group",
            "temporary_path": str(self.runtime_temp),
        }

    def cleanup(self) -> Mapping[str, Any]:
        return self.reconcile()

    def reconcile(self) -> Mapping[str, Any]:
        removed_container_ids: list[str] = []
        if self.runtime_temp.exists():
            marker = json.loads(self.marker.read_text(encoding="utf-8"))
            if marker != {"run_id": self.run_id}:
                raise RuntimeError("ephemeral runtime ownership marker mismatch")
            self.marker.unlink()
            self.runtime_temp.rmdir()
            removed_container_ids.append(
                hashlib.sha256(self.run_id.encode("utf-8")).hexdigest()[:12]
            )
        return {
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": True,
            "managed_candidates": len(removed_container_ids),
            "removed_container_ids": removed_container_ids,
            "skipped_foreign_container_ids": [],
            "listener_absent": True,
            "noop": not removed_container_ids,
            "errors": [],
        }


def _manager_factory(
    *,
    probe_root: Path,
    identity_path: Path,
    runtime_temp: Path,
    repo_root: Path,
    process_identity_probe: Callable[[int], Mapping[str, Any]] | None = None,
    created_managers: list[SupervisedRunManager] | None = None,
    created_controllers: list[_EphemeralRuntimeController] | None = None,
) -> Callable[..., SupervisedRunManager]:
    def factory(**kwargs: Any) -> SupervisedRunManager:
        original_contract_factory = kwargs["contract_factory"]

        def controller_factory(record: RunInfo, _run_dir: Path) -> Any:
            controller = _EphemeralRuntimeController(
                run_id=record.run_id,
                runtime_temp=runtime_temp,
            )
            if created_controllers is not None:
                created_controllers.append(controller)
            return controller

        def contract_factory(
            record: RunInfo,
            attempt_dir: Path,
            controller: Any,
        ) -> RunSpec:
            spec = original_contract_factory(record, attempt_dir, controller)
            environment = dict(spec.env)
            environment.update(
                {
                    "FORT_GYM_ORPHAN_IDENTITY_PATH": str(identity_path),
                    "FORT_GYM_ORPHAN_TEST_WORKER": "1",
                    "PYTHONPATH": os.pathsep.join(
                        (str(probe_root), str(repo_root))
                    ),
                }
            )
            return replace(
                spec,
                env=environment,
                env_allowlist=tuple(sorted(environment)),
            )

        manager_kwargs = {
            "registry": kwargs["registry"],
            "control_root": kwargs["control_root"],
            "runtime_controller_factory": controller_factory,
            "contract_factory": contract_factory,
        }
        if process_identity_probe is not None:
            manager_kwargs["process_identity_probe"] = process_identity_probe
        manager = SupervisedRunManager(**manager_kwargs)
        if created_managers is not None:
            created_managers.append(manager)
        return manager

    return factory


def _service_config(payload: Mapping[str, Any]) -> ServiceConfig:
    return ServiceConfig(
        db_path=Path(str(payload["db_path"])),
        artifacts_root=Path(str(payload["artifacts_root"])),
        control_root=Path(str(payload["control_root"])),
        repo_root=Path(str(payload["repo_root"])),
        python_executable=Path(str(payload["python_executable"])),
        entrypoint_path=Path(str(payload["entrypoint_path"])),
        dfroot=Path(str(payload["dfroot"])),
        code_sha256=_CODE_SHA256,
        base_port=int(payload["base_port"]),
        max_cohort=1,
        timeout_seconds=300.0,
        term_grace_seconds=0.2,
        poll_interval_seconds=0.01,
        image_manifest_sha256=_IMAGE_MANIFEST_SHA256,
        image_config_sha256=_IMAGE_CONFIG_SHA256,
        image_archive_sha256=_IMAGE_ARCHIVE_SHA256,
        seed_tree_sha256=_SEED_TREE_SHA256,
        seed_world_sha256=_SEED_WORLD_SHA256,
    )


def _manager_process_main(config_path: Path) -> int:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    config = _service_config(payload)
    registry = RunRegistry(
        db_path=config.db_path,
        artifacts_root=config.artifacts_root,
        recover_interrupted=False,
    )
    service = SupervisionService(
        registry=registry,
        config=config,
        manager_factory=_manager_factory(
            probe_root=Path(str(payload["probe_root"])),
            identity_path=Path(str(payload["identity_path"])),
            runtime_temp=Path(str(payload["runtime_temp"])),
            repo_root=config.repo_root,
        ),
    )
    service.run_reserved(str(payload["run_id"]))
    return 0


def _journal_rows(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def _wait_until(
    predicate: Callable[[], bool],
    *,
    manager_process: subprocess.Popen[bytes],
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        returncode = manager_process.poll()
        if returncode is not None:
            raise AssertionError(
                f"manager process exited before the durable barrier: {returncode}"
            )
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the durable manager/child barrier")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(os.name != "posix", reason="ORPHAN-2 requires POSIX groups")
def test_orphan2_sigkill_manager_recovers_and_reaps_exact_worker_group(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    artifacts_root = (tmp_path / "artifacts").resolve()
    control_root = (tmp_path / "control").resolve()
    db_path = (tmp_path / "shared.sqlite3").resolve()
    dfroot = (tmp_path / "dfroot").resolve()
    dfroot.mkdir()
    probe_root = (tmp_path / "probe-pythonpath").resolve()
    probe_root.mkdir()
    runtime_temp = (tmp_path / "owned-runtime-temp").resolve()
    run_dir = control_root / _RUN_ID
    attempt_dir = run_dir / "attempts" / "attempt-0001"
    identity_path = attempt_dir / "live-child-identity.json"
    attempt_journal = attempt_dir / "attempt-journal.jsonl"
    manager_journal = run_dir / "manager-journal.jsonl"
    owner_path = run_dir / "owner.json"
    manager_terminal_path = run_dir / "manager-terminal.json"
    supervisor_terminal_path = attempt_dir / "terminal.json"
    audit_journal = (control_root / "orphan2-residue-audit.jsonl").resolve()

    (probe_root / "sitecustomize.py").write_text(
        """
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from fort_gym.bench.run.network_guard import install_from_environment

install_from_environment()
if os.environ.get("FORT_GYM_ORPHAN_TEST_WORKER") == "1":
    identity_path = Path(os.environ["FORT_GYM_ORPHAN_IDENTITY_PATH"])
    descendant_ready_path = identity_path.with_name("descendant-ready")
    descendant_env = dict(os.environ)
    descendant_env.pop("FORT_GYM_ORPHAN_TEST_WORKER", None)
    descendant_env.pop("PYTHONPATH", None)
    descendant_program = (
        "import os,signal,sys,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "fd=os.open(sys.argv[1],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);"
        "os.write(fd,b'ready\\\\n');os.fsync(fd);os.close(fd);"
        "time.sleep(300)"
    )
    descendant = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            descendant_program,
            str(descendant_ready_path),
        ],
        env=descendant_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    while not descendant_ready_path.is_file():
        if descendant.poll() is not None:
            raise RuntimeError("stubborn descendant failed before ready evidence")
        time.sleep(0.01)
    descendant_ready_path.unlink()
    identity = {
        "pid": os.getpid(),
        "process_group_id": os.getpgrp(),
        "descendant_pid": descendant.pid,
        "argv": sys.orig_argv,
        "environment": {
            name: os.environ[name]
            for name in (
                "FORT_GYM_RUN_ID",
                "FORT_GYM_RUN_CONTRACT_SHA256",
                "FORT_GYM_RUN_NONCE",
            )
        },
    }
    with identity_path.open("w", encoding="utf-8") as handle:
        json.dump(identity, handle, sort_keys=True)
        handle.write("\\n")
        handle.flush()
        os.fsync(handle.fileno())
    while True:
        time.sleep(60)
""".lstrip(),
        encoding="utf-8",
    )

    config_payload = {
        "run_id": _RUN_ID,
        "db_path": str(db_path),
        "artifacts_root": str(artifacts_root),
        "control_root": str(control_root),
        "repo_root": str(repo_root),
        "python_executable": str(Path(sys.executable).absolute()),
        "entrypoint_path": str(
            (repo_root / "infra/m1b/runtime_entrypoint.sh").resolve()
        ),
        "dfroot": str(dfroot),
        "base_port": 58_071,
        "probe_root": str(probe_root),
        "identity_path": str(identity_path),
        "runtime_temp": str(runtime_temp),
    }
    config = _service_config(config_payload)
    initial_registry = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    )
    initial_service = SupervisionService(
        registry=initial_registry,
        config=config,
        id_factory=lambda: _RUN_ID,
        nonce_factory=lambda: _NONCE,
    )
    launch = initial_service.reserve(
        SupervisedRunRequest(
            backend="mock",
            model="fake",
            max_steps=20,
            ticks_per_step=1,
        )
    )
    assert launch.run_ids == (_RUN_ID,)
    child_config_path = (tmp_path / "manager-process.json").resolve()
    child_config_path.write_text(
        json.dumps(config_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manager_stdout_path = tmp_path / "manager.stdout.log"
    manager_stderr_path = tmp_path / "manager.stderr.log"
    manager_process: subprocess.Popen[bytes] | None = None
    child_pid: int | None = None
    foreign_canary = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(300)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    stdout_handle = manager_stdout_path.open("wb")
    stderr_handle = manager_stderr_path.open("wb")
    try:
        manager_environment = {
            "FORT_GYM_DISABLE_DOTENV": "1",
            "LANG": "C.UTF-8",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(repo_root),
        }
        manager_process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(child_config_path)],
            cwd=repo_root,
            env=manager_environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )

        def durable_barrier_reached() -> bool:
            events = [row.get("event") for row in _journal_rows(attempt_journal)]
            return (
                owner_path.is_file()
                and "child_started" in events
                and identity_path.is_file()
                and runtime_temp.is_dir()
            )

        _wait_until(durable_barrier_reached, manager_process=manager_process)
        assert os.getpgid(manager_process.pid) == manager_process.pid
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        attempt_rows_before = _journal_rows(attempt_journal)
        child_rows = [
            row for row in attempt_rows_before if row.get("event") == "child_started"
        ]
        assert len(child_rows) == 1
        assert child_rows[0]["supervisor_pid"] == manager_process.pid
        child_pid = int(child_rows[0]["child_pid"])
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        worker_argv0 = str(identity["argv"][0])
        assert owner["state"] == "active"
        assert owner["manager_pid"] == manager_process.pid
        assert Path(worker_argv0).is_absolute()
        assert next(
            row["argv0"]
            for row in attempt_rows_before
            if row.get("event") == "attempt_started"
        ) == str(config.python_executable)
        assert identity == {
            "pid": child_pid,
            "process_group_id": child_pid,
            "descendant_pid": identity["descendant_pid"],
            "argv": [
                worker_argv0,
                "-m",
                "fort_gym.bench.cli",
                "experiment",
                str((run_dir / "experiment.json").resolve()),
                "--external-run-id",
                _RUN_ID,
            ],
            "environment": {
                "FORT_GYM_RUN_ID": _RUN_ID,
                "FORT_GYM_RUN_CONTRACT_SHA256": next(
                    row["environment_identity"]["contract_sha256"]
                    for row in attempt_rows_before
                    if row.get("event") == "attempt_started"
                ),
                "FORT_GYM_RUN_NONCE": _NONCE,
            },
        }
        descendant_pid = int(identity["descendant_pid"])
        assert descendant_pid > 0
        assert descendant_pid != child_pid
        assert os.getpgid(descendant_pid) == child_pid
        assert os.getpgid(child_pid) == child_pid
        assert initial_registry.claim_pending_run(
            _RUN_ID,
            started_at=datetime.now(UTC),
        )
        running = initial_registry.get(_RUN_ID)
        assert running is not None and running.status == "running"

        os.kill(manager_process.pid, signal.SIGKILL)
        assert manager_process.wait(timeout=5) == -signal.SIGKILL
        assert not _process_group_exists(manager_process.pid)
        assert _process_group_exists(child_pid)
        assert foreign_canary.poll() is None
        assert not supervisor_terminal_path.exists()
        assert not manager_terminal_path.exists()

        expected_worker_argv = (
            worker_argv0,
            "-m",
            "fort_gym.bench.cli",
            "experiment",
            str((run_dir / "experiment.json").resolve()),
            "--external-run-id",
            _RUN_ID,
        )

        def process_identity_probe(pid: int) -> Mapping[str, Any]:
            assert pid == child_pid
            live = json.loads(identity_path.read_text(encoding="utf-8"))
            assert live["pid"] == pid
            assert live["process_group_id"] == pid
            assert os.getpgid(pid) == pid
            cmdline = tuple(live["argv"])
            assert cmdline == expected_worker_argv
            return {
                "cmdline": cmdline,
                "environment": dict(live["environment"]),
            }

        reopened_registry = RunRegistry(
            db_path=db_path,
            artifacts_root=artifacts_root,
            recover_interrupted=False,
        )
        created_managers: list[SupervisedRunManager] = []
        created_controllers: list[_EphemeralRuntimeController] = []
        recovery_service = SupervisionService(
            registry=reopened_registry,
            config=config,
            manager_factory=_manager_factory(
                probe_root=probe_root,
                identity_path=identity_path,
                runtime_temp=runtime_temp,
                repo_root=repo_root,
                process_identity_probe=process_identity_probe,
                created_managers=created_managers,
                created_controllers=created_controllers,
            ),
        )

        recovered = recovery_service.reconcile_all()

        assert set(recovered) == {_RUN_ID}
        first = recovered[_RUN_ID]
        assert isinstance(first, ManagedRunResult)
        assert first.finalized is True
        assert first.recovered is True
        assert first.status == "failed"
        assert first.returncode == 22
        assert first.reason["code"] == "supervisor_lost"
        assert first.reason["supervisor_events"].count("child_started") == 1
        harness = first.reason["reconciliation"]["harness_process_group"]
        assert harness["ok"] is True
        assert harness["child_pid"] == child_pid
        assert harness["process_group_id"] == child_pid
        assert harness["term_sent"] is True
        assert harness["kill_sent"] is True
        assert harness["absent"] is True
        assert harness["identity"]["command"] == {
            "mode": "direct",
            "module": "fort_gym.bench.cli",
            "subcommand": "experiment",
            "external_run_id": _RUN_ID,
        }
        assert harness["identity"]["environment"] == {
            "run_id": _RUN_ID,
            "contract_sha256": identity["environment"][
                "FORT_GYM_RUN_CONTRACT_SHA256"
            ],
            "nonce_matched": True,
        }
        assert _NONCE not in json.dumps(first.reason, sort_keys=True)
        assert not _process_group_exists(child_pid)
        assert not _process_exists(child_pid)
        assert not _process_exists(descendant_pid)
        assert foreign_canary.poll() is None
        assert not runtime_temp.exists()
        assert len(created_controllers) == 1

        persisted = reopened_registry.get(_RUN_ID)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.ended_at is not None
        assert persisted.metadata["terminal_reason"]["code"] == "supervisor_lost"
        assert "cleanup_completed_at" in persisted.metadata

        manager_terminal = json.loads(
            manager_terminal_path.read_text(encoding="utf-8")
        )
        assert manager_terminal["recovered"] is True
        assert manager_terminal["reason"]["code"] == "supervisor_lost"
        cleanup = manager_terminal["supervision"]["cleanup"]
        assert cleanup["ok"] is True
        assert [stage["stage"] for stage in cleanup["stages"]] == [
            "orphan_harness_process_group",
            "runtime_reconcile",
        ]
        manager_events = [
            row["event"] for row in _journal_rows(manager_journal)
        ]
        assert manager_events.index("reconcile_dead_owner_cleanup_attempted") < (
            manager_events.index("cleanup_completion_recorded")
        )
        assert manager_events.index("cleanup_completion_recorded") < (
            manager_events.index("registry_terminal_recorded")
        )
        attempt_rows_after = _journal_rows(attempt_journal)
        assert [row["event"] for row in attempt_rows_after].count("child_started") == 1
        assert supervisor_terminal_path.is_file()
        supervisor_terminal = json.loads(
            supervisor_terminal_path.read_text(encoding="utf-8")
        )
        validate_terminal_chain(
            attempt_dir,
            supervisor_terminal,
            run_id=_RUN_ID,
            require_cleanup_success=True,
        )
        assert sorted(path.name for path in (run_dir / "attempts").iterdir()) == [
            "attempt-0001"
        ]

        assert len(created_managers) == 1
        terminal_before_second_reconcile = manager_terminal_path.read_bytes()
        manager_journal_before_second_reconcile = _journal_rows(manager_journal)
        persisted_before_second_reconcile = reopened_registry.get(_RUN_ID)
        second = created_managers[0].reconcile(_RUN_ID)
        assert second.action == "already_terminal"
        assert second.status == "failed"
        assert recovery_service.reconcile_all() == {}
        assert manager_terminal_path.read_bytes() == terminal_before_second_reconcile
        assert _journal_rows(manager_journal) == manager_journal_before_second_reconcile
        assert reopened_registry.get(_RUN_ID) == persisted_before_second_reconcile
        assert len(created_controllers) == 1
        assert [row["event"] for row in _journal_rows(attempt_journal)].count(
            "child_started"
        ) == 1

        command_calls: list[tuple[str, ...]] = []

        def fake_container_listener_probe(
            argv: Sequence[str],
        ) -> tuple[int, str, str]:
            command = tuple(argv)
            command_calls.append(command)
            if command[:3] == ("docker", "ps", "--all"):
                return 0, "", ""
            if command[:2] == ("ss", "-Hlnpt"):
                return 0, "", ""
            raise AssertionError(f"unexpected residue probe: {command}")

        expectation = ResidueExpectation(
            run_ids=(_RUN_ID,),
            ports=(config.base_port,),
            process_group_ids=(manager_process.pid, child_pid),
            temporary_paths=(runtime_temp,),
            retained_evidence_paths=(
                manager_terminal_path,
                supervisor_terminal_path,
                attempt_journal,
                identity_path,
            ),
            foreign_process_ids=(foreign_canary.pid,),
            port_lock_dir=(tmp_path / "port-leases").resolve(),
        )
        auditor = BatchResidueAuditor(
            command_probe=fake_container_listener_probe,
            process_group_exists=_process_group_exists,
            process_exists=_process_exists,
            mount_exists=lambda _path: False,
            path_exists=Path.exists,
            lease_available=lambda _port, _lock_dir: True,
        )

        first_audit, second_audit = auditor.audit_twice(
            expectation,
            journal_path=audit_journal,
        )

        expected_residues = {
            "containers": {},
            "process_groups": [],
            "listeners": {},
            "leases": [],
            "mounts": [],
            "temporary_paths": [],
            "probe_errors": [],
        }
        for report in (first_audit, second_audit):
            assert report.ok is True
            assert report.residues == expected_residues
            assert report.foreign_canaries == {
                "processes": {str(foreign_canary.pid): True},
                "containers": {},
                "all_untouched": True,
            }
            assert report.retained_evidence == [
                str(manager_terminal_path),
                str(supervisor_terminal_path),
                str(attempt_journal),
                str(identity_path),
            ]
        assert foreign_canary.poll() is None
        assert [call[0] for call in command_calls] == [
            "docker",
            "ss",
            "docker",
            "ss",
        ]
        audit_rows = _journal_rows(audit_journal)
        assert [row["pass_index"] for row in audit_rows] == [1, 2]
        assert [row["ok"] for row in audit_rows] == [True, True]
    finally:
        if manager_process is not None and manager_process.poll() is None:
            os.kill(manager_process.pid, signal.SIGKILL)
            manager_process.wait(timeout=5)
        if child_pid is not None and _process_group_exists(child_pid):
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if foreign_canary.poll() is None:
            try:
                os.killpg(foreign_canary.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        foreign_canary.wait(timeout=5)
        stdout_handle.close()
        stderr_handle.close()
        if runtime_temp.exists():
            shutil.rmtree(runtime_temp)


if __name__ == "__main__":
    raise SystemExit(_manager_process_main(Path(sys.argv[1]).resolve()))
