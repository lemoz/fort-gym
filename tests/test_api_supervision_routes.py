from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import routes_step, server
from fort_gym.bench.run.jobs import JobInfo
from fort_gym.bench.run.runtime_contract import ProviderPolicy
from fort_gym.bench.run.storage import RunInfo, ShareToken
from fort_gym.bench.run.supervision_service import (
    SUPERVISION_MODE,
    CohortLaunch,
    SupervisedRunRequest,
    SupervisionConfigurationError,
)

_DEDICATED_KEY = "m1b-test-key-must-never-be-serialized"


class _FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[str, RunInfo] = {}
        self.shares: dict[str, ShareToken] = {}
        self.direct_create_calls: list[dict[str, Any]] = []
        self.status_writes: list[tuple[str, str]] = []
        self.share_writes: list[str] = []
        self.stop_requests: list[str] = []

    def add_reserved(self, record: RunInfo) -> None:
        self.records[record.run_id] = record

    def add_share(self, share: ShareToken) -> None:
        self.shares[share.token] = share

    def create(self, **kwargs: Any) -> RunInfo:
        self.direct_create_calls.append(kwargs)
        raise AssertionError("the M1b API path must not create run rows directly")

    def get(self, run_id: str) -> RunInfo | None:
        return self.records.get(run_id)

    def list(self) -> list[RunInfo]:
        return list(self.records.values())

    def set_status(self, run_id: str, *, status: str, **_kwargs: Any) -> None:
        self.status_writes.append((run_id, status))
        self.records[run_id].status = status

    def create_share(self, run_id: str, **_kwargs: Any) -> None:
        self.share_writes.append(run_id)
        raise AssertionError("a supervised run must not reach share creation")

    def get_share(self, token: str) -> ShareToken | None:
        return self.shares.get(token)

    def request_stop(self, run_id: str) -> bool:
        record = self.records.get(run_id)
        if record is None or record.status in {"completed", "failed", "stopped"}:
            return False
        self.stop_requests.append(run_id)
        return True


class _FakeSupervisionService:
    def __init__(
        self,
        registry: _FakeRegistry,
        *,
        fail_first_execution: bool = False,
    ) -> None:
        self.registry = registry
        self.fail_first_execution = fail_first_execution
        self.config = SimpleNamespace(openrouter_api_key=_DEDICATED_KEY)
        self.launch_requests: list[SupervisedRunRequest] = []
        self.reserve_requests: list[SupervisedRunRequest] = []
        self.run_calls: list[str] = []
        self.terminalized: list[tuple[str, str, str]] = []
        self.capture_calls: list[str] = []
        self.reconcile_calls = 0
        self._requests_by_run: dict[str, SupervisedRunRequest] = {}
        self._next_id = 0
        self._execution_failure_emitted = False

    def _reserve(self, request: SupervisedRunRequest) -> CohortLaunch:
        records: list[RunInfo] = []
        run_ids: list[str] = []
        for _ in range(request.cohort_size):
            self._next_id += 1
            run_id = f"supervised-{self._next_id}"
            runtime_prefix = request.runtime_save_prefix or "m1b-test"
            record = RunInfo(
                run_id=run_id,
                backend=request.backend,
                model=request.model,
                max_steps=request.max_steps,
                ticks_per_step=request.ticks_per_step,
                status="pending",
                seed_save=request.seed_save or "seed-test",
                runtime_save=f"{runtime_prefix}-{run_id}",
                preserve_save=request.preserve_save,
                evaluation_protocol=request.evaluation_protocol,
                supervision_mode=SUPERVISION_MODE,
            )
            self.registry.add_reserved(record)
            self._requests_by_run[run_id] = request
            records.append(record)
            run_ids.append(run_id)
        return CohortLaunch(run_ids=tuple(run_ids), records=tuple(records))

    def launch_async(self, request: SupervisedRunRequest) -> CohortLaunch:
        self.launch_requests.append(request)
        return self._reserve(request)

    def reserve(self, request: SupervisedRunRequest) -> CohortLaunch:
        self.reserve_requests.append(request)
        return self._reserve(request)

    def run_reserved(self, run_id: str) -> SimpleNamespace:
        self.run_calls.append(run_id)
        if self.fail_first_execution and not self._execution_failure_emitted:
            self._execution_failure_emitted = True
            raise RuntimeError("synthetic preclaim execution failure")
        self.registry.records[run_id].status = "completed"
        return SimpleNamespace(status="completed")

    def terminalize_unstarted(
        self,
        run_id: str,
        exc: BaseException,
        *,
        code: str = "manager_thread_start_failed",
    ) -> None:
        self.terminalized.append((run_id, code, type(exc).__name__))
        self.registry.records[run_id].status = "failed"

    def environment_identity(self, run_id: str) -> dict[str, Any]:
        request = self._requests_by_run[run_id]
        provider = request.provider_policy or ProviderPolicy()
        return {
            "schema": "fortgym.m1b-runtime-contract/v1",
            "run_id": run_id,
            "contract_sha256": "a" * 64,
            "runtime": {"image_manifest_sha256": "b" * 64},
            "seed": {"tree_sha256": "c" * 64},
            "code_sha256": "d" * 64,
            "rpc": {
                "host": "127.0.0.1",
                "port": 58_000,
                "nonce_attested": True,
            },
            "paths": {"control_root": "/host/path/must-not-be-exposed"},
            "scripted": not provider.enabled,
            "provider": provider.identity(),
            "cotenancy": {"cohort_size": request.cohort_size},
        }

    def capture_screen(self, run_id: str) -> dict[str, Any]:
        self.capture_calls.append(run_id)
        return {"run_id": run_id, "screen": "isolated"}

    def reconcile_all(self) -> dict[str, str]:
        self.reconcile_calls += 1
        return {}


