from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_public_routes_exist() -> None:
    from fort_gym.bench.api.server import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/r/{token}" in paths
    assert "/replay/{token}" in paths
    assert "/public/runs" in paths
    assert "/public/leaderboard" in paths
    assert "/public/runs/{token}" in paths
    assert "/public/runs/{token}/events/stream" in paths
    assert "/public/runs/{token}/events/replay" in paths


def test_public_html_entrypoints_are_not_cached() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)

    for path in ("/", "/r/example-token", "/replay/example-token", "/leaderboard"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert response.headers["Pragma"] == "no-cache"


def test_public_screenshot_recovers_stale_dfhack_client(monkeypatch) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    class BrokenScreenshotClient:
        closed = False

        def get_screen(self):
            raise BrokenPipeError(32, "Broken pipe")

        def close(self) -> None:
            self.closed = True

    class WorkingScreenshotClient:
        def get_screen(self):
            return {"width": 1, "height": 1, "tiles": [[46, 7, 0]]}

    RUN_REGISTRY.reset_for_tests()
    server._screenshot_client = None
    try:
        run_id = uuid.uuid4().hex
        RUN_REGISTRY.create(
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
            run_id=run_id,
        )
        share = RUN_REGISTRY.create_share(run_id, scope=["live"])

        broken = BrokenScreenshotClient()
        working = WorkingScreenshotClient()
        clients = [broken, working]

        def get_screenshot_client():
            return clients.pop(0)

        server._screenshot_client = broken
        monkeypatch.setattr(server, "_get_screenshot_client", get_screenshot_client)

        client = TestClient(server.app)
        response = client.get(f"/public/runs/{share.token}/screenshot")

        assert response.status_code == 200
        assert response.json() == {"width": 1, "height": 1, "tiles": [[46, 7, 0]]}
        assert broken.closed is True
    finally:
        server._screenshot_client = None
        RUN_REGISTRY.reset_for_tests()
