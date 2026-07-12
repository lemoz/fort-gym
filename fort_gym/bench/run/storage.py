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
from ..eval.protocol import validate_evaluation_protocol

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


def _normalize_score_version(value: object) -> int:
    """Coerce a summary's ``score_version`` to an int, defaulting to 1.

    Runs recorded before ``score_version`` existed (the pre-v2 era) carry no
    such field in their ``summary.json`` — WDSLL treats those as version 1,
    same as an explicit ``score_version: 1``.
    """

    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


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
    preserve_save: bool = False
    evaluation_protocol: Optional[str] = None
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
        self._stop_events: Dict[str, threading.Event] = {}

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
              preserve_save INTEGER NOT NULL DEFAULT 0,
              evaluation_protocol TEXT,
              artifacts_dir TEXT,
              trace_path TEXT,
              last_score REAL,
              total_score REAL,
              survival_score REAL,
              milestones_json TEXT,
              summary_json TEXT,
              terminal_reason_json TEXT,
              stop_requested_at TEXT,
              cleanup_completed_at TEXT
            )
            """
        )
        RunRegistry._ensure_column(
            conn,
            table="runs",
            column="preserve_save",
            definition="INTEGER NOT NULL DEFAULT 0",
        )
        RunRegistry._ensure_column(
            conn,
            table="runs",
            column="evaluation_protocol",
            definition="TEXT",
        )
        RunRegistry._ensure_column(
            conn,
            table="runs",
            column="terminal_reason_json",
            definition="TEXT",
        )
        RunRegistry._ensure_column(
            conn,
            table="runs",
            column="stop_requested_at",
            definition="TEXT",
        )
        RunRegistry._ensure_column(
            conn,
            table="runs",
            column="cleanup_completed_at",
            definition="TEXT",
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_public ON "
            "runs(backend, status, ended_at, started_at, created_at)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_run ON shares(run_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shares_run_expiry ON shares(run_id, expires_at)"
        )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, *, table: str, column: str, definition: str
    ) -> None:
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _mark_interrupted_runs(conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE runs
               SET status = CASE
                       WHEN stop_requested_at IS NOT NULL
                        AND cleanup_completed_at IS NOT NULL
                        AND summary_json IS NOT NULL THEN 'stopped'
                       ELSE 'failed'
                   END,
                   ended_at = COALESCE(ended_at, ?)
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
        preserve_save: bool = False,
        seed_save: Optional[str] = None,
        runtime_save: Optional[str] = None,
        evaluation_protocol: Optional[str] = None,
    ) -> RunInfo:
        """Register a new run and return its record.

        ``seed_save``/``runtime_save`` record a per-run seed override so run
        provenance shows the embark the run ACTUALLY used, not the
        deployment default.
        """

        conn = self._ensure_conn()
        evaluation_protocol = validate_evaluation_protocol(evaluation_protocol)

        identifier = run_id or uuid.uuid4().hex
        queue: asyncio.Queue[EventPayload] = asyncio.Queue(maxsize=512)

        now = datetime.utcnow()
        settings = get_settings()
        artifacts_root = Path(settings.ARTIFACTS_DIR).resolve()
        artifacts_dir = artifacts_root / identifier
        trace_path = artifacts_dir / "trace.jsonl"

        git_sha = _git_sha()
        seed_save = seed_save or settings.FORT_GYM_SEED_SAVE
        runtime_save = runtime_save or getattr(settings, "FORT_GYM_RUNTIME_SAVE", None)

        with self._db_lock:
            row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (identifier,)).fetchone()
            if row is not None:
                raise ValueError(f"Run '{identifier}' already registered")
            conn.execute(
                """
                INSERT INTO runs (
                  run_id, backend, model, max_steps, ticks_per_step,
                  status, step, created_at, git_sha, seed_save, runtime_save,
                  preserve_save, evaluation_protocol, artifacts_dir, trace_path
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if preserve_save else 0,
                    evaluation_protocol,
                    str(artifacts_dir),
                    str(trace_path),
                ),
            )
            conn.commit()

            self._queues[identifier] = queue
            self._stop_events[identifier] = threading.Event()
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
            preserve_save=preserve_save,
            evaluation_protocol=evaluation_protocol,
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
        return [
            self._row_to_runinfo(
                row, queue=queues.get(row["run_id"]), loop=loops.get(row["run_id"])
            )
            for row in rows
        ]

    def claim_pending_run(self, run_id: str, *, started_at: datetime) -> bool:
        """Atomically claim a pending run for exactly one worker."""

        conn = self._ensure_conn()
        with self._db_lock:
            cursor = conn.execute(
                """
                UPDATE runs
                   SET status = 'running', step = 0, started_at = ?
                 WHERE run_id = ? AND status = 'pending'
                """,
                (_dt_to_iso(started_at), run_id),
            )
            conn.commit()
            return cursor.rowcount == 1

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
            # Terminal states are immutable. A worker can only observe a
            # transition after an in-flight call returns, so later lifecycle
            # bookkeeping must not replace an already-terminal outcome.
            updates.append(
                "status = CASE WHEN status IN ('stopped', 'failed', 'completed') "
                "THEN status ELSE ? END"
            )
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

    def record_terminal_failure(
        self,
        run_id: str,
        *,
        terminal_reason: Dict[str, Any],
        step: int,
        ended_at: datetime,
    ) -> None:
        """Persist a terminal runner failure without replacing another terminal outcome."""

        conn = self._ensure_conn()
        with self._db_lock:
            conn.execute(
                """
                UPDATE runs
                   SET terminal_reason_json = CASE
                           WHEN status IN ('stopped', 'failed', 'completed')
                           THEN terminal_reason_json ELSE ? END,
                       step = CASE
                           WHEN status IN ('stopped', 'failed', 'completed')
                           THEN step ELSE ? END,
                       status = CASE
                           WHEN status IN ('stopped', 'failed', 'completed') THEN status
                           ELSE 'failed'
                       END,
                       ended_at = COALESCE(ended_at, ?)
                 WHERE run_id = ?
                """,
                (
                    json.dumps(terminal_reason),
                    int(step),
                    _dt_to_iso(ended_at),
                    run_id,
                ),
            )
            conn.commit()

    def record_pending_terminal_failure(
        self,
        run_id: str,
        *,
        terminal_reason: Dict[str, Any],
        step: int,
    ) -> None:
        """Durably stage failure evidence while the worker still owns cleanup."""

        conn = self._ensure_conn()
        with self._db_lock:
            conn.execute(
                """
                UPDATE runs
                   SET terminal_reason_json = CASE
                           WHEN status IN ('stopped', 'failed', 'completed')
                           THEN terminal_reason_json ELSE ? END,
                       step = CASE
                           WHEN status IN ('stopped', 'failed', 'completed')
                           THEN step ELSE ? END
                 WHERE run_id = ?
                """,
                (
                    json.dumps(terminal_reason),
                    int(step),
                    run_id,
                ),
            )
            conn.commit()

    def bind_loop(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        with self._db_lock:
            self._loops[run_id] = loop

    def record_cleanup_completed(self, run_id: str, *, completed_at: datetime) -> None:
        """Durably prove runtime ownership was released before terminalization."""

        conn = self._ensure_conn()
        with self._db_lock:
            conn.execute(
                """
                UPDATE runs
                   SET cleanup_completed_at = COALESCE(cleanup_completed_at, ?)
                 WHERE run_id = ?
                   AND status NOT IN ('stopped', 'failed', 'completed')
                """,
                (_dt_to_iso(completed_at), run_id),
            )
            conn.commit()

    def finalize_success_after_cleanup(
        self,
        run_id: str,
        *,
        step: int,
        ended_at: datetime,
    ) -> str:
        """Atomically choose completed or stopped after the worker releases DF."""

        conn = self._ensure_conn()
        with self._db_lock:
            row = conn.execute(
                """
                SELECT status, stop_requested_at, cleanup_completed_at, summary_json
                  FROM runs
                 WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current_status = str(row["status"])
            event = self._stop_events.get(run_id)
            if current_status in {"stopped", "failed", "completed"}:
                if event is not None:
                    event.clear()
                return current_status
            if row["cleanup_completed_at"] is None:
                raise RuntimeError(f"Run '{run_id}' cannot finalize before cleanup completes")
            if row["summary_json"] is None:
                raise RuntimeError(f"Run '{run_id}' cannot finalize before summary persistence")
            stop_requested = row["stop_requested_at"] is not None or bool(event and event.is_set())
            final_status = "stopped" if stop_requested else "completed"
            conn.execute(
                """
                UPDATE runs
                   SET status = ?, step = ?, ended_at = ?, stop_requested_at = NULL
                 WHERE run_id = ?
                   AND status NOT IN ('stopped', 'failed', 'completed')
                """,
                (
                    final_status,
                    int(step),
                    _dt_to_iso(ended_at),
                    run_id,
                ),
            )
            if event is not None:
                event.clear()
            conn.commit()
            return final_status

    def request_stop(self, run_id: str) -> bool:
        conn = self._ensure_conn()
        with self._db_lock:
            row = conn.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None or str(row["status"]) in {"stopped", "failed", "completed"}:
                return False
            event = self._stop_events.get(run_id)
            if event is None:
                event = threading.Event()
                self._stop_events[run_id] = event
            conn.execute(
                """
                UPDATE runs
                   SET stop_requested_at = COALESCE(stop_requested_at, ?)
                 WHERE run_id = ?
                """,
                (datetime.utcnow().isoformat(), run_id),
            )
            conn.commit()
            event.set()
        return True

    def stop_requested(self, run_id: str) -> bool:
        conn = self._ensure_conn()
        with self._db_lock:
            event = self._stop_events.get(run_id)
            row = conn.execute(
                "SELECT stop_requested_at FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return bool((event and event.is_set()) or (row and row["stop_requested_at"]))

    def clear_stop(self, run_id: str) -> None:
        conn = self._ensure_conn()
        with self._db_lock:
            event = self._stop_events.get(run_id)
            if event is not None:
                event.clear()
            conn.execute(
                "UPDATE runs SET stop_requested_at = NULL WHERE run_id = ?",
                (run_id,),
            )
            conn.commit()

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
        expires_at = (
            datetime.utcnow() + timedelta(seconds=int(ttl_seconds))
            if ttl_seconds is not None
            else None
        )

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

    def list_public_for_protocol(
        self, evaluation_protocol: str, *, limit: int = 5000
    ) -> Tuple[list[Tuple[RunInfo, ShareToken]], bool]:
        """Return a bounded public cohort for one exact protocol label."""

        self._ensure_conn()
        now = datetime.utcnow().isoformat()
        read_conn = sqlite3.connect(
            f"{self._db_path().resolve().as_uri()}?mode=ro", uri=True, timeout=1.0
        )
        read_conn.row_factory = sqlite3.Row
        try:
            read_conn.execute("PRAGMA query_only = ON")
            rows = read_conn.execute(
                """
                WITH protocol_runs AS (
                    SELECT r.*
                      FROM runs r
                     WHERE r.evaluation_protocol = ?
                       AND EXISTS (
                           SELECT 1
                             FROM shares active_share
                            WHERE active_share.run_id = r.run_id
                              AND (
                                  active_share.expires_at IS NULL
                                  OR active_share.expires_at > ?
                              )
                       )
                     ORDER BY r.run_id
                     LIMIT ?
                )
                SELECT
                  r.*,
                  s.token AS share_token,
                  s.scope_json AS share_scope_json,
                  s.expires_at AS share_expires_at,
                  s.created_at AS share_created_at
                  FROM protocol_runs r
                  JOIN shares s ON s.run_id = r.run_id
                 WHERE s.expires_at IS NULL OR s.expires_at > ?
                """,
                (evaluation_protocol, now, int(limit) + 1, now),
            ).fetchall()
        finally:
            read_conn.close()

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

        truncated = len(grouped) > limit
        items: list[Tuple[RunInfo, ShareToken]] = []
        for run_row, shares in list(grouped.values())[:limit]:
            share = self._select_share(shares)
            if share is not None:
                items.append((self._row_to_runinfo(run_row), share))
        return items, truncated

    def list_public_page(
        self,
        *,
        limit: int,
        offset: int,
        status: Optional[str] = None,
        model: Optional[str] = None,
        evaluation_protocol: Optional[str] = None,
        seed_save: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Tuple[list[Tuple[RunInfo, ShareToken]], int]:
        """Return one bounded page of shared run metadata from the registry.

        The database filters and orders runs before loading their shares. Trace
        files are intentionally outside this query path.
        """

        self._ensure_conn()
        now = datetime.utcnow().isoformat()
        where = [
            "r.backend = 'dfhack'",
            "EXISTS (SELECT 1 FROM shares s "
            "WHERE s.run_id = r.run_id "
            "AND (s.expires_at IS NULL OR s.expires_at > ?) "
            "AND 2 = (SELECT COUNT(DISTINCT scope.value) "
            "FROM json_each(s.scope_json) scope "
            "WHERE scope.value IN ('replay', 'export')))",
        ]
        params: list[object] = [now]

        for column, value in (
            ("status", status),
            ("model", model),
            ("evaluation_protocol", evaluation_protocol),
            ("seed_save", seed_save),
        ):
            if value is not None:
                where.append(f"r.{column} = ?")
                params.append(value)

        if query and query.strip():
            pattern = self._public_query_pattern(query)
            fields = (
                "r.model",
                "r.backend",
                "r.status",
                "r.evaluation_protocol",
                "r.seed_save",
                "r.git_sha",
            )
            where.append(
                "("
                + " OR ".join(
                    f"LOWER(COALESCE({field}, '')) LIKE ? ESCAPE '\\'" for field in fields
                )
                + ")"
            )
            params.extend([pattern] * len(fields))

        where_sql = " AND ".join(where)
        ordering = """
            CASE WHEN r.status IN ('pending', 'running', 'paused') THEN 0 ELSE 1 END ASC,
            COALESCE(r.ended_at, r.started_at, r.created_at) DESC,
            r.run_id DESC
        """
        read_conn = sqlite3.connect(
            f"{self._db_path().resolve().as_uri()}?mode=ro", uri=True, timeout=1.0
        )
        read_conn.row_factory = sqlite3.Row
        try:
            read_conn.execute("PRAGMA query_only = ON")
            total_row = read_conn.execute(
                f"SELECT COUNT(*) AS total FROM runs r WHERE {where_sql}", params
            ).fetchone()
            rows = read_conn.execute(
                f"""
                WITH page_runs AS (
                    SELECT r.*
                      FROM runs r
                     WHERE {where_sql}
                     ORDER BY {ordering}
                     LIMIT ? OFFSET ?
                )
                SELECT
                  r.*,
                  s.token AS share_token,
                  s.scope_json AS share_scope_json,
                  s.expires_at AS share_expires_at,
                  s.created_at AS share_created_at
                  FROM page_runs r
                  JOIN shares s ON s.run_id = r.run_id
                 WHERE (s.expires_at IS NULL OR s.expires_at > ?)
                   AND 2 = (
                     SELECT COUNT(DISTINCT scope.value)
                       FROM json_each(s.scope_json) scope
                      WHERE scope.value IN ('replay', 'export')
                   )
                 ORDER BY {ordering}, s.created_at ASC
                """,
                [*params, int(limit), int(offset), now],
            ).fetchall()
        finally:
            read_conn.close()

        shares_by_run: Dict[str, list[ShareToken]] = {}
        run_rows: Dict[str, sqlite3.Row] = {}
        run_order: list[str] = []
        for row in rows:
            run_id = str(row["run_id"])
            if run_id not in run_rows:
                run_rows[run_id] = row
                run_order.append(run_id)
            shares_by_run.setdefault(run_id, []).append(
                ShareToken(
                    token=str(row["share_token"]),
                    run_id=run_id,
                    scope=set(json.loads(row["share_scope_json"])),
                    expires_at=_dt_from_iso(row["share_expires_at"]),
                    created_at=_dt_from_iso(row["share_created_at"]) or datetime.utcnow(),
                )
            )

        items: list[Tuple[RunInfo, ShareToken]] = []
        for run_id in run_order:
            share = self._select_share(shares_by_run[run_id])
            if share is not None:
                items.append((self._row_to_runinfo(run_rows[run_id]), share))
        return items, int(total_row["total"] if total_row is not None else 0)

    @staticmethod
    def _public_query_pattern(query: str) -> str:
        escaped = query.strip().lower()
        escaped = escaped.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def public_overview_runs(
        self, *, recent_limit: int = 20
    ) -> Tuple[
        list[Tuple[RunInfo, ShareToken]],
        list[Tuple[RunInfo, ShareToken]],
        list[Tuple[RunInfo, ShareToken]],
    ]:
        """Return active, recent terminal, and all terminal shared runs.

        This reads the registry only. In particular, callers must not inspect
        trace files while constructing an overview response.
        """

        active_statuses = {"pending", "running", "paused"}
        terminal_statuses = {"completed", "failed", "stopped"}
        active_runs: list[Tuple[RunInfo, ShareToken]] = []
        terminal_runs: list[Tuple[RunInfo, ShareToken]] = []

        for item in self.list_public():
            record, _share = item
            if record.status in active_statuses:
                active_runs.append(item)
            elif record.status in terminal_statuses:
                terminal_runs.append(item)

        def sort_key(
            item: Tuple[RunInfo, ShareToken], timestamp: Optional[datetime]
        ) -> tuple[float, str]:
            return (
                timestamp.timestamp() if timestamp is not None else float("-inf"),
                item[0].run_id,
            )

        active_runs.sort(key=lambda item: sort_key(item, item[0].started_at), reverse=True)
        terminal_runs.sort(key=lambda item: sort_key(item, item[0].ended_at), reverse=True)
        return active_runs, terminal_runs[:recent_limit], terminal_runs

    @staticmethod
    def _select_share(tokens: Iterable[ShareToken]) -> Optional[ShareToken]:
        comprehensive: Optional[ShareToken] = None
        evidence: Optional[ShareToken] = None
        replay: Optional[ShareToken] = None
        preferred: Optional[ShareToken] = None
        fallback: Optional[ShareToken] = None
        for share in tokens:
            if {"live", "replay", "export"}.issubset(share.scope) and comprehensive is None:
                comprehensive = share
            if {"replay", "export"}.issubset(share.scope) and evidence is None:
                evidence = share
            if "replay" in share.scope and replay is None:
                replay = share
            if "live" in share.scope and preferred is None:
                preferred = share
            if fallback is None:
                fallback = share
        return comprehensive or evidence or replay or preferred or fallback

    def public_leaderboard(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Return per-(model, score_version, seed_save) aggregates.

        WDSLL's non-negotiables hold scores comparable only on the same seed
        and (per the score-v2/v3 boundary entries) the same ``score_version``.
        Mixing eras/seeds into a single ``mean_score`` is a display-truth bug,
        so every row here is scoped to one (model, score_version, seed_save)
        bucket. Runs with no recorded ``score_version`` predate the field and
        are bucketed as version 1.
        """

        conn = self._ensure_conn()
        now = datetime.utcnow().isoformat()
        with self._db_lock:
            rows = conn.execute(
                """
                SELECT r.run_id, r.model, r.summary_json, r.seed_save,
                       s.token AS share_token, s.scope_json AS share_scope_json,
                       s.expires_at AS share_expires_at, s.created_at AS share_created_at
                  FROM runs r
                  JOIN shares s ON s.run_id = r.run_id
                 WHERE (s.expires_at IS NULL OR s.expires_at > ?)
                   AND r.summary_json IS NOT NULL
                 ORDER BY COALESCE(r.ended_at, r.created_at) DESC
                 LIMIT ?
                """,
                (now, int(limit)),
            ).fetchall()

        # A run may carry more than one live share token; dedupe to one row
        # per run_id and collect all its shares for `_select_share`.
        run_rows: Dict[str, sqlite3.Row] = {}
        shares_by_run: Dict[str, list[ShareToken]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            run_rows.setdefault(run_id, row)
            try:
                scopes = set(json.loads(row["share_scope_json"]))
            except Exception:
                scopes = set()
            shares_by_run.setdefault(run_id, []).append(
                ShareToken(
                    token=str(row["share_token"]),
                    run_id=run_id,
                    scope=scopes,
                    expires_at=_dt_from_iso(row["share_expires_at"]),
                    created_at=_dt_from_iso(row["share_created_at"]) or datetime.utcnow(),
                )
            )

        aggregates: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        for run_id, row in run_rows.items():
            model = str(row["model"])
            try:
                summary = json.loads(row["summary_json"])
            except Exception:
                continue
            score_version = _normalize_score_version(summary.get("score_version"))
            seed_save = str(row["seed_save"]) if row["seed_save"] else "unspecified"
            key = (model, score_version, seed_save)
            stats = aggregates.setdefault(
                key,
                {
                    "model": model,
                    "score_version": score_version,
                    "seed_save": seed_save,
                    "runs": 0,
                    "total_score": 0.0,
                    "survival_total": 0.0,
                    "best_score": None,
                    "best_token": None,
                },
            )
            score = float(summary.get("total_score", 0.0))
            stats["runs"] += 1
            stats["total_score"] += score
            stats["survival_total"] += float(summary.get("survival_score", 0.0))
            if stats["best_score"] is None or score >= stats["best_score"]:
                stats["best_score"] = score
                share = self._select_share(shares_by_run.get(run_id, []))
                stats["best_token"] = share.token if share else None

        leaderboard: list[Dict[str, Any]] = []
        for stats in aggregates.values():
            runs = stats["runs"] or 1
            leaderboard.append(
                {
                    "model": stats["model"],
                    "score_version": stats["score_version"],
                    "seed_save": stats["seed_save"],
                    "runs": stats["runs"],
                    "mean_score": round(stats["total_score"] / runs, 2),
                    "survival_mean": round(stats["survival_total"] / runs, 2),
                    "best_score": round(stats["best_score"], 2)
                    if stats["best_score"] is not None
                    else None,
                    "best_token": stats["best_token"],
                }
            )
        leaderboard.sort(key=lambda item: (item["score_version"], item["mean_score"]), reverse=True)
        return leaderboard

    def best_scores_over_time(
        self,
        *,
        days: int = 30,
        backend: Optional[str] = None,
        model: Optional[str] = None,
        max_steps: Optional[int] = None,
        limit_per_series: int = 500,
    ) -> list[Dict[str, Any]]:
        """Return best-score time series per (model, git_sha, backend, score_version, seed_save).

        Same comparability rule as `public_leaderboard`: a "best score so far"
        line must not silently splice together runs from different scoring
        eras or seeds, so the series key includes `score_version`/`seed_save`
        alongside the existing `model`/`git_sha`/`backend` grouping.
        """

        conn = self._ensure_conn()
        now_dt = datetime.utcnow()
        since_dt = now_dt - timedelta(days=max(1, int(days)))
        now = now_dt.isoformat()
        since = since_dt.isoformat()

        where: list[str] = [
            "(s.expires_at IS NULL OR s.expires_at > ?)",
            "r.ended_at IS NOT NULL",
            "r.total_score IS NOT NULL",
            "r.ended_at >= ?",
        ]
        params: list[object] = [now, since]

        if backend:
            where.append("r.backend = ?")
            params.append(str(backend))
        if model:
            where.append("r.model = ?")
            params.append(str(model))
        if max_steps is not None:
            where.append("r.max_steps = ?")
            params.append(int(max_steps))

        query = f"""
            SELECT
              r.run_id, r.backend, r.model, r.git_sha, r.max_steps, r.ticks_per_step,
              r.ended_at, r.total_score, r.summary_json, r.seed_save,
              s.token AS share_token, s.scope_json AS share_scope_json,
              s.expires_at AS share_expires_at, s.created_at AS share_created_at
            FROM runs r
            JOIN shares s ON s.run_id = r.run_id
            WHERE {' AND '.join(where)}
            ORDER BY r.ended_at ASC
        """

        with self._db_lock:
            rows = conn.execute(query, params).fetchall()

        runs: Dict[str, sqlite3.Row] = {}
        shares_by_run: Dict[str, list[ShareToken]] = {}
        for row in rows:
            run_id = str(row["run_id"])
            runs.setdefault(run_id, row)
            try:
                scopes = set(json.loads(row["share_scope_json"]))
            except Exception:
                scopes = set()
            shares_by_run.setdefault(run_id, []).append(
                ShareToken(
                    token=str(row["share_token"]),
                    run_id=run_id,
                    scope=scopes,
                    expires_at=_dt_from_iso(row["share_expires_at"]),
                    created_at=_dt_from_iso(row["share_created_at"]) or datetime.utcnow(),
                )
            )

        grouped: Dict[Tuple[str, str, str, int, str], list[Dict[str, Any]]] = {}
        for run_id, run_row in runs.items():
            share = self._select_share(shares_by_run.get(run_id, []))
            if not share:
                continue
            ended_at = _dt_from_iso(run_row["ended_at"])
            if ended_at is None:
                continue
            score = float(run_row["total_score"])
            git_sha = str(run_row["git_sha"] or "unknown")
            score_version = 1
            if run_row["summary_json"]:
                try:
                    score_version = _normalize_score_version(
                        json.loads(run_row["summary_json"]).get("score_version")
                    )
                except Exception:
                    score_version = 1
            seed_save = str(run_row["seed_save"]) if run_row["seed_save"] else "unspecified"
            key = (
                str(run_row["model"]),
                git_sha,
                str(run_row["backend"]),
                score_version,
                seed_save,
            )
            grouped.setdefault(key, []).append(
                {
                    "t": ended_at.isoformat(),
                    "score": score,
                    "run_id": run_id,
                    "token": share.token,
                    "max_steps": int(run_row["max_steps"]),
                    "ticks_per_step": int(run_row["ticks_per_step"]),
                }
            )

        series: list[Dict[str, Any]] = []
        for (
            model_name,
            git_sha,
            backend_name,
            score_version,
            seed_save,
        ), points in grouped.items():
            points.sort(key=lambda item: item["t"])
            best = float("-inf")
            best_point: Optional[Dict[str, Any]] = None
            for point in points:
                if point["score"] >= best:
                    best = point["score"]
                    best_point = point
                point["best"] = best
            if limit_per_series and len(points) > limit_per_series:
                points = points[-int(limit_per_series) :]
            series.append(
                {
                    "model": model_name,
                    "git_sha": git_sha,
                    "backend": backend_name,
                    "score_version": score_version,
                    "seed_save": seed_save,
                    "points": points,
                    "best": best_point,
                }
            )

        series.sort(key=lambda item: (item.get("best") or {}).get("score", 0.0), reverse=True)
        return series

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
        if row["terminal_reason_json"]:
            try:
                metadata["terminal_reason"] = json.loads(row["terminal_reason_json"])
            except Exception:
                pass
        if row["stop_requested_at"]:
            metadata["stop_requested_at"] = str(row["stop_requested_at"])
        if row["cleanup_completed_at"]:
            metadata["cleanup_completed_at"] = str(row["cleanup_completed_at"])

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
            preserve_save=bool(row["preserve_save"]),
            evaluation_protocol=row["evaluation_protocol"],
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
            self._stop_events.clear()


RUN_REGISTRY = RunRegistry()


__all__ = ["RUN_REGISTRY", "RunInfo", "RunRegistry", "ShareToken"]
