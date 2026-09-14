"""Host observation of one owned container; never retries a model or game input."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import PurePosixPath
import re
import shlex
import subprocess
import time


def _exchange_read(
    command: list[str], inspection: list[str], directory: str = "/evidence/astra/exchange"
) -> bool:
    """Only the two existing, literal exchange probes may opt into retries."""
    if (
        len(inspection) < 5
        or inspection[-4] != "inspect"
        or inspection[-2:]
        != [
            "--format",
            "{{json .State}}",
        ]
    ):
        return False
    prefix, owner = inspection[:-4], inspection[-3]
    if command[:-1] != prefix + ["exec", owner, "/bin/sh", "-c"]:
        return False
    if (not isinstance(directory, str) or not directory.startswith("/")
            or directory == "/" or str(PurePosixPath(directory)) != directory
            or ".." in PurePosixPath(directory).parts
            or any(ord(char) < 32 for char in directory)):
        return False
    quoted = shlex.quote(directory)
    if command[-1] == f"if test -d {quoted}; then ls -1 {quoted}; fi":
        return True
    try:
        # Extract only a candidate path. The exact canonical command comparison
        # below still rejects extra statements, options, and shell substitutions.
        candidate = PurePosixPath(shlex.split(command[-1])[3].removesuffix(";"))
    except (ValueError, IndexError):
        return False
    if (candidate.name != "request.json" or candidate.parent.parent != PurePosixPath(directory)
            or re.fullmatch(r"[a-f0-9]{32}", candidate.parent.name) is None):
        return False
    return command[-1] == f"if test -f {shlex.quote(str(candidate))}; then echo ready; fi"


def _read_failure(
    error: BaseException, command: list[str], attempt: int, state: object
) -> dict:
    raw = getattr(error, "output", None)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="replace")
    if not isinstance(raw, bytes):
        raw = None
    return {
        "schema_version": "fortgym.private-container-read-failure/v1",
        "attempt": attempt,
        "command": list(command),
        "error_type": type(error).__name__,
        "error": str(error),
        "command_exit_code": getattr(error, "returncode", None),
        "output_excerpt": None
        if raw is None
        else raw[:8192].decode("utf-8", errors="replace"),
        "output_bytes": None if raw is None else len(raw),
        "output_sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
        "output_truncated": None if raw is None else len(raw) > 8192,
        "container_state": state,
        "underlying_cause": "unverified",
        "model_or_gameplay_input_retried": False,
    }


def observe_container_output(
    command: list[str],
    *,
    output: Callable[[list[str]], str],
    inspect_command: list[str],
    retain_warning: Callable[[dict], None],
    max_live_read_attempts: int = 1,
    exchange_directory: str = "/evidence/astra/exchange",
    retain_failure: Callable[[dict], None] | None = None,
    wait: Callable[[float], None] = time.sleep,
) -> str | None:
    """Return no output only after independently observing a stopped container.

    A read error does not prove that native work completed. The owner must still
    reconcile the native result, checkpoint and teardown. Unknown or live state
    propagates the original read error rather than silently dropping a response.
    A caller may opt in to at most three attempts for the exact read-only exchange
    probes, only with a private failure recorder and freshly observed live state.
    No model invocation, input, response publication or unknown command is retried.
    """
    if type(max_live_read_attempts) is not int or not 1 <= max_live_read_attempts <= 3:
        raise ValueError("Container reads require a finite attempt bound")
    if max_live_read_attempts > 1 and (
        retain_failure is None or not _exchange_read(command, inspect_command, exchange_directory)
    ):
        raise ValueError(
            "Retries require an exact read-only exchange probe and failure recorder"
        )
    for attempt in range(1, max_live_read_attempts + 1):
        try:
            return output(command)
        except (
            RuntimeError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as error:
            try:
                state = json.loads(output(inspect_command))
            except Exception as inspection_error:
                if retain_failure is not None:
                    failure = _read_failure(error, command, attempt, None)
                    failure["inspection_error_type"] = type(inspection_error).__name__
                    retain_failure(failure)
                error.add_note(
                    "Container state recheck failed: " + type(inspection_error).__name__
                )
                raise error from inspection_error
            if retain_failure is not None:
                retain_failure(_read_failure(error, command, attempt, state))
            if (
                isinstance(state, dict)
                and state.get("Status") in ("exited", "dead")
                and state.get("Running") is False
                and state.get("Restarting") is False
                and type(state.get("Pid")) is int
                and state["Pid"] == 0
            ):
                retain_warning(
                    {
                        "schema_version": "fortgym.container-observation-warning/v1",
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "command": list(command),
                        "command_exit_code": getattr(error, "returncode", None),
                        "terminal_container_state": state,
                        "underlying_cause": "unverified",
                        "native_completion": "requires_separate_result_and_checkpoint_audit",
                    }
                )
                return None
            if (
                attempt < max_live_read_attempts
                and isinstance(state, dict)
                and state.get("Status") == "running"
                and state.get("Running") is True
                and state.get("Restarting") is False
                and state.get("Paused") is False
                and state.get("OOMKilled") is False
                and type(state.get("Pid")) is int
                and state["Pid"] > 0
            ):
                wait(0.5 * attempt)
                continue
            raise
    raise AssertionError("Container read attempts exhausted without a result")
