from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.run.process_supervisor import EVIDENCE_SNAPSHOT_SCHEMA
from fort_gym.bench.run.runtime_controller import RuntimeTestFault
from fort_gym.bench.run.startup_replacement import (
    StartupReplacementDenied,
    StartupReplacementError,
    StartupReplacementLedger,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import ManagedRunResult
from fort_gym.bench.run.supervision_service import (
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionConfigurationError,
    SupervisionService,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _journal(path: Path, events: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"event": event}) + "\n" for event in events),
        encoding="utf-8",
    )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seal_attempt_terminal(
    attempt_dir: Path,
    terminal: dict[str, Any],
    *,
    prefix_events: list[str],
) -> None:
    """Emit the exact generic seven-event chain used by the real supervisor."""

    run_id = str(terminal["run_id"])
    environment = terminal["environment_identity"]
    rpc = environment["rpc"]
    identity = {
        "run_id": run_id,
        "contract_sha256": environment["contract_sha256"],
        "nonce_sha256": hashlib.sha256(
            str(rpc["nonce"]).encode("utf-8")
        ).hexdigest(),
        "environment_identity_sha256": _canonical_sha256(environment),
        "child_pid": terminal["child_pid"],
        "port": terminal["port"],
    }
    snapshot_path = attempt_dir / "evidence-snapshot.json"
    _json(
        snapshot_path,
        {
            "schema": EVIDENCE_SNAPSHOT_SCHEMA,
            "identity": identity,
            "primary_terminal_class": terminal["primary_terminal_class"],
            "primary_reason": terminal["primary_reason"],
            "prepare": terminal["prepare"],
            "termination": terminal["termination"],
            "files": {
                "trace": {"present": False},
                "child_stdout": {"present": False},
                "child_stderr": {"present": False},
            },
            "fault_snapshot": None,
            "fault_snapshot_error": None,
            "recovered_by_manager": False,
        },
    )
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    cleanup = terminal["cleanup"]
    cleanup_ok = cleanup["ok"] is True
    cleanup_sha256 = _canonical_sha256(cleanup)
    common = {
        "schema": "fortgym.process-supervisor-attempt/v1",
        "run_id": run_id,
        "supervisor_pid": 4242,
    }

    rows: list[dict[str, Any]] = [
        {"event": event, **common} for event in prefix_events
    ]
    rows.extend(
        [
            {
                "event": "terminal_pending_cleanup",
                "monotonic_ns": 1,
                "identity": identity,
                "primary_terminal_class": terminal["primary_terminal_class"],
                "primary_reason_sha256": _canonical_sha256(
                    terminal["primary_reason"]
                ),
                **common,
            },
            {
                "event": "evidence_snapshot_completed",
                "monotonic_ns": 2,
                "identity": identity,
                "ok": True,
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": snapshot_sha256,
                "fault_snapshot_attached": False,
                "error": None,
                **common,
            },
            {
                "event": "harness_process_group_reaped",
                "monotonic_ns": 3,
                "identity": identity,
                "ok": True,
                "skipped": terminal["child_pid"] is None,
                "child_pid": terminal["child_pid"],
                "group_exists": (
                    None if terminal["child_pid"] is None else False
                ),
                **common,
            },
            {
                "event": "runtime_container_removed",
                "monotonic_ns": 4,
                "identity": identity,
                "ok": cleanup_ok,
                "skipped": False,
                "container_absent": cleanup_ok,
                "listener_absent": cleanup_ok,
                **common,
            },
            {"event": "cleanup_recorded", "cleanup": cleanup, **common},
            {
                "event": "cleanup_verified",
                "monotonic_ns": 5,
                "identity": identity,
                "ok": cleanup_ok,
                "cleanup_sha256": cleanup_sha256,
                **common,
            },
            {
                "event": "cleanup_completed",
                "monotonic_ns": 6,
                "identity": identity,
                "ok": cleanup_ok,
                "cleanup_sha256": cleanup_sha256,
                **common,
            },
            {
                "event": "immutable_terminal_classification",
                "monotonic_ns": 7,
                "identity": identity,
                "terminal_class": terminal["terminal_class"],
                "reason_sha256": _canonical_sha256(terminal["reason"]),
                "cleanup_sha256": cleanup_sha256,
                "evidence_snapshot_sha256": snapshot_sha256,
                **common,
            },
            {
                "event": "terminal_pending",
                "terminal_class": terminal["terminal_class"],
                "cleanup_ok": cleanup_ok,
                **common,
            },
        ]
    )
    journal_path = attempt_dir / "attempt-journal.jsonl"
    journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _json(attempt_dir / "terminal.json", terminal)


