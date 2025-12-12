"""Helpers to reset DFHack saves from a pristine seed."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from ..config import DFROOT, Settings


class SeedResetError(RuntimeError):
    """Raised when a DFHack seed reset fails."""


def maybe_reset_dfhack_seed(settings: Settings) -> None:
    """Reset the DFHack save to a pristine seed if configured.

    When ``FORT_GYM_SEED_SAVE`` is set, this copies that save directory to
    ``current`` and restarts the ``dfhack-headless`` service so the new save is loaded.
    """

    seed_name = settings.FORT_GYM_SEED_SAVE
    if not seed_name:
        return

    reset_current_from_seed(
        seed_name,
        dfroot=DFROOT,
        restart_service=True,
        host=settings.DFHACK_HOST,
        port=settings.DFHACK_PORT,
    )


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

    if any(token in seed_name for token in ("/", "\\", "..")):
        raise SeedResetError(f"Invalid seed save name: {seed_name!r}")

    saves_dir = dfroot / "data" / "save"
    seed_dir = saves_dir / seed_name
    current_dir = saves_dir / "current"

    if not seed_dir.is_dir():
        raise SeedResetError(f"Seed save not found: {seed_dir}")

    try:
        _reset_with_shutil(seed_dir, current_dir)
    except PermissionError:
        _reset_with_sudo(seed_dir, current_dir)

    if restart_service and host in {"127.0.0.1", "localhost"}:
        _restart_dfhack_headless(host, port, timeout_s=timeout_s)


def _reset_with_shutil(seed_dir: Path, current_dir: Path) -> None:
    if current_dir.exists():
        shutil.rmtree(current_dir)
    shutil.copytree(seed_dir, current_dir, symlinks=True)
    _make_writable(current_dir)


def _reset_with_sudo(seed_dir: Path, current_dir: Path) -> None:
    subprocess.check_call(["sudo", "-n", "rm", "-rf", str(current_dir)])
    subprocess.check_call(["sudo", "-n", "cp", "-a", str(seed_dir), str(current_dir)])
    subprocess.check_call(["sudo", "-n", "chmod", "-R", "u+w", str(current_dir)])


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


__all__ = ["SeedResetError", "maybe_reset_dfhack_seed", "reset_current_from_seed"]