class _FakeJobRegistry:
    def __init__(
        self,
        run_registry: _FakeRegistry,
        *,
        fail_first_thread_start: bool = False,
        raise_during_activation: bool = False,
        drop_after_activation: bool = False,
    ) -> None:
        self.run_registry = run_registry
        self.fail_first_thread_start = fail_first_thread_start
        self.raise_during_activation = raise_during_activation
        self.drop_after_activation = drop_after_activation
        self.jobs: dict[str, JobInfo] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.start_calls: list[tuple[str, tuple[str, ...]]] = []
        self.execution_views: list[tuple[list[str], tuple[str, ...]]] = []
        self.callback_was_supplied = False
        self.execution_callback_was_supplied = False
        self.barrier_callback_was_supplied = False
        self.start_barrier = False
        self.activation_failures: list[tuple[str, str]] = []

    def create(self, **kwargs: Any) -> JobInfo:
        self.create_calls.append(dict(kwargs))
        job = JobInfo(
            job_id=f"job-{len(self.jobs) + 1}",
            model=kwargs["model"],
            backend=kwargs["backend"],
            n=kwargs["n"],
            parallelism=kwargs["parallelism"],
            isolation_supervised=kwargs.get("isolation_supervised", False),
        )
        self.jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobInfo | None:
        return self.jobs.get(job_id)

    def list(self) -> list[JobInfo]:
        return list(self.jobs.values())

    def fail_activation(
        self,
        job_id: str,
        *,
        reason: str = "activation_failed",
    ) -> JobInfo:
        self.activation_failures.append((job_id, reason))
        job = self.jobs[job_id]
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        job.failure_reason = reason
        return job

    def start_reserved(
        self,
        job_id: str,
        run_ids: Sequence[str],
        execute_run: Callable[[str], str],
        *,
        on_launch_failure: Callable[[str, BaseException], None] | None = None,
        on_execution_failure: Callable[[str, BaseException], None] | None = None,
        on_barrier_failure: Callable[[str, BaseException], None] | None = None,
        start_barrier: bool = False,
    ) -> None:
        reserved = tuple(run_ids)
        self.start_calls.append((job_id, reserved))
        self.callback_was_supplied = on_launch_failure is not None
        self.execution_callback_was_supplied = on_execution_failure is not None
        self.barrier_callback_was_supplied = on_barrier_failure is not None
        self.start_barrier = start_barrier
        job = self.jobs[job_id]
        job.run_ids = list(reserved)
        job.status = "running"
        job.start_barrier = start_barrier is True
        if job.start_barrier:
            job.barrier_state = "released"
            job.barrier_released_at = datetime.now(UTC)
        if self.drop_after_activation:
            self.run_registry.records[reserved[0]].status = "running"
            self.jobs.pop(job_id)
            return
        if self.raise_during_activation:
            raise RuntimeError("synthetic activation failure")

        failed = False
        for index, run_id in enumerate(reserved):
            visible = self.get(job_id)
            assert visible is not None
            visible_records = tuple(
                candidate for candidate in reserved if self.run_registry.get(candidate)
            )
            self.execution_views.append((list(visible.run_ids), visible_records))
            if index == 0 and self.fail_first_thread_start:
                assert on_launch_failure is not None
                on_launch_failure(
                    run_id, RuntimeError("synthetic thread-start failure")
                )
                failed = True
                continue
            try:
                failed = execute_run(run_id) != "completed" or failed
            except Exception as exc:  # noqa: BLE001 - mirrors scheduler boundary
                assert on_execution_failure is not None
                on_execution_failure(run_id, exc)
                failed = True

        job.status = "failed" if failed else "completed"
        job.finished_at = datetime.now(UTC)