class EvidenceManager:
    """Deterministic manager/controller model; never executes Docker or a child."""

    def __init__(self, outcomes: list[dict[str, Any]]) -> None:
        self.outcomes = list(outcomes)
        self.registry: RunRegistry | None = None
        self.runtime_controller_factory: Any = None
        self.controllers: list[Any] = []
        self.run_calls: list[str] = []

    def factory(self, **kwargs: Any) -> EvidenceManager:
        self.registry = kwargs["registry"]
        self.runtime_controller_factory = kwargs["runtime_controller_factory"]
        return self

    def run(self, run_id: str) -> ManagedRunResult:
        assert self.registry is not None
        assert self.runtime_controller_factory is not None
        self.run_calls.append(run_id)
        outcome = self.outcomes.pop(0)
        record = self.registry.get(run_id)
        assert record is not None
        run_dir = Path(outcome["control_root"]) / run_id
        controller = self.runtime_controller_factory(record, run_dir)
        self.controllers.append(controller)
        assert self.registry.claim_pending_run(run_id, started_at=datetime.now(UTC))

        attempt_dir = run_dir / "attempts" / "attempt-0001"
        runtime_dir = attempt_dir / "runtime"
        runtime_dir.mkdir(parents=True)
        code = str(outcome["code"])
        status = str(outcome.get("status", "failed"))
        harness_started = bool(outcome.get("harness_started", status == "completed"))
        cleanup_ok = bool(outcome.get("cleanup_ok", True))
        callback_details = {
            "ok": cleanup_ok,
            "container_absent": cleanup_ok,
            "listener_absent": cleanup_ok,
            "container_name": controller.container_name,
        }
        cleanup = {
            "ok": cleanup_ok,
            "stages": [
                {"stage": "process_group", "ok": True},
                {
                    "stage": "callback",
                    "ok": cleanup_ok,
                    "details": callback_details,
                },
                {
                    "stage": "port_lease",
                    "ok": True,
                    "port": controller.contract.port,
                },
            ],
        }
        terminal_reason = (
            {"code": "child_completed"} if status == "completed" else {"code": code}
        )
        manager_reason = (
            {"code": "external_worker_completed", "returncode": 0}
            if status == "completed"
            else {"code": code}
        )
        terminal = {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": run_id,
            "terminal_class": "completed"
            if status == "completed"
            else "prepare_failure",
            "primary_terminal_class": (
                "completed" if status == "completed" else "prepare_failure"
            ),
            "primary_reason": terminal_reason,
            "reason": terminal_reason,
            "child_pid": 4321 if harness_started else None,
            "returncode": 0 if status == "completed" else None,
            "child_signal": None,
            "port": controller.contract.port,
            "environment_identity": controller.contract.environment_identity(),
            "runtime_cleanup_required": True,
            "prepare": {},
            "termination": {},
            "cleanup": cleanup,
        }
        attempt_events = ["attempt_started", "port_leased", "runtime_prepare_started"]
        if harness_started:
            attempt_events.extend(["runtime_prepare_completed", "child_started"])
        else:
            attempt_events.append("runtime_prepare_failed")
        _seal_attempt_terminal(
            attempt_dir,
            terminal,
            prefix_events=attempt_events,
        )
        _journal(
            run_dir / "manager-journal.jsonl",
            [
                "ownership_acquired",
                "supervision_started",
                "supervision_finished",
                "cleanup_completion_recorded",
                "registry_terminal_recorded",
            ],
        )
        if code in {
            "container_create_failure",
            "rpc_readiness_timeout",
            "map_readiness_timeout",
        }:
            _json(
                runtime_dir / "startup-terminal.json",
                {
                    "schema": "fortgym.m1b-startup-terminal/v1",
                    "run_id": run_id,
                    "contract_sha256": controller.contract.contract_sha256,
                    "terminal_code": code,
                    "injected": (
                        controller.test_fault is not None
                        and code == "rpc_readiness_timeout"
                    ),
                },
            )

        now = datetime.now(UTC)
        if status == "completed":
            self.registry.set_summary(
                run_id,
                {
                    "run_id": run_id,
                    "provider_calls": 0,
                    "provider_cost_usd": 0.0,
                },
            )
        if cleanup_ok:
            self.registry.record_cleanup_completed(run_id, completed_at=now)
        if status == "completed":
            self.registry.finalize_success_after_cleanup(run_id, step=1, ended_at=now)
        else:
            self.registry.record_terminal_failure(
                run_id,
                terminal_reason=manager_reason,
                step=0,
                ended_at=now,
            )
        _json(
            run_dir / "manager-terminal.json",
            {
                "schema": "fortgym.supervised-manager-terminal/v1",
                "run_id": run_id,
                "status": status,
                "reason": manager_reason,
                "returncode": 0 if status == "completed" else None,
                "supervision": terminal,
            },
        )
        return ManagedRunResult(
            run_id=run_id,
            status=status,
            finalized=True,
            recovered=False,
            action="finalized",
            returncode=0 if status == "completed" else None,
            control_dir=run_dir,
            reason=manager_reason,
        )

    def reconcile(self, run_id: str) -> ManagedRunResult:  # pragma: no cover
        raise AssertionError(f"unexpected reconcile: {run_id}")


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcomes: list[dict[str, Any]],
    ids: tuple[str, ...],
    allow_test_faults: bool,
) -> tuple[SupervisionService, RunRegistry, ServiceConfig, EvidenceManager]:
    artifacts_root = (tmp_path / "artifacts").resolve()
    control_root = (tmp_path / "control").resolve()
    db_path = (tmp_path / "registry.sqlite3").resolve()
    repo_root = (tmp_path / "repo").resolve()
    repo_root.mkdir()
    entrypoint = repo_root / "runtime_entrypoint.sh"
    entrypoint.write_text("#!/bin/bash\n", encoding="utf-8")
    entrypoint.chmod(0o700)
    dfroot = (tmp_path / "dfroot").resolve()
    dfroot.mkdir()
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    config = ServiceConfig(
        db_path=db_path,
        artifacts_root=artifacts_root,
        control_root=control_root,
        repo_root=repo_root,
        python_executable=Path(sys.executable).absolute(),
        entrypoint_path=entrypoint,
        dfroot=dfroot,
        code_sha256="a" * 64,
        allow_test_startup_faults=allow_test_faults,
    )
    registry = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    )
    manager = EvidenceManager(
        [{**outcome, "control_root": control_root} for outcome in outcomes]
    )
    id_values = iter(ids)
    nonce_values = iter(f"{index + 1:032x}" for index in range(len(ids)))
    service = SupervisionService(
        registry=registry,
        config=config,
        manager_factory=manager.factory,
        id_factory=lambda: next(id_values),
        nonce_factory=lambda: next(nonce_values),
    )
    return service, registry, config, manager


