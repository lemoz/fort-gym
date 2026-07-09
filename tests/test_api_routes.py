from __future__ import annotations


def test_routes_import() -> None:
    from fort_gym.bench.api.server import app

    paths = sorted(route.path for route in app.routes if hasattr(route, "path"))
    assert "/runs" in "".join(paths)


def test_run_create_request_accepts_preserve_save() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="openrouter-keystroke-perception-review",
        preserve_save=True,
    )

    assert request.preserve_save is True


def test_run_create_request_accepts_poi_review_keystroke_model() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="anthropic-keystroke-poi-review",
        max_steps=100,
        ticks_per_step=10,
    )

    assert request.model == "anthropic-keystroke-poi-review"


def test_run_create_request_accepts_openrouter_keystroke_models() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="openrouter-keystroke-perception-review",
        max_steps=100,
        ticks_per_step=10,
    )
    glm_request = RunCreateRequest(
        backend="dfhack",
        model="openrouter-glm-5.2",
        max_steps=100,
        ticks_per_step=10,
    )

    assert request.model == "openrouter-keystroke-perception-review"
    assert glm_request.model == "openrouter-glm-5.2"


def test_run_create_request_accepts_governed_dfhack_model() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=100,
        ticks_per_step=1000,
    )

    assert request.model == "dfhack-governed-scripted"


def test_run_create_request_accepts_openai_keystroke_model() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="openai-keystroke-perception-review",
        max_steps=100,
        ticks_per_step=10,
    )

    assert request.model == "openai-keystroke-perception-review"


def test_run_create_request_accepts_plan_review_keystroke_model() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="anthropic-keystroke-plan-review",
        max_steps=100,
        ticks_per_step=10,
    )

    assert request.model == "anthropic-keystroke-plan-review"


def test_run_create_request_accepts_perception_review_keystroke_models() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="anthropic-keystroke-perception-review",
        max_steps=100,
        ticks_per_step=10,
    )
    opus_request = RunCreateRequest(
        backend="dfhack",
        model="anthropic-keystroke-perception-review-opus",
        max_steps=100,
        ticks_per_step=10,
    )

    assert request.model == "anthropic-keystroke-perception-review"
    assert opus_request.model == "anthropic-keystroke-perception-review-opus"


def test_run_registry_persists_preserve_save(tmp_path) -> None:
    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")

    created = registry.create(
        backend="dfhack",
        model="openrouter-keystroke-perception-review",
        max_steps=2,
        ticks_per_step=500,
        preserve_save=True,
    )
    loaded = registry.get(created.run_id)

    assert created.preserve_save is True
    assert loaded is not None
    assert loaded.preserve_save is True


def test_run_registry_stop_flag_lifecycle(tmp_path) -> None:
    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="openrouter-glm-5.2",
        max_steps=200,
        ticks_per_step=10,
    )

    assert registry.stop_requested(created.run_id) is False
    assert registry.request_stop(created.run_id) is True
    assert registry.stop_requested(created.run_id) is True

    registry.clear_stop(created.run_id)

    assert registry.stop_requested(created.run_id) is False
    registry.set_status(created.run_id, status="completed")
    assert registry.request_stop(created.run_id) is False
    assert registry.request_stop("missing-run") is False


def test_success_finalization_serializes_with_stop_acceptance(tmp_path) -> None:
    from datetime import datetime

    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    stop_first = registry.create(backend="mock", model="fake", max_steps=1, ticks_per_step=1)
    assert registry.claim_pending_run(stop_first.run_id, started_at=datetime.utcnow()) is True
    assert registry.request_stop(stop_first.run_id) is True
    registry.record_cleanup_completed(stop_first.run_id, completed_at=datetime.utcnow())
    registry.set_summary(stop_first.run_id, {"total_score": 0.0})
    assert (
        registry.finalize_success_after_cleanup(
            stop_first.run_id,
            step=0,
            ended_at=datetime.utcnow(),
        )
        == "stopped"
    )

    finish_first = registry.create(backend="mock", model="fake", max_steps=1, ticks_per_step=1)
    assert registry.claim_pending_run(finish_first.run_id, started_at=datetime.utcnow()) is True
    registry.record_cleanup_completed(finish_first.run_id, completed_at=datetime.utcnow())
    registry.set_summary(finish_first.run_id, {"total_score": 0.0})
    assert (
        registry.finalize_success_after_cleanup(
            finish_first.run_id,
            step=0,
            ended_at=datetime.utcnow(),
        )
        == "completed"
    )
    assert registry.request_stop(finish_first.run_id) is False


