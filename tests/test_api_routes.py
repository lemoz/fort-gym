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
