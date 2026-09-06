from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from fort_gym.bench.run.fault_classification import (
    FAULT_CLASSIFIER_RESULT_SCHEMA,
    FAULT_OBSERVATION_SCHEMA,
    FaultClassificationError,
    validate_fault_classifier_result,
)


def _observation(**changes: Any) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "schema": FAULT_OBSERVATION_SCHEMA,
        "run_id": "fault-run",
        "primary_terminal_class": "child_exit",
        "primary_reason": {"code": "child_nonzero_exit"},
        "child_pid": 4242,
        "returncode": 22,
        "child_signal": None,
        "environment_identity": {"run_id": "fault-run"},
        "prepare": {"ok": True},
        "termination": {},
        "cleanup": {"ok": True, "stages": []},
    }
    observation.update(changes)
    return observation


def _result(terminal_class: str | None, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
        "terminal_class": terminal_class,
        "evidence": dict(evidence),
    }


RUNTIME_IDENTITY = {"expected": "container-a", "observed": "container-a"}


@pytest.mark.parametrize(
    ("terminal_class", "evidence", "observation_changes"),
    [
        (
            "runtime_df_killed",
            {
                "runtime_identity": RUNTIME_IDENTITY,
                "signal": 9,
                "oom_killed": False,
            },
            {},
        ),
        (
            "harness_killed",
            {"child_pid": 4242, "signal": 9},
            {
                "primary_terminal_class": "external_signal",
                "primary_reason": {"code": "child_signaled", "signal": 9},
                "returncode": -9,
                "child_signal": 9,
            },
        ),
        (
            "runtime_oom",
            {
                "runtime_identity": RUNTIME_IDENTITY,
                "runtime_exit_code": 137,
                "cgroup_memory_events": {
                    "before": {"oom": 3, "oom_kill": 1},
                    "after": {"oom": 4, "oom_kill": 2},
                },
            },
            {},
        ),
        (
            "workspace_enospc",
            {
                "errno": 28,
                "operation": "write private fault fixture",
                "workspace": {
                    "run_id": "fault-run",
                    "scope_root": "/tmp/fortgym-control/fault-run/workspace",
                    "fault_path": (
                        "/tmp/fortgym-control/fault-run/workspace/tmp/fill.bin"
                    ),
                    "fault_bytes": 16_777_216,
                    "maximum_fault_bytes": 16_777_216,
                },
            },
            {},
        ),
        (
            "runtime_container_restarted",
            {
                "container_identity": {
                    "expected": "container-a",
                    "before": "container-a",
                    "after": "container-a",
                },
                "restart_count": {"before": 0, "after": 1},
            },
            {},
        ),
        (
            "docker_daemon_restarted",
            {
                "daemon_generation": {"before": "boot-a", "after": "boot-b"},
                "runtime_identity": RUNTIME_IDENTITY,
            },
            {},
        ),
    ],
)
def test_every_frozen_runtime_fault_requires_and_preserves_typed_evidence(
    terminal_class: str,
    evidence: Mapping[str, Any],
    observation_changes: Mapping[str, Any],
) -> None:
    classification = validate_fault_classifier_result(
        _result(terminal_class, evidence),
        _observation(**observation_changes),
    )

    assert classification.classified is True
    assert classification.terminal_class == terminal_class
    assert classification.reason() == {
        "code": terminal_class,
        "fault_evidence": evidence,
    }


@pytest.mark.parametrize(
    "terminal_class",
    [
        "runtime_df_killed",
        "harness_killed",
        "runtime_oom",
        "workspace_enospc",
        "runtime_container_restarted",
        "docker_daemon_restarted",
    ],
)
def test_every_typed_fault_rejects_missing_evidence(terminal_class: str) -> None:
    with pytest.raises(FaultClassificationError, match="keys are invalid"):
        validate_fault_classifier_result(
            _result(terminal_class, {}),
            _observation(
                primary_terminal_class="external_signal",
                returncode=-9,
                child_signal=9,
            ),
        )


def test_runtime_oom_rejects_exit_137_without_cgroup_memory_events_delta() -> None:
    exit_only = {
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_exit_code": 137,
    }
    with pytest.raises(FaultClassificationError, match="keys are invalid"):
        validate_fault_classifier_result(
            _result("runtime_oom", exit_only),
            _observation(returncode=137),
        )

    unchanged_counter = {
        **exit_only,
        "cgroup_memory_events": {
            "before": {"oom": 1, "oom_kill": 1},
            "after": {"oom": 1, "oom_kill": 1},
        },
    }
    with pytest.raises(FaultClassificationError, match="positive.*oom_kill delta"):
        validate_fault_classifier_result(
            _result("runtime_oom", unchanged_counter),
            _observation(returncode=137),
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"errno": 5}, "errno 28"),
        (
            {
                "workspace": {
                    "run_id": "fault-run",
                    "scope_root": "/tmp/fortgym-control/fault-run/workspace",
                    "fault_path": "/tmp/foreign/fill.bin",
                    "fault_bytes": 1,
                    "maximum_fault_bytes": 16_777_216,
                }
            },
            "outside the bounded run workspace",
        ),
        (
            {
                "workspace": {
                    "run_id": "fault-run",
                    "scope_root": "/tmp/fortgym-control/fault-run/workspace",
                    "fault_path": "/tmp/fortgym-control/fault-run/workspace/fill.bin",
                    "fault_bytes": 1,
                    "maximum_fault_bytes": 16_777_217,
                }
            },
            "exceeds the frozen 16 MiB bound",
        ),
    ],
)
def test_workspace_enospc_rejects_wrong_errno_or_unbounded_workspace(
    change: Mapping[str, Any], message: str
) -> None:
    evidence: dict[str, Any] = {
        "errno": 28,
        "operation": "write private fault fixture",
        "workspace": {
            "run_id": "fault-run",
            "scope_root": "/tmp/fortgym-control/fault-run/workspace",
            "fault_path": "/tmp/fortgym-control/fault-run/workspace/fill.bin",
            "fault_bytes": 1,
            "maximum_fault_bytes": 16_777_216,
        },
    }
    evidence.update(change)

    with pytest.raises(FaultClassificationError, match=message):
        validate_fault_classifier_result(
            _result("workspace_enospc", evidence),
            _observation(),
        )


