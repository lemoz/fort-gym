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
    assert registry.request_stop("missing-run") is False


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
