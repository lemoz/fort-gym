from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fort_gym.bench.run.storage import RunRegistry

STARTED_AT = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


def test_worker_registry_does_not_recover_sibling_running_rows(tmp_path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    api_registry = RunRegistry(db_path=db_path)
    first = api_registry.create(
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    second = api_registry.create(
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    assert api_registry.claim_pending_run(first.run_id, started_at=STARTED_AT)
    assert api_registry.claim_pending_run(second.run_id, started_at=STARTED_AT)

    worker_registry = RunRegistry(
        db_path=db_path,
        recover_interrupted=False,
    )

    first_from_worker = worker_registry.get(first.run_id)
    second_from_worker = worker_registry.get(second.run_id)
    first_from_api = api_registry.get(first.run_id)
    second_from_api = api_registry.get(second.run_id)

    assert first_from_worker is not None and first_from_worker.status == "running"
    assert second_from_worker is not None and second_from_worker.status == "running"
    assert first_from_api is not None and first_from_api.status == "running"
    assert second_from_api is not None and second_from_api.status == "running"


def test_default_registry_still_recovers_interrupted_running_rows(tmp_path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    worker_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    created = worker_registry.create(
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    assert worker_registry.claim_pending_run(created.run_id, started_at=STARTED_AT)

    api_registry = RunRegistry(db_path=db_path)

    recovered = api_registry.get(created.run_id)
    assert recovered is not None and recovered.status == "failed"


def test_supervision_mode_round_trips_and_rejects_unknown_authority(tmp_path) -> None:
    registry = RunRegistry(
        db_path=tmp_path / "runs.sqlite3",
        recover_interrupted=False,
    )

    created = registry.create(
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
        supervision_mode="m1b-process",
    )

    recovered = registry.get(created.run_id)
    assert recovered is not None
    assert recovered.supervision_mode == "m1b-process"

    try:
        registry.create(
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
            supervision_mode="truthy-but-untrusted",
        )
    except ValueError as exc:
        assert "unsupported supervision_mode" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("unknown supervision authority was accepted")


def test_default_startup_recovery_does_not_steal_supervised_run(tmp_path) -> None:
    db_path = tmp_path / "runs.sqlite3"
    owner_registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    created = owner_registry.create(
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
        supervision_mode="m1b-process",
    )
    assert owner_registry.claim_pending_run(created.run_id, started_at=STARTED_AT)

    default_registry = RunRegistry(db_path=db_path)

    recovered = default_registry.get(created.run_id)
    assert recovered is not None
    assert recovered.status == "running"
    assert recovered.supervision_mode == "m1b-process"


def test_registry_exposes_exact_storage_identity(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    database = tmp_path / "state" / "runs.sqlite3"
    registry = RunRegistry(
        db_path=database,
        artifacts_root=artifacts,
        recover_interrupted=False,
    )

    assert registry.database_path == database.resolve()
    assert registry.artifacts_root == artifacts.resolve()
    record = registry.create(
        backend="mock",
        model="random",
        max_steps=1,
        ticks_per_step=1,
    )
    assert Path(record.artifacts_dir).parent == artifacts.resolve()
