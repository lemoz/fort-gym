from __future__ import annotations


def test_routes_import() -> None:
    from fort_gym.bench.api.server import app

    paths = sorted(route.path for route in app.routes)
    assert "/runs" in "".join(paths)
