from __future__ import annotations

from fastapi.testclient import TestClient


def test_public_routes_exist() -> None:
    from fort_gym.bench.api.server import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/public/runs" in paths
    assert "/public/leaderboard" in paths
    assert "/public/runs/{token}" in paths
    assert "/public/runs/{token}/events/stream" in paths
    assert "/public/runs/{token}/events/replay" in paths


def test_public_html_entrypoints_are_not_cached() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)

    for path in ("/", "/leaderboard"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert response.headers["Pragma"] == "no-cache"
