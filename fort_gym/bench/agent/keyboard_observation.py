"""Host observation of one owned container; never retries a model or game input."""

from __future__ import annotations

from collections.abc import Callable
import json
import subprocess


def observe_container_output(
    command: list[str],
    *,
    output: Callable[[list[str]], str],
    inspect_command: list[str],
    retain_warning: Callable[[dict], None],
) -> str | None:
    """Return no output only after independently observing a stopped container.

    A read error does not prove that native work completed. The owner must still
    reconcile the native result, checkpoint and teardown. Unknown or live state
    propagates the original read error rather than silently dropping a response.
    """
    try:
        return output(command)
    except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        try:
            state = json.loads(output(inspect_command))
        except Exception as inspection_error:
            error.add_note("Container state recheck failed: " + type(inspection_error).__name__)
            raise error from inspection_error
        if (
            not isinstance(state, dict)
            or state.get("Status") not in ("exited", "dead")
            or state.get("Running") is not False
            or state.get("Restarting") is not False
            or type(state.get("Pid")) is not int
            or state["Pid"] != 0
        ):
            raise
        retain_warning({
            "schema_version": "fortgym.container-observation-warning/v1",
            "error_type": type(error).__name__,
            "error": str(error),
            "command": list(command),
            "command_exit_code": getattr(error, "returncode", None),
            "terminal_container_state": state,
            "underlying_cause": "unverified",
            "native_completion": "requires_separate_result_and_checkpoint_audit",
        })
        return None

