from __future__ import annotations

import threading
import time
from collections import Counter

import pytest
from pydantic import ValidationError

from fort_gym.bench.run import jobs as jobs_module
from fort_gym.bench.run.jobs import JobInfo, JobRegistry


def _wait_for_status(
    registry: JobRegistry,
    job_id: str,
    status: str,
    *,
    timeout: float = 2.0,
) -> JobInfo:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = registry.get(job_id)
        if info is not None and info.status == status:
            return info
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach {status}")


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


def test_job_registry_serializes_dfhack_jobs() -> None:
    registry = JobRegistry()

    # dfhack drives the single live DF instance: requested parallelism must
    # clamp to 1 so concurrent workers cannot race the same save.
    dfhack_job = registry.create(model="random", backend="dfhack", n=3, parallelism=4)
    assert dfhack_job.parallelism == 1
    assert dfhack_job.isolation_supervised is False

    mock_job = registry.create(model="random", backend="mock", n=3, parallelism=4)
    assert mock_job.parallelism == 4
    assert mock_job.isolation_supervised is False


def test_supervised_dfhack_honors_bounded_parallelism() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="random",
        backend="dfhack",
        n=3,
        parallelism=8,
        isolation_supervised=True,
    )
    lock = threading.Lock()
    all_started = threading.Event()
    release = threading.Event()
    calls = 0
    running = 0
    max_running = 0

    def make_run() -> str:
        nonlocal calls, max_running, running
        with lock:
            index = calls
            calls += 1
            running += 1
            max_running = max(max_running, running)
            if calls == job.n:
                all_started.set()
        release.wait(2.0)
        with lock:
            running -= 1
        return f"run-{index}"

    assert job.parallelism == job.n
    assert job.isolation_supervised is True
    with pytest.raises(ValidationError):
        job.isolation_supervised = False

    registry.start(job.job_id, make_run)
    assert all_started.wait(1.0)
    assert calls == job.n
    assert max_running == job.n
    release.set()

    completed = _wait_for_status(registry, job.job_id, "completed")
    assert len(completed.run_ids) == job.n


def test_truthy_non_boolean_isolation_marker_fails_closed() -> None:
    registry = JobRegistry()

    job = registry.create(
        model="random",
        backend="dfhack",
        n=3,
        parallelism=3,
        isolation_supervised=1,  # type: ignore[arg-type]
    )

    assert job.isolation_supervised is False
    assert job.parallelism == 1


def test_completion_accounting_launches_exactly_n_runs() -> None:
    registry = JobRegistry()
    job = registry.create(model="random", backend="mock", n=7, parallelism=3)
    lock = threading.Lock()
    calls = 0

    def make_run() -> str:
        nonlocal calls
        with lock:
            index = calls
            calls += 1
        return f"run-{index}"

    registry.start(job.job_id, make_run)
    completed = _wait_for_status(registry, job.job_id, "completed")

    assert calls == job.n
    assert len(completed.run_ids) == job.n
    assert len(set(completed.run_ids)) == job.n
    registry.start(job.job_id, make_run)
    assert calls == job.n


def test_failure_accounting_does_not_replenish_failed_job() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="random",
        backend="dfhack",
        n=5,
        parallelism=2,
        isolation_supervised=True,
    )
    lock = threading.Lock()
    both_started = threading.Event()
    release_success = threading.Event()
    calls = 0

    def make_run() -> str:
        nonlocal calls
        with lock:
            index = calls
            calls += 1
            if calls == 2:
                both_started.set()
        if index == 0:
            both_started.wait(2.0)
            raise RuntimeError("synthetic failure")
        release_success.wait(2.0)
        return f"run-{index}"

    registry.start(job.job_id, make_run)
    assert both_started.wait(1.0)
    failed = _wait_for_status(registry, job.job_id, "failed")
    assert failed.finished_at is not None
    assert calls == 2

    release_success.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        failed = registry.get(job.job_id)
        if failed is not None and failed.run_ids == ["run-1"]:
            break
        time.sleep(0.005)

    assert failed is not None
    assert failed.status == "failed"
    assert failed.run_ids == ["run-1"]
    assert calls == 2
    registry.start(job.job_id, make_run)
    assert calls == 2


