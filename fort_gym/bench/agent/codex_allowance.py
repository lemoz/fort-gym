"""Fresh read-only subscription admission through the documented app-server RPC.

Never creates a thread/turn, logs in/out, buys credits, or consumes a reset.
This is a preflight, not an atomic reservation against other account activity.
https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt
"""

from __future__ import annotations

import json
import math
import os
import selectors
import subprocess
import time
from pathlib import Path

from .codex_transport import DISABLED_FEATURES, _stop_owned_process, isolated_environment


def account_command(executable: Path) -> list[str]:
    command = [
        str(executable),
        "app-server",
        "--listen",
        "stdio://",
        "-c",
        'forced_login_method="chatgpt"',
    ]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    return command


def _account_read(executable: Path, timeout_seconds: float) -> tuple[dict, dict]:
    deadline = time.monotonic() + timeout_seconds
    process = subprocess.Popen(
        account_command(executable),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=isolated_environment(os.environ),
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None
    incoming, outgoing = process.stdout, process.stdin
    pending = bytearray()
    consumed = 0
    selector = selectors.DefaultSelector()
    selector.register(incoming, selectors.EVENT_READ)

    def send(message: dict) -> None:
        outgoing.write(json.dumps(message).encode() + b"\n")
        outgoing.flush()

    def response(identifier: int) -> dict:
        nonlocal consumed
        while time.monotonic() < deadline:
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending[:] = rest
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Invalid account RPC response")
                if message.get("id") == identifier:
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise ValueError("Account RPC failed")
                    return message["result"]
                if "id" in message:
                    raise ValueError("Unexpected account RPC request or response")
            events = selector.select(max(0, deadline - time.monotonic()))
            if not events:
                break
            chunk = os.read(incoming.fileno(), 65536)
            if not chunk:
                raise ValueError("Account RPC closed before its response")
            consumed += len(chunk)
            if consumed > 1024 * 1024:
                raise ValueError("Account RPC response exceeds size limit")
            pending.extend(chunk)
        raise TimeoutError("Account read timed out")

    try:
        send(
            {
                "method": "initialize",
                "id": 0,
                "params": {"clientInfo": {"name": "fort_gym_allowance", "version": "1.0.0"}},
            }
        )
        response(0)
        send({"method": "initialized", "params": {}})
        send({"method": "account/read", "id": 1, "params": {"refreshToken": False}})
        account = response(1)
        send({"method": "account/rateLimits/read", "id": 2})
        limits = response(2)
        return account, limits
    finally:
        selector.close()
        _stop_owned_process(process)
        process.stdin.close()
        process.stdout.close()


def evaluate_allowance(
    account: dict, limits: dict, *, now: float, maximum_used_percent: float = 90
) -> dict:
    """Retain only auth mode and limit data, never account email or credentials."""
    if (
        type(maximum_used_percent) not in (int, float)
        or not math.isfinite(maximum_used_percent)
        or not 0 < maximum_used_percent < 100
    ):
        raise ValueError("Invalid included-usage threshold")
    identity = account.get("account")
    mode = identity.get("type") if isinstance(identity, dict) else None
    buckets = limits.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if isinstance(buckets, dict) else limits.get("rateLimits")
    result: dict = {
        "allowed": False,
        "basis": "fresh_codex_app_server_account_read/v1",
        "captured_at_unix": now,
        "auth_mode": mode,
        "maximum_used_percent": maximum_used_percent,
        "atomic_account_reservation": False,
        "reported_charge_usd": None,
        "windows": [],
    }
    if mode != "chatgpt" or not isinstance(bucket, dict):
        return {**result, "reason": "ChatGPT account and Codex quota are required"}
    if bucket.get("rateLimitReachedType") is not None:
        return {**result, "reason": "Account reports a reached rate limit"}
    for name in ("primary", "secondary"):
        window = bucket.get(name)
        if window is None:
            continue  # Some accounts have only one window; absent is not zero usage.
        if not isinstance(window, dict):
            return {**result, "reason": "Invalid quota window"}
        used, duration, reset = (
            window.get(k) for k in ("usedPercent", "windowDurationMins", "resetsAt")
        )
        if (
            not isinstance(used, (int, float))
            or isinstance(used, bool)
            or not math.isfinite(used)
            or not 0 <= used <= 100
            or type(duration) is not int
            or duration <= 0
            or type(reset) is not int
            or reset <= now
        ):
            return {**result, "reason": "Incomplete or stale quota window"}
        result["windows"].append(
            {
                "name": name,
                "used_percent": used,
                "window_minutes": duration,
                "resets_at_unix": reset,
            }
        )
    if not result["windows"]:
        return {**result, "reason": "No current quota window was reported"}
    if any(window["used_percent"] >= maximum_used_percent for window in result["windows"]):
        return {**result, "reason": "Included-usage headroom threshold reached"}
    return {**result, "allowed": True, "reason": "Current quota has declared headroom"}


def read_allowance(
    executable: Path, *, maximum_used_percent: float = 90, timeout_seconds: float = 20
) -> dict:
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("Use an existing absolute Codex executable")
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 60:
        raise ValueError("Invalid account read timeout")
    account, limits = _account_read(executable, timeout_seconds)
    return evaluate_allowance(
        account, limits, now=time.time(), maximum_used_percent=maximum_used_percent
    )
