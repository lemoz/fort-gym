"""Exercise the shared registry through two independent batch HTTP requests."""

import threading
import time


def test_api_batches_share_native_run_lock(monkeypatch):
    from fastapi.testclient import TestClient

    from fort_gym.bench.api import server
    from fort_gym.bench.run.jobs import JobRegistry

    registry = JobRegistry()
    entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_run(_agent, **kwargs):
        assert kwargs["backend"] == "dfhack"
        calls.append(kwargs["max_steps"])
        if kwargs["max_steps"] == 1:
            entered.set()
            assert release.wait(5)
            return "first-run"
        second_entered.set()
        return "second-run"

    monkeypatch.setenv("FORT_GYM_INSECURE_ADMIN", "1")
    monkeypatch.setattr(server, "JOB_REGISTRY", registry)
    monkeypatch.setattr(server, "_get_agent_factory", lambda _model: object)
    monkeypatch.setattr(server, "run_once", fake_run)
    client = TestClient(server.app)
    payload = {"model": "random", "backend": "dfhack", "n": 1, "parallelism": 4}

    try:
        first = client.post("/jobs", json={**payload, "max_steps": 1})
        assert first.status_code == 200
        assert first.json()["parallelism"] == 1
        assert entered.wait(5)
        second = client.post("/jobs", json={**payload, "max_steps": 2})
        assert second.status_code == 200
        assert second.json()["parallelism"] == 1
        assert not second_entered.wait(0.2)
        pending = client.get(f"/jobs/{second.json()['job_id']}")
        assert pending.status_code == 200
        assert pending.json()["status"] == "running"
        assert pending.json()["run_ids"] == []
        assert len(client.get("/jobs").json()) == 2
    finally:
        release.set()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(job.status == "completed" for job in registry.list()):
            break
        time.sleep(0.01)
    first_result = client.get(f"/jobs/{first.json()['job_id']}").json()
    second_result = client.get(f"/jobs/{second.json()['job_id']}").json()
    assert first_result["status"] == second_result["status"] == "completed"
    assert first_result["run_ids"] == ["first-run"]
    assert second_result["run_ids"] == ["second-run"]
    assert calls == [1, 2]
