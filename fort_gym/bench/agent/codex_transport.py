"""One bounded subscription decision in an isolated, no-tools Codex invocation.

The caller owns usage admission and game execution. This transport has no API-key
fallback, implicit retry, game access, or claim of zero subscription charges.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .codex_protocol import TRANSPORT, decode_events

MODEL = "gpt-6-astra"
REASONING_EFFORT = "medium"
MAX_EVENT_BYTES = 16 * 1024 * 1024
DISABLED_FEATURES = (
    "apps",
    "plugins",
    "shell_tool",
    "unified_exec",
    "code_mode_host",
    "memories",
    "chronicle",
    "skill_search",
    "multi_agent",
    "multi_agent_v2",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "workspace_dependencies",
    "tool_suggest",
    "hooks",
    "shell_snapshot",
    "goals",
    "sleep_tool",
    "remote_plugin",
)


class CodexTransportError(RuntimeError):
    def __init__(self, message: str, receipt: dict) -> None:
        super().__init__(message)
        self.receipt = receipt


def invocation(executable: Path, schema_path: Path) -> list[str]:
    command = [
        str(executable),
        "-a",
        "never",
        "exec",
        "--ignore-user-config",
        "--strict-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        MODEL,
        "-c",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'web_search="disabled"',
        "-c",
        "project_doc_max_bytes=0",
        "--json",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
    ]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    # Input stays out of the process command line and comes exclusively from stdin.
    return [*command, "-"]


def isolated_environment(source: Mapping[str, str]) -> dict[str, str]:
    # Leave the user's credential store in place. Never copy tokens, inherit API
    # credentials/proxy/provider overrides, or alter global Codex configuration.
    return {key: source[key] for key in ("HOME", "PATH", "LANG", "TMPDIR") if key in source}


def _stop_owned_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=5)
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def request_decision(
    prompt: str,
    schema: dict,
    *,
    executable: Path,
    artifact_root: Path,
    allowance_check: Callable[[], dict],
    timeout_seconds: float = 180,
) -> dict:
    """Return a retained transport receipt, or raise with the same failure receipt.

    The fresh allowance callback is mandatory; callers must supply a real account
    and cumulative-run guard before live inference. Passing a test fixture is only
    appropriate for synthetic/offline tests. A preflight is not an atomic account
    reservation: other subscription sessions can consume allowance concurrently.
    """
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or not isinstance(schema, dict)
        or type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not 1 <= timeout_seconds <= 600
    ):
        raise ValueError("Invalid Codex decision request")
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("Codex executable must be an existing absolute file")
    if not artifact_root.is_absolute() or not artifact_root.is_dir():
        raise ValueError("Use an existing absolute project-owned artifact directory")
    schema_json = json.dumps(schema, allow_nan=False, sort_keys=True)
    admission = allowance_check()
    if (
        not isinstance(admission, dict)
        or admission.get("allowed") is not True
        or not isinstance(admission.get("basis"), str)
        or not admission["basis"]
    ):
        raise CodexTransportError(
            "Subscription decision was not admitted",
            {"accepted": False, "dispatched": False, "admission": admission},
        )
    admission = json.loads(json.dumps(admission, allow_nan=False))
    directory = Path(tempfile.mkdtemp(prefix="codex-decision-", dir=artifact_root))
    schema_path = directory / "output-schema.json"
    schema_path.write_text(schema_json + "\n", encoding="utf-8")
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    metadata = {
        "schema_version": "fortgym.codex-decision-receipt/v1",
        "transport": TRANSPORT,
        "model_requested": MODEL,
        "reasoning_effort_requested": REASONING_EFFORT,
        "auth_mode": "chatgpt",
        "api_credentials_inherited": False,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "output_schema_sha256": hashlib.sha256(schema_json.encode()).hexdigest(),
        "admission": admission,
        "run_directory": str(directory),
        "dispatched": False,
    }
    # A missing final receipt must never look like proof that no model dispatch
    # happened. Persist intent before launch and keep its outcome explicitly unknown.
    request_record = {key: value for key, value in metadata.items() if key != "dispatched"}
    request_record["dispatch_outcome"] = "unknown_until_result_receipt"
    with (directory / "request.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(request_record, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    start = time.monotonic()
    timed_out, interrupted, process, launch_error = False, False, None, None
    try:
        with (
            (directory / "events.jsonl").open("xb") as out,
            (directory / "stderr.log").open("xb") as err,
        ):
            process = subprocess.Popen(
                invocation(executable, schema_path),
                cwd=directory,
                env=isolated_environment(os.environ),
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            metadata["dispatched"] = True
            try:
                process.communicate(input=prompt.encode(), timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                _stop_owned_process(process)
    except OSError as error:
        launch_error = type(error).__name__
    except BaseException:
        interrupted = True
        raise
    finally:
        events_path = directory / "events.jsonl"
        oversized = events_path.exists() and events_path.stat().st_size > MAX_EVENT_BYTES
        raw = (
            events_path.read_text(encoding="utf-8", errors="replace")
            if events_path.exists() and not oversized
            else ""
        )
        receipt = {
            **metadata,
            **decode_events(
                raw, exit_code=process.returncode if process else None, timed_out=timed_out
            ),
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "interrupted": interrupted,
            "launch_error": launch_error,
        }
        for failed, code in (
            (oversized, "event_byte_limit"),
            (interrupted, "interrupted"),
            (launch_error, "launch_error"),
        ):
            if failed:
                receipt["accepted"] = False
                receipt["errors"].append(code)
        (directory / "result.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
    if not receipt["accepted"]:
        raise CodexTransportError("Codex decision failed; usage and artifacts retained", receipt)
    return receipt