def _request() -> SupervisedRunRequest:
    return SupervisedRunRequest(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=1,
        ticks_per_step=1,
    )


def test_cold_retry_records_injected_timeout_cleanup_and_fresh_completed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[
            {"code": "rpc_readiness_timeout", "harness_started": False},
            {"code": "external_worker_completed", "status": "completed"},
        ],
        ids=("cold-primary", "cold-replacement"),
        allow_test_faults=True,
    )

    outcome = service.run_cold_retry_preflight(_request())

    assert outcome.run_ids == ("cold-primary", "cold-replacement")
    assert outcome.replacement_kind == "test_injector_invalid_rerun"
    assert outcome.completed is True
    assert [result.status for result in outcome.results] == ["failed", "completed"]
    assert manager.controllers[0].test_fault is RuntimeTestFault.SUPPRESS_RPC_READINESS
    assert manager.controllers[1].test_fault is None
    assert (
        manager.controllers[0].container_name != manager.controllers[1].container_name
    )

    first_launch = json.loads(
        (config.control_root / "cold-primary" / "launch.json").read_text()
    )
    second_launch = json.loads(
        (config.control_root / "cold-replacement" / "launch.json").read_text()
    )
    assert first_launch["test_fault"]["injected"] is True
    assert "test_fault" not in second_launch
    first_contract = first_launch["contract"]
    second_contract = second_launch["contract"]
    assert first_contract["run_id"] != second_contract["run_id"]
    assert first_contract["rpc"]["nonce"] != second_contract["rpc"]["nonce"]
    assert first_contract["contract_sha256"] != second_contract["contract_sha256"]
    assert (
        first_contract["seed"]["runtime_save"]
        != (second_contract["seed"]["runtime_save"])
    )
    assert first_contract["rpc"]["port"] == second_contract["rpc"]["port"]

    records = StartupReplacementLedger(
        outcome.evidence_path,
        packet_id=outcome.packet_id,
        cohort_size=1,
    ).records()
    assert [record["sequence"] for record in records] == list(
        range(1, len(records) + 1)
    )
    assert [record["event"] for record in records] == [
        "packet_started",
        "attempt_terminal",
        "replacement_authorized",
        "replacement_reserved",
        "attempt_terminal",
        "packet_completed",
    ]
    attempts = [record for record in records if record["event"] == "attempt_terminal"]
    assert attempts[0]["terminal_code"] == "rpc_readiness_timeout"
    assert attempts[0]["injected"] is True
    assert attempts[0]["harness_started"] is False
    assert attempts[0]["cleanup_verified"] is True
    assert attempts[1]["status"] == "completed"
    assert attempts[1]["injected"] is False
    assert all(
        attempt["lease_lifecycle"]
        == {
            "port": config.base_port,
            "acquired": True,
            "released": True,
        }
        for attempt in attempts
    )
    assert first_contract["rpc"]["nonce"] not in outcome.evidence_path.read_text()
    assert second_contract["rpc"]["nonce"] not in outcome.evidence_path.read_text()
    assert {record.run_id for record in registry.list()} == {
        "cold-primary",
        "cold-replacement",
    }


