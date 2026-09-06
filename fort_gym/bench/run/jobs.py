"""Batch job orchestration utilities."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class JobInfo(BaseModel):
    job_id: str
    model: str
    backend: str
    n: int
    parallelism: int
    isolation_supervised: bool = Field(default=False, frozen=True)
    run_ids: List[str] = Field(default_factory=list)
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    start_barrier: bool = False
    barrier_state: str = "not_required"
    barrier_released_at: Optional[datetime] = None


class JobRegistry:
    """Manage job metadata and run scheduling with a concurrency cap."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobInfo] = {}
        self._state: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    def create(
        self,
        model: str,
        backend: str,
        n: int,
        parallelism: int,
        *,
        isolation_supervised: bool = False,
    ) -> JobInfo:
        if n < 1:
            raise ValueError("n must be at least 1")
        # A literal True is required to lift the single-instance DFHack clamp;
        # merely truthy configuration values fail closed. The caller providing
        # this marker owns an isolation-capable supervised launcher.
        supervised = isolation_supervised is True
        if backend == "dfhack":
            effective_parallelism = min(n, max(1, parallelism)) if supervised else 1
        else:
            # Preserve legacy mock metadata. Runtime launches remain bounded by
            # min(parallelism, n) in start().
            effective_parallelism = max(1, parallelism)
        job = JobInfo(
            job_id=uuid.uuid4().hex,
            model=model,
            backend=backend,
            n=n,
            parallelism=effective_parallelism,
            isolation_supervised=supervised,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._state[job.job_id] = {"started": 0, "completed": 0}
        return job

    def list(self) -> List[JobInfo]:
        with self._lock:
            return [_copy_job(job) for job in self._jobs.values()]

    def get(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            job = self._jobs.get(job_id)
            return _copy_job(job) if job else None

    def fail_activation(
        self, job_id: str, *, reason: str = "activation_failed"
    ) -> JobInfo:
        """Terminalize a job whose reserved scheduler could not be activated."""

        if reason != "activation_failed":
            raise ValueError("unsupported activation failure reason")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status not in {"completed", "failed"}:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                job.failure_reason = reason
            return _copy_job(job)

    def start(self, job_id: str, make_run: Callable[[], str]) -> None:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            if job.status not in {"pending", "running"}:
                return
            job.status = "running"

        def launch_next() -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                state = self._state.get(job_id)
                if not job or not state or job.status in {"failed", "completed"}:
                    return
                running = state["started"] - state["completed"]
                if state["started"] >= job.n or running >= job.parallelism:
                    return
                state["started"] += 1
                slot_index = state["started"]

            def worker(index: int) -> None:
                run_id: Optional[str] = None
                failed = False
                try:
                    run_id = make_run()
                except Exception:
                    failed = True

                launch_another = False
                with self._lock:
                    job = self._jobs.get(job_id)
                    state = self._state.get(job_id)
                    if not job or not state:
                        return
                    if failed or run_id is None:
                        job.status = "failed"
                        job.finished_at = datetime.utcnow()
                        return
                    job.run_ids.append(run_id)
                    state["completed"] += 1
                    if state["completed"] >= job.n:
                        job.status = "completed"
                        job.finished_at = datetime.utcnow()
                    else:
                        if job.status == "running" and state["started"] < job.n:
                            launch_another = True

                if launch_another:
                    launch_next()

            threading.Thread(
                target=worker,
                args=(slot_index,),
                name=f"job-{job_id}-{slot_index}",
                daemon=True,
            ).start()

        with self._lock:
            initial = min(self._jobs[job_id].parallelism, self._jobs[job_id].n)
        for _ in range(initial):
            launch_next()

    def start_reserved(
        self,
        job_id: str,
        run_ids: Sequence[str],
        execute_run: Callable[[str], str],
        *,
        on_launch_failure: Callable[[str, BaseException], None] | None = None,
        on_execution_failure: Callable[[str, BaseException], None] | None = None,
        on_barrier_failure: Callable[[str, BaseException], None] | None = None,
        start_barrier: bool = False,
    ) -> None:
        """Run an already-reserved supervised cohort without losing failed IDs.

        Every planned run ID is visible before launch and every slot is attempted
        even if a peer fails. The job becomes ``failed`` only after all reserved
        workers return, which keeps the evidence cohort complete.
        """

        reserved = tuple(str(run_id) for run_id in run_ids)
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            if not job.isolation_supervised:
                raise ValueError("reserved cohorts require supervised isolation")
            if job.status != "pending":
                raise ValueError("reserved cohort job must be pending")
            if len(reserved) != job.n or len(set(reserved)) != len(reserved):
                raise ValueError("reserved run IDs must be unique and exactly match n")
            if any(not run_id for run_id in reserved):
                raise ValueError("reserved run IDs must be non-empty")
            barrier_required = start_barrier is True
            if barrier_required and job.parallelism != job.n:
                raise ValueError("cohort start barrier requires parallelism=n")
            job.run_ids = list(reserved)
            job.status = "running"
            job.start_barrier = barrier_required
            job.barrier_state = "pending" if barrier_required else "not_required"
            job.barrier_released_at = None
            self._state[job_id] = {"started": 0, "completed": 0, "failed": 0}
            total = job.n
            parallelism = job.parallelism

        def mark_barrier_released() -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None and job.barrier_state == "pending":
                    job.barrier_state = "released"
                    job.barrier_released_at = datetime.utcnow()

        start_gate = (
            threading.Barrier(total + 1, action=mark_barrier_released)
            if barrier_required
            else None
        )

        def break_barrier() -> None:
            if start_gate is None:
                return
            try:
                start_gate.abort()
            except threading.BrokenBarrierError:
                pass
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None and job.barrier_state == "pending":
                    job.barrier_state = "broken"
                    job.failure_reason = "cohort_start_barrier_failed"

        def complete_attempt(*, failed: bool) -> bool:
            """Account exactly one reserved slot and request one replacement."""

            with self._lock:
                job = self._jobs.get(job_id)
                state = self._state.get(job_id)
                if not job or not state:
                    return False
                state["completed"] += 1
                if failed:
                    state["failed"] += 1
                if state["completed"] == total:
                    job.status = "failed" if state["failed"] else "completed"
                    job.finished_at = datetime.utcnow()
                    return False
                return state["started"] < total

        def launch_next() -> None:
            while True:
                with self._lock:
                    job = self._jobs.get(job_id)
                    state = self._state.get(job_id)
                    if not job or not state or job.status != "running":
                        return
                    running = state["started"] - state["completed"]
                    if state["started"] >= total or running >= parallelism:
                        return
                    index = state["started"]
                    state["started"] += 1
                    run_id = reserved[index]

                def worker(reserved_run_id: str = run_id) -> None:
                    try:
                        if start_gate is not None:
                            start_gate.wait(timeout=10.0)
                        failed = execute_run(reserved_run_id) != "completed"
                    except threading.BrokenBarrierError as exc:
                        failed = True
                        if on_barrier_failure is not None:
                            try:
                                on_barrier_failure(reserved_run_id, exc)
                            except Exception:
                                pass
                    except Exception as exc:
                        failed = True
                        if on_execution_failure is not None:
                            try:
                                on_execution_failure(reserved_run_id, exc)
                            except Exception:
                                # Job accounting must still reach a terminal
                                # result; the caller owns durable compensation.
                                pass
                    if complete_attempt(failed=failed):
                        launch_next()

                try:
                    thread = threading.Thread(
                        target=worker,
                        name=f"job-{job_id}-reserved-{index + 1}",
                        daemon=True,
                    )
                    thread.start()
                except Exception as exc:
                    break_barrier()
                    if on_launch_failure is not None:
                        on_launch_failure(run_id, exc)
                    if complete_attempt(failed=True):
                        continue
                return

        for _ in range(min(parallelism, total)):
            launch_next()
        if start_gate is not None:
            try:
                start_gate.wait(timeout=10.0)
            except threading.BrokenBarrierError:
                break_barrier()


JOB_REGISTRY = JobRegistry()


def _copy_job(job: JobInfo) -> JobInfo:
    if hasattr(job, "model_copy"):
        return job.model_copy(deep=True)
    return job.copy(deep=True)  # pragma: no cover - Pydantic v1 compatibility


__all__ = ["JobInfo", "JobRegistry", "JOB_REGISTRY"]
