"""Pure validation for M1b runtime-fault classifications.

Runtime controllers observe Docker/cgroup/workspace state that the process
supervisor cannot inspect safely on its own.  This module defines the small,
secret-free result contract a controller may return and validates that a fault
label is supported by the minimum frozen M1b evidence.  It performs no Docker,
network, provider, or filesystem mutation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

FAULT_OBSERVATION_SCHEMA = "fortgym.runtime-fault-observation/v1"
FAULT_CLASSIFIER_RESULT_SCHEMA = "fortgym.runtime-fault-classifier-result/v1"
FAULT_CLASSIFICATION_RECORD_SCHEMA = "fortgym.runtime-fault-classification/v1"
PRE_READINESS_OOM_RECEIPT_SCHEMA = (
    "fortgym.m1b-pre-readiness-oom-observation/v1"
)
MAX_WORKSPACE_FAULT_BYTES = 16_777_216
RUNTIME_FAULT_CLASSIFICATION_FAILURE = "runtime_fault_classification_failure"
RUNTIME_FAULT_TERMINAL_CLASSES = frozenset(
    {
        "runtime_df_killed",
        "harness_killed",
        "runtime_oom",
        "workspace_enospc",
        "runtime_container_restarted",
        "docker_daemon_restarted",
    }
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class FaultClassificationError(ValueError):
    """A classifier result is missing or contradicts required fault evidence."""


@dataclass(frozen=True)
class ValidatedFaultClassification:
    """A controller result normalized for the supervisor terminal record."""

    terminal_class: str | None
    evidence: Mapping[str, Any]

    @property
    def classified(self) -> bool:
        return self.terminal_class is not None

    def reason(self) -> dict[str, Any] | None:
        if self.terminal_class is None:
            return None
        return {
            "code": self.terminal_class,
            "fault_evidence": dict(self.evidence),
        }


def validate_fault_classifier_result(
    result: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    enospc_snapshot: Mapping[str, Any] | None = None,
) -> ValidatedFaultClassification:
    """Validate one controller classification against supervisor observation.

    The classifier result has exactly three top-level fields::

        {
          "schema": "fortgym.runtime-fault-classifier-result/v1",
          "terminal_class": <one supported class, or null>,
          "evidence": {...}
        }

    ``terminal_class: null`` is the explicit, successful "no typed fault"
    result and requires empty evidence.  Missing, contradictory, or invented
    evidence raises :class:`FaultClassificationError` so the supervisor can
    terminate fail closed instead of guessing from an exit code.
    """

    result_mapping = _mapping("classifier result", result)
    observation_mapping = _mapping("fault observation", observation)
    _exact_keys(
        "classifier result",
        result_mapping,
        {"schema", "terminal_class", "evidence"},
    )
    if result_mapping.get("schema") != FAULT_CLASSIFIER_RESULT_SCHEMA:
        raise FaultClassificationError("classifier result schema is invalid")
    if observation_mapping.get("schema") != FAULT_OBSERVATION_SCHEMA:
        raise FaultClassificationError("fault observation schema is invalid")
    cleanup = _mapping("fault observation cleanup", observation_mapping.get("cleanup"))
    if cleanup.get("ok") is not True:
        raise FaultClassificationError(
            "runtime fault classification requires verified cleanup"
        )

    terminal_class = result_mapping.get("terminal_class")
    evidence = _mapping("classifier evidence", result_mapping.get("evidence"))
    if terminal_class is None:
        if evidence:
            raise FaultClassificationError(
                "unclassified result must not carry fault evidence"
            )
        return ValidatedFaultClassification(None, MappingProxyType({}))
    if not isinstance(terminal_class, str):
        raise FaultClassificationError("classifier terminal_class must be a string")
    if terminal_class not in RUNTIME_FAULT_TERMINAL_CLASSES:
        raise FaultClassificationError(
            f"unsupported runtime fault terminal class: {terminal_class!r}"
        )

    pre_readiness_oom = _pre_readiness_oom_from_observation(observation_mapping)
    if pre_readiness_oom is not None:
        if terminal_class != "runtime_oom":
            raise FaultClassificationError(
                "pre-readiness OOM can classify only as runtime_oom"
            )
        if any(
            observation_mapping.get(name) is not None
            for name in ("child_pid", "returncode", "child_signal")
        ):
            raise FaultClassificationError(
                "pre-readiness OOM must not invent a harness child observation"
            )
    else:
        returncode = observation_mapping.get("returncode")
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            raise FaultClassificationError(
                "typed runtime faults require an observed child returncode"
            )
        if (
            returncode == 0
            or observation_mapping.get("primary_terminal_class") == "completed"
        ):
            raise FaultClassificationError(
                "typed runtime fault contradicts a successful child observation"
            )
        enospc_trace_proven = False
        if enospc_snapshot is not None:
            from .fault_session import PRE_CLEANUP_OBSERVATION_SCHEMA, validate_pre_cleanup_snapshot

            snapshot = validate_pre_cleanup_snapshot(
                enospc_snapshot,
                {**observation_mapping, "schema": PRE_CLEANUP_OBSERVATION_SCHEMA},
            )
            primary_reason = _mapping("primary reason", observation_mapping.get("primary_reason"))
            enospc_trace_proven = (
                terminal_class == "workspace_enospc"
                and observation_mapping.get("primary_terminal_class") == "cap_trip"
                and primary_reason.get("code") == "trace_accounting_invalid"
                and observation_mapping.get("scripted") is True
                and observation_mapping.get("provider_enabled") is False
                and snapshot.get("gate") == "ENOSPC"
                and snapshot.get("role") == "target"
                and snapshot.get("classifier_result") == result_mapping
            )
        if not enospc_trace_proven and observation_mapping.get("primary_terminal_class") not in {
            "child_exit",
            "external_signal",
            "timeout",
        }:
            raise FaultClassificationError(
                "typed runtime fault cannot override an authoritative supervisor terminal"
            )

    validators = {
        "runtime_df_killed": _validate_runtime_df_killed,
        "harness_killed": _validate_harness_killed,
        "runtime_oom": _validate_runtime_oom,
        "workspace_enospc": _validate_workspace_enospc,
        "runtime_container_restarted": _validate_runtime_container_restarted,
        "docker_daemon_restarted": _validate_docker_daemon_restarted,
    }
    validators[terminal_class](evidence, observation_mapping)
    return ValidatedFaultClassification(
        terminal_class,
        MappingProxyType(dict(evidence)),
    )


def validate_pre_readiness_oom_receipt(
    receipt: Mapping[str, Any],
    *,
    run_id: str,
    environment_identity: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate the one controller receipt allowed before harness readiness."""

    value = _mapping("pre-readiness OOM receipt", receipt)
    _exact_keys(
        "pre-readiness OOM receipt",
        value,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "container_name",
            "container_id",
            "fault_profile",
            "memory_bytes",
            "memory_swap_bytes",
            "state",
        },
    )
    if value.get("schema") != PRE_READINESS_OOM_RECEIPT_SCHEMA:
        raise FaultClassificationError("pre-readiness OOM receipt schema is invalid")
    if value.get("run_id") != run_id:
        raise FaultClassificationError("pre-readiness OOM receipt run_id mismatch")
    identity = _mapping("runtime environment identity", environment_identity)
    contract_sha256 = identity.get("contract_sha256")
    rpc = _mapping("runtime RPC identity", identity.get("rpc"))
    nonce = rpc.get("nonce")
    if (
        identity.get("run_id") != run_id
        or not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or value.get("contract_sha256") != contract_sha256
        or not isinstance(nonce, str)
        or not nonce
        or value.get("nonce_sha256")
        != hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    ):
        raise FaultClassificationError(
            "pre-readiness OOM receipt contract or nonce identity mismatch"
        )
    _bounded_string(value.get("container_name"), "OOM container_name", maximum=200)
    _bounded_string(value.get("container_id"), "OOM container_id", maximum=200)
    if value.get("fault_profile") != "oom_256m":
        raise FaultClassificationError("pre-readiness OOM fault profile is invalid")
    if (
        value.get("memory_bytes") != 268_435_456
        or isinstance(value.get("memory_bytes"), bool)
        or value.get("memory_swap_bytes") != 268_435_456
        or isinstance(value.get("memory_swap_bytes"), bool)
    ):
        raise FaultClassificationError(
            "pre-readiness OOM memory limits are not exact"
        )
    state = _mapping("pre-readiness OOM state", value.get("state"))
    _exact_keys("pre-readiness OOM state", state, {"running", "oom_killed", "exit_code"})
    if (
        state.get("running") is not False
        or state.get("oom_killed") is not True
        or state.get("exit_code") != 137
        or isinstance(state.get("exit_code"), bool)
    ):
        raise FaultClassificationError(
            "pre-readiness OOM state is not an exact OOMKilled exit 137"
        )
    return MappingProxyType(dict(value))


