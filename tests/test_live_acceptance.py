from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import fort_gym.bench.run.live_acceptance as live
from infra.m1b.diagnostics import capture_run_diagnostics
from infra.m1b.run_live_acceptance import LinuxM1BHostAdapter
from infra.m1b.root_broker import BrokerLayout, RootBroker, _LedgerSnapshot
from fort_gym.bench.run.live_acceptance import (
    FROZEN_ACCEPTANCE_SHA256,
    FROZEN_GATE_PLAN,
    BatchDecisionValue,
    CleanupPassContext,
    CleanupPassResult,
    GateExecutionContext,
    GateExecutionResult,
    GateStatus,
    LiveAcceptanceAuthorizationError,
    LiveAcceptanceBatchController,
    LiveAcceptanceContractError,
    LiveAcceptanceEvidenceError,
    LiveAcceptanceProtocolError,
    LiveAcceptanceResumeError,
    LocalCreditImport,
    LocalCreditScope,
    PrivilegedCommandResult,
    SourceManifestLock,
    authorize_private_m1b_live_acceptance,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ACCEPTANCE = _REPO_ROOT / "infra" / "m1b" / "acceptance.yaml"


class DeterministicClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._value
        self._value += timedelta(microseconds=1)
        return value


@dataclass
class FakePrivilegedCommands:
    calls: list[tuple[tuple[str, ...], float]] = field(default_factory=list)

    def execute(
        self, logical_argv: tuple[str, ...], *, timeout_seconds: float
    ) -> PrivilegedCommandResult:
        argv = tuple(logical_argv)
        self.calls.append((argv, timeout_seconds))
        empty = hashlib.sha256(b"").hexdigest()
        return PrivilegedCommandResult(
            logical_argv=argv,
            returncode=0,
            stdout_sha256=empty,
            stderr_sha256=empty,
            executor_identity_sha256="e" * 64,
        )


@dataclass
class FakeAdapter:
    root: Path
    fail_gate: str | None = None
    omit_last_attempt_gate: str | None = None
    cleanup_fail: tuple[str, str | None, int] | None = None
    interrupt_gate: str | None = None
    interrupt_cleanup: tuple[str, str | None, int] | None = None
    wrong_gate_result: str | None = None
    mutate_gate_evidence_during_final_cleanup: str | None = None
    use_privilege_on: frozenset[str] = frozenset(
        {"DF-KILL", "ENOSPC", "DAEMON-RESTART"}
    )
    executed: list[str] = field(default_factory=list)
    cleanup_calls: list[tuple[str, str | None, int]] = field(default_factory=list)
    contexts: dict[str, GateExecutionContext] = field(default_factory=dict)
    gate_evidence: dict[str, Path] = field(default_factory=dict)

    def _write(self, relative: str, payload: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
        self.executed.append(context.gate_id)
        self.contexts[context.gate_id] = context
        if context.gate_id == self.interrupt_gate:
            raise KeyboardInterrupt("synthetic crash")
        if context.gate_id in self.use_privilege_on:
            command = context.privileged_commands.execute(
                ("/logical/helper", context.gate_id.lower()),
                timeout_seconds=30.0,
            )
            assert command.logical_argv == (
                "/logical/helper",
                context.gate_id.lower(),
            )
        permits = context.attempts
        if context.gate_id == self.omit_last_attempt_gate:
            permits = permits[:-1]
        for permit in permits:
            identity = hashlib.sha256(permit.attempt_id.encode("utf-8")).hexdigest()
            permit.start(identity_sha256=identity)
            if context.gate_id == "ENOSPC" and permit.role == "target":
                permit.bind_private_authorization(
                    authorization_identity_sha256="a" * 64
                )
            evidence = self._write(
                f"gates/{context.gate_id}/attempts/{permit.attempt_id}.json",
                json.dumps(
                    {
                        "attempt_id": permit.attempt_id,
                        "kind": permit.kind.value,
                        "role": permit.role,
                    },
                    sort_keys=True,
                ),
            )
            permit.complete(
                outcome_code=(
                    "port_lease_conflict"
                    if permit.kind.value == "non_runtime_conflict"
                    else "terminal_recorded"
                ),
                evidence_paths=(evidence,),
            )
        gate_evidence = self._write(
            f"gates/{context.gate_id}/gate-result.json",
            json.dumps(
                {"gate_id": context.gate_id, "criteria": context.required_criteria},
                sort_keys=True,
            ),
        )
        self.gate_evidence[context.gate_id] = gate_evidence
        if context.gate_id == self.fail_gate:
            return GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=context.required_criteria[:-1],
                evidence_paths=(gate_evidence,),
                failure_code="synthetic_gate_failure",
            )
        return GateExecutionResult(
            gate_id=self.wrong_gate_result or context.gate_id,
            criteria_passed=context.required_criteria,
            evidence_paths=(gate_evidence,),
        )

    def cleanup_pass(self, context: CleanupPassContext) -> CleanupPassResult:
        key = (context.scope, context.gate_id, context.pass_index)
        self.cleanup_calls.append(key)
        if key == self.interrupt_cleanup:
            self.interrupt_cleanup = None
            raise KeyboardInterrupt("synthetic cleanup crash")
        if (
            context.scope == "batch"
            and context.pass_index == 2
            and self.mutate_gate_evidence_during_final_cleanup is not None
        ):
            self.gate_evidence[
                self.mutate_gate_evidence_during_final_cleanup
            ].write_text("mutated", encoding="utf-8")
        path = self._write(
            "cleanup/"
            f"{context.scope}-{context.gate_id or 'final'}-pass-{context.pass_index}.json",
            json.dumps(
                {
                    "scope": context.scope,
                    "gate_id": context.gate_id,
                    "pass_index": context.pass_index,
                },
                sort_keys=True,
            ),
        )
        criteria = next(
            gate.criteria for gate in FROZEN_GATE_PLAN if gate.gate_id == "CLEANUP"
        )
        if key == self.cleanup_fail:
            return CleanupPassResult(
                scope=context.scope,
                gate_id=context.gate_id,
                pass_index=context.pass_index,
                criteria_passed=criteria[:-1],
                evidence_paths=(path,),
                failure_code="synthetic_cleanup_failure",
            )
        return CleanupPassResult(
            scope=context.scope,
            gate_id=context.gate_id,
            pass_index=context.pass_index,
            criteria_passed=criteria,
            evidence_paths=(path,),
        )


@dataclass(frozen=True)
class Packet:
    root: Path
    contract: Path
    source: SourceManifestLock
    credits: tuple[LocalCreditImport, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_packet(tmp_path: Path, *, name: str = "packet") -> Packet:
    root = (tmp_path / name).resolve()
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    contract = inputs / "acceptance.yaml"
    shutil.copyfile(_ACCEPTANCE, contract)
    assert _sha256(contract) == FROZEN_ACCEPTANCE_SHA256
    source_path = inputs / "source-manifest.sha256"
    source_path.write_text("1" * 64 + "  source-tree\n", encoding="utf-8")
    credits: list[LocalCreditImport] = []
    for gate in FROZEN_GATE_PLAN:
        if gate.local_credit_scope is None:
            continue
        path = inputs / "local" / f"{gate.gate_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "gate_id": gate.gate_id,
                    "scope": gate.local_credit_scope.value,
                    "criteria": gate.criteria,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        credits.append(
            LocalCreditImport(
                gate_id=gate.gate_id,
                scope=gate.local_credit_scope,
                criteria_passed=gate.criteria,
                evidence_paths=(path,),
            )
        )
    return Packet(
        root=root,
        contract=contract,
        source=SourceManifestLock(path=source_path, sha256=_sha256(source_path)),
        credits=tuple(credits),
    )


def _controller(
    packet: Packet,
    adapter: FakeAdapter,
    *,
    privileged: FakePrivilegedCommands | None = None,
    clock: DeterministicClock | None = None,
    credits: tuple[LocalCreditImport, ...] | None = None,
) -> LiveAcceptanceBatchController:
    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id="m1b-live-20260817",
        evidence_root=packet.root,
        contract_path=packet.contract,
    )
    return LiveAcceptanceBatchController(
        authorization=authorization,
        adapter=adapter,
        privileged_commands=privileged or FakePrivilegedCommands(),
        source_manifest=packet.source,
        local_credits=packet.credits if credits is None else credits,
        now=clock or DeterministicClock(),
    )


def _ledger(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_frozen_plan_has_exact_order_and_26_runtime_slots() -> None:
    assert [gate.gate_id for gate in FROZEN_GATE_PLAN] == [
        "PORT-1",
        "PORT-2",
        "COLD-RETRY",
        "CO-8",
        "DF-KILL",
        "HARNESS-KILL",
        "OOM",
        "ENOSPC",
        "CONTAINER-RESTART",
        "DAEMON-RESTART",
        "ORPHAN-1",
        "ORPHAN-2",
        "PROVIDER-ENV",
        "PROVIDER-NET",
        "CAP-FAKE",
        "CLEANUP",
    ]
    assert sum(gate.real_runtime_attempts for gate in FROZEN_GATE_PLAN) == 26
    non_runtime = [
        (gate.gate_id, attempt.role)
        for gate in FROZEN_GATE_PLAN
        for attempt in gate.attempts
        if attempt.kind.value == "non_runtime_conflict"
    ]
    assert non_runtime == [("PORT-2", "contender_b")]


@pytest.mark.parametrize("test_mode", [False, 1, "1", {}, None])
def test_authorization_rejects_every_nonliteral_test_mode(
    tmp_path: Path, test_mode: object
) -> None:
    packet = _make_packet(tmp_path)
    with pytest.raises(LiveAcceptanceAuthorizationError):
        authorize_private_m1b_live_acceptance(
            test_mode=test_mode,  # type: ignore[arg-type]
            batch_id="m1b-live-20260817",
            evidence_root=packet.root,
            contract_path=packet.contract,
        )


def test_authorization_is_single_use_and_redacted(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id="m1b-live-20260817",
        evidence_root=packet.root,
        contract_path=packet.contract,
    )
    assert "capability=<redacted>" in repr(authorization)
    kwargs = {
        "authorization": authorization,
        "adapter": FakeAdapter(packet.root),
        "privileged_commands": FakePrivilegedCommands(),
        "source_manifest": packet.source,
        "local_credits": packet.credits,
    }
    LiveAcceptanceBatchController(**kwargs)
    with pytest.raises(LiveAcceptanceAuthorizationError, match="single-use"):
        LiveAcceptanceBatchController(**kwargs)


def test_rejects_contract_hash_drift_before_writing(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    packet.contract.write_text(
        packet.contract.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(LiveAcceptanceContractError, match="hash differs"):
        _controller(packet, FakeAdapter(packet.root))
    assert not (packet.root / "control").exists()


def test_rejects_in_code_plan_digest_drift_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet = _make_packet(tmp_path)
    monkeypatch.setattr(live, "FROZEN_PLAN_SHA256", "0" * 64)
    with pytest.raises(LiveAcceptanceContractError, match="plan digest differs"):
        _controller(packet, FakeAdapter(packet.root))
    assert not (packet.root / "control").exists()


def test_rejects_source_manifest_hash_drift(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    packet.source.path.write_text("drift", encoding="utf-8")
    with pytest.raises(LiveAcceptanceEvidenceError, match="digest differs"):
        _controller(packet, FakeAdapter(packet.root))


def test_rejects_symlinked_packet_or_contract_roots(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    root_link = (tmp_path / "packet-link").resolve(strict=False)
    root_link.symlink_to(packet.root, target_is_directory=True)
    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id="m1b-live-20260817",
        evidence_root=root_link,
        contract_path=packet.contract,
    )
    with pytest.raises(LiveAcceptanceEvidenceError, match="root cannot be a symlink"):
        LiveAcceptanceBatchController(
            authorization=authorization,
            adapter=FakeAdapter(packet.root),
            privileged_commands=FakePrivilegedCommands(),
            source_manifest=packet.source,
            local_credits=packet.credits,
        )

    contract_link = packet.root / "inputs" / "acceptance-link.yaml"
    contract_link.symlink_to(packet.contract)
    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id="m1b-live-20260817",
        evidence_root=packet.root,
        contract_path=contract_link,
    )
    with pytest.raises(LiveAcceptanceContractError, match="cannot be a symlink"):
        LiveAcceptanceBatchController(
            authorization=authorization,
            adapter=FakeAdapter(packet.root),
            privileged_commands=FakePrivilegedCommands(),
            source_manifest=packet.source,
            local_credits=packet.credits,
        )


def test_rejects_local_credit_promotion_or_omission(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    with pytest.raises(LiveAcceptanceEvidenceError, match="exactly match"):
        _controller(packet, FakeAdapter(packet.root), credits=packet.credits[:-1])
    wrong = list(packet.credits)
    orphan_index = next(
        index for index, credit in enumerate(wrong) if credit.gate_id == "ORPHAN-1"
    )
    orphan = wrong[orphan_index]
    wrong[orphan_index] = LocalCreditImport(
        gate_id=orphan.gate_id,
        scope=LocalCreditScope.COMPLETE_LOCAL_GATE,
        criteria_passed=orphan.criteria_passed,
        evidence_paths=orphan.evidence_paths,
    )
    with pytest.raises(LiveAcceptanceEvidenceError, match="scope differs"):
        _controller(packet, FakeAdapter(packet.root), credits=tuple(wrong))


def test_focused_two_fort_selection_preserves_frozen_matrix_and_no_go(
    tmp_path: Path, monkeypatch
) -> None:
    packet = _make_packet(tmp_path, name="state/evidence/m1b-live-20260817")
    source_path = packet.root / "inputs" / "source-manifest.json"
    packet.source.path.rename(source_path)
    packet = replace(packet, source=SourceManifestLock(path=source_path, sha256=_sha256(source_path)))
    calls = FakeAdapter(packet.root)

    class Backend:
        execute = calls.execute_gate
        cleanup = calls.cleanup_pass

    adapter = LinuxM1BHostAdapter(Backend(), two_fort_diagnostic=True)
    controller = _controller(packet, adapter)
    outcome = controller.run()
    assert calls.executed == ["DF-KILL"]
    assert outcome.real_runtime_attempts_started == 2
    assert outcome.real_runtime_attempts_completed == 2
    assert outcome.non_runtime_attempts_started == 0
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    assert len(calls.cleanup_calls) == 32
    results = json.loads(outcome.gate_results_path.read_text())["gates"]
    assert [row["gate"]["id"] for row in results] == [gate.gate_id for gate in FROZEN_GATE_PLAN]
    for row in results:
        if row["gate"]["class"] == "live" and row["gate"]["id"] != "DF-KILL":
            assert row["status"] == "FAIL"
            assert row["failure_code"] == "diagnostic_not_selected"
    manifest = json.loads(outcome.evidence_manifest_path.read_text())
    assert any(item["path"].endswith("/not-selected.json") for item in manifest["artifacts"])
    layout = BrokerLayout(
        repo_root=_REPO_ROOT,
        state_root=(tmp_path / "state").resolve(),
        packet_root=(tmp_path / "pinned-inputs").resolve(),
    )
    layout.packet_root.mkdir()
    layout.source_manifest_path.write_bytes(packet.source.path.read_bytes())
    broker = RootBroker(layout=layout, caller_uid=os.getuid(), trusted_uid=os.getuid())
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    attempts = [json.loads(line) for line in controller.attempt_ledger_path.read_text().splitlines()]
    batch = [json.loads(line) for line in controller.batch_ledger_path.read_text().splitlines()]
    mirror = broker._strict_attempt_replay(attempts)
    phase = broker._strict_batch_replay(batch, attempt_records=attempts, attempts=mirror)
    assert phase.finalized is True
    document_paths = {
        "gate_results": outcome.gate_results_path,
        "decision": outcome.decision_path,
        "evidence_manifest": outcome.evidence_manifest_path,
        "seal": outcome.seal_path,
    }
    counts = broker._validate_final_controller_documents(
        batch_id="m1b-live-20260817",
        batch_root=packet.root,
        documents={key: json.loads(path.read_text()) for key, path in document_paths.items()},
        digests={key: _sha256(path) for key, path in document_paths.items()},
        snapshot=_LedgerSnapshot(
            batch_records=tuple(batch),
            attempt_records=tuple(attempts),
            phase=phase,
            attempts=mirror,
            batch_file_sha256=_sha256(controller.batch_ledger_path),
            attempt_file_sha256=_sha256(controller.attempt_ledger_path),
        ),
        caller_uid=os.getuid(),
    )
    assert counts == {
        "planned": 27,
        "real_runtime_started": 2,
        "real_runtime_completed": 2,
        "non_runtime_started": 0,
        "non_runtime_completed": 0,
    }


def test_failed_gate_diagnostic_bytes_are_sealed_and_survive_source_teardown(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    source = tmp_path.resolve() / "runtime"
    attempt = source / "control/target/attempts/attempt-0001"
    attempt.mkdir(parents=True)
    (attempt / "child.stderr.log").write_text("exact pre-readiness worker failure\n")

    class DiagnosticAdapter(FakeAdapter):
        def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
            result = super().execute_gate(context)
            if context.gate_id != "DF-KILL":
                return result
            payload = capture_run_diagnostics(
                control_root=source / "control", artifacts_root=source / "artifacts", run_id="target",
            )
            path = self._write("gates/DF-KILL/diagnostics/gate-return/target.json", json.dumps(payload))
            return replace(result, evidence_paths=(*result.evidence_paths, path))

    controller = _controller(packet, DiagnosticAdapter(packet.root, fail_gate="DF-KILL"))
    outcome = controller.run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    relative = "gates/DF-KILL/diagnostics/gate-return/target.json"
    manifest = json.loads(outcome.evidence_manifest_path.read_text())
    reference = next(item for item in manifest["artifacts"] if item["path"] == relative)
    retained = packet.root / relative
    assert reference["sha256"] == hashlib.sha256(retained.read_bytes()).hexdigest()
    shutil.rmtree(source)  # only this test's temporary, already-exported runtime
    assert controller.run().decision is BatchDecisionValue.INCOMPLETE_NO_GO
    assert "exact pre-readiness worker failure" in retained.read_text()
    retained.write_text("{}\n")
    with pytest.raises(LiveAcceptanceEvidenceError):
        controller.run()


def test_full_fake_batch_go_has_exact_attempt_and_cleanup_accounting(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root)
    privileged = FakePrivilegedCommands()
    controller = _controller(packet, adapter, privileged=privileged)

    outcome = controller.run()

    assert outcome.decision is BatchDecisionValue.GO
    assert outcome.real_runtime_attempts_started == 26
    assert outcome.real_runtime_attempts_completed == 26
    assert outcome.non_runtime_attempts_started == 1
    assert outcome.non_runtime_attempts_completed == 1
    assert len(adapter.cleanup_calls) == 32
    assert adapter.cleanup_calls[-2:] == [("batch", None, 1), ("batch", None, 2)]
    assert "PORT-1" not in adapter.executed
    assert "PROVIDER-ENV" not in adapter.executed
    assert "CAP-FAKE" not in adapter.executed
    assert "CLEANUP" not in adapter.executed
    assert "ORPHAN-1" in adapter.executed
    assert adapter.contexts["ORPHAN-1"].local_credit is not None
    assert [call[0][1] for call in privileged.calls] == [
        "df-kill",
        "enospc",
        "daemon-restart",
    ]

    gate_results = json.loads(outcome.gate_results_path.read_text(encoding="utf-8"))
    assert [row["gate"]["id"] for row in gate_results["gates"]] == [
        gate.gate_id for gate in FROZEN_GATE_PLAN
    ]
    statuses = {row["gate"]["id"]: row["status"] for row in gate_results["gates"]}
    assert statuses["PORT-1"] == GateStatus.PASS_LOCAL.value
    assert statuses["PROVIDER-ENV"] == GateStatus.PASS_LOCAL.value
    assert statuses["CAP-FAKE"] == GateStatus.PASS_LOCAL.value
    assert statuses["ORPHAN-1"] == GateStatus.PASS.value
    assert statuses["CLEANUP"] == GateStatus.PASS.value


def test_port2_conflict_is_separate_nonruntime_attempt(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    controller = _controller(packet, FakeAdapter(packet.root))
    controller.run()
    rows = _ledger(controller.attempt_ledger_path)
    starts = [row["payload"] for row in rows if row["event"] == "attempt_started"]
    port2 = [row for row in starts if row["gate_id"] == "PORT-2"]
    assert [(row["role"], row["kind"]) for row in port2] == [
        ("peer_a", "real_runtime"),
        ("contender_b", "non_runtime_conflict"),
    ]
    assert sum(row["kind"] == "real_runtime" for row in starts) == 26
    assert sum(row["kind"] == "non_runtime_conflict" for row in starts) == 1


def test_enospc_requires_and_records_private_authorization_binding(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    controller = _controller(packet, FakeAdapter(packet.root))
    controller.run()
    rows = _ledger(controller.attempt_ledger_path)
    bindings = [
        row["payload"] for row in rows if row["event"] == "private_authorization_bound"
    ]
    assert bindings == [
        {
            "gate_id": "ENOSPC",
            "attempt_id": "g08-a01-target",
            "authorization_identity_sha256": "a" * 64,
        }
    ]


def test_attempt_permits_reject_reuse_and_completion_before_start(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)

    class BadAdapter(FakeAdapter):
        def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
            if context.gate_id != "PORT-2":
                return super().execute_gate(context)
            permit = context.attempts[0]
            evidence = self._write("bad/evidence.json", "{}")
            with pytest.raises(LiveAcceptanceProtocolError, match="durable start"):
                permit.complete(
                    outcome_code="terminal_recorded", evidence_paths=(evidence,)
                )
            permit.start(identity_sha256="a" * 64)
            with pytest.raises(LiveAcceptanceProtocolError, match="single-use"):
                permit.start(identity_sha256="a" * 64)
            permit.complete(
                outcome_code="terminal_recorded", evidence_paths=(evidence,)
            )
            second = context.attempts[1]
            second.start(identity_sha256="b" * 64)
            second_evidence = self._write("bad/conflict.json", "{}")
            second.complete(
                outcome_code="port_lease_conflict",
                evidence_paths=(second_evidence,),
            )
            gate_evidence = self._write("bad/gate.json", "{}")
            return GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=context.required_criteria,
                evidence_paths=(gate_evidence,),
            )

    outcome = _controller(packet, BadAdapter(packet.root)).run()
    assert outcome.decision is BatchDecisionValue.GO


def test_worker_thread_can_durably_account_attempts_while_batch_is_running(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)

    class WorkerAdapter(FakeAdapter):
        def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
            if context.gate_id != "PORT-2":
                return super().execute_gate(context)
            errors: list[BaseException] = []

            def account() -> None:
                try:
                    for permit in context.attempts:
                        permit.start(
                            identity_sha256=hashlib.sha256(
                                permit.attempt_id.encode("utf-8")
                            ).hexdigest()
                        )
                        evidence = self._write(
                            f"threaded/{permit.attempt_id}.json", "{}"
                        )
                        permit.complete(
                            outcome_code=(
                                "port_lease_conflict"
                                if permit.kind.value == "non_runtime_conflict"
                                else "terminal_recorded"
                            ),
                            evidence_paths=(evidence,),
                        )
                except BaseException as exc:  # noqa: BLE001 - re-raise in caller
                    errors.append(exc)

            worker = threading.Thread(target=account, name="attempt-accounting")
            worker.start()
            worker.join(timeout=2.0)
            assert not worker.is_alive(), "attempt accounting deadlocked behind run lock"
            if errors:
                raise errors[0]
            gate_evidence = self._write("threaded/PORT-2.json", "{}")
            return GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=context.required_criteria,
                evidence_paths=(gate_evidence,),
            )

    outcome = _controller(packet, WorkerAdapter(packet.root)).run()
    assert outcome.decision is BatchDecisionValue.GO
    starts = [
        row["payload"]
        for row in _ledger(packet.root / "control" / "attempt-ledger.jsonl")
        if row["event"] == "attempt_started"
        and row["payload"]["gate_id"] == "PORT-2"
    ]
    assert [row["attempt_id"] for row in starts] == [
        "g02-a01-peer_a",
        "g02-a02-contender_b",
    ]


def test_enospc_target_cannot_complete_without_binding(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)

    class MissingBindingAdapter(FakeAdapter):
        def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
            if context.gate_id != "ENOSPC":
                return super().execute_gate(context)
            target = context.attempts[0]
            target.start(identity_sha256="a" * 64)
            evidence = self._write("enospc/unbound.json", "{}")
            with pytest.raises(
                LiveAcceptanceProtocolError, match="requires authorization binding"
            ):
                target.complete(
                    outcome_code="terminal_recorded",
                    evidence_paths=(evidence,),
                )
            return GateExecutionResult(
                gate_id="ENOSPC",
                criteria_passed=(),
                evidence_paths=(evidence,),
                failure_code="authorization_unavailable",
            )

    outcome = _controller(packet, MissingBindingAdapter(packet.root)).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    decision = json.loads(outcome.decision_path.read_text(encoding="utf-8"))
    assert "gate_not_passed:ENOSPC" in decision["reasons"]
    assert "attempt_terminal_evidence_incomplete" in decision["reasons"]


def test_missing_attempt_forces_no_go_even_with_all_criteria(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root, omit_last_attempt_gate="CO-8")
    outcome = _controller(packet, adapter).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    decision = json.loads(outcome.decision_path.read_text(encoding="utf-8"))
    assert "gate_not_passed:CO-8" in decision["reasons"]
    assert decision["real_runtime_attempts_started"] == 25
    assert "real_runtime_attempt_count_not_26" in decision["reasons"]


def test_failed_gate_never_prevents_remaining_safe_gates_after_clean_cleanup(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root, fail_gate="DF-KILL")
    outcome = _controller(packet, adapter).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    assert adapter.executed[-1] == "PROVIDER-NET"
    decision = json.loads(outcome.decision_path.read_text(encoding="utf-8"))
    assert decision["failed_or_incomplete_gates"] == ["DF-KILL"]


def test_cleanup_failure_runs_both_passes_stops_new_gates_and_runs_final_cleanup(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(
        packet.root,
        cleanup_fail=("gate", "COLD-RETRY", 1),
    )
    outcome = _controller(packet, adapter).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    assert ("gate", "COLD-RETRY", 1) in adapter.cleanup_calls
    assert ("gate", "COLD-RETRY", 2) in adapter.cleanup_calls
    assert adapter.cleanup_calls[-2:] == [("batch", None, 1), ("batch", None, 2)]
    assert adapter.executed == ["PORT-2", "COLD-RETRY"]
    decision = json.loads(outcome.decision_path.read_text(encoding="utf-8"))
    assert "CLEANUP" in decision["failed_or_incomplete_gates"]
    assert "CO-8" in decision["failed_or_incomplete_gates"]


def test_zero_attempt_cleanup_failure_seals_with_durable_empty_attempt_ledger(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(
        packet.root,
        cleanup_fail=("gate", "PORT-1", 1),
    )
    controller = _controller(packet, adapter)

    outcome = controller.run()

    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    assert adapter.executed == []
    assert controller.attempt_ledger_path.is_file()
    assert not controller.attempt_ledger_path.is_symlink()
    assert controller.attempt_ledger_path.read_bytes() == b""
    manifest = json.loads(outcome.evidence_manifest_path.read_text(encoding="utf-8"))
    attempt_entry = next(
        item
        for item in manifest["artifacts"]
        if item["path"] == "control/attempt-ledger.jsonl"
    )
    assert attempt_entry == {
        "path": "control/attempt-ledger.jsonl",
        "sha256": hashlib.sha256(b"").hexdigest(),
        "size_bytes": 0,
    }


def test_resume_retries_only_missing_cleanup_pass(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(
        packet.root,
        interrupt_cleanup=("gate", "PORT-1", 2),
    )
    controller = _controller(packet, adapter)
    with pytest.raises(KeyboardInterrupt):
        controller.run()
    assert adapter.cleanup_calls == [
        ("gate", "PORT-1", 1),
        ("gate", "PORT-1", 2),
    ]

    resumed = _controller(packet, adapter)
    outcome = resumed.run()
    assert outcome.decision is BatchDecisionValue.GO
    assert adapter.cleanup_calls.count(("gate", "PORT-1", 1)) == 1
    assert adapter.cleanup_calls.count(("gate", "PORT-1", 2)) == 2


def test_resume_refuses_to_guess_interrupted_gate(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root, interrupt_gate="PORT-2")
    with pytest.raises(KeyboardInterrupt):
        _controller(packet, adapter).run()
    adapter.interrupt_gate = None
    with pytest.raises(LiveAcceptanceResumeError, match="cannot be inferred"):
        _controller(packet, adapter).run()
    assert adapter.executed.count("PORT-2") == 1


def test_sealed_resume_is_read_only_and_returns_same_outcome(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    first_adapter = FakeAdapter(packet.root)
    first = _controller(packet, first_adapter).run()
    ledger_before = (packet.root / "control" / "batch-ledger.jsonl").read_bytes()
    second_adapter = FakeAdapter(packet.root)
    second = _controller(packet, second_adapter).run()
    assert second == first
    assert second_adapter.executed == []
    assert second_adapter.cleanup_calls == []
    assert (
        packet.root / "control" / "batch-ledger.jsonl"
    ).read_bytes() == ledger_before


def test_ledger_tamper_and_evidence_hash_drift_fail_closed(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root)
    controller = _controller(packet, adapter)
    controller.run()
    rows = _ledger(controller.batch_ledger_path)
    rows[0]["payload"]["plan_sha256"] = "0" * 64
    controller.batch_ledger_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LiveAcceptanceEvidenceError, match="hash chain differs"):
        _controller(packet, FakeAdapter(packet.root)).run()

    packet2 = _make_packet(tmp_path, name="packet2")
    adapter2 = FakeAdapter(packet2.root)
    controller2 = _controller(packet2, adapter2)
    controller2.run()
    adapter2.gate_evidence["DF-KILL"].write_text("drift", encoding="utf-8")
    with pytest.raises(LiveAcceptanceEvidenceError, match="hash drifted"):
        _controller(packet2, FakeAdapter(packet2.root)).run()


def test_external_or_symlink_evidence_is_rejected_without_copying_content(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    outside = tmp_path / "outside-secret.json"
    outside.write_text("TOP_SECRET_VALUE", encoding="utf-8")

    class OutsideAdapter(FakeAdapter):
        def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
            if context.gate_id == "PORT-2":
                return GateExecutionResult(
                    gate_id=context.gate_id,
                    criteria_passed=(),
                    evidence_paths=(outside,),
                    failure_code="outside_evidence",
                )
            return super().execute_gate(context)

    outcome = _controller(packet, OutsideAdapter(packet.root)).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    control_bytes = b"".join(
        path.read_bytes()
        for path in (packet.root / "control").iterdir()
        if path.is_file()
    )
    assert b"TOP_SECRET_VALUE" not in control_bytes

    packet2 = _make_packet(tmp_path, name="packet-symlink")
    symlink = packet2.root / "inputs" / "linked-evidence.json"
    symlink.symlink_to(outside)
    credit = packet2.credits[0]
    credits = list(packet2.credits)
    credits[0] = LocalCreditImport(
        gate_id=credit.gate_id,
        scope=credit.scope,
        criteria_passed=credit.criteria_passed,
        evidence_paths=(symlink,),
    )
    with pytest.raises(LiveAcceptanceEvidenceError, match="symlink"):
        _controller(
            packet2,
            FakeAdapter(packet2.root),
            credits=tuple(credits),
        )


def test_manifest_and_seal_are_sorted_content_addressed_and_deterministic(
    tmp_path: Path,
) -> None:
    packet_a = _make_packet(tmp_path, name="packet-a")
    packet_b = _make_packet(tmp_path, name="packet-b")
    outcome_a = _controller(packet_a, FakeAdapter(packet_a.root)).run()
    outcome_b = _controller(packet_b, FakeAdapter(packet_b.root)).run()

    manifest_a = json.loads(
        outcome_a.evidence_manifest_path.read_text(encoding="utf-8")
    )
    manifest_b = json.loads(
        outcome_b.evidence_manifest_path.read_text(encoding="utf-8")
    )
    paths = [item["path"] for item in manifest_a["artifacts"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert manifest_a == manifest_b
    assert outcome_a.seal_path.read_bytes() == outcome_b.seal_path.read_bytes()


def test_gate_evidence_mutation_before_seal_is_detected(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(
        packet.root,
        mutate_gate_evidence_during_final_cleanup="DF-KILL",
    )
    with pytest.raises(LiveAcceptanceEvidenceError, match="hash drifted"):
        _controller(packet, adapter).run()
    assert not (packet.root / "control" / "seal.json").exists()


def test_ledgers_and_write_once_outputs_are_private_files(tmp_path: Path) -> None:
    packet = _make_packet(tmp_path)
    controller = _controller(packet, FakeAdapter(packet.root))
    outcome = controller.run()
    for path in (
        controller.batch_ledger_path,
        controller.attempt_ledger_path,
        outcome.gate_results_path,
        outcome.decision_path,
        outcome.evidence_manifest_path,
        outcome.seal_path,
    ):
        assert path.stat().st_mode & 0o777 == 0o600


def test_append_paths_call_fsync_for_files_and_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet = _make_packet(tmp_path)
    calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(live.os, "fsync", recording_fsync)
    _controller(packet, FakeAdapter(packet.root)).run()
    assert len(calls) > 100


def test_privileged_command_result_binds_original_argv_without_shell() -> None:
    fake = FakePrivilegedCommands()
    result = fake.execute(("/bin/kill", "-KILL", "123"), timeout_seconds=10.0)
    assert result.logical_argv == ("/bin/kill", "-KILL", "123")
    assert fake.calls == [(result.logical_argv, 10.0)]
    with pytest.raises(ValueError, match="argv"):
        PrivilegedCommandResult(
            logical_argv=("/bin/sh\0",),
            returncode=0,
            stdout_sha256="0" * 64,
            stderr_sha256="0" * 64,
            executor_identity_sha256="0" * 64,
        )
    with pytest.raises(ValueError, match="never use a shell"):
        PrivilegedCommandResult(
            logical_argv=("/bin/kill", "-KILL", "123"),
            returncode=0,
            stdout_sha256="0" * 64,
            stderr_sha256="0" * 64,
            executor_identity_sha256="0" * 64,
            shell=True,
        )


def test_adapter_result_for_wrong_gate_fails_closed_without_secret_exception_text(
    tmp_path: Path,
) -> None:
    packet = _make_packet(tmp_path)
    adapter = FakeAdapter(packet.root, wrong_gate_result="CO-8")
    outcome = _controller(packet, adapter).run()
    assert outcome.decision is BatchDecisionValue.INCOMPLETE_NO_GO
    batch_bytes = (packet.root / "control" / "batch-ledger.jsonl").read_bytes()
    assert b"gate adapter result identity differs" not in batch_bytes
    assert b"adapter_liveacceptanceprotocolerror" in batch_bytes