def _forbidden_legacy_guards(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def forbidden(name: str) -> Callable[..., Any]:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise AssertionError(f"M1b unexpectedly used legacy {name}")

        return fail

    monkeypatch.setattr(server, "_get_agent_factory", forbidden("agent factory"))
    monkeypatch.setattr(server, "run_once", forbidden("run_once"))
    monkeypatch.setattr(
        server,
        "threading",
        SimpleNamespace(Thread=forbidden("API run thread")),
    )
    return calls


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_first_thread_start: bool = False,
    fail_first_execution: bool = False,
    raise_during_activation: bool = False,
    drop_after_activation: bool = False,
) -> tuple[_FakeRegistry, _FakeSupervisionService, _FakeJobRegistry, list[str]]:
    monkeypatch.setenv("FORT_GYM_INSECURE_ADMIN", "1")
    monkeypatch.setenv("FORT_GYM_RATE_LIMIT_ENABLED", "0")
    registry = _FakeRegistry()
    service = _FakeSupervisionService(
        registry,
        fail_first_execution=fail_first_execution,
    )
    jobs = _FakeJobRegistry(
        registry,
        fail_first_thread_start=fail_first_thread_start,
        raise_during_activation=raise_during_activation,
        drop_after_activation=drop_after_activation,
    )
    monkeypatch.setattr(server, "RUN_REGISTRY", registry)
    monkeypatch.setattr(routes_step, "RUN_REGISTRY", registry)
    monkeypatch.setattr(server, "JOB_REGISTRY", jobs)
    monkeypatch.setattr(server, "_get_supervision_service", lambda: service)
    legacy_calls = _forbidden_legacy_guards(monkeypatch)
    return registry, service, jobs, legacy_calls


def _m1b_run_payload(*, provider: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "backend": "dfhack",
        "model": "dfhack-governed-llm" if provider else "dfhack-governed-scripted",
        "max_steps": 2,
        "ticks_per_step": 10,
        "safe": True,
        "runtime_save_prefix": "m1b-api-test",
        "supervision_mode": SUPERVISION_MODE,
    }
    if provider:
        payload["provider"] = {
            "route": "openrouter",
            "model": "openai/test-model",
            "provider_name": "OpenAI",
            "max_total_tokens": 321,
            "max_cost_usd": 0.25,
        }
    return payload


def _m1b_job_payload() -> dict[str, Any]:
    return {
        "backend": "dfhack",
        "model": "dfhack-governed-scripted",
        "n": 3,
        "parallelism": 3,
        "max_steps": 2,
        "ticks_per_step": 10,
        "safe": True,
        "runtime_save_prefix": "m1b-job-test",
        "supervision_mode": SUPERVISION_MODE,
    }


def test_explicit_m1b_run_uses_only_service_and_keeps_provider_key_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, _jobs, legacy_calls = _install_fakes(monkeypatch)
    client = TestClient(server.app)
    try:
        response = client.post("/runs", json=_m1b_run_payload(provider=True))
    finally:
        client.close()

    assert response.status_code == 200, response.text
    assert registry.direct_create_calls == []
    assert legacy_calls == []
    assert len(service.launch_requests) == 1
    request = service.launch_requests[0]
    assert request.cohort_size == 1
    assert request.provider_policy is not None
    assert request.provider_policy.api_key == _DEDICATED_KEY
    assert request.provider_policy.model == "openai/test-model"
    assert request.provider_policy.provider_name == "OpenAI"
    assert request.provider_policy.max_total_tokens == 321
    assert request.provider_policy.max_cost_usd == 0.25

    body = response.json()
    serialized = json.dumps(body, sort_keys=True)
    assert body["supervision_mode"] == SUPERVISION_MODE
    assert body["environment"]["provider"]["credential_present"] is True
    assert body["environment"]["provider"]["provider_name"] == "OpenAI"
    assert "paths" not in body["environment"]
    assert _DEDICATED_KEY not in serialized
    assert "OPENROUTER_API_KEY" not in serialized


