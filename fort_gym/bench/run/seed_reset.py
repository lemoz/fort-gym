"""Helpers to reset DFHack saves from a pristine seed."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from ..config import DFROOT, Settings, dfhack_cmd
from ..dfhack_exec import DFHackError, run_dfhack, run_lua_expr


class SeedResetError(RuntimeError):
    """Raised when a DFHack seed reset fails."""


def _validate_save_name(name: str, *, label: str) -> None:
    if any(token in name for token in ("/", "\\", "..")):
        raise SeedResetError(f"Invalid {label} save name: {name!r}")


def maybe_reset_dfhack_seed(settings: Settings) -> None:
    """Reset the DFHack save to a pristine seed if configured.

    When ``FORT_GYM_SEED_SAVE`` is set, this copies that save directory to
    the configured runtime save (defaults to ``current``) and restarts the
    ``dfhack-headless`` service so the new save is loaded.
    """

    seed_name = settings.FORT_GYM_SEED_SAVE
    if not seed_name:
        return

    reset_save_from_seed(
        seed_name,
        runtime_name=settings.FORT_GYM_RUNTIME_SAVE,
        dfroot=DFROOT,
        restart_service=True,
        host=settings.DFHACK_HOST,
        port=settings.DFHACK_PORT,
    )


def reset_save_from_seed(
    seed_name: str,
    *,
    runtime_name: str,
    dfroot: Path = DFROOT,
    restart_service: bool = True,
    host: str = "127.0.0.1",
    port: int = 5000,
    timeout_s: float = 90.0,
) -> None:
    """Copy ``seed_name`` to ``runtime_name`` and optionally restart DF headless."""

    _validate_save_name(seed_name, label="seed")
    _validate_save_name(runtime_name, label="runtime")

    saves_dir = dfroot / "data" / "save"
    seed_dir = _resolve_seed_dir(dfroot, seed_name)
    runtime_dir = saves_dir / runtime_name

    try:
        _reset_with_shutil(seed_dir, runtime_dir)
    except PermissionError:
        _reset_with_sudo(seed_dir, runtime_dir)

    if restart_service and host in {"127.0.0.1", "localhost"}:
        _restart_dfhack_headless(host, port, timeout_s=timeout_s)
        _load_runtime_save(runtime_name, timeout_s=max(timeout_s, 180.0))
        _wait_for_map_loaded(timeout_s=max(timeout_s, 180.0))


def reset_current_from_seed(
    seed_name: str,
    *,
    dfroot: Path = DFROOT,
    restart_service: bool = True,
    host: str = "127.0.0.1",
    port: int = 5000,
    timeout_s: float = 90.0,
) -> None:
    """Copy ``seed_name`` to ``current`` and optionally restart DF headless."""

    reset_save_from_seed(
        seed_name,
        runtime_name="current",
        dfroot=dfroot,
        restart_service=restart_service,
        host=host,
        port=port,
        timeout_s=timeout_s,
    )


def _reset_with_shutil(seed_dir: Path, runtime_dir: Path) -> None:
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    shutil.copytree(seed_dir, runtime_dir, symlinks=True)
    _make_writable(runtime_dir)


def _reset_with_sudo(seed_dir: Path, runtime_dir: Path) -> None:
    subprocess.check_call(["sudo", "-n", "rm", "-rf", str(runtime_dir)])
    subprocess.check_call(["sudo", "-n", "cp", "-a", str(seed_dir), str(runtime_dir)])
    subprocess.check_call(["sudo", "-n", "chmod", "-R", "u+w", str(runtime_dir)])


def _make_writable(path: Path) -> None:
    for entry in path.rglob("*"):
        try:
            mode = entry.stat().st_mode
            entry.chmod(mode | 0o200)  # add user-write
        except OSError:
            continue


def _restart_dfhack_headless(host: str, port: int, *, timeout_s: float) -> None:
    if shutil.which("systemctl") is None:
        return

    subprocess.check_call(["sudo", "-n", "systemctl", "restart", "dfhack-headless"])
    _wait_for_port(host, port, timeout_s)


def _wait_for_port(host: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise SeedResetError(f"DFHack RPC did not come up on {host}:{port}: {last_error}")


def _load_runtime_save(runtime_name: str, *, timeout_s: float) -> None:
    try:
        run_dfhack(dfhack_cmd("load-save", runtime_name), timeout=timeout_s, cwd=str(DFROOT))
    except DFHackError as exc:
        raise SeedResetError(f"Failed to load DF save {runtime_name!r}: {exc}") from exc


def _wait_for_map_loaded(*, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            out = run_lua_expr(
                "print(dfhack.isMapLoaded() and 'FG_MAP_LOADED' or 'FG_MAP_NOT_LOADED')",
                timeout=2.5,
            )
            if "FG_MAP_LOADED" in out:
                return
        except DFHackError as exc:
            last_error = exc
        time.sleep(0.5)

    raise SeedResetError(f"Timed out waiting for DF map to load: {last_error}")


def _resolve_seed_dir(dfroot: Path, seed_name: str) -> Path:
    candidates = [
        dfroot / "data" / "seed_saves" / seed_name,
        dfroot / "data" / "save" / seed_name,
    ]

    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except PermissionError:
            if _sudo_is_dir(candidate):
                return candidate

    message = ", ".join(str(path) for path in candidates)
    raise SeedResetError(f"Seed save not found (checked: {message})")


def _sudo_is_dir(path: Path) -> bool:
    """Check directory existence via sudo when direct stat is blocked."""
    try:
        subprocess.check_call(["sudo", "-n", "test", "-d", str(path)])
        return True
    except Exception:
        return False


__all__ = [
    "SeedResetError",
    "maybe_reset_dfhack_seed",
    "reset_save_from_seed",
    "reset_current_from_seed",
]