def test_restart_preserves_stop_only_after_cleanup_completed(tmp_path) -> None:
    from datetime import datetime

    from fort_gym.bench.run.storage import RunRegistry

    stopped_db = tmp_path / "stopped.sqlite3"
    stopped_registry = RunRegistry(db_path=stopped_db)
    stopped = stopped_registry.create(backend="dfhack", model="fake", max_steps=1, ticks_per_step=1)
    assert stopped_registry.claim_pending_run(stopped.run_id, started_at=datetime.utcnow())
    assert stopped_registry.request_stop(stopped.run_id)
    stopped_registry.record_cleanup_completed(stopped.run_id, completed_at=datetime.utcnow())
    stopped_registry.set_summary(stopped.run_id, {"total_score": 0.0})

    recovered_stopped = RunRegistry(db_path=stopped_db).get(stopped.run_id)
    assert recovered_stopped is not None
    assert recovered_stopped.status == "stopped"

    interrupted_db = tmp_path / "interrupted.sqlite3"
    interrupted_registry = RunRegistry(db_path=interrupted_db)
    interrupted = interrupted_registry.create(
        backend="dfhack", model="fake", max_steps=1, ticks_per_step=1
    )
    assert interrupted_registry.claim_pending_run(interrupted.run_id, started_at=datetime.utcnow())
    assert interrupted_registry.request_stop(interrupted.run_id)

    recovered_interrupted = RunRegistry(db_path=interrupted_db).get(interrupted.run_id)
    assert recovered_interrupted is not None
    assert recovered_interrupted.status == "failed"

    missing_summary_db = tmp_path / "missing-summary.sqlite3"
    missing_summary_registry = RunRegistry(db_path=missing_summary_db)
    missing_summary = missing_summary_registry.create(
        backend="dfhack", model="fake", max_steps=1, ticks_per_step=1
    )
    assert missing_summary_registry.claim_pending_run(
        missing_summary.run_id, started_at=datetime.utcnow()
    )
    assert missing_summary_registry.request_stop(missing_summary.run_id)
    missing_summary_registry.record_cleanup_completed(
        missing_summary.run_id, completed_at=datetime.utcnow()
    )

    recovered_missing_summary = RunRegistry(db_path=missing_summary_db).get(missing_summary.run_id)
    assert recovered_missing_summary is not None
    assert recovered_missing_summary.status == "failed"


def test_stop_endpoint_defers_terminal_status_to_worker(monkeypatch) -> None:
    from datetime import datetime

    from fastapi.testclient import TestClient

    from fort_gym.bench.api import server

    monkeypatch.setenv("FORT_GYM_INSECURE_ADMIN", "1")
    server.RUN_REGISTRY.reset_for_tests()
    try:
        created = server.RUN_REGISTRY.create(
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=10,
            ticks_per_step=1000,
        )
        assert (
            server.RUN_REGISTRY.claim_pending_run(
                created.run_id,
                started_at=datetime.utcnow(),
            )
            is True
        )

        response = TestClient(server.app).post(f"/runs/{created.run_id}/stop")

        assert response.status_code == 200
        assert response.json() == {
            "status": "stop_requested",
            "run_id": created.run_id,
        }
        loaded = server.RUN_REGISTRY.get(created.run_id)
        assert loaded is not None
        assert loaded.status == "running"
        assert server.RUN_REGISTRY.stop_requested(created.run_id) is True

        server.RUN_REGISTRY.set_status(created.run_id, status="completed")
        terminal_response = TestClient(server.app).post(f"/runs/{created.run_id}/stop")
        assert terminal_response.status_code == 200
        assert terminal_response.json() == {
            "status": "completed",
            "run_id": created.run_id,
        }
    finally:
        server.RUN_REGISTRY.reset_for_tests()