def test_supervised_environment_response_deeply_rejects_poisoned_secret_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registry, service, _jobs, legacy_calls = _install_fakes(monkeypatch)
    poison_values = {
        "poison-api-key",
        "poison-runtime-nonce",
        "/poisoned/absolute/host/path",
    }

    def poisoned_identity(run_id: str) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-runtime-contract/v1",
            "run_id": run_id,
            "contract_sha256": "a" * 64,
            "runtime": {
                "image_manifest_sha256": "b" * 64,
                "nested": {"api_key": "poison-api-key"},
            },
            "seed": {
                "tree_sha256": "c" * 64,
                "host_path": "/poisoned/absolute/host/path",
            },
            "code_sha256": "d" * 64,
            "rpc": {
                "host": "127.0.0.1",
                "port": 58_000,
                "nonce": "poison-runtime-nonce",
                "nonce_attested": True,
            },
            "paths": {"control_root": "/poisoned/top-level/path"},
            "scripted": True,
            "provider": {
                "enabled": False,
                "nested": {"api_key": "poison-api-key"},
            },
            "cotenancy": {
                "cohort_size": 1,
                "nested": {"host_path": "/poisoned/absolute/host/path"},
            },
        }

    monkeypatch.setattr(service, "environment_identity", poisoned_identity)
    client = TestClient(server.app)
    try:
        response = client.post("/runs", json=_m1b_run_payload())
    finally:
        client.close()

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json()["environment"], sort_keys=True)
    assert "paths" not in response.json()["environment"]
    assert all(value not in serialized for value in poison_values)
    assert legacy_calls == []


def test_bounded_environment_identity_preserves_public_attestation_projection() -> None:
    identity = {
        "schema": "fortgym.m1b-runtime-contract/v1",
        "run_id": "supervised-attestation",
        "backend": "dfhack",
        "model": "dfhack-governed-scripted",
        "contract_sha256": "a" * 64,
        "runtime": {
            "classification": "source-built-reproducible",
            "source_reproducible": True,
            "image_manifest_sha256": "b" * 64,
            "image_config_sha256": "c" * 64,
            "image_archive_sha256": "d" * 64,
            "unknown": "must-be-dropped",
        },
        "seed": {
            "tree_sha256": "e" * 64,
            "world_sha256": "f" * 64,
            "seed_save": "seed-a",
            "runtime_save": "runtime-a",
            "host_path": "/private/seed/path",
        },
        "code_sha256": "0" * 64,
        "rpc": {
            "host": "127.0.0.1",
            "port": 58_001,
            "nonce": "must-be-dropped",
            "nonce_attested": True,
        },
        "paths": {"control_root": "/private/control/path"},
        "scripted": True,
        "provider": {
            "enabled": False,
            "route": "openrouter",
            "model": None,
            "provider_name": None,
            "base_url": "https://openrouter.ai/api/v1",
            "max_total_tokens": 128_000,
            "max_cost_usd": 25.0,
            "credential_present": False,
            "strict_supervised": True,
            "api_key": "must-be-dropped",
        },
        "cotenancy": {
            "schema": "fortgym.m1b-cotenancy/v1",
            "cohort_sha256": "1" * 64,
            "cohort_size": 2,
            "slot": 0,
            "peer_run_ids": ["supervised-peer"],
            "control_path": "/private/peer/path",
        },
    }

    assert server._bounded_environment_identity(identity) == {
        "schema": "fortgym.m1b-runtime-contract/v1",
        "run_id": "supervised-attestation",
        "contract_sha256": "a" * 64,
        "runtime": {
            "classification": "source-built-reproducible",
            "source_reproducible": True,
            "image_manifest_sha256": "b" * 64,
            "image_config_sha256": "c" * 64,
            "image_archive_sha256": "d" * 64,
        },
        "seed": {
            "tree_sha256": "e" * 64,
            "world_sha256": "f" * 64,
            "seed_save": "seed-a",
            "runtime_save": "runtime-a",
        },
        "code_sha256": "0" * 64,
        "rpc": {
            "host": "127.0.0.1",
            "port": 58_001,
            "nonce_attested": True,
        },
        "scripted": True,
        "provider": {
            "enabled": False,
            "route": "openrouter",
            "model": None,
            "provider_name": None,
            "base_url": "https://openrouter.ai/api/v1",
            "max_total_tokens": 128_000,
            "max_cost_usd": 25.0,
            "credential_present": False,
            "strict_supervised": True,
        },
        "cotenancy": {
            "schema": "fortgym.m1b-cotenancy/v1",
            "cohort_sha256": "1" * 64,
            "cohort_size": 2,
            "slot": 0,
            "peer_run_ids": ["supervised-peer"],
        },
    }


