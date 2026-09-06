from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.run.live_acceptance import (
    FROZEN_ACCEPTANCE_SHA256,
    FROZEN_PLAN_SHA256,
    GateExecutionContext,
)
from infra.m1b import diagnostics
from infra.m1b.run_live_acceptance import HostPaths, LinuxGateBackend, VerifiedGateReceipt


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    control = tmp_path.resolve() / "control"
    artifacts = tmp_path.resolve() / "artifacts"
    (control / "target" / "attempts" / "attempt-0001").mkdir(parents=True)
    (artifacts / "target").mkdir(parents=True)
    return control, artifacts


def _snapshot(control: Path, artifacts: Path) -> dict:
    return diagnostics.capture_run_diagnostics(
        control_root=control, artifacts_root=artifacts, run_id="target"
    )


def test_snapshot_retains_terminal_journal_and_stderr_without_foreign_files(tmp_path: Path) -> None:
    control, artifacts = _roots(tmp_path)
    original = '{"reason":"RPC listener never opened"}\n'
    attempt = control / "target/attempts/attempt-0001"
    (attempt / "terminal.json").write_text(original)
    (attempt / "attempt-journal.jsonl").write_text('{"event":"child_started"}\n')
    (attempt / "child.stderr.log").write_text("real failure detail\n")
    (control / "target/manager-terminal.json").write_text(original)
    (control / "target/credentials.json").write_text("MUST_NOT_EXPORT")
    (control / "target/home").mkdir()
    (control / "target/home/terminal.json").write_text("MUST_NOT_EXPORT")
    (control / "foreign").mkdir()
    (control / "foreign/manager-terminal.json").write_text("MUST_NOT_EXPORT")
    snapshot = _snapshot(control, artifacts)
    assert snapshot["capture_ok"] is True
    assert snapshot["terminal_evidence_present"] is True
    record = next(x for x in snapshot["files"] if x["path"].endswith("attempt-0001/terminal.json"))
    assert record["content"] == original
    assert record["captured_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert record["byte_exact"] is True
    assert "real failure detail" in json.dumps(snapshot)
    assert "MUST_NOT_EXPORT" not in json.dumps(snapshot)


@pytest.mark.parametrize("link_kind", ["symlink", "ancestor_symlink", "hardlink", "fifo"])
def test_snapshot_never_follows_unsafe_sources(tmp_path: Path, link_kind: str) -> None:
    control, artifacts = _roots(tmp_path)
    private = tmp_path / "private.txt"
    private.write_text("MUST_NOT_EXPORT")
    selected = control / "target/manager-terminal.json"
    if link_kind == "symlink":
        selected.symlink_to(private)
    elif link_kind == "hardlink":
        os.link(private, selected)
    elif link_kind == "fifo":
        os.mkfifo(selected)
    else:
        # A linked named directory must not grant access to another run/root.
        (control / "target/attempts/attempt-0001").rmdir()
        (control / "target/attempts/attempt-0001").symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "terminal.json").write_text("MUST_NOT_EXPORT")
    snapshot = _snapshot(control, artifacts)
    assert snapshot["capture_ok"] is False
    assert "MUST_NOT_EXPORT" not in json.dumps(snapshot)


def test_missing_terminal_is_unknown_not_success(tmp_path: Path) -> None:
    control, artifacts = _roots(tmp_path)
    snapshot = _snapshot(control, artifacts)
    assert snapshot["terminal_evidence_present"] is False
    assert {x["status"] for x in snapshot["files"]} == {"missing"}


def test_cleanup_container_logs_survive_diagnostic_export(tmp_path: Path) -> None:
    control, artifacts = _roots(tmp_path)
    runtime = control / "target/attempts/attempt-0001/runtime"
    runtime.mkdir()
    for stream in ("stdout", "stderr"):
        name = f"container.logs.{stream}.txt"
        original = f"2026-09-05T14:00:00Z startup failure on {stream}\n"
        (runtime / name).write_text(original)
    (runtime / "unselected.log").write_text("MUST_NOT_EXPORT")
    snapshot = _snapshot(control, artifacts)
    for stream in ("stdout", "stderr"):
        record = next(
            item for item in snapshot["files"]
            if item["path"].endswith(f"/container.logs.{stream}.txt")
        )
        assert record["byte_exact"] is True
        assert f"startup failure on {stream}" in record["content"]
    assert snapshot["capture_ok"] is True
    assert snapshot["terminal_evidence_present"] is False
    assert "MUST_NOT_EXPORT" not in json.dumps(snapshot)