def test_run_registry_terminal_statuses_are_monotonic(tmp_path) -> None:
    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    for terminal_status in ("stopped", "failed", "completed"):
        created = registry.create(
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
        )
        registry.set_status(created.run_id, status=terminal_status)
        registry.set_status(created.run_id, status="running", step=1)
        registry.set_status(created.run_id, status="paused")
        registry.set_status(created.run_id, status="completed", step=2)
        registry.set_status(created.run_id, status="failed")
        registry.set_status(created.run_id, status="stopped")

        loaded = registry.get(created.run_id)
        assert loaded is not None
        assert loaded.status == terminal_status
        assert loaded.step == 2


def test_run_registry_pending_claim_is_atomic(tmp_path) -> None:
    from datetime import datetime

    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(backend="mock", model="fake", max_steps=2, ticks_per_step=10)

    assert registry.claim_pending_run(created.run_id, started_at=datetime.utcnow()) is True
    assert registry.claim_pending_run(created.run_id, started_at=datetime.utcnow()) is False

    loaded = registry.get(created.run_id)
    assert loaded is not None
    assert loaded.status == "running"


def test_late_terminal_failure_cannot_relabel_or_annotate_stopped_run(tmp_path) -> None:
    from datetime import datetime

    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(backend="mock", model="fake", max_steps=2, ticks_per_step=10)
    registry.set_status(created.run_id, status="stopped", step=1, ended_at=datetime.utcnow())

    registry.record_terminal_failure(
        created.run_id,
        terminal_reason={"code": "late_tick_failure"},
        step=2,
        ended_at=datetime.utcnow(),
    )

    loaded = registry.get(created.run_id)
    assert loaded is not None
    assert loaded.status == "stopped"
    assert loaded.step == 1
    assert "terminal_reason" not in loaded.metadata


