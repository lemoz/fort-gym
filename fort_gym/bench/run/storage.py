"""SQLite-backed registry tracking runs, share tokens, and streaming events.

Runs and share tokens persist across API restarts via SQLite. Live SSE events are
still delivered via in-memory asyncio queues and are not replayed from the DB
(replay uses the persisted NDJSON trace file).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from ..config import get_settings


EventPayload = Dict[str, Any]


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


_GIT_SHA_UNSET: object = object()
_GIT_SHA_CACHE: object = _GIT_SHA_UNSET


def _git_sha() -> Optional[str]:
    global _GIT_SHA_CACHE
    if _GIT_SHA_CACHE is not _GIT_SHA_UNSET:
        return _GIT_SHA_CACHE  # type: ignore[return-value]

    env_sha = os.getenv("FORT_GYM_GIT_SHA")
    if env_sha:
        _GIT_SHA_CACHE = env_sha
        return env_sha

    try:
        repo_root = Path(__file__).resolve().parents[3]
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        _GIT_SHA_CACHE = sha
        return sha
    except Exception:
        _GIT_SHA_CACHE = None
        return None


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
    git_sha: Optional[str] = None
    seed_save: Optional[str] = None
    runtime_save: Optional[str] = None
    artifacts_dir: Optional[str] = None
    trace_path: Optional[str] = None
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
    """Thread-safe run registry with SQLite persistence."""

    def __init__(self, *, db_path: Optional[Path] = None) -> None:
        self._db_path_override = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._db_lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self._loops: Dict[str, asyncio.AbstractEventLoop] = {}

    # ------------------------------------------------------------------
    # SQLite wiring
    # ------------------------------------------------------------------
    def _db_path(self) -> Path:
        if self._db_path_override is not None:
            return self._db_path_override
        env_path = os.getenv("FORT_GYM_DB_PATH")
        if env_path:
            return Path(env_path).expanduser()
        artifacts_dir = Path(get_settings().ARTIFACTS_DIR).resolve()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return artifacts_dir / "fort_gym.sqlite3"

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        with self._init_lock:
            if self._conn is not None:
                return self._conn
            path = self._db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                self._ensure_schema(conn)
                self._mark_interrupted_runs(conn)
            self._conn = conn
            return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              backend TEXT NOT NULL,
              model TEXT NOT NULL,
              max_steps INTEGER NOT NULL,
              ticks_per_step INTEGER NOT NULL,
              status TEXT NOT NULL,
              step INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              started_at TEXT,
              ended_at TEXT,
              git_sha TEXT,
              seed_save TEXT,
              runtime_save TEXT,
              artifacts_dir TEXT,
              trace_path TEXT,
              last_score REAL,
              total_score REAL,
              survival_score REAL,
              milestones_json TEXT,
              summary_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shares (
              token TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              scope_json TEXT NOT NULL,
              expires_at TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_model_sha ON runs(model, git_sha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_end ON runs(ended_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_run ON shares(run_id)")

    @staticmethod
    def _mark_interrupted_runs(conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE runs
               SET status = 'failed', ended_at = COALESCE(ended_at, ?)
             WHERE status = 'running' AND ended_at IS NULL
            """,
            (now,),
        )

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
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

        conn = self._ensure_conn()

        identifier = run_id or uuid.uuid4().hex
        queue: asyncio.Queue[EventPayload] = asyncio.Queue(maxsize=512)

        now = datetime.utcnow()
        settings = get_settings()
        artifacts_root = Path(settings.ARTIFACTS_DIR).resolve()
        artifacts_dir = artifacts_root / identifier
        trace_path = artifacts_dir / "trace.jsonl"

        git_sha = _git_sha()
        seed_save = settings.FORT_GYM_SEED_SAVE
        runtime_save = getattr(settings, "FORT_GYM_RUNTIME_SAVE", None)

        with self._db_lock:
            row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (identifier,)).fetchone()
            if row is not None:
                raise ValueError(f"Run '{identifier}' already registered")
            conn.execute(
                """
                INSERT INTO runs (
                  run_id, backend, model, max_steps, ticks_per_step,
                  status, step, created_at, git_sha, seed_save, runtime_save,
                  artifacts_dir, trace_path
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    backend,
                    model,
                    int(max_steps),
                    int(ticks_per_step),
                    now.isoformat(),
                    git_sha,
                    seed_save,
                    runtime_save,
                    str(artifacts_dir),
                    str(trace_path),
                ),
            )
            conn.commit()

            self._queues[identifier] = queue
            if loop is not None:
                self._loops[identifier] = loop

        return RunInfo(
            run_id=identifier,
            backend=backend,
            model=model,
            max_steps=max_steps,
            ticks_per_step=ticks_per_step,
            queue=queue,
            loop=loop,
            git_sha=git_sha,
            seed_save=seed_save,
            runtime_save=runtime_save,
            artifacts_dir=str(artifacts_dir),
            trace_path=str(trace_path),
        )

    def get(self, run_id: str) -> Optional[RunInfo]:
        conn = self._ensure_conn()
        with self._db_lock:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            queue = self._queues.get(run_id)
            loop = self._loops.get(run_id)
        return self._row_to_runinfo(row, queue=queue, loop=loop)

    def list(self) -> list[RunInfo]:
        conn = self._ensure_conn()
        with self._db_lock:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
            queues = dict(self._queues)
            loops = dict(self._loops)
        return [self._row_to_runinfo(row, queue=queues.get(row["run_id"]), loop=loops.get(row["run_id"])) for row in rows]

    def set_status(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        step: Optional[int] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        conn = self._ensure_conn()
        updates: list[str] = []
        params: list[object] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if step is not None:
            updates.append("step = ?")
            params.append(int(step))
        if started_at is not None:
            updates.append("started_at = ?")
            params.append(_dt_to_iso(started_at))
        if ended_at is not None:
            updates.append("ended_at = ?")
            params.append(_dt_to_iso(ended_at))
        if not updates:
            return
        params.append(run_id)
        with self._db_lock:
            conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?", params)
            conn.commit()

    def bind_loop(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        with self._db_lock:
            self._loops[run_id] = loop

    def get_queue(self, run_id: str) -> Optional[asyncio.Queue[EventPayload]]:
        with self._db_lock:
            return self._queues.get(run_id)

    def append_event(self, run_id: str, event: EventPayload) -> None:
        with self._db_lock:
            queue = self._queues.get(run_id)
            loop = self._loops.get(run_id)

        if queue is None:
            return

        payload = {"t": event.get("t", "message"), "data": event.get("data", {})}
        event_type = payload["t"]
        data = payload["data"] or {}

        if event_type == "score":
            score_value = data.get("total_score")
            if score_value is None:
                score_value = data.get("score")
            if score_value is None:
                score_value = data.get("value")
            milestones = data.get("milestones")
            self._update_score(run_id, score_value, milestones)

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

    def _update_score(self, run_id: str, score_value: object, milestones: object) -> None:
        conn = self._ensure_conn()
        score: Optional[float] = None
        if score_value is not None:
            try:
                score = float(score_value)
            except (TypeError, ValueError):
                score = None
        milestones_json: Optional[str] = None
        if milestones is not None:
            try:
                milestones_json = json.dumps(milestones)
            except TypeError:
                milestones_json = None
        with self._db_lock:
            if score is None and milestones_json is None:
                return
            sets: list[str] = []
            params: list[object] = []
            if score is not None:
                sets.append("last_score = ?")
                params.append(score)
            if milestones_json is not None:
                sets.append("milestones_json = ?")
                params.append(milestones_json)
            params.append(run_id)
            conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?", params)
            conn.commit()

    def set_summary(self, run_id: str, summary: Dict[str, Any]) -> None:
        conn = self._ensure_conn()
        summary_json = json.dumps(summary)
        total_score = summary.get("total_score")
        survival_score = summary.get("survival_score")
        milestones = summary.get("milestones")
        milestones_json = json.dumps(milestones) if milestones is not None else None

        with self._db_lock:
            conn.execute(
                """
                UPDATE runs
                   SET summary_json = ?,
                       total_score = COALESCE(?, total_score),
                       survival_score = COALESCE(?, survival_score),
                       milestones_json = COALESCE(?, milestones_json),
                       last_score = COALESCE(?, last_score)
                 WHERE run_id = ?
                """,
                (
                    summary_json,
                    total_score,
                    survival_score,
                    milestones_json,
                    total_score,
                    run_id,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Share token helpers
    # ------------------------------------------------------------------
    def create_share(
        self,
        run_id: str,
        *,
        scope: Optional[Iterable[str]] = None,
        ttl_seconds: Optional[int] = 86400,
    ) -> ShareToken:
        conn = self._ensure_conn()
        token = secrets.token_urlsafe(24)
        resolved_scope = {str(item) for item in (scope or {"live", "replay", "export"})}
        expires_at = datetime.utcnow() + timedelta(seconds=int(ttl_seconds)) if ttl_seconds is not None else None

        with self._db_lock:
            exists = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if exists is None:
                raise KeyError(run_id)
            conn.execute(
                """
                INSERT INTO shares (token, run_id, scope_json, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token,
                    run_id,
                    json.dumps(sorted(resolved_scope)),
                    _dt_to_iso(expires_at),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

        return ShareToken(
            token=token,
            run_id=run_id,
            scope=resolved_scope,
            expires_at=expires_at,
            created_at=datetime.utcnow(),
        )

    def get_share(self, token: str) -> Optional[ShareToken]:
        conn = self._ensure_conn()
        now = datetime.utcnow().isoformat()
        with self._db_lock:
            row = conn.execute(
                """
                SELECT token, run_id, scope_json, expires_at, created_at
                  FROM shares
                 WHERE token = ?
                   AND (expires_at IS NULL OR expires_at > ?)
                """,
                (token, now),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_sharetoken(row)

    def list_public(self) -> list[Tuple[RunInfo, ShareToken]]:
        conn = self._ensure_conn()
        now = datetime.utcnow().isoformat()
        with self._db_lock:
            rows = conn.execute(
                """
                SELECT
                  r.*,
                  s.token AS share_token,
                  s.scope_json AS share_scope_json,
                  s.expires_at AS share_expires_at,
                  s.created_at AS share_created_at
                FROM shares s
                JOIN runs r ON r.run_id = s.run_id
                WHERE s.expires_at IS NULL OR s.expires_at > ?
                """,
                (now,),
            ).fetchall()

        grouped: Dict[str, Tuple[sqlite3.Row, list[ShareToken]]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            share = ShareToken(
                token=str(row["share_token"]),
                run_id=run_id,
                scope=set(json.loads(row["share_scope_json"])),
                expires_at=_dt_from_iso(row["share_expires_at"]),
                created_at=_dt_from_iso(row["share_created_at"]) or datetime.utcnow(),
            )
            item = grouped.get(run_id)
            if item is None:
                grouped[run_id] = (row, [share])
            else:
                item[1].append(share)

        items: list[Tuple[RunInfo, ShareToken]] = []
        for run_row, shares in grouped.values():
            share = self._select_share(shares)
            if share is None:
                continue
            items.append((self._row_to_runinfo(run_row), share))
        return items

    @staticmethod
    def _select_share(tokens: Iterable[ShareToken]) -> Optional[ShareToken]:
        preferred: Optional[ShareToken] = None
        fallback: Optional[ShareToken] = None
        for share in tokens:
            if "live" in share.scope and preferred is None:
                preferred = share
            if fallback is None:
                fallback = share
        return preferred or fallback

    def public_leaderboard(self, limit: int = 50) -> list[Dict[str, Any]]:
        conn = self._ensure_conn()
        now = datetime.utcnow().isoformat()
        with self._db_lock:
            rows = conn.execute(
                """
                SELECT r.model, r.summary_json
                  FROM runs r
                  JOIN shares s ON s.run_id = r.run_id
                 WHERE (s.expires_at IS NULL OR s.expires_at > ?)
                   AND r.summary_json IS NOT NULL
                 ORDER BY COALESCE(r.ended_at, r.created_at) DESC
                 LIMIT ?
                """,
                (now, int(limit)),
            ).fetchall()

        aggregates: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            model = str(row["model"])
            try:
                summary = json.loads(row["summary_json"])
            except Exception:
                continue
            stats = aggregates.setdefault(
                model,
                {"model": model, "runs": 0, "total_score": 0.0, "survival_total": 0.0},
            )
            stats["runs"] += 1
            stats["total_score"] += float(summary.get("total_score", 0.0))
            stats["survival_total"] += float(summary.get("survival_score", 0.0))

        leaderboard: list[Dict[str, Any]] = []
        for stats in aggregates.values():
            runs = stats["runs"] or 1
            leaderboard.append(
                {
                    "model": stats["model"],
                    "runs": stats["runs"],
                    "mean_score": round(stats["total_score"] / runs, 2),
                    "survival_mean": round(stats["survival_total"] / runs, 2),
                }
            )
        leaderboard.sort(key=lambda item: item["mean_score"], reverse=True)
        return leaderboard

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _row_to_runinfo(
        self,
        row: sqlite3.Row,
        *,
        queue: Optional[asyncio.Queue[EventPayload]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> RunInfo:
        metadata: Dict[str, Any] = {}
        if row["last_score"] is not None:
            metadata["last_score"] = float(row["last_score"])
        if row["milestones_json"]:
            try:
                metadata["milestones"] = json.loads(row["milestones_json"])
            except Exception:
                pass
        if row["survival_score"] is not None:
            try:
                metadata["survived"] = float(row["survival_score"]) > 0
            except Exception:
                pass

        latest_summary: Optional[Dict[str, Any]] = None
        if row["summary_json"]:
            try:
                latest_summary = json.loads(row["summary_json"])
            except Exception:
                latest_summary = None

        return RunInfo(
            run_id=str(row["run_id"]),
            backend=str(row["backend"]),
            model=str(row["model"]),
            max_steps=int(row["max_steps"]),
            ticks_per_step=int(row["ticks_per_step"]),
            status=str(row["status"]),
            step=int(row["step"]),
            started_at=_dt_from_iso(row["started_at"]),
            ended_at=_dt_from_iso(row["ended_at"]),
            queue=queue,
            loop=loop,
            git_sha=row["git_sha"],
            seed_save=row["seed_save"],
            runtime_save=row["runtime_save"],
            artifacts_dir=row["artifacts_dir"],
            trace_path=row["trace_path"],
            metadata=metadata,
            latest_summary=latest_summary,
        )

    @staticmethod
    def _row_to_sharetoken(row: sqlite3.Row) -> ShareToken:
        try:
            scope = set(json.loads(row["scope_json"]))
        except Exception:
            scope = set()
        return ShareToken(
            token=str(row["token"]),
            run_id=str(row["run_id"]),
            scope=scope,
            expires_at=_dt_from_iso(row["expires_at"]),
            created_at=_dt_from_iso(row["created_at"]) or datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------
    def reset_for_tests(self) -> None:
        """Clear DB state and in-memory queues (pytest helper)."""

        conn = self._ensure_conn()
        with self._db_lock:
            conn.execute("DELETE FROM shares")
            conn.execute("DELETE FROM runs")
            conn.commit()
            self._queues.clear()
            self._loops.clear()


RUN_REGISTRY = RunRegistry()


__all__ = ["RUN_REGISTRY", "RunInfo", "RunRegistry", "ShareToken"]