@pytest.mark.parametrize(
    "malformation,expected_compensated",
    [
        ("zero", ()),
        ("multiple", ("malformed-a", "malformed-b")),
        ("id-mismatch", ("claimed-id", "returned-id")),
        ("missing-persisted", ()),
    ],
)
def test_malformed_single_run_launch_fails_closed_and_compensates_pending_rows(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected_compensated: tuple[str, ...],
) -> None:
    registry, service, _jobs, legacy_calls = _install_fakes(monkeypatch)

    def record(run_id: str) -> RunInfo:
        return RunInfo(
            run_id=run_id,
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=2,
            ticks_per_step=10,
            status="pending",
            supervision_mode=SUPERVISION_MODE,
        )

    def malformed_launch(request: SupervisedRunRequest) -> CohortLaunch:
        service.launch_requests.append(request)
        if malformation == "zero":
            return CohortLaunch(run_ids=(), records=())
        if malformation == "multiple":
            records = (record("malformed-a"), record("malformed-b"))
            for candidate in records:
                registry.add_reserved(candidate)
            return CohortLaunch(
                run_ids=("malformed-a", "malformed-b"),
                records=records,
            )
        if malformation == "id-mismatch":
            claimed = record("claimed-id")
            returned = record("returned-id")
            registry.add_reserved(claimed)
            registry.add_reserved(returned)
            return CohortLaunch(run_ids=(claimed.run_id,), records=(returned,))
        assert malformation == "missing-persisted"
        missing = record("missing-id")
        return CohortLaunch(run_ids=(missing.run_id,), records=(missing,))

    monkeypatch.setattr(service, "launch_async", malformed_launch)
    client = TestClient(server.app)
    try:
        response = client.post("/runs", json=_m1b_run_payload())
    finally:
        client.close()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "M1b single-run reservation returned an invalid cohort"
    }
    assert len(service.launch_requests) == 1
    assert tuple(run_id for run_id, _code, _error in service.terminalized) == (
        expected_compensated
    )
    assert {code for _run_id, code, _error in service.terminalized} <= {
        "api_single_launch_invalid"
    }
    assert not any(record.status == "pending" for record in registry.list())
    assert registry.direct_create_calls == []
    assert legacy_calls == []


@pytest.mark.parametrize(
    "malformation,expected_compensated,expected_untouched",
    [
        ("cardinality", ("job-a", "job-b"), ()),
        ("duplicate", ("duplicate", "job-c"), ()),
        ("record-mismatch", ("job-a", "job-b", "job-c"), ()),
        ("missing-persisted", ("job-a", "job-b"), ()),
        ("wrong-owner", ("job-a", "job-b"), ("job-c",)),
    ],
)
def test_malformed_job_launch_fails_before_scheduler_and_compensates_owned_rows(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected_compensated: tuple[str, ...],
    expected_untouched: tuple[str, ...],
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(monkeypatch)

    def record(run_id: str, *, supervised: bool = True) -> RunInfo:
        candidate = RunInfo(
            run_id=run_id,
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=2,
            ticks_per_step=10,
            status="pending",
            supervision_mode=SUPERVISION_MODE if supervised else None,
        )
        registry.add_reserved(candidate)
        return candidate

    def malformed_reserve(request: SupervisedRunRequest) -> CohortLaunch:
        service.reserve_requests.append(request)
        if malformation == "cardinality":
            records = (record("job-a"), record("job-b"))
            return CohortLaunch(run_ids=("job-a", "job-b"), records=records)
        if malformation == "duplicate":
            duplicate = record("duplicate")
            third = record("job-c")
            return CohortLaunch(
                run_ids=("duplicate", "duplicate", "job-c"),
                records=(duplicate, duplicate, third),
            )
        if malformation == "record-mismatch":
            first = record("job-a")
            second = record("job-b")
            third = record("job-c")
            return CohortLaunch(
                run_ids=("job-a", "job-b", "job-c"),
                records=(first, third, second),
            )
        first = record("job-a")
        second = record("job-b")
        if malformation == "missing-persisted":
            missing = RunInfo(
                run_id="job-c",
                backend="dfhack",
                model="dfhack-governed-scripted",
                max_steps=2,
                ticks_per_step=10,
                status="pending",
                supervision_mode=SUPERVISION_MODE,
            )
            return CohortLaunch(
                run_ids=("job-a", "job-b", "job-c"),
                records=(first, second, missing),
            )
        assert malformation == "wrong-owner"
        foreign = record("job-c", supervised=False)
        return CohortLaunch(
            run_ids=("job-a", "job-b", "job-c"),
            records=(first, second, foreign),
        )

    monkeypatch.setattr(service, "reserve", malformed_reserve)
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "M1b job reservation returned an invalid cohort"
    }
    assert len(service.reserve_requests) == 1
    assert tuple(run_id for run_id, _code, _error in service.terminalized) == (
        expected_compensated
    )
    assert {code for _run_id, code, _error in service.terminalized} <= {
        "api_job_launch_invalid"
    }
    assert all(
        registry.get(run_id).status == "failed"  # type: ignore[union-attr]
        for run_id in expected_compensated
    )
    assert all(
        registry.get(run_id).status == "pending"  # type: ignore[union-attr]
        for run_id in expected_untouched
    )
    assert jobs.create_calls == []
    assert jobs.start_calls == []
    assert legacy_calls == []