def test_default_service_rejects_cold_fault_before_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[],
        ids=("unused",),
        allow_test_faults=False,
    )

    with pytest.raises(SupervisionConfigurationError, match="explicit test"):
        service.run_cold_retry_preflight(_request())

    assert registry.list() == []
    assert manager.run_calls == []
    assert not config.control_root.exists()


@pytest.mark.parametrize(
    ("code", "harness_started"),
    [
        ("port_policy_failure", False),
        ("nonce_mismatch", False),
        ("rpc_readiness_timeout", True),
    ],
)
def test_natural_replacement_denies_forbidden_or_post_harness_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    harness_started: bool,
) -> None:
    service, registry, _config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[{"code": code, "harness_started": harness_started}],
        ids=("natural-primary",),
        allow_test_faults=False,
    )

    outcome = service.run_with_startup_replacement(_request())

    assert outcome.run_ids == ("natural-primary",)
    assert outcome.replacement_kind is None
    assert manager.run_calls == ["natural-primary"]
    assert len(registry.list()) == 1
    records = StartupReplacementLedger(
        outcome.evidence_path,
        packet_id=outcome.packet_id,
        cohort_size=1,
    ).records()
    assert "replacement_denied" in [record["event"] for record in records]


def test_natural_replacement_stops_after_one_retry_even_if_second_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, _config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[
            {"code": "rpc_readiness_timeout", "harness_started": False},
            {"code": "rpc_readiness_timeout", "harness_started": False},
        ],
        ids=("natural-a", "natural-b", "must-not-be-used"),
        allow_test_faults=False,
    )

    outcome = service.run_with_startup_replacement(_request())

    assert outcome.run_ids == ("natural-a", "natural-b")
    assert outcome.replacement_kind == "natural_startup"
    assert outcome.completed is False
    assert manager.run_calls == ["natural-a", "natural-b"]
    assert len(registry.list()) == 2
    records = StartupReplacementLedger(
        outcome.evidence_path,
        packet_id=outcome.packet_id,
        cohort_size=1,
    ).records()
    assert [record["event"] for record in records].count("replacement_authorized") == 1
    assert "replacement_cap_enforced" in [record["event"] for record in records]


@pytest.mark.parametrize(
    "terminal_code",
    [
        "container_create_failure",
        "rpc_readiness_timeout",
        "map_readiness_timeout",
    ],
)
def test_each_durable_natural_startup_code_allows_exactly_one_fresh_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_code: str,
) -> None:
    service, registry, _config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[
            {"code": terminal_code, "harness_started": False},
            {"code": "external_worker_completed", "status": "completed"},
        ],
        ids=(f"{terminal_code}-primary", f"{terminal_code}-replacement"),
        allow_test_faults=False,
    )

    outcome = service.run_with_startup_replacement(_request())

    assert outcome.replacement_kind == "natural_startup"
    assert outcome.completed is True
    assert len(outcome.run_ids) == 2
    assert len(registry.list()) == 2
    assert manager.run_calls == list(outcome.run_ids)


