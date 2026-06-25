from __future__ import annotations


def test_routes_import() -> None:
    from fort_gym.bench.api.server import app

    paths = sorted(route.path for route in app.routes if hasattr(route, "path"))
    assert "/runs" in "".join(paths)


def test_run_create_request_accepts_preserve_save() -> None:
    from fort_gym.bench.api.schemas import RunCreateRequest

    request = RunCreateRequest(
        backend="dfhack",
        model="anthropic-keystroke",
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
        model="anthropic-keystroke",
        max_steps=2,
        ticks_per_step=500,
        preserve_save=True,
    )
    loaded = registry.get(created.run_id)

    assert created.preserve_save is True
    assert loaded is not None
    assert loaded.preserve_save is True