def test_pending_terminal_reason_survives_interrupted_worker_recovery(tmp_path) -> None:
    from datetime import datetime

    from fort_gym.bench.run.storage import RunRegistry

    db_path = tmp_path / "runs.sqlite3"
    registry = RunRegistry(db_path=db_path)
    created = registry.create(backend="dfhack", model="fake", max_steps=2, ticks_per_step=10)
    assert registry.claim_pending_run(created.run_id, started_at=datetime.utcnow()) is True
    reason = {"code": "tick_timeout_zero_progress", "ticks_advanced": 0}

    registry.record_pending_terminal_failure(
        created.run_id,
        terminal_reason=reason,
        step=1,
    )

    staged = registry.get(created.run_id)
    assert staged is not None
    assert staged.status == "running"
    assert staged.step == 1
    assert staged.metadata["terminal_reason"] == reason

    recovered = RunRegistry(db_path=db_path).get(created.run_id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.step == 1
    assert recovered.metadata["terminal_reason"] == reason


def _make_scored_run(registry, *, model, seed_save, score_version, total_score, survival_score=1.0):
    """Register a run + share + summary with a given score_version/seed_save.

    ``score_version=None`` simulates a pre-v2-era run whose summary.json never
    recorded the field at all.
    """

    run = registry.create(
        backend="dfhack",
        model=model,
        max_steps=10,
        ticks_per_step=100,
        seed_save=seed_save,
    )
    share = registry.create_share(run.run_id, scope=["live"])
    summary = {"total_score": total_score, "survival_score": survival_score}
    if score_version is not None:
        summary["score_version"] = score_version
    registry.set_summary(run.run_id, summary)
    return run.run_id, share.token


def test_public_leaderboard_never_mixes_score_versions_or_seeds(tmp_path) -> None:
    """WDSLL: scores are comparable only on the same seed and score_version.

    Regression test for the display-truth bug where /public/leaderboard
    averaged score-v2 (seed_region1_fresh) and score-v3 (seed_region3_fresh)
    runs into a single mean_score for the model.
    """

    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")

    # score-v3 · region3 runs.
    for score in (60.0, 80.0):
        _make_scored_run(
            registry,
            model="glm-5v",
            seed_save="seed_region3_fresh",
            score_version=3,
            total_score=score,
        )

    # score-v2 · region1 runs -- an incompatible era AND seed for the same model.
    for score in (400.0, 420.0):
        _make_scored_run(
            registry,
            model="glm-5v",
            seed_save="seed_region1_fresh",
            score_version=2,
            total_score=score,
        )

    # pre-v2-era run: summary.json never recorded score_version at all.
    pre_v2_run_id, pre_v2_token = _make_scored_run(
        registry,
        model="glm-5v",
        seed_save="seed_region1_fresh",
        score_version=None,
        total_score=10.0,
    )

    leaderboard = registry.public_leaderboard()

    # Every row is scoped to one (model, score_version, seed_save) bucket --
    # rows never mix score_versions or seeds.
    keys = [(row["model"], row["score_version"], row["seed_save"]) for row in leaderboard]
    assert len(keys) == len(set(keys))
    assert len(leaderboard) == 3

    by_key = {(row["score_version"], row["seed_save"]): row for row in leaderboard}

    v3 = by_key[(3, "seed_region3_fresh")]
    assert v3["runs"] == 2
    assert v3["mean_score"] == 70.0
    assert v3["best_score"] == 80.0
    # The historical bug averaged all 8 GLM-5V runs (mixed eras/seeds) into
    # mean_score 215.4 -- that number must never reappear for a segmented row.
    assert v3["mean_score"] != 215.4

    v2 = by_key[(2, "seed_region1_fresh")]
    assert v2["runs"] == 2
    assert v2["mean_score"] == 410.0
    assert v2["best_score"] == 420.0

    # Missing score_version (pre-v2 era) groups under version 1.
    v1 = by_key[(1, "seed_region1_fresh")]
    assert v1["runs"] == 1
    assert v1["mean_score"] == 10.0
    assert v1["best_token"] == pre_v2_token

    # Sorted by score_version desc, then mean_score desc.
    assert [row["score_version"] for row in leaderboard] == [3, 2, 1]


def test_public_leaderboard_sorts_by_mean_score_within_same_version(tmp_path) -> None:
    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")

    _make_scored_run(
        registry, model="glm-5v", seed_save="seed_region3_fresh", score_version=3, total_score=70.0
    )
    _make_scored_run(
        registry,
        model="gpt-5.5-vision",
        seed_save="seed_region3_fresh",
        score_version=3,
        total_score=90.0,
    )

    leaderboard = registry.public_leaderboard()

    assert [row["model"] for row in leaderboard] == ["gpt-5.5-vision", "glm-5v"]


def test_best_scores_over_time_never_mixes_score_versions_or_seeds(tmp_path) -> None:
    """Same comparability rule applies to the best-over-time series."""

    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")

    _make_scored_run(
        registry, model="glm-5v", seed_save="seed_region3_fresh", score_version=3, total_score=80.0
    )
    _make_scored_run(
        registry, model="glm-5v", seed_save="seed_region1_fresh", score_version=2, total_score=420.0
    )

    # Mark both runs ended so best_scores_over_time's WHERE clause picks them up.
    conn = registry._ensure_conn()  # noqa: SLF001 - test-only introspection
    conn.execute("UPDATE runs SET ended_at = created_at")
    conn.commit()

    series = registry.best_scores_over_time(days=3650)

    assert len(series) == 2
    keys = [(item["score_version"], item["seed_save"]) for item in series]
    assert (3, "seed_region3_fresh") in keys
    assert (2, "seed_region1_fresh") in keys
    for item in series:
        assert len(item["points"]) == 1
