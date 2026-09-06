from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run.fault_classification import (
    FAULT_CLASSIFIER_RESULT_SCHEMA,
    FAULT_OBSERVATION_SCHEMA,
    FaultClassificationError,
    validate_fault_classifier_result,
)
from fort_gym.bench.run.process_supervisor import (
    ProcessSupervisor,
    RunSpec,
    TerminalClass,
)
from fort_gym.bench.run.runtime_controller import RuntimeOomPreReadiness

_RUN_ID = "pre-readiness-oom"
_CONTRACT_SHA256 = "a" * 64
_NONCE = "b" * 32


def _environment_identity() -> dict[str, Any]:
    return {
        "run_id": _RUN_ID,
        "contract_sha256": _CONTRACT_SHA256,
        "rpc": {"host": "127.0.0.1", "port": 50_001, "nonce": _NONCE},
    }


def _receipt() -> dict[str, Any]:
    return {
        "schema": "fortgym.m1b-pre-readiness-oom-observation/v1",
        "run_id": _RUN_ID,
        "contract_sha256": _CONTRACT_SHA256,
        "nonce_sha256": hashlib.sha256(_NONCE.encode("utf-8")).hexdigest(),
        "container_name": "fortgym-m1b-pre-readiness-oom",
        "container_id": "c" * 64,
        "fault_profile": "oom_256m",
        "memory_bytes": 268_435_456,
        "memory_swap_bytes": 268_435_456,
        "state": {"running": False, "oom_killed": True, "exit_code": 137},
    }


def _oom_evidence() -> dict[str, Any]:
    return {
        "runtime_identity": {
            "expected": "container-runtime-id",
            "observed": "container-runtime-id",
        },
        "runtime_exit_code": 137,
        "cgroup_memory_events": {
            "before": {"oom": 0, "oom_kill": 0},
            "after": {"oom": 1, "oom_kill": 1},
        },
    }


def _result(terminal_class: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
        "terminal_class": terminal_class,
        "evidence": dict(evidence),
    }


def _observation(receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
    prepare: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "terminal_code": "oom_256m_pre_readiness",
        "runtime_oom_classifier_eligible": True,
        "pre_readiness_oom": dict(receipt or _receipt()),
        "error": {
            "type": "RuntimeOomPreReadiness",
            "message": "verified pre-readiness OOM before harness launch",
        },
    }
    return {
        "schema": FAULT_OBSERVATION_SCHEMA,
        "run_id": _RUN_ID,
        "primary_terminal_class": "prepare_failure",
        "primary_reason": {"code": "oom_256m_pre_readiness"},
        "child_pid": None,
        "returncode": None,
        "child_signal": None,
        "environment_identity": _environment_identity(),
        "prepare": prepare,
        "termination": {},
        "cleanup": {"ok": True, "stages": []},
    }


def _spec(tmp_path: Path) -> RunSpec:
    child_marker = tmp_path / "child-must-not-start"
    return RunSpec(
        run_id=_RUN_ID,
        argv=(
            sys.executable,
            "-c",
            f"from pathlib import Path;Path({str(child_marker)!r}).touch()",
        ),
        artifact_dir=tmp_path / "attempt",
        timeout_seconds=1.0,
        term_grace_seconds=0.1,
        poll_interval_seconds=0.01,
        environment_identity=_environment_identity(),
    )


def test_exact_oom_receipt_opens_only_runtime_oom_after_verified_cleanup(
    tmp_path: Path,
) -> None:
    lifecycle: list[str] = []
    spec = _spec(tmp_path)

    def prepare() -> None:
        lifecycle.append("prepare_oom")
        raise RuntimeOomPreReadiness(evidence=_receipt())

    def cleanup() -> Mapping[str, Any]:
        lifecycle.append("cleanup")
        return {"ok": True, "runtime_absent": True}

    def classify(observation: Mapping[str, Any]) -> Mapping[str, Any]:
        lifecycle.append("classifier")
        assert observation["child_pid"] is None
        assert observation["returncode"] is None
        assert observation["cleanup"]["ok"] is True
        assert observation["prepare"]["pre_readiness_oom"] == _receipt()
        return _result("runtime_oom", _oom_evidence())

    result = ProcessSupervisor().run(
        spec,
        prepare=prepare,
        cleanup=cleanup,
        fault_classifier=classify,
    )

    assert lifecycle == ["prepare_oom", "cleanup", "classifier"]
    assert result.terminal_class is TerminalClass.RUNTIME_OOM
    assert result.payload["primary_terminal_class"] == "prepare_failure"
    assert result.payload["primary_reason"]["code"] == "oom_256m_pre_readiness"
    assert result.payload["child_pid"] is None
    assert result.payload["returncode"] is None
    assert result.payload["prepare"] == _observation()["prepare"]
    assert result.payload["reason"] == {
        "code": "runtime_oom",
        "fault_evidence": _oom_evidence(),
    }
    assert not (tmp_path / "child-must-not-start").exists()


