"""In-memory registry tracking runs, share tokens, and streaming events."""

from __future__ import annotations

import asyncio
import secrets
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional, Set, Tuple


EventPayload = Dict[str, Any]


@dataclass
class RunInfo:
    """Lightweight record of a single run lifecycle."""

    run_id: str
    backend: str
    model: str
    max_steps: int
    ticks_per_step: int
    status: str = "pending"
    step: int = 0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    queue: Optional[asyncio.Queue[EventPayload]] = field(default=None, repr=False)
    loop: Optional[asyncio.AbstractEventLoop] = field(default=None, repr=False)
    metadata: Dict[str, Any] = field(default_factory=dict, repr=False)
    latest_summary: Optional[Dict[str, Any]] = field(default=None, repr=False)


@dataclass
class ShareToken:
    """Read-only access token for spectator endpoints."""

    token: str
    run_id: str
    scope: Set[str]
    expires_at: Optional[datetime]
    created_at: datetime


class RunRegistry:
    """Thread-safe store for run metadata and SSE queues."""

    def __init__(self) -> None:
        self._runs: Dict[str, RunInfo] = {}
        self._lock = threading.Lock()
        self._shares: Dict[str, ShareToken] = {}
        self._shares_by_run: Dict[str, Set[str]] = {}

    def create(
        self,
        *,
        backend: str,
        model: str,
        max_steps: int,
        ticks_per_step: int,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        run_id: Optional[str] = None,
    ) -> RunInfo:
        """Register a new run and return its record."""

        queue: asyncio.Queue[EventPayload] = asyncio.Queue(maxsize=512)
        identifier = run_id or uuid.uuid4().hex
        record = RunInfo(
            run_id=identifier,
            backend=backend,
            model=model,
            max_steps=max_steps,
            ticks_per_step=ticks_per_step,
            queue=queue,
            loop=loop,
        )

        with self._lock:
            if identifier in self._runs:
                raise ValueError(f"Run '{identifier}' already registered")
            self._runs[identifier] = record
        return record

    def get(self, run_id: str) -> Optional[RunInfo]:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            return replace(record)

    def list(self) -> list[RunInfo]:
        with self._lock:
            return [replace(record) for record in self._runs.values()]

    def set_status(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        step: Optional[int] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return
            if status is not None:
                record.status = status
                if status in {"completed", "failed", "stopped"}:
                    record.metadata["survived"] = status == "completed"
            if step is not None:
                record.step = step
            if started_at is not None:
                record.started_at = started_at
            if ended_at is not None:
                record.ended_at = ended_at

    def get_queue(self, run_id: str) -> Optional[asyncio.Queue[EventPayload]]:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return None
            return record.queue

    def bind_loop(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record:
                record.loop = loop

    def append_event(self, run_id: str, event: EventPayload) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if not record or not record.queue:
                return

            event_type = event.get("t", "message")
            data = event.get("data", {})
            record.metadata["last_event_at"] = datetime.utcnow()
            if event_type == "state":
                record.metadata["last_state"] = data.get("state")
            if event_type == "score":
                score_value = data.get("score")
                if score_value is None:
                    score_value = data.get("value")
                if score_value is not None:
                    try:
                        record.metadata["last_score"] = float(score_value)
                    except (TypeError, ValueError):
                        pass
                if "milestones" in data:
                    record.metadata["milestones"] = data["milestones"]

            queue = record.queue
            loop = record.loop

        payload = {
            "t": event.get("t", "message"),
            "data": event.get("data", {}),
        }

        def push() -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                queue.put_nowait(payload)

        if loop and loop.is_running():
            loop.call_soon_threadsafe(push)
        else:
            push()

    # ------------------------------------------------------------------
    # Share token helpers
    # ------------------------------------------------------------------
    def _prune_shares_locked(self) -> None:
        now = datetime.utcnow()
        expired = [token for token, share in self._shares.items() if share.expires_at and share.expires_at < now]
        for token in expired:
            share = self._shares.pop(token)
            run_tokens = self._shares_by_run.get(share.run_id)
            if run_tokens:
                run_tokens.discard(token)
                if not run_tokens:
                    self._shares_by_run.pop(share.run_id, None)

    def create_share(
        self,
        run_id: str,
        *,
        scope: Optional[Iterable[str]] = None,
        ttl_seconds: Optional[int] = 86400,
    ) -> ShareToken:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            token = secrets.token_urlsafe(24)
            resolved_scope = {str(item) for item in (scope or {"live", "replay", "export"})}
            expires_at = (
                datetime.utcnow() + timedelta(seconds=int(ttl_seconds))
                if ttl_seconds is not None
                else None
            )
            share = ShareToken(
                token=token,
                run_id=run_id,
                scope=resolved_scope,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
            )
            self._shares[token] = share
            self._shares_by_run.setdefault(run_id, set()).add(token)
            return share

    def get_share(self, token: str) -> Optional[ShareToken]:
        with self._lock:
            self._prune_shares_locked()
            share = self._shares.get(token)
            if not share:
                return None
            return share

    def _select_share(self, tokens: Iterable[str]) -> Optional[ShareToken]:
        preferred: Optional[ShareToken] = None
        fallback: Optional[ShareToken] = None
        for token in tokens:
            share = self._shares.get(token)
            if not share:
                continue
            if "live" in share.scope and preferred is None:
                preferred = share
            if fallback is None:
                fallback = share
        return preferred or fallback

    def list_public(self) -> list[Tuple[RunInfo, ShareToken]]:
        with self._lock:
            self._prune_shares_locked()
            items: list[Tuple[RunInfo, ShareToken]] = []
            for run_id, tokens in self._shares_by_run.items():
                record = self._runs.get(run_id)
                if not record:
                    continue
                share = self._select_share(tokens)
                if not share:
                    continue
                items.append((replace(record), share))
            return items

    def public_leaderboard(self, limit: int = 50) -> list[Dict[str, Any]]:
        with self._lock:
            self._prune_shares_locked()
            run_ids = [rid for rid in self._shares_by_run if rid in self._runs]
            run_ids.sort(key=lambda rid: self._runs[rid].started_at or datetime.min, reverse=True)
            run_ids = run_ids[:limit]

            aggregates: Dict[str, Dict[str, Any]] = {}
            for run_id in run_ids:
                record = self._runs[run_id]
                summary = record.latest_summary
                if not summary:
                    continue
                stats = aggregates.setdefault(
                    record.model,
                    {
                        "model": record.model,
                        "runs": 0,
                        "total_score": 0.0,
                        "survival_total": 0.0,
                    },
                )
                stats["runs"] += 1
                stats["total_score"] += float(summary.get("total_score", 0.0))
                stats["survival_total"] += float(summary.get("survival_score", 0.0))

        leaderboard: list[Dict[str, Any]] = []
        for stats in aggregates.values():
            runs = stats["runs"] or 1
            mean_score = stats["total_score"] / runs
            survival_mean = stats["survival_total"] / runs
            leaderboard.append(
                {
                    "model": stats["model"],
                    "runs": stats["runs"],
                    "mean_score": round(mean_score, 2),
                    "survival_mean": round(survival_mean, 2),
                }
            )

        leaderboard.sort(key=lambda item: item["mean_score"], reverse=True)
        return leaderboard

    def set_summary(self, run_id: str, summary: Dict[str, Any]) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return
            record.latest_summary = summary
            if "total_score" in summary:
                record.metadata["last_score"] = summary["total_score"]
            if "milestones" in summary:
                record.metadata["milestones"] = summary["milestones"]
            if "survival_score" in summary:
                record.metadata["survived"] = summary.get("survival_score", 0) > 0


RUN_REGISTRY = RunRegistry()


__all__ = ["RUN_REGISTRY", "RunInfo", "RunRegistry", "ShareToken"]