def test_reserved_supervised_cohort_exposes_ids_and_attempts_every_slot() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=5,
        parallelism=2,
        isolation_supervised=True,
    )
    run_ids = tuple(f"reserved-{index}" for index in range(job.n))
    lock = threading.Lock()
    called: list[str] = []

    def execute_run(run_id: str) -> str:
        with lock:
            called.append(run_id)
        return "failed" if run_id == "reserved-1" else "completed"

    registry.start_reserved(job.job_id, run_ids, execute_run)

    started = registry.get(job.job_id)
    assert started is not None
    assert started.run_ids == list(run_ids)
    failed = _wait_for_status(registry, job.job_id, "failed")
    assert failed.finished_at is not None
    assert failed.run_ids == list(run_ids)
    assert set(called) == set(run_ids)
    assert len(called) == job.n


def test_reserved_failure_replenishes_every_slot_and_defers_terminal_status() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=6,
        parallelism=2,
        isolation_supervised=True,
    )
    run_ids = tuple(f"cohort-{index}" for index in range(job.n))
    lock = threading.Lock()
    initial_started = threading.Event()
    release_failure = threading.Event()
    replacement_started = threading.Event()
    release_remaining = threading.Event()
    called: list[str] = []
    cohort_views: list[tuple[list[str], str]] = []
    running = 0
    max_running = 0

    def execute_run(run_id: str) -> str:
        nonlocal max_running, running
        visible = registry.get(job.job_id)
        assert visible is not None
        with lock:
            cohort_views.append((visible.run_ids, visible.status))
            called.append(run_id)
            running += 1
            max_running = max(max_running, running)
            if len(called) == job.parallelism:
                initial_started.set()

        if run_id == run_ids[0]:
            assert initial_started.wait(1.0)
            assert release_failure.wait(1.0)
            outcome = "failed"
        else:
            if run_id == run_ids[2]:
                replacement_started.set()
            assert release_remaining.wait(2.0)
            outcome = "completed"

        with lock:
            running -= 1
        return outcome

    registry.start_reserved(job.job_id, run_ids, execute_run)

    assert initial_started.wait(1.0)
    initial = registry.get(job.job_id)
    assert initial is not None
    assert initial.run_ids == list(run_ids)
    assert initial.status == "running"
    assert initial.finished_at is None

    release_failure.set()
    assert replacement_started.wait(1.0)
    after_failure = registry.get(job.job_id)
    assert after_failure is not None
    assert after_failure.status == "running"
    assert after_failure.finished_at is None
    assert set(called) == set(run_ids[:3])

    release_remaining.set()
    terminal = _wait_for_status(registry, job.job_id, "failed")

    assert terminal.finished_at is not None
    assert terminal.run_ids == list(run_ids)
    assert Counter(called) == Counter(run_ids)
    assert max_running == job.parallelism
    assert cohort_views == [(list(run_ids), "running")] * job.n
    assert registry._state[job.job_id] == {
        "started": job.n,
        "completed": job.n,
        "failed": 1,
    }


def test_reserved_duplicate_and_restart_calls_cannot_replace_active_cohort() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=2,
        parallelism=1,
        isolation_supervised=True,
    )
    run_ids = ("original-0", "original-1")
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    called: list[str] = []
    replacement_calls: list[str] = []

    def execute_run(run_id: str) -> str:
        with lock:
            called.append(run_id)
        entered.set()
        assert release.wait(2.0)
        return "completed"

    registry.start_reserved(job.job_id, run_ids, execute_run)
    assert entered.wait(1.0)

    with pytest.raises(ValueError, match="must be pending"):
        registry.start_reserved(
            job.job_id,
            ("replacement-0", "replacement-1"),
            lambda run_id: replacement_calls.append(run_id) or "completed",
        )
    active = registry.get(job.job_id)
    assert active is not None
    assert active.run_ids == list(run_ids)
    assert active.status == "running"

    release.set()
    terminal = _wait_for_status(registry, job.job_id, "completed")
    assert terminal.run_ids == list(run_ids)
    assert Counter(called) == Counter(run_ids)
    assert replacement_calls == []

    with pytest.raises(ValueError, match="must be pending"):
        registry.start_reserved(job.job_id, run_ids, execute_run)
    assert Counter(called) == Counter(run_ids)


