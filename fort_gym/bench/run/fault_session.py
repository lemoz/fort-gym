"""Durable, provider-free coordination for bounded M1b live fault sessions.

The ordinary run path does not discover this protocol.  A parent must persist
an exact two-participant session, explicitly add its manifest path and digest
to a supervised worker's allowlisted environment, and inject the matching
pre-cleanup observer into :class:`~fort_gym.bench.run.process_supervisor.ProcessSupervisor`.

The module owns no Docker, provider, API, or fault-injection authority.  It
only supplies the step-2 hold/release receipts and the completed-observation
claims needed to keep evidence capture ahead of destructive cleanup.  In
particular, the DAEMON-RESTART completed receipt publishes one independently
bound claim per affected participant so both supervisors can derive the same
typed terminal from one source observation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from .fault_classification import FAULT_CLASSIFIER_RESULT_SCHEMA

try:  # pragma: no cover - POSIX is the M1b acceptance target
    import fcntl
except ImportError:  # pragma: no cover - Windows cannot run the live fault gates
    fcntl = None  # type: ignore[assignment]

FAULT_SESSION_SCHEMA = "fortgym.m1b-fault-session/v1"
FAULT_SESSION_READY_SCHEMA = "fortgym.m1b-fault-session-step2-ready/v1"
FAULT_SESSION_RELEASE_SCHEMA = "fortgym.m1b-fault-session-release/v1"
FAULT_SESSION_ABORT_SCHEMA = "fortgym.m1b-fault-session-abort/v1"
FAULT_SESSION_RELEASED_SCHEMA = "fortgym.m1b-fault-session-released/v1"
FAULT_SESSION_CLAIM_SCHEMA = "fortgym.m1b-fault-session-claim/v1"
FAULT_SESSION_COMPLETED_SCHEMA = "fortgym.m1b-fault-session-completed/v1"
FAULT_SESSION_COMPLETION_ABORT_SCHEMA = "fortgym.m1b-fault-session-completion-abort/v1"
PRE_CLEANUP_OBSERVATION_SCHEMA = "fortgym.m1b-pre-cleanup-observation/v1"
PRE_CLEANUP_SNAPSHOT_SCHEMA = "fortgym.m1b-pre-cleanup-snapshot/v1"

FAULT_SESSION_MANIFEST_ENV = "FORT_GYM_FAULT_SESSION_MANIFEST"
FAULT_SESSION_SHA256_ENV = "FORT_GYM_FAULT_SESSION_SHA256"

_FAULT_DRIVER_OBSERVATION_SCHEMA = "fortgym.m1b-fault-driver-observation/v1"
_FAULT_DRIVER_CLASSIFIER_EVIDENCE_SCHEMA = (
    "fortgym.m1b-fault-driver-classifier-evidence/v1"
)
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PACKET_ID_RE = _RUN_ID_RE
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NONCE_RE = re.compile(r"^[a-f0-9]{32,64}$")
_MAX_JSON_BYTES = 256 * 1024
_MAX_DRIVER_JOURNAL_BYTES = 8 * _MAX_JSON_BYTES
_MAX_STEP2_TRACE_BYTES = 64 * 1024 * 1024
_MAX_HOLD_SECONDS = 600.0
_MAX_ACK_SECONDS = 300.0

POST_READINESS_FAULT_GATES = frozenset(
    {
        "DF-KILL",
        "HARNESS-KILL",
        "ENOSPC",
        "CONTAINER-RESTART",
        "DAEMON-RESTART",
    }
)
_TERMINAL_BY_GATE = {
    "DF-KILL": "runtime_df_killed",
    "HARNESS-KILL": "harness_killed",
    "ENOSPC": "workspace_enospc",
    "CONTAINER-RESTART": "runtime_container_restarted",
    "DAEMON-RESTART": "docker_daemon_restarted",
}


class FaultSessionError(RuntimeError):
    """Base error for invalid or incomplete live fault-session evidence."""


class FaultSessionTimeout(FaultSessionError):
    """A bounded barrier or pre-cleanup evidence wait expired."""


class FaultSessionAborted(FaultSessionError):
    """The parent durably aborted a held worker."""


class FaultSessionEvidenceError(FaultSessionError):
    """Persisted fault-session evidence is malformed or contradictory."""


@dataclass(frozen=True)
class FaultSessionParticipant:
    """Secret-free contract identity for one target or peer worker."""

    run_id: str
    role: Literal["target", "peer"]
    contract_sha256: str
    nonce_sha256: str
    cohort_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("fault-session run_id is invalid")
        if self.role not in {"target", "peer"}:
            raise ValueError("fault-session role must be target or peer")
        for name in ("contract_sha256", "nonce_sha256", "cohort_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"fault-session {name} must be lowercase SHA-256")

    def payload(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "contract_sha256": self.contract_sha256,
            "nonce_sha256": self.nonce_sha256,
            "cohort_sha256": self.cohort_sha256,
        }


@dataclass(frozen=True)
class FaultSessionIdentity:
    """Immutable identity shared by exactly one target and one peer."""

    packet_id: str
    authority_sha256: str
    gate: str
    participants: Sequence[FaultSessionParticipant]
    barrier_step: int = 2
    hold_timeout_seconds: float = 180.0
    cleanup_ack_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not isinstance(self.packet_id, str) or not _PACKET_ID_RE.fullmatch(
            self.packet_id
        ):
            raise ValueError("fault-session packet_id is invalid")
        if not isinstance(self.authority_sha256, str) or not _SHA256_RE.fullmatch(
            self.authority_sha256
        ):
            raise ValueError("fault-session authority_sha256 is invalid")
        if self.gate not in POST_READINESS_FAULT_GATES:
            raise ValueError("fault-session gate is not a post-readiness M1b gate")
        participants = tuple(self.participants)
        if (
            len(participants) != 2
            or {item.role for item in participants} != {"target", "peer"}
            or len({item.run_id for item in participants}) != 2
        ):
            raise ValueError("fault session requires one distinct target and peer")
        if len({item.cohort_sha256 for item in participants}) != 1:
            raise ValueError("fault-session participants must share one cohort digest")
        object.__setattr__(
            self,
            "participants",
            tuple(sorted(participants, key=lambda item: item.run_id)),
        )
        if self.barrier_step != 2 or isinstance(self.barrier_step, bool):
            raise ValueError("fault-session barrier_step is frozen at 2")
        for name, maximum in (
            ("hold_timeout_seconds", _MAX_HOLD_SECONDS),
            ("cleanup_ack_timeout_seconds", _MAX_ACK_SECONDS),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 < float(value) <= maximum
            ):
                raise ValueError(f"fault-session {name} is outside its bounded range")
            object.__setattr__(self, name, float(value))

    def participant(self, run_id: str) -> FaultSessionParticipant:
        matches = [item for item in self.participants if item.run_id == run_id]
        if len(matches) != 1:
            raise FaultSessionEvidenceError("run is not an exact session participant")
        return matches[0]

    @property
    def target(self) -> FaultSessionParticipant:
        return next(item for item in self.participants if item.role == "target")

    @property
    def peer(self) -> FaultSessionParticipant:
        return next(item for item in self.participants if item.role == "peer")

    def payload(self) -> dict[str, Any]:
        return {
            "schema": FAULT_SESSION_SCHEMA,
            "packet_id": self.packet_id,
            "authority_sha256": self.authority_sha256,
            "gate": self.gate,
            "barrier_step": self.barrier_step,
            "hold_timeout_seconds": self.hold_timeout_seconds,
            "cleanup_ack_timeout_seconds": self.cleanup_ack_timeout_seconds,
            "participants": [item.payload() for item in self.participants],
        }

    @property
    def session_sha256(self) -> str:
        return _payload_sha256(self.payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FaultSessionIdentity:
        value = _mapping("fault-session manifest", payload)
        _exact_keys(
            "fault-session manifest",
            value,
            {
                "schema",
                "packet_id",
                "authority_sha256",
                "gate",
                "barrier_step",
                "hold_timeout_seconds",
                "cleanup_ack_timeout_seconds",
                "participants",
            },
        )
        if value.get("schema") != FAULT_SESSION_SCHEMA:
            raise FaultSessionEvidenceError("fault-session manifest schema differs")
        raw_participants = value.get("participants")
        if not isinstance(raw_participants, list):
            raise FaultSessionEvidenceError("fault-session participants must be a list")
        try:
            participants = tuple(
                FaultSessionParticipant(
                    run_id=str(_mapping("participant", item).get("run_id") or ""),
                    role=_mapping("participant", item).get("role"),  # type: ignore[arg-type]
                    contract_sha256=str(
                        _mapping("participant", item).get("contract_sha256") or ""
                    ),
                    nonce_sha256=str(
                        _mapping("participant", item).get("nonce_sha256") or ""
                    ),
                    cohort_sha256=str(
                        _mapping("participant", item).get("cohort_sha256") or ""
                    ),
                )
                for item in raw_participants
            )
            for item in raw_participants:
                _exact_keys(
                    "fault-session participant",
                    _mapping("participant", item),
                    {
                        "run_id",
                        "role",
                        "contract_sha256",
                        "nonce_sha256",
                        "cohort_sha256",
                    },
                )
            return cls(
                packet_id=str(value.get("packet_id") or ""),
                authority_sha256=str(value.get("authority_sha256") or ""),
                gate=str(value.get("gate") or ""),
                participants=participants,
                barrier_step=value.get("barrier_step"),  # type: ignore[arg-type]
                hold_timeout_seconds=value.get("hold_timeout_seconds"),  # type: ignore[arg-type]
                cleanup_ack_timeout_seconds=value.get(  # type: ignore[arg-type]
                    "cleanup_ack_timeout_seconds"
                ),
            )
        except (TypeError, ValueError) as exc:
            raise FaultSessionEvidenceError(
                "fault-session manifest identity is invalid"
            ) from exc


@dataclass(frozen=True)
class StepCommit:
    """One run step whose trace row and registry step are already durable."""

    run_id: str
    step: int
    trace_path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("step commit run_id is invalid")
        if (
            isinstance(self.step, bool)
            or not isinstance(self.step, int)
            or self.step < 0
        ):
            raise ValueError("step commit step must be a non-negative integer")
        path = Path(self.trace_path)
        if not path.is_absolute() or "\0" in str(path):
            raise ValueError("step commit trace_path must be absolute")
        object.__setattr__(self, "trace_path", path.resolve(strict=False))


class StepCommitObserver(Protocol):
    def __call__(self, commit: StepCommit) -> None: ...


class FaultSessionStore:
    """Write-once durable files for one exact fault-session identity."""

    def __init__(
        self,
        *,
        control_root: Path | str,
        session: FaultSessionIdentity,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        root = Path(control_root)
        if not root.is_absolute() or "\0" in str(root):
            raise ValueError("fault-session control_root must be absolute")
        root = root.resolve(strict=False)
        if root == Path(root.anchor):
            raise ValueError("fault-session control_root cannot be a filesystem root")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not math.isfinite(float(poll_interval_seconds))
            or not 0 < float(poll_interval_seconds) <= 1.0
        ):
            raise ValueError("fault-session poll interval is invalid")
        self.control_root = root
        self.session = session
        self.session_dir = (
            self.control_root / "_fault-sessions" / session.session_sha256
        )
        self.manifest_path = self.session_dir / "session.json"
        self._sleep = sleep
        self._monotonic = monotonic
        self._poll_interval_seconds = float(poll_interval_seconds)

    def initialize(self) -> Path:
        """Persist or verify the one canonical session manifest."""

        _write_once_or_verify(self.manifest_path, self.session.payload())
        return self.manifest_path

    def worker_environment(self, run_id: str) -> Mapping[str, str]:
        """Return the two secret-free overrides for one exact session worker."""

        self.session.participant(run_id)
        self._verify_manifest()
        return MappingProxyType(
            {
                FAULT_SESSION_MANIFEST_ENV: str(self.manifest_path),
                FAULT_SESSION_SHA256_ENV: self.session.session_sha256,
            }
        )

    def step_observer(self, run_id: str) -> StepCommitObserver:
        participant = self.session.participant(run_id)
        self._verify_manifest()

        def observe(commit: StepCommit) -> None:
            if commit.run_id != participant.run_id:
                raise FaultSessionEvidenceError("step commit run identity differs")
            if self.session.gate == "DF-KILL" and participant.role == "peer" and commit.step == 5:
                self._hold_peer_progress(commit)
                return
            if commit.step != self.session.barrier_step:
                return
            trace_size_bytes, trace_sha256 = _sha256_regular_file(
                commit.trace_path,
                maximum=_MAX_STEP2_TRACE_BYTES,
            )
            ready = {
                "schema": FAULT_SESSION_READY_SCHEMA,
                "session_sha256": self.session.session_sha256,
                "gate": self.session.gate,
                "run_id": participant.run_id,
                "role": participant.role,
                "contract_sha256": participant.contract_sha256,
                "nonce_sha256": participant.nonce_sha256,
                "cohort_sha256": participant.cohort_sha256,
                "step": self.session.barrier_step,
                "trace_size_bytes": trace_size_bytes,
                "trace_sha256": trace_sha256,
                "durable": True,
            }
            ready_path = self._ready_path(participant.run_id)
            _write_once_json(ready_path, ready)
            deadline = self._monotonic() + self.session.hold_timeout_seconds
            while True:
                decision_path = self._decision_path(participant.run_id)
                if decision_path.exists():
                    decision = self._load_bound_control(decision_path)
                    if decision["schema"] == FAULT_SESSION_ABORT_SCHEMA:
                        raise FaultSessionAborted(str(decision["reason_code"]))
                    released = {
                        "schema": FAULT_SESSION_RELEASED_SCHEMA,
                        "session_sha256": self.session.session_sha256,
                        "gate": self.session.gate,
                        "run_id": participant.run_id,
                        "role": participant.role,
                        "step": self.session.barrier_step,
                        "trigger_record_sha256": decision["trigger_record_sha256"],
                    }
                    _write_once_json(self._released_path(participant.run_id), released)
                    return
                if self._monotonic() >= deadline:
                    raise FaultSessionTimeout("step-2 fault-session hold timed out")
                self._sleep(self._poll_interval_seconds)

        return observe

    def _hold_peer_progress(self, commit: StepCommit) -> None:
        """Keep the healthy step-5 peer observable until the driver acknowledges it."""
        released = self.released(commit.run_id)
        if released is None:
            raise FaultSessionEvidenceError("peer progress precedes fault action release")
        size, digest = _sha256_regular_file(commit.trace_path, maximum=_MAX_STEP2_TRACE_BYTES)
        receipt = {
            "schema": "fortgym.m1b-peer-progress-hold/v1",
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "run_id": commit.run_id,
            "step": commit.step,
            "trigger_record_sha256": released["trigger_record_sha256"],
            "trace_size_bytes": size,
            "trace_sha256": digest,
        }
        root = self._participant_dir(commit.run_id)
        _write_once_json(root / "peer-progress-ready.json", receipt)
        deadline = self._monotonic() + self.session.hold_timeout_seconds
        while not self._completion_path().exists():
            if self._monotonic() >= deadline:
                raise FaultSessionTimeout("peer progress observation hold timed out")
            self._sleep(self._poll_interval_seconds)
        completed = _read_json(self._completion_path())
        if (
            completed.get("session_sha256") != self.session.session_sha256
            or completed.get("gate") != self.session.gate
        ):
            raise FaultSessionEvidenceError("peer progress completion identity differs")
        if completed.get("schema") == FAULT_SESSION_COMPLETION_ABORT_SCHEMA:
            _exact_keys("peer progress abort", completed, {"schema", "session_sha256", "gate", "reason_code"})
            reason = completed.get("reason_code")
            if not isinstance(reason, str) or not _RUN_ID_RE.fullmatch(reason):
                raise FaultSessionEvidenceError("peer progress abort reason differs")
            raise FaultSessionAborted(reason)
        if (
            completed.get("schema") != FAULT_SESSION_COMPLETED_SCHEMA
            or completed.get("source_run_id") != self.session.target.run_id
            or completed.get("source_contract_sha256") != self.session.target.contract_sha256
        ):
            raise FaultSessionEvidenceError("peer progress completion source differs")
        records = self._validated_driver_records(
            self.control_root / self.session.target.run_id / "fault-driver-observations.jsonl"
        )
        self.action_attempted_sha256()
        if (
            not records or records[-1].get("phase") != "completed"
            or completed.get("source_completed_record_sha256") != _payload_sha256(records[-1])
        ):
            raise FaultSessionEvidenceError("peer progress lacks completed driver evidence")
        _write_once_json(root / "peer-progress-released.json", {
            **receipt, "completion_sha256": _payload_sha256(completed)
        })

    def ready(self, run_id: str) -> Mapping[str, Any] | None:
        participant = self.session.participant(run_id)
        self._verify_manifest()
        path = self._ready_path(run_id)
        if not path.exists():
            return None
        value = _read_json(path)
        expected = {
            "schema",
            "session_sha256",
            "gate",
            "run_id",
            "role",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "step",
            "trace_size_bytes",
            "trace_sha256",
            "durable",
        }
        _exact_keys("fault-session ready receipt", value, expected)
        if (
            value.get("schema") != FAULT_SESSION_READY_SCHEMA
            or value.get("session_sha256") != self.session.session_sha256
            or value.get("gate") != self.session.gate
            or value.get("run_id") != participant.run_id
            or value.get("role") != participant.role
            or value.get("contract_sha256") != participant.contract_sha256
            or value.get("nonce_sha256") != participant.nonce_sha256
            or value.get("cohort_sha256") != participant.cohort_sha256
            or value.get("step") != self.session.barrier_step
            or value.get("durable") is not True
            or not _SHA256_RE.fullmatch(str(value.get("trace_sha256") or ""))
            or isinstance(value.get("trace_size_bytes"), bool)
            or not isinstance(value.get("trace_size_bytes"), int)
            or value.get("trace_size_bytes") < 1
        ):
            raise FaultSessionEvidenceError("fault-session ready receipt differs")
        return MappingProxyType(dict(value))

    def release(self, run_id: str, *, trigger_record_sha256: str) -> Path:
        """Release one held participant after a durable action record exists."""

        participant = self.session.participant(run_id)
        self._verify_manifest()
        if self.ready(run_id) is None:
            raise FaultSessionEvidenceError(
                "cannot release before step-2 ready receipt"
            )
        if not isinstance(trigger_record_sha256, str) or not _SHA256_RE.fullmatch(
            trigger_record_sha256
        ):
            raise ValueError("trigger_record_sha256 must be lowercase SHA-256")
        payload = {
            "schema": FAULT_SESSION_RELEASE_SCHEMA,
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "run_id": participant.run_id,
            "role": participant.role,
            "contract_sha256": participant.contract_sha256,
            "nonce_sha256": participant.nonce_sha256,
            "cohort_sha256": participant.cohort_sha256,
            "step": self.session.barrier_step,
            "trigger_record_sha256": trigger_record_sha256,
        }
        path = self._decision_path(run_id)
        _write_once_or_verify(path, payload)
        return path

    def abort(self, run_id: str, *, reason_code: str) -> Path:
        participant = self.session.participant(run_id)
        self._verify_manifest()
        if not isinstance(reason_code, str) or not _RUN_ID_RE.fullmatch(reason_code):
            raise ValueError("fault-session abort reason_code is invalid")
        payload = {
            "schema": FAULT_SESSION_ABORT_SCHEMA,
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "run_id": participant.run_id,
            "role": participant.role,
            "contract_sha256": participant.contract_sha256,
            "nonce_sha256": participant.nonce_sha256,
            "cohort_sha256": participant.cohort_sha256,
            "step": self.session.barrier_step,
            "reason_code": reason_code,
        }
        path = self._decision_path(run_id)
        _write_once_or_verify(path, payload)
        return path

    def released(self, run_id: str) -> Mapping[str, Any] | None:
        """Return a validated worker release acknowledgement when present."""

        participant = self.session.participant(run_id)
        self._verify_manifest()
        path = self._released_path(run_id)
        if not path.exists():
            return None
        value = _read_json(path)
        _exact_keys(
            "fault-session released receipt",
            value,
            {
                "schema",
                "session_sha256",
                "gate",
                "run_id",
                "role",
                "step",
                "trigger_record_sha256",
            },
        )
        decision = self._load_bound_control(self._decision_path(run_id))
        if (
            value.get("schema") != FAULT_SESSION_RELEASED_SCHEMA
            or value.get("session_sha256") != self.session.session_sha256
            or value.get("gate") != self.session.gate
            or value.get("run_id") != participant.run_id
            or value.get("role") != participant.role
            or value.get("step") != self.session.barrier_step
            or decision.get("schema") != FAULT_SESSION_RELEASE_SCHEMA
            or value.get("trigger_record_sha256")
            != decision.get("trigger_record_sha256")
        ):
            raise FaultSessionEvidenceError("fault-session released receipt differs")
        return MappingProxyType(dict(value))

    def action_attempted_sha256(self) -> str | None:
        """Return the canonical action receipt digest when the driver reaches it.

        A caller polls this before releasing either step-2 hold.  A failed or
        contradictory journal raises instead of granting release authority.
        """

        self._verify_manifest()
        path = (
            self.control_root
            / self.session.target.run_id
            / "fault-driver-observations.jsonl"
        )
        if not path.exists():
            return None
        records = self._validated_driver_records(path, allow_empty=True)
        expected = (
            "authorized",
            "barrier_confirmed",
            "ownership_confirmed",
            "before_observed",
            "action_armed",
            "action_attempted",
        )
        phases = tuple(str(record["phase"]) for record in records)
        if "failed" in phases:
            raise FaultSessionAborted("fault driver failed before release")
        if len(phases) < len(expected):
            if phases != expected[: len(phases)]:
                raise FaultSessionEvidenceError(
                    "fault driver pre-action sequence differs"
                )
            return None
        if phases[: len(expected)] != expected or phases[len(expected) :] not in {
            (),
            ("completed",),
        }:
            raise FaultSessionEvidenceError(
                "fault driver action receipt sequence differs"
            )
        action_record = records[len(expected) - 1]
        if len(records) == len(expected) + 1:
            completed_payload = _mapping(
                "completed fault payload", records[-1].get("payload")
            )
            if action_record.get("payload") != completed_payload.get("action"):
                raise FaultSessionEvidenceError(
                    "action_attempted record does not bind the completed action"
                )
        return _payload_sha256(action_record)

    def persist_completed_claims(
        self,
        completed_observation: Mapping[str, Any],
        *,
        target_nonce: str,
    ) -> Mapping[str, Any]:
        """Publish target and, for DAEMON-RESTART, peer terminal claims.

        ``completed_observation`` must already have passed the fault driver's
        strict loader.  This method independently binds its target, peer,
        cohort, gate, nonce hashes, classifier evidence, and source digest to
        the persisted session before publishing claims.
        """

        self._verify_manifest()
        target = self.session.target
        if (
            not isinstance(target_nonce, str)
            or not _NONCE_RE.fullmatch(target_nonce)
            or hashlib.sha256(target_nonce.encode("utf-8")).hexdigest()
            != target.nonce_sha256
        ):
            raise FaultSessionEvidenceError(
                "completed observation target nonce identity differs"
            )
        # Re-read the canonical append-only driver journal.  The caller-provided
        # mapping is never accepted as proof on its own.
        from .fault_driver import FaultGate, load_completed_fault_observation

        loaded = load_completed_fault_observation(
            control_root=self.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target_nonce,
            expected_gate=FaultGate(self.session.gate),
        )
        if loaded is None or _json_copy(loaded) != _json_copy(completed_observation):
            raise FaultSessionEvidenceError(
                "completed observation is not the canonical durable driver record"
            )
        record = _mapping("completed fault observation", completed_observation)
        _exact_keys(
            "completed fault observation",
            record,
            {
                "schema",
                "event_index",
                "recorded_at",
                "phase",
                "gate",
                "run_id",
                "contract_sha256",
                "nonce_sha256",
                "payload",
            },
        )
        peer = self.session.peer
        payload = _mapping("completed fault payload", record.get("payload"))
        _exact_keys(
            "completed fault payload",
            payload,
            {
                "target",
                "peer",
                "barrier",
                "ownership",
                "before",
                "action",
                "after",
                "peer_after",
                "canaries",
                "timing",
                "classifier_evidence_schema",
                "classifier_evidence",
                "pending_external_checks",
            },
        )
        target_public = _mapping("completed target", payload.get("target"))
        peer_public = _mapping("completed peer", payload.get("peer"))
        if (
            record.get("schema") != _FAULT_DRIVER_OBSERVATION_SCHEMA
            or record.get("phase") != "completed"
            or record.get("gate") != self.session.gate
            or record.get("run_id") != target.run_id
            or record.get("contract_sha256") != target.contract_sha256
            or record.get("nonce_sha256") != target.nonce_sha256
            or not isinstance(record.get("event_index"), int)
            or isinstance(record.get("event_index"), bool)
            or record.get("event_index") < 1
            or not isinstance(record.get("recorded_at"), str)
            or not record.get("recorded_at")
        ):
            raise FaultSessionEvidenceError(
                "completed observation does not match the fault-session target"
            )
        _validate_public_participant(target_public, target)
        _validate_public_participant(peer_public, peer)
        classifier_evidence = _mapping(
            "completed classifier evidence", payload.get("classifier_evidence")
        )
        if (
            payload.get("classifier_evidence_schema")
            != _FAULT_DRIVER_CLASSIFIER_EVIDENCE_SCHEMA
        ):
            raise FaultSessionEvidenceError(
                "completed classifier evidence schema differs"
            )
        action_record_sha256 = self._driver_action_record_sha256(record)
        for participant in self.session.participants:
            if self.ready(participant.run_id) is None:
                raise FaultSessionEvidenceError(
                    "completed observation lacks a session step-2 ready receipt"
                )
            decision = self._load_bound_control(self._decision_path(participant.run_id))
            if (
                decision.get("schema") != FAULT_SESSION_RELEASE_SCHEMA
                or decision.get("trigger_record_sha256") != action_record_sha256
            ):
                raise FaultSessionEvidenceError(
                    "fault-session release is not bound to action_attempted"
                )
        terminal_class = _TERMINAL_BY_GATE[self.session.gate]
        source_sha256 = _payload_sha256(record)
        claims: dict[str, dict[str, Any]] = {}
        claims[target.run_id] = self._claim_payload(
            participant=target,
            source_completed_record_sha256=source_sha256,
            terminal_class=terminal_class,
            evidence=classifier_evidence,
        )
        if self.session.gate == "DAEMON-RESTART":
            generation = _mapping(
                "daemon generation", classifier_evidence.get("daemon_generation")
            )
            _exact_keys("daemon generation", generation, {"before", "after"})
            peer_container_id = _bounded_string(
                peer_public.get("container_id"), "peer container_id", maximum=200
            )
            peer_evidence = {
                "daemon_generation": dict(generation),
                "runtime_identity": {
                    "expected": peer_container_id,
                    "observed": peer_container_id,
                },
            }
            claims[peer.run_id] = self._claim_payload(
                participant=peer,
                source_completed_record_sha256=source_sha256,
                terminal_class=terminal_class,
                evidence=peer_evidence,
            )

        claim_digests: dict[str, str] = {}
        for run_id, claim in sorted(claims.items()):
            _write_once_or_verify(self._claim_path(run_id), claim)
            claim_digests[run_id] = _payload_sha256(claim)
        completed = {
            "schema": FAULT_SESSION_COMPLETED_SCHEMA,
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "source_run_id": target.run_id,
            "source_contract_sha256": target.contract_sha256,
            "source_completed_record_sha256": source_sha256,
            "classified_run_ids": sorted(claims),
            "participant_claim_sha256": dict(sorted(claim_digests.items())),
        }
        _write_once_or_verify(self._completion_path(), completed)
        return MappingProxyType(completed)

    def abort_completion(self, *, reason_code: str) -> Path:
        """Unblock cleanup after a driver/coordinator failure, without classifying."""

        self._verify_manifest()
        if not isinstance(reason_code, str) or not _RUN_ID_RE.fullmatch(reason_code):
            raise ValueError("fault-session completion abort reason_code is invalid")
        payload = {
            "schema": FAULT_SESSION_COMPLETION_ABORT_SCHEMA,
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "reason_code": reason_code,
        }
        path = self._completion_path()
        _write_once_or_verify(path, payload)
        return path

    def pre_cleanup_observer(
        self,
        run_id: str,
    ) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
        """Return one bounded observer suitable for ``ProcessSupervisor.run``."""

        participant = self.session.participant(run_id)
        if participant.role == "peer" and self.session.gate != "DAEMON-RESTART":
            raise FaultSessionEvidenceError(
                "only DAEMON-RESTART may classify the peer from shared evidence"
            )
        self._verify_manifest()

        def observe(observation: Mapping[str, Any]) -> Mapping[str, Any]:
            deadline = self._monotonic() + self.session.cleanup_ack_timeout_seconds
            while not self._completion_path().exists():
                if self._monotonic() >= deadline:
                    raise FaultSessionTimeout(
                        "completed fault observation was not published before cleanup"
                    )
                self._sleep(self._poll_interval_seconds)
            completed = _read_json(self._completion_path())
            if completed.get("schema") == FAULT_SESSION_COMPLETION_ABORT_SCHEMA:
                _exact_keys(
                    "fault-session completion abort",
                    completed,
                    {"schema", "session_sha256", "gate", "reason_code"},
                )
                if (
                    completed.get("session_sha256") != self.session.session_sha256
                    or completed.get("gate") != self.session.gate
                    or not isinstance(completed.get("reason_code"), str)
                    or not _RUN_ID_RE.fullmatch(completed["reason_code"])
                ):
                    raise FaultSessionEvidenceError(
                        "fault-session completion abort differs"
                    )
                raise FaultSessionAborted(str(completed["reason_code"]))
            if completed.get("schema") != FAULT_SESSION_COMPLETED_SCHEMA:
                raise FaultSessionEvidenceError(
                    "fault-session completion decision is invalid"
                )
            claim = _read_json(self._claim_path(participant.run_id))
            snapshot = {
                "schema": PRE_CLEANUP_SNAPSHOT_SCHEMA,
                "ok": True,
                "run_id": participant.run_id,
                "session_sha256": self.session.session_sha256,
                "gate": self.session.gate,
                "role": participant.role,
                "completed_receipt": completed,
                "participant_claim": claim,
                "classifier_result": claim.get("classifier_result"),
            }
            return validate_pre_cleanup_snapshot(snapshot, observation)

        return observe

    def _claim_payload(
        self,
        *,
        participant: FaultSessionParticipant,
        source_completed_record_sha256: str,
        terminal_class: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": FAULT_SESSION_CLAIM_SCHEMA,
            "session_sha256": self.session.session_sha256,
            "gate": self.session.gate,
            "run_id": participant.run_id,
            "role": participant.role,
            "contract_sha256": participant.contract_sha256,
            "nonce_sha256": participant.nonce_sha256,
            "cohort_sha256": participant.cohort_sha256,
            "source_run_id": self.session.target.run_id,
            "source_contract_sha256": self.session.target.contract_sha256,
            "source_completed_record_sha256": source_completed_record_sha256,
            "classifier_result": {
                "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
                "terminal_class": terminal_class,
                "evidence": dict(evidence),
            },
        }

    def _driver_action_record_sha256(
        self,
        completed: Mapping[str, Any],
    ) -> str:
        records = self._validated_driver_records(
            self.control_root
            / self.session.target.run_id
            / "fault-driver-observations.jsonl"
        )
        if not records or records[-1] != _json_copy(completed):
            raise FaultSessionEvidenceError(
                "completed observation is not the final driver journal record"
            )
        action_records = [
            record for record in records if record.get("phase") == "action_attempted"
        ]
        if len(action_records) != 1:
            raise FaultSessionEvidenceError(
                "fault-session requires one action_attempted driver record"
            )
        action_record = action_records[0]
        completed_payload = _mapping(
            "completed fault payload", completed.get("payload")
        )
        if action_record.get("payload") != completed_payload.get(
            "action"
        ) or action_record.get("event_index", 0) >= completed.get("event_index", 0):
            raise FaultSessionEvidenceError(
                "action_attempted record does not bind the completed action"
            )
        return _payload_sha256(action_record)

    def _validated_driver_records(
        self, path: Path, *, allow_empty: bool = False
    ) -> list[dict[str, Any]]:
        records = _read_jsonl(path, allow_empty=allow_empty)
        if len(records) > 64:
            raise FaultSessionEvidenceError("fault driver journal has too many records")
        for record in records:
            _exact_keys(
                "fault driver journal record",
                record,
                {
                    "schema",
                    "event_index",
                    "recorded_at",
                    "phase",
                    "gate",
                    "run_id",
                    "contract_sha256",
                    "nonce_sha256",
                    "payload",
                },
            )
            if (
                record.get("schema") != _FAULT_DRIVER_OBSERVATION_SCHEMA
                or record.get("gate") != self.session.gate
                or record.get("run_id") != self.session.target.run_id
                or record.get("contract_sha256") != self.session.target.contract_sha256
                or record.get("nonce_sha256") != self.session.target.nonce_sha256
                or isinstance(record.get("event_index"), bool)
                or not isinstance(record.get("event_index"), int)
                or record.get("event_index") < 1
                or not isinstance(record.get("recorded_at"), str)
                or not record.get("recorded_at")
                or not isinstance(record.get("phase"), str)
                or not isinstance(record.get("payload"), Mapping)
            ):
                raise FaultSessionEvidenceError("fault driver journal binding differs")
        return records

    def _verify_manifest(self) -> None:
        manifest = _read_json(self.manifest_path)
        loaded = FaultSessionIdentity.from_payload(manifest)
        if (
            loaded.payload() != self.session.payload()
            or loaded.session_sha256 != self.session.session_sha256
        ):
            raise FaultSessionEvidenceError("fault-session manifest identity differs")

    def _load_bound_control(self, path: Path) -> Mapping[str, Any]:
        value = _read_json(path)
        run_id = path.parent.name
        participant = self.session.participant(run_id)
        schema = value.get("schema")
        if schema not in {FAULT_SESSION_ABORT_SCHEMA, FAULT_SESSION_RELEASE_SCHEMA}:
            raise FaultSessionEvidenceError("fault-session decision schema is invalid")
        abort = schema == FAULT_SESSION_ABORT_SCHEMA
        common_keys = {
            "schema",
            "session_sha256",
            "gate",
            "run_id",
            "role",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "step",
        }
        expected_keys = common_keys | (
            {"reason_code"} if abort else {"trigger_record_sha256"}
        )
        _exact_keys("fault-session control receipt", value, expected_keys)
        expected_schema = (
            FAULT_SESSION_ABORT_SCHEMA if abort else FAULT_SESSION_RELEASE_SCHEMA
        )
        if (
            value.get("schema") != expected_schema
            or value.get("session_sha256") != self.session.session_sha256
            or value.get("gate") != self.session.gate
            or value.get("run_id") != participant.run_id
            or value.get("role") != participant.role
            or value.get("contract_sha256") != participant.contract_sha256
            or value.get("nonce_sha256") != participant.nonce_sha256
            or value.get("cohort_sha256") != participant.cohort_sha256
            or value.get("step") != self.session.barrier_step
        ):
            raise FaultSessionEvidenceError("fault-session control receipt differs")
        tail = value.get("reason_code" if abort else "trigger_record_sha256")
        if abort:
            if not isinstance(tail, str) or not _RUN_ID_RE.fullmatch(tail):
                raise FaultSessionEvidenceError("fault-session abort reason is invalid")
        elif not isinstance(tail, str) or not _SHA256_RE.fullmatch(tail):
            raise FaultSessionEvidenceError("fault-session release trigger is invalid")
        return value

    def _participant_dir(self, run_id: str) -> Path:
        self.session.participant(run_id)
        return self.session_dir / "participants" / run_id

    def _ready_path(self, run_id: str) -> Path:
        return self._participant_dir(run_id) / "step2-ready.json"

    def _decision_path(self, run_id: str) -> Path:
        return self._participant_dir(run_id) / "step2-decision.json"

    def _released_path(self, run_id: str) -> Path:
        return self._participant_dir(run_id) / "step2-released.json"

    def _claim_path(self, run_id: str) -> Path:
        return self._participant_dir(run_id) / "terminal-claim.json"

    def _completion_path(self) -> Path:
        return self.session_dir / "completion.json"


def step_observer_from_environment(
    environment: Mapping[str, str],
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> StepCommitObserver | None:
    """Load an explicitly allowlisted session or return ``None`` when absent."""

    manifest_raw = environment.get(FAULT_SESSION_MANIFEST_ENV)
    digest_raw = environment.get(FAULT_SESSION_SHA256_ENV)
    if manifest_raw is None and digest_raw is None:
        return None
    if not manifest_raw or not digest_raw or not _SHA256_RE.fullmatch(digest_raw):
        raise FaultSessionEvidenceError(
            "fault-session worker environment is incomplete or invalid"
        )
    manifest_path = Path(manifest_raw)
    if not manifest_path.is_absolute() or "\0" in str(manifest_path):
        raise FaultSessionEvidenceError("fault-session manifest path must be absolute")
    manifest_path = manifest_path.resolve(strict=False)
    if (
        manifest_path.name != "session.json"
        or manifest_path.parent.name != digest_raw
        or manifest_path.parent.parent.name != "_fault-sessions"
    ):
        raise FaultSessionEvidenceError("fault-session manifest path is noncanonical")
    session = FaultSessionIdentity.from_payload(_read_json(manifest_path))
    if session.session_sha256 != digest_raw:
        raise FaultSessionEvidenceError("fault-session worker digest differs")
    run_id = environment.get("FORT_GYM_RUN_ID")
    contract_sha256 = environment.get("FORT_GYM_RUN_CONTRACT_SHA256")
    nonce = environment.get("FORT_GYM_RUN_NONCE")
    if not run_id or not contract_sha256 or not nonce or not _NONCE_RE.fullmatch(nonce):
        raise FaultSessionEvidenceError(
            "fault-session worker lacks its exact run contract environment"
        )
    participant = session.participant(run_id)
    if (
        participant.contract_sha256 != contract_sha256
        or participant.nonce_sha256 != hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    ):
        raise FaultSessionEvidenceError(
            "fault-session worker contract identity differs"
        )
    control_root = manifest_path.parent.parent.parent
    store = FaultSessionStore(
        control_root=control_root,
        session=session,
        sleep=sleep,
        monotonic=monotonic,
    )
    return store.step_observer(run_id)


def validate_pre_cleanup_snapshot(
    snapshot: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate one completed-session claim against the local supervisor run."""

    value = _mapping("pre-cleanup snapshot", snapshot)
    observed = _mapping("pre-cleanup observation", observation)
    _exact_keys(
        "pre-cleanup snapshot",
        value,
        {
            "schema",
            "ok",
            "run_id",
            "session_sha256",
            "gate",
            "role",
            "completed_receipt",
            "participant_claim",
            "classifier_result",
        },
    )
    if (
        value.get("schema") != PRE_CLEANUP_SNAPSHOT_SCHEMA
        or value.get("ok") is not True
        or observed.get("schema") != PRE_CLEANUP_OBSERVATION_SCHEMA
        or value.get("run_id") != observed.get("run_id")
        or value.get("gate") not in POST_READINESS_FAULT_GATES
        or value.get("role") not in {"target", "peer"}
        or not _SHA256_RE.fullmatch(str(value.get("session_sha256") or ""))
    ):
        raise FaultSessionEvidenceError("pre-cleanup snapshot identity differs")
    if value.get("role") == "peer" and value.get("gate") != "DAEMON-RESTART":
        raise FaultSessionEvidenceError(
            "only DAEMON-RESTART may classify a peer supervisor"
        )
    environment_identity = _mapping(
        "pre-cleanup environment identity", observed.get("environment_identity")
    )
    rpc = _mapping("pre-cleanup RPC identity", environment_identity.get("rpc"))
    cotenancy = _mapping("pre-cleanup cotenancy", environment_identity.get("cotenancy"))
    nonce = rpc.get("nonce")
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        raise FaultSessionEvidenceError("pre-cleanup RPC nonce is invalid")
    claim = _mapping("pre-cleanup participant claim", value.get("participant_claim"))
    _exact_keys(
        "pre-cleanup participant claim",
        claim,
        {
            "schema",
            "session_sha256",
            "gate",
            "run_id",
            "role",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "source_run_id",
            "source_contract_sha256",
            "source_completed_record_sha256",
            "classifier_result",
        },
    )
    if (
        claim.get("schema") != FAULT_SESSION_CLAIM_SCHEMA
        or claim.get("session_sha256") != value.get("session_sha256")
        or claim.get("gate") != value.get("gate")
        or claim.get("run_id") != value.get("run_id")
        or claim.get("role") != value.get("role")
        or claim.get("contract_sha256") != environment_identity.get("contract_sha256")
        or claim.get("nonce_sha256")
        != hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        or claim.get("cohort_sha256") != cotenancy.get("cohort_sha256")
        or not _RUN_ID_RE.fullmatch(str(claim.get("source_run_id") or ""))
        or not _SHA256_RE.fullmatch(str(claim.get("source_contract_sha256") or ""))
        or not _SHA256_RE.fullmatch(
            str(claim.get("source_completed_record_sha256") or "")
        )
    ):
        raise FaultSessionEvidenceError("pre-cleanup participant claim differs")
    completed = _mapping(
        "pre-cleanup completed receipt", value.get("completed_receipt")
    )
    _exact_keys(
        "pre-cleanup completed receipt",
        completed,
        {
            "schema",
            "session_sha256",
            "gate",
            "source_run_id",
            "source_contract_sha256",
            "source_completed_record_sha256",
            "classified_run_ids",
            "participant_claim_sha256",
        },
    )
    claim_digests = _mapping(
        "pre-cleanup claim digests", completed.get("participant_claim_sha256")
    )
    classified = completed.get("classified_run_ids")
    if (
        completed.get("schema") != FAULT_SESSION_COMPLETED_SCHEMA
        or completed.get("session_sha256") != value.get("session_sha256")
        or completed.get("gate") != value.get("gate")
        or completed.get("source_run_id") != claim.get("source_run_id")
        or completed.get("source_contract_sha256")
        != claim.get("source_contract_sha256")
        or completed.get("source_completed_record_sha256")
        != claim.get("source_completed_record_sha256")
        or not isinstance(classified, (list, tuple))
        or list(classified) != sorted(claim_digests)
        or value.get("run_id") not in classified
        or claim_digests.get(str(value.get("run_id"))) != _payload_sha256(claim)
    ):
        raise FaultSessionEvidenceError("pre-cleanup completed receipt differs")
    classifier_result = _mapping(
        "pre-cleanup classifier result", value.get("classifier_result")
    )
    if classifier_result != _mapping(
        "claim classifier result", claim.get("classifier_result")
    ):
        raise FaultSessionEvidenceError("pre-cleanup classifier result differs")
    _exact_keys(
        "pre-cleanup classifier result",
        classifier_result,
        {"schema", "terminal_class", "evidence"},
    )
    if (
        classifier_result.get("schema") != FAULT_CLASSIFIER_RESULT_SCHEMA
        or classifier_result.get("terminal_class")
        != _TERMINAL_BY_GATE[str(value.get("gate"))]
        or not isinstance(classifier_result.get("evidence"), Mapping)
    ):
        raise FaultSessionEvidenceError("pre-cleanup classifier result is invalid")
    return MappingProxyType(_json_copy(value))


