"""Separate batches must not concurrently drive one shared DFHack game."""

import threading
import time

import pytest

from fort_gym.bench.run.jobs import JobRegistry


def wait_finished(registry, *jobs):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        states = [registry.get(job.job_id) for job in jobs]
        if all(state.status in {"completed", "failed"} for state in states):
            return states
        time.sleep(0.01)
    raise AssertionError("Mocked batch workers did not finish")


def test_distinct_dfhack_batches_do_not_overlap_shared_game():
    registry = JobRegistry()
    first = registry.create("model-a", "dfhack", n=1, parallelism=1)
    second = registry.create("model-b", "dfhack", n=1, parallelism=1)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def run_first():
        first_entered.set()
        assert release.wait(5)
        return "first-native-run"

    def run_second():
        second_entered.set()
        return "second-native-run"

    registry.start(first.job_id, run_first)
    try:
        assert first_entered.wait(5)
        registry.start(second.job_id, run_second)
        assert not second_entered.wait(0.2), "Separate batches entered the same game concurrently"
    finally:
        release.set()
        wait_finished(registry, first, second)
    assert second_entered.is_set()
    assert registry.get(first.job_id).run_ids == ["first-native-run"]
    assert registry.get(second.job_id).run_ids == ["second-native-run"]


@pytest.mark.parametrize("failure", ["exception", "missing_run_id"])
def test_failed_native_run_releases_waiting_batch(failure):
    registry = JobRegistry()
    first = registry.create("model-a", "dfhack", n=3, parallelism=3)
    second = registry.create("model-b", "dfhack", n=2, parallelism=2)
    first_entered = threading.Event()
    release = threading.Event()
    calls = []

    def run_first():
        calls.append("failed-run")
        first_entered.set()
        assert release.wait(5)
        if failure == "exception":
            raise RuntimeError("Simulated native failure")
        return None

    def run_second():
        run_id = f"successful-run-{len(calls)}"
        calls.append(run_id)
        return run_id

    registry.start(first.job_id, run_first)
    try:
        assert first_entered.wait(5)
        registry.start(second.job_id, run_second)
    finally:
        release.set()
    failed, completed = wait_finished(registry, first, second)
    assert failed.status == "failed"
    assert failed.run_ids == []
    assert failed.finished_at is not None
    assert completed.status == "completed"
    assert completed.run_ids == ["successful-run-1", "successful-run-2"]
    assert completed.finished_at is not None
    assert calls.count("failed-run") == 1


def test_mock_workers_and_polling_progress_with_native_running_and_queued():
    registry = JobRegistry()
    first = registry.create("model-a", "dfhack", n=1, parallelism=1)
    second = registry.create("model-b", "dfhack", n=1, parallelism=1)
    mock = registry.create("random", "mock", n=2, parallelism=2)
    native_entered = threading.Event()
    second_entered = threading.Event()
    mock_workers = threading.Barrier(3)
    release = threading.Event()

    def run_first():
        native_entered.set()
        assert release.wait(5)
        return "native-first"

    def run_second():
        second_entered.set()
        return "native-second"

    def run_mock():
        index = mock_workers.wait(timeout=5)
        return f"mock-{index}"

    registry.start(first.job_id, run_first)
    try:
        assert native_entered.wait(5)
        registry.start(second.job_id, run_second)
        registry.start(mock.job_id, run_mock)
        mock_workers.wait(timeout=5)
        completed_mock, = wait_finished(registry, mock)
        assert completed_mock.status == "completed"
        assert len(set(completed_mock.run_ids)) == 2
        assert not second_entered.is_set()
        assert registry.get(first.job_id).status == "running"
        assert registry.get(second.job_id).status == "running"
        assert len(registry.list()) == 3
    finally:
        release.set()
    first_result, second_result = wait_finished(registry, first, second)
    assert first_result.status == second_result.status == "completed"


def test_native_batches_complete_all_runs_without_overlap_or_duplicate_starts():
    registry = JobRegistry()
    jobs = [registry.create(model, "dfhack", n=3, parallelism=4) for model in ("a", "b")]
    tracker_lock = threading.Lock()
    active = 0
    maximum_active = 0
    call_ids = []

    def run_native():
        nonlocal active, maximum_active
        with tracker_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            run_id = f"native-{len(call_ids)}"
            call_ids.append(run_id)
        time.sleep(0.01)
        with tracker_lock:
            active -= 1
        return run_id

    for job in jobs:
        registry.start(job.job_id, run_native)
        registry.start(job.job_id, run_native)
    results = wait_finished(registry, *jobs)
    assert maximum_active == 1
    assert len(call_ids) == 6
    assert all(result.status == "completed" for result in results)
    assert all(result.parallelism == 1 for result in results)
    assert all(len(result.run_ids) == 3 for result in results)
    assert all(result.finished_at is not None for result in results)
    assert sorted(run_id for result in results for run_id in result.run_ids) == sorted(call_ids)
    for job in jobs:
        registry.start(job.job_id, run_native)
    assert len(call_ids) == 6