def test_malformed_typed_receipt_keeps_prepare_failure_and_skips_classifier(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["state"] = {"running": False, "oom_killed": False, "exit_code": 137}
    classifier_calls = 0

    def classify(_observation: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal classifier_calls
        classifier_calls += 1
        return _result("runtime_oom", _oom_evidence())

    result = ProcessSupervisor().run(
        _spec(tmp_path),
        prepare=lambda: (_ for _ in ()).throw(
            RuntimeOomPreReadiness(evidence=receipt)
        ),
        cleanup=lambda: {"ok": True},
        fault_classifier=classify,
    )

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == "runtime_prepare_failed"
    assert "pre_readiness_oom" not in result.payload["prepare"]
    assert result.payload["fault_classification"]["skipped"] == (
        "authoritative_primary_terminal_precedence"
    )
    assert classifier_calls == 0


def test_exact_receipt_cannot_override_failed_cleanup_or_become_other_fault(
    tmp_path: Path,
) -> None:
    classifier_calls = 0

    def classify(_observation: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal classifier_calls
        classifier_calls += 1
        return _result("runtime_oom", _oom_evidence())

    cleanup_failed = ProcessSupervisor().run(
        _spec(tmp_path / "cleanup"),
        prepare=lambda: (_ for _ in ()).throw(
            RuntimeOomPreReadiness(evidence=_receipt())
        ),
        cleanup=lambda: {"ok": False, "residue": 1},
        fault_classifier=classify,
    )
    assert cleanup_failed.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert classifier_calls == 0

    wrong_fault = ProcessSupervisor().run(
        _spec(tmp_path / "wrong-fault"),
        prepare=lambda: (_ for _ in ()).throw(
            RuntimeOomPreReadiness(evidence=_receipt())
        ),
        cleanup=lambda: {"ok": True},
        fault_classifier=lambda _observation: _result(
            "runtime_df_killed",
            {
                "runtime_identity": {
                    "expected": "container-runtime-id",
                    "observed": "container-runtime-id",
                },
                "signal": 9,
                "oom_killed": False,
            },
        ),
    )
    assert wrong_fault.terminal_class is (
        TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    )
    assert wrong_fault.payload["reason"]["prior_terminal_class"] == "prepare_failure"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_receipt", "typed runtime faults require an observed child"),
        ("synthetic_child", "must not invent a harness child"),
        ("wrong_contract", "contract or nonce identity mismatch"),
        ("wrong_nonce", "contract or nonce identity mismatch"),
        ("wrong_state", "exact OOMKilled exit 137"),
    ],
)
def test_pre_readiness_oom_validator_rejects_partial_or_contradictory_receipts(
    mutation: str,
    message: str,
) -> None:
    observation = _observation()
    if mutation == "missing_receipt":
        observation["prepare"].pop("pre_readiness_oom")
        observation["prepare"].pop("runtime_oom_classifier_eligible")
    elif mutation == "synthetic_child":
        observation["child_pid"] = 4242
        observation["returncode"] = 137
    elif mutation == "wrong_contract":
        observation["prepare"]["pre_readiness_oom"]["contract_sha256"] = "0" * 64
    elif mutation == "wrong_nonce":
        observation["prepare"]["pre_readiness_oom"]["nonce_sha256"] = "0" * 64
    else:
        observation["prepare"]["pre_readiness_oom"]["state"]["oom_killed"] = False

    with pytest.raises(FaultClassificationError, match=message):
        validate_fault_classifier_result(
            _result("runtime_oom", _oom_evidence()),
            observation,
        )


def test_pre_readiness_oom_validator_accepts_exact_no_child_observation() -> None:
    classification = validate_fault_classifier_result(
        _result("runtime_oom", _oom_evidence()),
        deepcopy(_observation()),
    )

    assert classification.terminal_class == "runtime_oom"
    assert classification.reason() == {
        "code": "runtime_oom",
        "fault_evidence": _oom_evidence(),
    }