def _validate_public_participant(
    payload: Mapping[str, Any], participant: FaultSessionParticipant
) -> None:
    if (
        payload.get("run_id") != participant.run_id
        or payload.get("contract_sha256") != participant.contract_sha256
        or payload.get("nonce_sha256") != participant.nonce_sha256
        or payload.get("cohort_sha256") != participant.cohort_sha256
        or not isinstance(payload.get("container_id"), str)
        or not payload.get("container_id")
    ):
        raise FaultSessionEvidenceError("completed participant identity differs")


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_copy(payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_copy(value: Any) -> Any:
    def thaw(item: Any) -> Any:
        if isinstance(item, Mapping):
            normalized: dict[str, Any] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise FaultSessionEvidenceError(
                        "fault-session evidence has a non-string key"
                    )
                normalized[key] = thaw(nested)
            return normalized
        if isinstance(item, (list, tuple)):
            return [thaw(nested) for nested in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise FaultSessionEvidenceError(
            f"fault-session evidence contains {type(item).__name__}"
        )

    try:
        encoded = json.dumps(
            thaw(value),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FaultSessionEvidenceError(
            "fault-session evidence is not JSON-safe"
        ) from exc


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FaultSessionEvidenceError(f"{name} must be a mapping")
    return value


def _exact_keys(name: str, value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise FaultSessionEvidenceError(f"{name} keys differ")


def _bounded_string(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise FaultSessionEvidenceError(f"{name} is invalid")
    return value


def _sha256_regular_file(path: Path, *, maximum: int) -> tuple[int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FaultSessionEvidenceError("step-2 trace is unreadable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum:
            raise FaultSessionEvidenceError(
                "step-2 trace is not a bounded regular file"
            )
        digest = hashlib.sha256()
        observed = 0
        while observed <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            digest.update(chunk)
        if observed != metadata.st_size or observed > maximum:
            raise FaultSessionEvidenceError("step-2 trace size changed")
        return observed, digest.hexdigest()
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FaultSessionEvidenceError(
            f"fault-session evidence is unreadable: {path.name}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_JSON_BYTES
        ):
            raise FaultSessionEvidenceError("fault-session evidence file is invalid")
        raw = os.read(descriptor, _MAX_JSON_BYTES + 1)
        if len(raw) != metadata.st_size or len(raw) > _MAX_JSON_BYTES:
            raise FaultSessionEvidenceError("fault-session evidence size changed")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultSessionEvidenceError(
            "fault-session evidence JSON is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise FaultSessionEvidenceError("fault-session evidence must be an object")
    return value


def _read_jsonl(path: Path, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FaultSessionEvidenceError("fault driver journal is unreadable") from exc
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not (0 if allow_empty else 1) <= metadata.st_size <= _MAX_DRIVER_JOURNAL_BYTES
        ):
            raise FaultSessionEvidenceError("fault driver journal file is invalid")
        raw = bytearray()
        while len(raw) <= _MAX_DRIVER_JOURNAL_BYTES:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) != metadata.st_size or len(raw) > _MAX_DRIVER_JOURNAL_BYTES:
            raise FaultSessionEvidenceError("fault driver journal size changed")
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    # The writer creates its file before acquiring the first append lock.
    # Only an in-progress action poll may observe that empty initial prefix;
    # completion readers still require nonempty, canonical journal evidence.
    if allow_empty and not raw:
        return []
    if not raw.endswith(b"\n"):
        raise FaultSessionEvidenceError("fault driver journal is partial")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultSessionEvidenceError(
                "fault driver journal JSONL is invalid"
            ) from exc
        if not isinstance(value, dict) or value.get("event_index") != index:
            raise FaultSessionEvidenceError("fault driver journal sequence differs")
        records.append(value)
    return records


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(_json_copy(payload), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise FaultSessionEvidenceError("fault-session evidence exceeds size bound")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short fault-session evidence write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # Hard-link publication is an atomic create-if-absent operation: a
        # reader can never observe the temporary file's partial contents, and
        # a concurrent contradictory writer cannot replace canonical evidence.
        os.link(temporary_path, path, follow_symlinks=False)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _write_once_or_verify(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        _write_once_json(path, payload)
    except FileExistsError:
        if _read_json(path) != _json_copy(payload):
            raise FaultSessionEvidenceError(
                "existing fault-session evidence contradicts the canonical payload"
            )


__all__ = [
    "FAULT_SESSION_ABORT_SCHEMA",
    "FAULT_SESSION_CLAIM_SCHEMA",
    "FAULT_SESSION_COMPLETED_SCHEMA",
    "FAULT_SESSION_COMPLETION_ABORT_SCHEMA",
    "FAULT_SESSION_MANIFEST_ENV",
    "FAULT_SESSION_READY_SCHEMA",
    "FAULT_SESSION_RELEASED_SCHEMA",
    "FAULT_SESSION_RELEASE_SCHEMA",
    "FAULT_SESSION_SCHEMA",
    "FAULT_SESSION_SHA256_ENV",
    "POST_READINESS_FAULT_GATES",
    "PRE_CLEANUP_OBSERVATION_SCHEMA",
    "PRE_CLEANUP_SNAPSHOT_SCHEMA",
    "FaultSessionAborted",
    "FaultSessionError",
    "FaultSessionEvidenceError",
    "FaultSessionIdentity",
    "FaultSessionParticipant",
    "FaultSessionStore",
    "FaultSessionTimeout",
    "StepCommit",
    "StepCommitObserver",
    "step_observer_from_environment",
    "validate_pre_cleanup_snapshot",
]
