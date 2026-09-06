"""Bounded diagnostic snapshots, separate from acceptance criteria.

Only named files of an exact run are read. No environment dump, database copy,
save tree, recursive directory copy, traceback locals, or source lines are
exported. Callers put the returned payload in their sealed evidence paths.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TRACE_BYTES = 4 * 1024 * 1024
MAX_RUN_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SECRET = re.compile(
    r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)"
    r"|\b(?:sk-(?:ant-|live-|or-v1-|proj-)?|gh[oprsu]_|xox[baprs]-)[A-Za-z0-9_-]{16,}"
    r"|\bAIza[A-Za-z0-9_-]{30,}|\bAKIA[A-Z0-9]{16}"
    r"|\bBearer\s+[^\s\"',;]+"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|https?://[^\s/@]+:[^\s/@]+@",
    re.DOTALL | re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"\b(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
    r"|authorization|cookie)[\"']?\s*[:=]\s*"
    r"(?!(?:null|true|false)\b|[\{\[])"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)",
    re.IGNORECASE,
)
_CONTROL_FILES = (
    "launch.json",
    "owner.json",
    "manager-journal.jsonl",
    "manager-terminal.json",
    "brokered-runtime-runner.json",
    "supervision-observed.json",
    "fault-driver-observations.jsonl",
)
_ATTEMPT_FILES = (
    "attempt-journal.jsonl",
    "terminal.json",
    "terminal-draft.json",
    "evidence-snapshot.json",
    "child.stdout.log",
    "child.stderr.log",
    "trace.jsonl",
)
_RUNTIME_FILES = (
    "container-created.json",
    "prepare.json",
    "cleanup.json",
    "reconcile.json",
    "startup-terminal.json",
    "container-start-command.json",
    "container-run-command.json",
    "container.inspect.json",
    "image-resolution.json",
    "oom-hold-failure.json",
    "pre-readiness-oom.json",
    "container.logs.stdout.txt",
    "container.logs.stderr.txt",
)


def redact_text(value: str) -> str:
    """Remove credential-shaped values, including multiline quoted assignments."""
    value = _SECRET.sub("[REDACTED]", value)
    return _SENSITIVE_ASSIGNMENT.sub("[REDACTED ASSIGNMENT]", value)


def describe_exception(exc: BaseException) -> dict[str, Any]:
    """Keep cause, message and stack location, never traceback locals/source."""
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        try:
            message = redact_text(str(current))[:4096]
        except Exception:
            message = "<exception message unavailable>"
        frames: list[dict[str, Any]] = []
        cursor = current.__traceback__
        while cursor is not None:
            frames.append(
                {
                    "file": Path(cursor.tb_frame.f_code.co_filename).name,
                    "function": cursor.tb_frame.f_code.co_name,
                    "line": cursor.tb_lineno,
                }
            )
            frames = frames[-12:]
            cursor = cursor.tb_next
        chain.append({"error_type": type(current).__name__, "message": message, "frames": frames})
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return {"chain": chain, "chain_truncated": current is not None}


def _open_directory(path: Path) -> int:
    # Walk from / using directory descriptors, refusing symlink ancestors and
    # directory-swap races. Callers resolve platform aliases on trusted roots.
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("diagnostic source root must be absolute without traversal")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _capture(
    root: Path, relative: str, remaining: int, *, file_limit: int | None = None
) -> tuple[dict[str, Any], int]:
    record: dict[str, Any] = {"path": relative}
    directory: int | None = None
    descriptor: int | None = None
    try:
        path = Path(relative)
        directory = _open_directory(root / path.parent)
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            record["status"] = "unsafe_file"
            return record, 0
        limit = min(MAX_FILE_BYTES if file_limit is None else file_limit, remaining)
        data = bytearray()
        while len(data) < limit:
            block = os.read(descriptor, min(65536, limit - len(data)))
            if not block:
                break
            data.extend(block)
        after = os.fstat(descriptor)
        changed = (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        truncated = len(data) < after.st_size
        try:
            original = data.decode("utf-8")
        except UnicodeDecodeError:
            record.update(status="non_utf8", size_bytes=after.st_size)
            return record, len(data)
        retained = redact_text(original)
        redacted = retained != original
        record.update(
            status="captured",
            size_bytes=after.st_size,
            captured_bytes=len(data),
            captured_sha256=hashlib.sha256(data).hexdigest(),
            retained_sha256=hashlib.sha256(retained.encode("utf-8")).hexdigest(),
            content=retained,
            truncated=truncated,
            changed_during_read=changed,
            redacted=redacted,
            byte_exact=not (truncated or changed or redacted),
        )
        return record, len(data)
    except FileNotFoundError:
        record["status"] = "missing"
        return record, 0
    except OSError as exc:
        record.update(status="unreadable", errno=exc.errno, error_type=type(exc).__name__)
        return record, 0
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def capture_run_diagnostics(
    *,
    control_root: Path,
    artifacts_root: Path,
    run_id: str,
    session_sha256: str | None = None,
) -> dict[str, Any]:
    """Snapshot the frozen first attempt and its actual worker output.

    Missing files are explicit, not invented terminal evidence. ``capture_ok``
    describes the readable existing selection; it does not say the run passed,
    reached a terminal state, or that optional/missing files ever existed.
    """
    if not _ID.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError("diagnostic run identity is invalid")
    selected = [("control", name) for name in _CONTROL_FILES]
    selected += [("control", f"attempts/attempt-0001/{name}") for name in _ATTEMPT_FILES]
    selected += [("control", f"attempts/attempt-0001/runtime/{name}") for name in _RUNTIME_FILES]
    selected += [("artifacts", name) for name in ("summary.json", "trace.jsonl")]
    roots = {"control": control_root / run_id, "artifacts": artifacts_root / run_id}
    if session_sha256 is not None:
        if not re.fullmatch(r"[a-f0-9]{64}", session_sha256):
            raise ValueError("diagnostic session identity is invalid")
        roots["session"] = control_root / "_fault-sessions" / session_sha256
        selected += [("session", name) for name in ("session.json", "completion.json")]
        selected += [
            ("session", f"participants/{run_id}/{name}")
            for name in (
                "step2-ready.json",
                "step2-decision.json",
                "step2-released.json",
                "terminal-claim.json",
                "peer-progress-ready.json",
                "peer-progress-released.json",
            )
        ]
    files: list[dict[str, Any]] = []
    remaining = MAX_RUN_BYTES
    for area, relative in selected:
        record, used = _capture(
            roots[area], relative, remaining,
            file_limit=MAX_TRACE_BYTES if area == "artifacts" and relative == "trace.jsonl" else None,
        )
        remaining -= used
        record["area"] = area
        files.append(record)
    captured = [record for record in files if record["status"] == "captured"]
    return {
        "schema": "fortgym.m1b-run-diagnostics/v1",
        "run_id": run_id,
        "capture_ok": all(
            record["status"] == "missing"
            or (record["status"] == "captured" and record["byte_exact"])
            for record in files
        ),
        "terminal_evidence_present": all(
            any(record["area"] == "control" and record["path"] == name for record in captured)
            for name in ("manager-terminal.json", "attempts/attempt-0001/terminal.json")
        ),
        "selection": "named-first-attempt-files-no-recursive-copy",
        "maximum_file_bytes": MAX_FILE_BYTES,
        "maximum_trace_bytes": MAX_TRACE_BYTES,
        "maximum_run_bytes": MAX_RUN_BYTES,
        "captured_bytes": MAX_RUN_BYTES - remaining,
        "files": files,
    }