def _pre_readiness_oom_from_observation(
    observation: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if observation.get("primary_terminal_class") != "prepare_failure":
        return None
    prepare = _mapping("pre-readiness OOM prepare evidence", observation.get("prepare"))
    if (
        prepare.get("terminal_code") != "oom_256m_pre_readiness"
        or prepare.get("runtime_oom_classifier_eligible") is not True
    ):
        return None
    receipt = prepare.get("pre_readiness_oom")
    if not isinstance(receipt, Mapping):
        raise FaultClassificationError(
            "pre-readiness OOM prepare evidence lacks its typed receipt"
        )
    primary_reason = _mapping(
        "pre-readiness OOM primary reason", observation.get("primary_reason")
    )
    if primary_reason.get("code") != "oom_256m_pre_readiness":
        raise FaultClassificationError(
            "pre-readiness OOM primary reason is contradictory"
        )
    environment_identity = _mapping(
        "pre-readiness OOM environment identity",
        observation.get("environment_identity"),
    )
    return validate_pre_readiness_oom_receipt(
        receipt,
        run_id=str(observation.get("run_id") or ""),
        environment_identity=environment_identity,
    )


def _validate_runtime_df_killed(
    evidence: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    _exact_keys(
        "runtime_df_killed evidence",
        evidence,
        {"runtime_identity", "signal", "oom_killed"},
    )
    _matching_identity(evidence.get("runtime_identity"), "runtime identity")
    if evidence.get("signal") != 9:
        raise FaultClassificationError("runtime_df_killed requires signal 9")
    if evidence.get("oom_killed") is not False:
        raise FaultClassificationError(
            "runtime_df_killed requires explicit oom_killed false"
        )
    if observation.get("child_signal") == 9:
        raise FaultClassificationError(
            "runtime_df_killed contradicts a SIGKILLed harness"
        )


def _validate_harness_killed(
    evidence: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    _exact_keys("harness_killed evidence", evidence, {"child_pid", "signal"})
    child_pid = _positive_int(evidence.get("child_pid"), "harness child_pid")
    if child_pid != observation.get("child_pid"):
        raise FaultClassificationError(
            "harness evidence child_pid contradicts supervisor observation"
        )
    if evidence.get("signal") != 9 or observation.get("child_signal") != 9:
        raise FaultClassificationError(
            "harness_killed requires observed harness signal 9"
        )
    primary_reason = _mapping(
        "harness primary reason", observation.get("primary_reason")
    )
    if primary_reason.get("code") != "child_signaled":
        raise FaultClassificationError(
            "harness_killed requires an independently signaled child observation"
        )


def _validate_runtime_oom(
    evidence: Mapping[str, Any], _observation: Mapping[str, Any]
) -> None:
    _exact_keys(
        "runtime_oom evidence",
        evidence,
        {"runtime_identity", "runtime_exit_code", "cgroup_memory_events"},
    )
    _matching_identity(evidence.get("runtime_identity"), "runtime identity")
    if evidence.get("runtime_exit_code") != 137:
        raise FaultClassificationError("runtime_oom requires runtime exit code 137")
    events = _mapping("cgroup memory.events", evidence.get("cgroup_memory_events"))
    _exact_keys("cgroup memory.events", events, {"before", "after"})
    before = _memory_events(events.get("before"), "cgroup memory.events before")
    after = _memory_events(events.get("after"), "cgroup memory.events after")
    if after["oom_kill"] <= before["oom_kill"]:
        raise FaultClassificationError(
            "runtime_oom requires a positive cgroup memory.events oom_kill delta"
        )
    if after["oom"] < before["oom"]:
        raise FaultClassificationError(
            "cgroup memory.events oom counter cannot decrease"
        )


def _validate_workspace_enospc(
    evidence: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    _exact_keys(
        "workspace_enospc evidence",
        evidence,
        {"errno", "operation", "workspace"},
    )
    if evidence.get("errno") != 28:
        raise FaultClassificationError("workspace_enospc requires errno 28")
    _bounded_string(evidence.get("operation"), "workspace operation", maximum=128)
    workspace = _mapping("workspace evidence", evidence.get("workspace"))
    _exact_keys(
        "workspace evidence",
        workspace,
        {
            "run_id",
            "scope_root",
            "fault_path",
            "fault_bytes",
            "maximum_fault_bytes",
        },
    )
    if workspace.get("run_id") != observation.get("run_id"):
        raise FaultClassificationError("workspace evidence run_id mismatch")
    scope_root = Path(
        _bounded_string(workspace.get("scope_root"), "workspace scope_root")
    )
    fault_path = Path(
        _bounded_string(workspace.get("fault_path"), "workspace fault_path")
    )
    if not scope_root.is_absolute() or not fault_path.is_absolute():
        raise FaultClassificationError("workspace paths must be absolute")
    resolved_root = scope_root.resolve(strict=False)
    resolved_fault = fault_path.resolve(strict=False)
    if resolved_root == Path(resolved_root.anchor):
        raise FaultClassificationError(
            "workspace scope_root cannot be a filesystem root"
        )
    try:
        resolved_fault.relative_to(resolved_root)
    except ValueError as exc:
        raise FaultClassificationError(
            "fault path is outside the bounded run workspace"
        ) from exc
    maximum = _positive_int(
        workspace.get("maximum_fault_bytes"), "workspace maximum_fault_bytes"
    )
    fault_bytes = _nonnegative_int(
        workspace.get("fault_bytes"), "workspace fault_bytes"
    )
    if maximum > MAX_WORKSPACE_FAULT_BYTES:
        raise FaultClassificationError(
            "workspace maximum_fault_bytes exceeds the frozen 16 MiB bound"
        )
    if fault_bytes > maximum:
        raise FaultClassificationError(
            "workspace fault_bytes exceeds the declared private bound"
        )


def _validate_runtime_container_restarted(
    evidence: Mapping[str, Any], _observation: Mapping[str, Any]
) -> None:
    keys = {"container_identity", "restart_count"}
    has_generation = "runtime_generation" in evidence
    if has_generation:
        keys.add("runtime_generation")
    _exact_keys(
        "runtime_container_restarted evidence",
        evidence,
        keys,
    )
    identity = _mapping("container identity", evidence.get("container_identity"))
    _exact_keys("container identity", identity, {"expected", "before", "after"})
    expected = _bounded_string(identity.get("expected"), "expected container identity")
    before_identity = _bounded_string(
        identity.get("before"), "before container identity"
    )
    after_identity = _bounded_string(identity.get("after"), "after container identity")
    if expected != before_identity or expected != after_identity:
        raise FaultClassificationError(
            "container restart identity does not match the expected runtime"
        )
    counts = _mapping("container restart_count", evidence.get("restart_count"))
    _exact_keys("container restart_count", counts, {"before", "after"})
    before = _nonnegative_int(counts.get("before"), "restart_count before")
    after = _nonnegative_int(counts.get("after"), "restart_count after")
    if has_generation:
        generation = _mapping("container runtime generation", evidence["runtime_generation"])
        _exact_keys("container runtime generation", generation, {"before", "after"})
        if any(
            not isinstance(generation.get(key), str)
            or len(generation[key]) != 64
            or any(char not in "0123456789abcdef" for char in generation[key])
            for key in ("before", "after")
        ) or generation["before"] == generation["after"]:
            raise FaultClassificationError("container runtime generation did not change")
    elif after <= before:
        raise FaultClassificationError(
            "runtime_container_restarted requires a positive restart-count delta"
        )


def _validate_docker_daemon_restarted(
    evidence: Mapping[str, Any], _observation: Mapping[str, Any]
) -> None:
    _exact_keys(
        "docker_daemon_restarted evidence",
        evidence,
        {"daemon_generation", "runtime_identity"},
    )
    generation = _mapping("daemon generation", evidence.get("daemon_generation"))
    _exact_keys("daemon generation", generation, {"before", "after"})
    before = _bounded_string(generation.get("before"), "daemon generation before")
    after = _bounded_string(generation.get("after"), "daemon generation after")
    if before == after:
        raise FaultClassificationError(
            "docker_daemon_restarted requires a changed daemon generation"
        )
    _matching_identity(evidence.get("runtime_identity"), "runtime identity")


def _memory_events(value: Any, name: str) -> dict[str, int]:
    events = _mapping(name, value)
    _exact_keys(name, events, {"oom", "oom_kill"})
    return {
        "oom": _nonnegative_int(events.get("oom"), f"{name} oom"),
        "oom_kill": _nonnegative_int(events.get("oom_kill"), f"{name} oom_kill"),
    }


def _matching_identity(value: Any, name: str) -> str:
    identity = _mapping(name, value)
    _exact_keys(name, identity, {"expected", "observed"})
    expected = _bounded_string(identity.get("expected"), f"{name} expected")
    observed = _bounded_string(identity.get("observed"), f"{name} observed")
    if expected != observed:
        raise FaultClassificationError(f"{name} does not match expected runtime")
    return expected


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FaultClassificationError(f"{name} must be a mapping")
    return value


def _exact_keys(name: str, value: Mapping[str, Any], expected: set[str]) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise FaultClassificationError(
            f"{name} keys are invalid; missing={missing!r}, unexpected={unexpected!r}"
        )


def _bounded_string(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise FaultClassificationError(
            f"{name} must be a non-empty bounded NUL-free string"
        )
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FaultClassificationError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    integer = _nonnegative_int(value, name)
    if integer == 0:
        raise FaultClassificationError(f"{name} must be positive")
    return integer


__all__ = [
    "FAULT_CLASSIFICATION_RECORD_SCHEMA",
    "FAULT_CLASSIFIER_RESULT_SCHEMA",
    "FAULT_OBSERVATION_SCHEMA",
    "MAX_WORKSPACE_FAULT_BYTES",
    "PRE_READINESS_OOM_RECEIPT_SCHEMA",
    "RUNTIME_FAULT_CLASSIFICATION_FAILURE",
    "RUNTIME_FAULT_TERMINAL_CLASSES",
    "FaultClassificationError",
    "ValidatedFaultClassification",
    "validate_fault_classifier_result",
    "validate_pre_readiness_oom_receipt",
]