def test_reserved_thread_start_failure_is_accounted_without_stranding_slots(
    monkeypatch,
) -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=4,
        parallelism=2,
        isolation_supervised=True,
    )
    run_ids = tuple(f"launch-{index}" for index in range(job.n))
    real_thread = threading.Thread
    lock = threading.Lock()
    launches = 0
    executed: list[str] = []
    launch_failures: list[tuple[str, str]] = []

    class RefusingThread:
        def start(self) -> None:
            raise RuntimeError("synthetic thread-start failure")

    def controlled_thread(*args, **kwargs):
        nonlocal launches
        with lock:
            index = launches
            launches += 1
        if index == 0:
            return RefusingThread()
        return real_thread(*args, **kwargs)

    def execute_run(run_id: str) -> str:
        with lock:
            executed.append(run_id)
        return "completed"

    monkeypatch.setattr(jobs_module.threading, "Thread", controlled_thread)
    registry.start_reserved(
        job.job_id,
        run_ids,
        execute_run,
        on_launch_failure=lambda run_id, exc: launch_failures.append(
            (run_id, str(exc))
        ),
    )
    terminal = _wait_for_status(registry, job.job_id, "failed")

    assert terminal.run_ids == list(run_ids)
    assert launches == job.n
    assert Counter(executed) == Counter(run_ids[1:])
    assert launch_failures == [
        (run_ids[0], "synthetic thread-start failure"),
    ]
    assert registry._state[job.job_id] == {
        "started": job.n,
        "completed": job.n,
        "failed": 1,
    }


def test_reserved_cohort_requires_exact_supervised_pending_authority() -> None:
    registry = JobRegistry()
    legacy = registry.create(model="random", backend="mock", n=2, parallelism=2)
    with pytest.raises(ValueError, match="supervised isolation"):
        registry.start_reserved(legacy.job_id, ("a", "b"), lambda _run_id: "completed")

    supervised = registry.create(
        model="random",
        backend="mock",
        n=2,
        parallelism=2,
        isolation_supervised=True,
    )
    with pytest.raises(ValueError, match="unique and exactly match"):
        registry.start_reserved(
            supervised.job_id,
            ("duplicate", "duplicate"),
            lambda _run_id: "completed",
        )


def test_activation_failure_terminalizes_job_with_typed_reason() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="random",
        backend="mock",
        n=2,
        parallelism=2,
        isolation_supervised=True,
    )

    failed = registry.fail_activation(job.job_id)

    assert failed.status == "failed"
    assert failed.failure_reason == "activation_failed"
    assert failed.finished_at is not None
    persisted = registry.get(job.job_id)
    assert persisted is not None
    assert persisted.status == "failed"
    with pytest.raises(ValueError, match="unsupported"):
        registry.fail_activation(job.job_id, reason="free-form-secret")


def test_reserved_execution_failure_invokes_compensation_and_finishes_job() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="random",
        backend="mock",
        n=2,
        parallelism=2,
        isolation_supervised=True,
    )
    failures: list[tuple[str, str]] = []
    executed: list[str] = []

    def execute(run_id: str) -> str:
        executed.append(run_id)
        if run_id == "run-a":
            raise RuntimeError("synthetic pre-manager failure")
        return "completed"

    registry.start_reserved(
        job.job_id,
        ("run-a", "run-b"),
        execute,
        on_execution_failure=lambda run_id, exc: failures.append((run_id, str(exc))),
    )

    terminal = _wait_for_status(registry, job.job_id, "failed")
    assert terminal.run_ids == ["run-a", "run-b"]
    assert Counter(executed) == Counter(("run-a", "run-b"))
    assert failures == [("run-a", "synthetic pre-manager failure")]