def test_restart_faults_reject_identity_count_and_generation_conflicts() -> None:
    wrong_identity = {
        "container_identity": {
            "expected": "container-a",
            "before": "container-a",
            "after": "container-b",
        },
        "restart_count": {"before": 0, "after": 1},
    }
    with pytest.raises(FaultClassificationError, match="identity"):
        validate_fault_classifier_result(
            _result("runtime_container_restarted", wrong_identity), _observation()
        )

    unchanged_count = {
        "container_identity": {
            "expected": "container-a",
            "before": "container-a",
            "after": "container-a",
        },
        "restart_count": {"before": 2, "after": 2},
    }
    with pytest.raises(FaultClassificationError, match="restart-count delta"):
        validate_fault_classifier_result(
            _result("runtime_container_restarted", unchanged_count), _observation()
        )

    manual_restart = {
        **unchanged_count,
        "runtime_generation": {"before": "a" * 64, "after": "b" * 64},
    }
    validate_fault_classifier_result(
        _result("runtime_container_restarted", manual_restart), _observation()
    )
    for invalid in ("a" * 64, "not-a-digest", True):
        manual_restart["runtime_generation"]["after"] = invalid
        with pytest.raises(FaultClassificationError, match="generation"):
            validate_fault_classifier_result(
                _result("runtime_container_restarted", manual_restart), _observation()
            )

    unchanged_generation = {
        "daemon_generation": {"before": "boot-a", "after": "boot-a"},
        "runtime_identity": RUNTIME_IDENTITY,
    }
    with pytest.raises(FaultClassificationError, match="changed daemon generation"):
        validate_fault_classifier_result(
            _result("docker_daemon_restarted", unchanged_generation), _observation()
        )


def test_kill_classifications_reject_oom_and_process_identity_contradictions() -> None:
    with pytest.raises(FaultClassificationError, match="oom_killed false"):
        validate_fault_classifier_result(
            _result(
                "runtime_df_killed",
                {
                    "runtime_identity": RUNTIME_IDENTITY,
                    "signal": 9,
                    "oom_killed": True,
                },
            ),
            _observation(),
        )

    with pytest.raises(FaultClassificationError, match="SIGKILLed harness"):
        validate_fault_classifier_result(
            _result(
                "runtime_df_killed",
                {
                    "runtime_identity": RUNTIME_IDENTITY,
                    "signal": 9,
                    "oom_killed": False,
                },
            ),
            _observation(
                primary_terminal_class="external_signal",
                returncode=-9,
                child_signal=9,
            ),
        )

    with pytest.raises(FaultClassificationError, match="child_pid contradicts"):
        validate_fault_classifier_result(
            _result("harness_killed", {"child_pid": 9999, "signal": 9}),
            _observation(
                primary_terminal_class="external_signal",
                primary_reason={"code": "child_signaled", "signal": 9},
                returncode=-9,
                child_signal=9,
            ),
        )

    with pytest.raises(FaultClassificationError, match="independently signaled"):
        validate_fault_classifier_result(
            _result("harness_killed", {"child_pid": 4242, "signal": 9}),
            _observation(
                primary_terminal_class="external_signal",
                primary_reason={"code": "supervisor_stop_requested", "signal": 15},
                returncode=-9,
                child_signal=9,
            ),
        )


def test_typed_fault_rejects_success_and_cleanup_contradictions() -> None:
    evidence = {
        "runtime_identity": RUNTIME_IDENTITY,
        "signal": 9,
        "oom_killed": False,
    }
    with pytest.raises(FaultClassificationError, match="successful child"):
        validate_fault_classifier_result(
            _result("runtime_df_killed", evidence),
            _observation(
                primary_terminal_class="completed",
                returncode=0,
            ),
        )
    with pytest.raises(FaultClassificationError, match="verified cleanup"):
        validate_fault_classifier_result(
            _result("runtime_df_killed", evidence),
            _observation(cleanup={"ok": False, "stages": []}),
        )
    with pytest.raises(FaultClassificationError, match="authoritative supervisor"):
        validate_fault_classifier_result(
            _result("runtime_df_killed", evidence),
            _observation(
                primary_terminal_class="cap_trip",
                primary_reason={"code": "token_cap_exceeded"},
            ),
        )


def test_explicit_no_fault_result_preserves_no_evidence() -> None:
    classification = validate_fault_classifier_result(
        _result(None, {}),
        _observation(
            primary_terminal_class="completed",
            returncode=0,
        ),
    )

    assert classification.classified is False
    assert classification.terminal_class is None
    assert classification.reason() is None

    with pytest.raises(FaultClassificationError, match="must not carry"):
        validate_fault_classifier_result(
            _result(None, {"guessed": True}),
            _observation(),
        )