def test_container_log_export_keeps_redaction_and_size_limits(tmp_path: Path, monkeypatch) -> None:
    control, artifacts = _roots(tmp_path)
    runtime = control / "target/attempts/attempt-0001/runtime"
    runtime.mkdir()
    (runtime / "container.logs.stdout.txt").write_text("OPENAI_API_KEY=private-value\n")
    (runtime / "container.logs.stderr.txt").write_text("x" * 100)
    monkeypatch.setattr(diagnostics, "MAX_FILE_BYTES", 64)
    snapshot = _snapshot(control, artifacts)
    logs = [item for item in snapshot["files"] if "/container.logs." in item["path"]]
    assert len(logs) == 2
    assert any(item["redacted"] for item in logs)
    assert any(item["truncated"] for item in logs)
    assert snapshot["capture_ok"] is False
    assert "private-value" not in json.dumps(snapshot)


def test_capture_limits_and_redaction_are_explicit(tmp_path: Path, monkeypatch) -> None:
    control, artifacts = _roots(tmp_path)
    (control / "target/owner.json").write_text("OPENROUTER_API_KEY=private-value\n")
    (control / "target/manager-journal.jsonl").write_text("x" * 100)
    monkeypatch.setattr(diagnostics, "MAX_FILE_BYTES", 64)
    monkeypatch.setattr(diagnostics, "MAX_RUN_BYTES", 80)
    snapshot = _snapshot(control, artifacts)
    assert snapshot["capture_ok"] is False
    assert snapshot["captured_bytes"] <= 80
    assert "private-value" not in json.dumps(snapshot)
    assert any(x.get("redacted") for x in snapshot["files"])
    assert any(x.get("truncated") for x in snapshot["files"])


def test_complete_twenty_step_trace_exceeding_generic_file_limit_is_retained(tmp_path: Path) -> None:
    control, artifacts = _roots(tmp_path)
    # The first successful real peer produced a 3,440,341-byte trace.
    original = b" " * 3_440_340 + b"\n"
    (artifacts / "target/trace.jsonl").write_bytes(original)
    snapshot = _snapshot(control, artifacts)
    record = next(x for x in snapshot["files"] if x["area"] == "artifacts" and x["path"] == "trace.jsonl")
    assert record["content"].encode() == original
    assert record["captured_sha256"] == hashlib.sha256(original).hexdigest()
    assert record["truncated"] is False
    assert snapshot["capture_ok"] is True
    assert snapshot["captured_bytes"] <= diagnostics.MAX_RUN_BYTES


def test_trace_exception_still_obeys_per_run_and_trace_bounds(tmp_path: Path, monkeypatch) -> None:
    control, artifacts = _roots(tmp_path)
    (artifacts / "target/trace.jsonl").write_text("x" * 100)
    monkeypatch.setattr(diagnostics, "MAX_TRACE_BYTES", 80)
    monkeypatch.setattr(diagnostics, "MAX_RUN_BYTES", 60)
    snapshot = _snapshot(control, artifacts)
    assert snapshot["captured_bytes"] == 60
    assert snapshot["capture_ok"] is False
    assert any(record.get("truncated") for record in snapshot["files"])


def test_exception_preserves_cause_and_location_without_locals_or_secrets() -> None:
    private_local = "MUST_NOT_EXPORT"
    try:
        try:
            raise ValueError("RPC did not settle")
        except ValueError as cause:
            raise RuntimeError("request failed Bearer " + "sensitive" * 5) from cause
    except RuntimeError as exc:
        payload = diagnostics.describe_exception(exc)
    assert [x["error_type"] for x in payload["chain"]] == ["RuntimeError", "ValueError"]
    assert payload["chain"][1]["message"] == "RPC did not settle"
    assert payload["chain"][0]["frames"][-1]["file"] == Path(__file__).name
    assert private_local not in json.dumps(payload)
    assert "sensitive" not in json.dumps(payload)


def test_redaction_handles_multiline_values_without_erasing_authority_digests() -> None:
    sensitive = '{"api_key":\n "private-value", "reason": "still useful"}'
    redacted = diagnostics.redact_text(sensitive)
    assert "private-value" not in redacted
    assert "still useful" in redacted
    public = json.dumps(
        {
            "authorization_identity_sha256": "a" * 64,
            "authorization": {"gate": "DF-KILL"},
            "api_key": None,
        }
    )
    assert diagnostics.redact_text(public) == public