def test_supervised_job_reserves_full_cohort_before_any_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(monkeypatch)
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 200, response.text
    assert registry.direct_create_calls == []
    assert legacy_calls == []
    assert len(service.reserve_requests) == 1
    request = service.reserve_requests[0]
    assert request.cohort_size == 3
    assert jobs.create_calls == [
        {
            "model": "dfhack-governed-scripted",
            "backend": "dfhack",
            "n": 3,
            "parallelism": 3,
            "isolation_supervised": True,
        }
    ]
    run_ids = tuple(response.json()["run_ids"])
    assert len(run_ids) == 3
    assert jobs.start_calls == [(response.json()["job_id"], run_ids)]
    assert service.run_calls == list(run_ids)
    assert jobs.execution_views == [(list(run_ids), run_ids)] * 3
    assert all(registry.get(run_id) is not None for run_id in run_ids)
    assert response.json()["isolation_supervised"] is True
    assert response.json()["start_barrier"] is True
    assert response.json()["barrier_state"] == "released"
    assert response.json()["barrier_released_at"] is not None
    assert jobs.barrier_callback_was_supplied is True
    assert jobs.start_barrier is True


def test_supervised_job_thread_start_failure_uses_run_compensation_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(
        monkeypatch,
        fail_first_thread_start=True,
    )
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 200, response.text
    run_ids = response.json()["run_ids"]
    assert jobs.callback_was_supplied is True
    assert service.terminalized == [
        (run_ids[0], "job_manager_thread_start_failed", "RuntimeError")
    ]
    assert registry.get(run_ids[0]).status == "failed"  # type: ignore[union-attr]
    assert all(
        registry.get(run_id).status == "completed"  # type: ignore[union-attr]
        for run_id in run_ids[1:]
    )
    assert not any(record.status == "pending" for record in registry.list())
    assert response.json()["status"] == "failed"
    assert legacy_calls == []


def test_supervised_job_preclaim_execution_failure_terminalizes_reserved_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(
        monkeypatch,
        fail_first_execution=True,
    )
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 200, response.text
    run_ids = response.json()["run_ids"]
    assert jobs.execution_callback_was_supplied is True
    assert service.run_calls == run_ids
    assert service.terminalized == [
        (
            run_ids[0],
            "job_manager_execution_failed_before_claim",
            "RuntimeError",
        )
    ]
    assert registry.get(run_ids[0]).status == "failed"  # type: ignore[union-attr]
    assert all(
        registry.get(run_id).status == "completed"  # type: ignore[union-attr]
        for run_id in run_ids[1:]
    )
    assert not any(record.status == "pending" for record in registry.list())
    assert response.json()["status"] == "failed"
    assert legacy_calls == []