def test_compensation_callback_error_cannot_strand_job_accounting() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="random",
        backend="mock",
        n=1,
        parallelism=1,
        isolation_supervised=True,
    )

    def fail_execution(_run_id: str) -> str:
        raise RuntimeError("worker failed")

    def fail_compensation(_run_id: str, _exc: BaseException) -> None:
        raise OSError("evidence disk unavailable")

    registry.start_reserved(
        job.job_id,
        ("run-a",),
        fail_execution,
        on_execution_failure=fail_compensation,
    )

    terminal = _wait_for_status(registry, job.job_id, "failed")
    assert terminal.run_ids == ["run-a"]
    assert registry._state[job.job_id]["completed"] == 1


def test_reserved_eight_run_cohort_releases_one_start_barrier() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=8,
        parallelism=8,
        isolation_supervised=True,
    )
    run_ids = tuple(f"barrier-{index}" for index in range(job.n))
    lock = threading.Lock()
    all_entered = threading.Event()
    release = threading.Event()
    entered: list[str] = []
    observed_states: list[str] = []

    def execute(run_id: str) -> str:
        visible = registry.get(job.job_id)
        assert visible is not None
        with lock:
            observed_states.append(visible.barrier_state)
            entered.append(run_id)
            if len(entered) == job.n:
                all_entered.set()
        assert release.wait(2.0)
        return "completed"

    registry.start_reserved(
        job.job_id,
        run_ids,
        execute,
        start_barrier=True,
    )

    assert all_entered.wait(1.0)
    active = registry.get(job.job_id)
    assert active is not None
    assert active.start_barrier is True
    assert active.barrier_state == "released"
    assert active.barrier_released_at is not None
    assert Counter(entered) == Counter(run_ids)
    assert observed_states == ["released"] * job.n

    release.set()
    completed = _wait_for_status(registry, job.job_id, "completed")
    assert completed.failure_reason is None


def test_reserved_start_barrier_requires_full_cohort_parallelism() -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=3,
        parallelism=2,
        isolation_supervised=True,
    )

    with pytest.raises(ValueError, match="parallelism=n"):
        registry.start_reserved(
            job.job_id,
            ("barrier-a", "barrier-b", "barrier-c"),
            lambda _run_id: "completed",
            start_barrier=True,
        )

    unchanged = registry.get(job.job_id)
    assert unchanged is not None
    assert unchanged.status == "pending"
    assert unchanged.run_ids == []
    assert unchanged.barrier_state == "not_required"


def test_reserved_start_failure_breaks_barrier_without_executing_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = JobRegistry()
    job = registry.create(
        model="dfhack-governed-scripted",
        backend="dfhack",
        n=3,
        parallelism=3,
        isolation_supervised=True,
    )
    run_ids = ("barrier-a", "barrier-b", "barrier-c")
    real_thread = threading.Thread
    constructed = 0
    launch_failures: list[str] = []
    barrier_failures: list[str] = []
    executed: list[str] = []

    class RefusingThread:
        def start(self) -> None:
            raise RuntimeError("synthetic cohort thread refusal")

    def controlled_thread(*args, **kwargs):
        nonlocal constructed
        index = constructed
        constructed += 1
        if index == 0:
            return RefusingThread()
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(jobs_module.threading, "Thread", controlled_thread)
    registry.start_reserved(
        job.job_id,
        run_ids,
        lambda run_id: executed.append(run_id) or "completed",
        on_launch_failure=lambda run_id, _exc: launch_failures.append(run_id),
        on_barrier_failure=lambda run_id, _exc: barrier_failures.append(run_id),
        start_barrier=True,
    )

    failed = _wait_for_status(registry, job.job_id, "failed")
    assert failed.barrier_state == "broken"
    assert failed.failure_reason == "cohort_start_barrier_failed"
    assert launch_failures == [run_ids[0]]
    assert Counter(barrier_failures) == Counter(run_ids[1:])
    assert executed == []
    assert registry._state[job.job_id] == {
        "started": job.n,
        "completed": job.n,
        "failed": job.n,
    }