def _backend_context(tmp_path: Path) -> tuple[LinuxGateBackend, GateExecutionContext]:
    paths = HostPaths(
        batch_id="diagnostic-test",
        packet_root=tmp_path.resolve() / "packet",
        state_root=tmp_path.resolve() / "state",
        require_canonical_host=False,
    )
    backend = LinuxGateBackend(paths=paths)
    backend.resources["DF-KILL"].run_ids.append("target")
    context = GateExecutionContext(
        batch_id=paths.batch_id,
        gate_id="DF-KILL",
        gate_class="live",
        procedure="diagnostic only",
        required_criteria=("peer_healthy",),
        attempts=(),
        local_credit=None,
        privileged_commands=SimpleNamespace(),
        evidence_root=paths.evidence_root,
        acceptance_sha256=FROZEN_ACCEPTANCE_SHA256,
        plan_sha256=FROZEN_PLAN_SHA256,
    )
    return backend, context


def test_failed_gate_returns_diagnostics_as_sealable_evidence(tmp_path: Path, monkeypatch) -> None:
    backend, context = _backend_context(tmp_path)
    control = backend.paths.service_control_root / "target"
    control.mkdir(parents=True)
    (control / "manager-terminal.json").write_text('{"reason":"worker failed"}\n')
    future = Future()
    future.set_exception(ValueError("original worker failure before step 2"))
    backend._run_futures["target"] = future

    def fail(_context):
        backend._failure_stage = "wait_for_step_2"
        raise RuntimeError("worker ended before readiness")

    monkeypatch.setattr(backend, "_gate_df_kill", fail)
    result = backend.execute(context)
    assert result.criteria_passed == ()
    assert result.failure_code == "host_runtimeerror"
    assert {x.name for x in result.evidence_paths} == {
        "gate-failure.json",
        "exception.json",
        "target.json",
    }
    exception = json.loads(result.evidence_paths[1].read_text())
    assert exception["stage"] == "wait_for_step_2"
    assert exception["chain"][0]["message"] == "worker ended before readiness"
    snapshot = json.loads(result.evidence_paths[2].read_text())
    assert "worker failed" in json.dumps(snapshot)
    assert snapshot["worker_future"]["exception"]["chain"][0]["message"] == (
        "original worker failure before step 2"
    )
    assert all(x.is_relative_to(context.evidence_root) for x in result.evidence_paths)


def test_registry_failure_does_not_discard_already_captured_files(
    tmp_path: Path, monkeypatch
) -> None:
    backend, _context = _backend_context(tmp_path)
    control = backend.paths.service_control_root / "target"
    control.mkdir(parents=True)
    (control / "manager-terminal.json").write_text('{"reason":"original evidence"}\n')

    def fail_registry(_run_id):
        raise OSError("registry unavailable")

    monkeypatch.setattr(backend.registry, "get", fail_registry)
    paths, ok = backend._capture_diagnostics("DF-KILL", "test", ("target",))
    assert ok is False
    payload = json.loads(paths[0].read_text())
    assert "original evidence" in json.dumps(payload["files"])
    assert payload["exception"]["chain"][0]["message"] == "registry unavailable"


def test_snapshot_retains_only_bound_session_participant(tmp_path: Path) -> None:
    control, artifacts = _roots(tmp_path)
    session = control / "_fault-sessions" / ("a" * 64)
    target = session / "participants/target"
    target.mkdir(parents=True)
    (target / "step2-decision.json").write_text('{"reason_code":"host_gate_failed"}')
    foreign = session / "participants/foreign"
    foreign.mkdir()
    (foreign / "step2-decision.json").write_text("MUST_NOT_EXPORT")
    payload = diagnostics.capture_run_diagnostics(
        control_root=control,
        artifacts_root=artifacts,
        run_id="target",
        session_sha256="a" * 64,
    )
    assert payload["capture_ok"] is True
    assert "host_gate_failed" in json.dumps(payload)
    assert "MUST_NOT_EXPORT" not in json.dumps(payload)


def test_success_cannot_hide_truncated_diagnostics(tmp_path: Path, monkeypatch) -> None:
    backend, context = _backend_context(tmp_path)
    control = backend.paths.service_control_root / "target"
    control.mkdir(parents=True)
    (control / "manager-terminal.json").write_text("x" * 100)
    monkeypatch.setattr(diagnostics, "MAX_FILE_BYTES", 32)
    receipt = backend.paths.evidence_root / "result.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{}\n")
    monkeypatch.setattr(
        backend,
        "_gate_df_kill",
        lambda _: VerifiedGateReceipt(path=receipt, criteria_passed=context.required_criteria),
    )
    result = backend.execute(context)
    assert result.criteria_passed == ()
    assert result.failure_code == "diagnostic_capture_incomplete"
