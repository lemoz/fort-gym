from __future__ import annotations


def test_public_routes_exist() -> None:
    from fort_gym.bench.api.server import app

    paths = {route.path for route in app.routes}
    assert "/public/runs" in paths
    assert "/public/leaderboard" in paths
    assert "/public/runs/{token}" in paths
    assert "/public/runs/{token}/events/stream" in paths
    assert "/public/runs/{token}/events/replay" in paths