def test_cleanup_failure_blocks_replacement_before_second_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, _config, manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[
            {
                "code": "rpc_readiness_timeout",
                "harness_started": False,
                "cleanup_ok": False,
            }
        ],
        ids=("cleanup-failed", "must-not-be-used"),
        allow_test_faults=False,
    )

    with pytest.raises(StartupReplacementError, match="cleanup"):
        service.run_with_startup_replacement(_request())

    assert manager.run_calls == ["cleanup-failed"]
    assert len(registry.list()) == 1


@pytest.mark.parametrize(
    ("crash_boundary", "expected_disposition"),
    [
        ("reserve", "pending_terminalized_failed"),
        ("fresh_identity", "pending_terminalized_failed"),
        ("run_reserved", "pending_terminalized_failed"),
        ("evidence", "already_terminal_completed"),
    ],
)
def test_authorized_replacement_crash_boundaries_are_durable_and_never_strand_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_boundary: str,
    expected_disposition: str,
) -> None:
    service, registry, config, _manager = _service(
        tmp_path,
        monkeypatch,
        outcomes=[
            {"code": "rpc_readiness_timeout", "harness_started": False},
            {"code": "external_worker_completed", "status": "completed"},
        ],
        ids=("crash-primary", "crash-replacement", "must-not-be-used"),
        allow_test_faults=False,
    )

    def crash() -> None:
        raise RuntimeError(f"synthetic {crash_boundary} crash")

    if crash_boundary == "reserve":
        original_reserve = service._reserve
        reserve_calls = 0

        def reserve(*args: Any, **kwargs: Any):
            nonlocal reserve_calls
            reserve_calls += 1
            result = original_reserve(*args, **kwargs)
            if reserve_calls == 2:
                crash()
            return result

        monkeypatch.setattr(service, "_reserve", reserve)
    elif crash_boundary == "fresh_identity":
        monkeypatch.setattr(
            service,
            "_fresh_replacement_identity",
            lambda *_args, **_kwargs: crash(),
        )
    elif crash_boundary == "run_reserved":
        original_run = service.run_reserved
        run_calls = 0

        def run_reserved(run_id: str):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 2:
                crash()
            return original_run(run_id)

        monkeypatch.setattr(service, "run_reserved", run_reserved)
    else:
        original_evidence = service._startup_attempt_evidence
        evidence_calls = 0

        def startup_evidence(run_id: str, result: ManagedRunResult):
            nonlocal evidence_calls
            evidence_calls += 1
            if evidence_calls == 2:
                crash()
            return original_evidence(run_id, result)

        monkeypatch.setattr(service, "_startup_attempt_evidence", startup_evidence)

    with pytest.raises(RuntimeError, match="synthetic"):
        service.run_with_startup_replacement(_request())

    evidence_path = (
        config.control_root / "_startup-replacements" / "crash-primary.jsonl"
    )
    records = StartupReplacementLedger(
        evidence_path,
        packet_id="crash-primary",
        cohort_size=1,
    ).records()
    events = [record["event"] for record in records]
    assert events.count("replacement_authorized") == 1
    assert events[-2:] == ["replacement_failed", "packet_failed"]
    assert "packet_completed" not in events
    failed = records[-2]
    assert (
        failed["stage"]
        == {
            "reserve": "replacement_reservation",
            "fresh_identity": "replacement_identity_validation",
            "run_reserved": "replacement_execution",
            "evidence": "replacement_evidence_validation",
        }[crash_boundary]
    )
    assert failed["pending_row_disposition"] == expected_disposition
    assert failed["maximum_additional_attempts"] == 0
    rows = {record.run_id: record for record in registry.list()}
    assert set(rows) <= {"crash-primary", "crash-replacement"}
    if "crash-replacement" in rows:
        assert rows["crash-replacement"].status != "pending"
    assert service._new_run_ids(1) == ["must-not-be-used"]


