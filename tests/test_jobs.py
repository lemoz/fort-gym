from __future__ import annotations

import threading
import time

from fort_gym.bench.run.jobs import JobRegistry


def test_job_registry_parallel_execution() -> None:
    registry = JobRegistry()
    job = registry.create(model="random", backend="mock", n=3, parallelism=2)

    lock = threading.Lock()
    counter = {"value": 0}
    tracker = {"current": 0, "max": 0}

    def make_run() -> str:
        with lock:
            idx = counter["value"]
            counter["value"] += 1
            tracker["current"] += 1
            tracker["max"] = max(tracker["max"], tracker["current"])
        time.sleep(0.05)
        with lock:
            tracker["current"] -= 1
        return f"run-{idx}"

    registry.start(job.job_id, make_run)

    for _ in range(200):
        info = registry.get(job.job_id)
        if info and info.status == "completed":
            break
        time.sleep(0.05)

    info = registry.get(job.job_id)
    assert info is not None
    assert info.status == "completed"
    assert len(info.run_ids) == 3
    assert tracker["max"] <= job.parallelism