def test_supervised_job_activation_failure_terminalizes_every_reserved_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(
        monkeypatch,
        raise_during_activation=True,
    )
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "M1b job activation failed after cohort reservation"
    }
    assert len(service.terminalized) == 3
    assert {code for _run_id, code, _exc_type in service.terminalized} == {
        "job_activation_failed"
    }
    assert not any(record.status == "pending" for record in registry.list())
    assert jobs.activation_failures == [("job-1", "activation_failed")]
    terminal_job = jobs.get("job-1")
    assert terminal_job is not None
    assert terminal_job.status == "failed"
    assert terminal_job.finished_at is not None
    assert terminal_job.failure_reason == "activation_failed"
    assert legacy_calls == []


def test_supervised_job_missing_after_activation_fails_closed_and_stops_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, jobs, legacy_calls = _install_fakes(
        monkeypatch,
        drop_after_activation=True,
    )
    client = TestClient(server.app)
    try:
        response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "M1b job activation lost its scheduler metadata"
    }
    [(job_id, run_ids)] = jobs.start_calls
    assert jobs.get(job_id) is None
    assert registry.get(run_ids[0]).status == "running"  # type: ignore[union-attr]
    assert registry.stop_requests == [run_ids[0]]
    assert service.terminalized == [
        (
            run_ids[1],
            "api_job_registry_missing",
            "RuntimeError",
        ),
        (
            run_ids[2],
            "api_job_registry_missing",
            "RuntimeError",
        ),
    ]
    assert all(
        registry.get(run_id).status == "failed"  # type: ignore[union-attr]
        for run_id in run_ids[1:]
    )
    assert not any(record.status == "pending" for record in registry.list())
    assert legacy_calls == []