def test_injector_budget_is_separate_and_natural_path_rejects_injected_fault(
    tmp_path: Path,
) -> None:
    ledger = StartupReplacementLedger(
        (tmp_path / "ledger.jsonl").resolve(),
        packet_id="budget-packet",
        cohort_size=1,
    )
    ledger.authorize(
        kind="test_injector_invalid_rerun",
        logical_run_id="logical-a",
        source_run_id="attempt-a",
        terminal_code="rpc_readiness_timeout",
        injected=True,
        harness_started=False,
        cleanup_verified=True,
    )

    with pytest.raises(StartupReplacementDenied, match="test-injector"):
        ledger.authorize(
            kind="test_injector_invalid_rerun",
            logical_run_id="logical-a",
            source_run_id="attempt-b",
            terminal_code="rpc_readiness_timeout",
            injected=True,
            harness_started=False,
            cleanup_verified=True,
        )
    with pytest.raises(StartupReplacementDenied, match="cannot consume natural"):
        ledger.authorize(
            kind="natural_startup",
            logical_run_id="logical-b",
            source_run_id="attempt-c",
            terminal_code="rpc_readiness_timeout",
            injected=True,
            harness_started=False,
            cleanup_verified=True,
        )


def test_packet_and_co8_natural_replacement_caps_are_enforced(tmp_path: Path) -> None:
    packet = StartupReplacementLedger(
        (tmp_path / "packet.jsonl").resolve(),
        packet_id="packet-cap",
        cohort_size=1,
    )
    for index in range(2):
        packet.authorize(
            kind="natural_startup",
            logical_run_id=f"logical-{index}",
            source_run_id=f"source-{index}",
            terminal_code="rpc_readiness_timeout",
            injected=False,
            harness_started=False,
            cleanup_verified=True,
        )
    with pytest.raises(StartupReplacementDenied, match="packet"):
        packet.authorize(
            kind="natural_startup",
            logical_run_id="logical-2",
            source_run_id="source-2",
            terminal_code="rpc_readiness_timeout",
            injected=False,
            harness_started=False,
            cleanup_verified=True,
        )

    co8 = StartupReplacementLedger(
        (tmp_path / "co8.jsonl").resolve(),
        packet_id="co8-cap",
        cohort_size=8,
    )
    co8.authorize(
        kind="natural_startup",
        logical_run_id="co8-logical-a",
        source_run_id="co8-source-a",
        terminal_code="rpc_readiness_timeout",
        injected=False,
        harness_started=False,
        cleanup_verified=True,
    )
    with pytest.raises(StartupReplacementDenied, match="packet"):
        co8.authorize(
            kind="natural_startup",
            logical_run_id="co8-logical-b",
            source_run_id="co8-source-b",
            terminal_code="rpc_readiness_timeout",
            injected=False,
            harness_started=False,
            cleanup_verified=True,
        )


def test_concurrent_authorization_cannot_exceed_co8_packet_cap(
    tmp_path: Path,
) -> None:
    ledger = StartupReplacementLedger(
        (tmp_path / "concurrent-co8.jsonl").resolve(),
        packet_id="concurrent-co8",
        cohort_size=8,
    )
    barrier = threading.Barrier(8)
    results: list[str] = []
    results_lock = threading.Lock()

    def authorize(index: int) -> None:
        barrier.wait()
        try:
            ledger.authorize(
                kind="natural_startup",
                logical_run_id=f"logical-{index}",
                source_run_id=f"source-{index}",
                terminal_code="rpc_readiness_timeout",
                injected=False,
                harness_started=False,
                cleanup_verified=True,
            )
        except StartupReplacementDenied:
            result = "denied"
        else:
            result = "authorized"
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=authorize, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert results.count("authorized") == 1
    assert results.count("denied") == 7
    records = ledger.records()
    assert [row["event"] for row in records] == ["replacement_authorized"]


@pytest.mark.parametrize(
    "reserved_key",
    ["schema", "packet_id", "sequence", "at", "event"],
)
def test_append_rejects_reserved_identity_field_collision(
    tmp_path: Path,
    reserved_key: str,
) -> None:
    ledger = StartupReplacementLedger(
        (tmp_path / f"reserved-{reserved_key}.jsonl").resolve(),
        packet_id="reserved-fields",
        cohort_size=1,
    )

    with pytest.raises(ValueError, match="reserved identity"):
        ledger.append("packet_started", **{reserved_key: "attacker-controlled"})

    assert ledger.records() == []
