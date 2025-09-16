"""Batch job orchestration utilities."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class JobInfo(BaseModel):
    job_id: str
    model: str
    backend: str
    n: int
    parallelism: int
    run_ids: List[str] = Field(default_factory=list)
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class JobRegistry:
    """Manage job metadata and run scheduling with a concurrency cap."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobInfo] = {}
        self._state: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    def create(self, model: str, backend: str, n: int, parallelism: int) -> JobInfo:
        job = JobInfo(
            job_id=uuid.uuid4().hex,
            model=model,
            backend=backend,
            n=n,
            parallelism=max(1, parallelism),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._state[job.job_id] = {"started": 0, "completed": 0}
        return job

    def list(self) -> List[JobInfo]:
        with self._lock:
            return [job.copy(deep=True) for job in self._jobs.values()]

    def get(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.copy(deep=True) if job else None

    def start(self, job_id: str, make_run: Callable[[], str]) -> None:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            state = self._state[job_id]
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


JOB_REGISTRY = JobRegistry()


__all__ = ["JobInfo", "JobRegistry", "JOB_REGISTRY"]