def test_supervised_control_routes_are_isolated_but_stop_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, service, _jobs, legacy_calls = _install_fakes(monkeypatch)
    run_id = "owned-run"
    registry.add_reserved(
        RunInfo(
            run_id=run_id,
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=2,
            ticks_per_step=10,
            status="running",
            supervision_mode=SUPERVISION_MODE,
        )
    )
    legacy_run_id = "legacy-run"
    legacy_token = "legacy-public-token"
    registry.add_reserved(
        RunInfo(
            run_id=legacy_run_id,
            backend="dfhack",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
            status="running",
        )
    )
    registry.add_share(
        ShareToken(
            token=legacy_token,
            run_id=legacy_run_id,
            scope={"live"},
            expires_at=None,
            created_at=datetime.now(UTC),
        )
    )

    def forbidden_control(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a global/interactive control seam was reached")

    monkeypatch.setattr(server, "_get_screenshot_client", forbidden_control)
    monkeypatch.setattr(server, "execute_keystroke_action", forbidden_control)
    monkeypatch.setattr(routes_step, "get_settings", forbidden_control)
    monkeypatch.setattr(routes_step, "DFHackClient", forbidden_control)
    monkeypatch.setattr(routes_step, "_get_context", forbidden_control)

    client = TestClient(server.app)
    try:
        pause = client.post(f"/runs/{run_id}/pause")
        resume = client.post(f"/runs/{run_id}/resume")
        share = client.post(f"/runs/{run_id}/share", json={})
        step = client.post("/step", json={"run_id": run_id, "action": {"type": "noop"}})
        keys = client.post("/admin/keys", json={"keys": ["A"]})
        unscoped_screen = client.get("/screenshot")
        legacy_scoped_screen = client.get(
            "/screenshot",
            params={"run_id": legacy_run_id},
        )
        legacy_public_screen = client.get(f"/public/runs/{legacy_token}/screenshot")
        scoped_screen = client.get("/screenshot", params={"run_id": run_id})
        stop = client.post(f"/runs/{run_id}/stop")
    finally:
        client.close()

    assert [
        pause.status_code,
        resume.status_code,
        share.status_code,
        step.status_code,
    ] == [
        409,
        409,
        409,
        409,
    ]
    assert keys.status_code == 409
    assert unscoped_screen.status_code == 409
    assert legacy_scoped_screen.status_code == 409
    assert legacy_public_screen.status_code == 409
    assert scoped_screen.status_code == 200
    assert scoped_screen.json() == {"run_id": run_id, "screen": "isolated"}
    assert service.capture_calls == [run_id]
    assert stop.status_code == 200
    assert stop.json() == {"status": "stop_requested", "run_id": run_id}
    assert registry.stop_requests == [run_id]
    assert registry.get(run_id).status == "running"  # type: ignore[union-attr]
    assert registry.status_writes == []
    assert registry.share_writes == []
    assert legacy_calls == []


def test_disabled_single_owner_gate_fails_closed_before_run_or_job_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORT_GYM_INSECURE_ADMIN", "1")
    monkeypatch.setenv("FORT_GYM_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("FORT_GYM_M1B_SUPERVISION_ENABLED", "1")
    monkeypatch.delenv("FORT_GYM_M1B_API_SINGLE_OWNER", raising=False)
    registry = _FakeRegistry()
    jobs = _FakeJobRegistry(registry)
    monkeypatch.setattr(server, "RUN_REGISTRY", registry)
    monkeypatch.setattr(server, "JOB_REGISTRY", jobs)
    legacy_calls = _forbidden_legacy_guards(monkeypatch)
    server._reset_supervision_service_for_tests()

    client = TestClient(server.app)
    try:
        run_response = client.post("/runs", json=_m1b_run_payload())
        job_response = client.post("/jobs", json=_m1b_job_payload())
    finally:
        client.close()
        server._reset_supervision_service_for_tests()

    assert run_response.status_code == 503
    assert job_response.status_code == 503
    assert "FORT_GYM_M1B_API_SINGLE_OWNER=1" in run_response.json()["detail"]
    assert "FORT_GYM_M1B_API_SINGLE_OWNER=1" in job_response.json()["detail"]
    assert registry.records == {}
    assert registry.direct_create_calls == []
    assert jobs.create_calls == []
    assert legacy_calls == []


def test_supervision_api_owner_flock_excludes_competing_process_until_reset(
    tmp_path: Path,
) -> None:
    if server.fcntl is None:
        pytest.skip("POSIX flock is unavailable")
    control_root = tmp_path / "shared-control"
    config = SimpleNamespace(control_root=control_root)
    repository_root = Path(server.__file__).resolve().parents[3]
    child_script = """
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fort_gym.bench.api import server

config = SimpleNamespace(control_root=Path(sys.argv[1]))
try:
    server._acquire_supervision_api_owner(config)
except Exception as exc:
    print(json.dumps({
        "acquired": False,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }, sort_keys=True))
else:
    print(json.dumps({"acquired": True}, sort_keys=True))
    server._reset_supervision_service_for_tests()
"""
    child_environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "FORT_GYM_DISABLE_DOTENV": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    def child_attempt() -> dict[str, Any]:
        completed = subprocess.run(
            [sys.executable, "-c", child_script, str(control_root)],
            cwd=repository_root,
            env=child_environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    server._reset_supervision_service_for_tests()
    try:
        server._acquire_supervision_api_owner(config)
        assert server._SUPERVISION_OWNER_FD is not None

        blocked = child_attempt()
        assert blocked == {
            "acquired": False,
            "error_type": "SupervisionConfigurationError",
            "message": "another API process already owns M1b supervision",
        }

        server._reset_supervision_service_for_tests()
        assert server._SUPERVISION_OWNER_FD is None

        acquired = child_attempt()
        assert acquired == {"acquired": True}
    finally:
        server._reset_supervision_service_for_tests()


def test_startup_reconciliation_requires_both_explicit_enablement_and_owner_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_getter = server._get_supervision_service
    getter_calls = 0

    def forbidden_getter() -> Any:
        nonlocal getter_calls
        getter_calls += 1
        raise AssertionError("disabled startup must not resolve M1b service")

    monkeypatch.delenv("FORT_GYM_M1B_SUPERVISION_ENABLED", raising=False)
    monkeypatch.delenv("FORT_GYM_M1B_API_SINGLE_OWNER", raising=False)
    monkeypatch.setattr(server, "_get_supervision_service", forbidden_getter)
    asyncio.run(server._reconcile_supervised_runs_on_startup())
    assert getter_calls == 0

    monkeypatch.setenv("FORT_GYM_M1B_SUPERVISION_ENABLED", "1")
    monkeypatch.setattr(server, "_get_supervision_service", original_getter)
    server._reset_supervision_service_for_tests()
    with pytest.raises(
        SupervisionConfigurationError,
        match="FORT_GYM_M1B_API_SINGLE_OWNER=1",
    ):
        asyncio.run(server._reconcile_supervised_runs_on_startup())

    registry = _FakeRegistry()
    service = _FakeSupervisionService(registry)
    monkeypatch.setenv("FORT_GYM_M1B_API_SINGLE_OWNER", "1")
    monkeypatch.setattr(server, "_get_supervision_service", lambda: service)
    asyncio.run(server._reconcile_supervised_runs_on_startup())
    assert service.reconcile_calls == 1
