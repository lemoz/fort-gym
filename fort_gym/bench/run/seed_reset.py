"""Helpers to reset DFHack saves from a pristine seed."""

from __future__ import annotations

import hashlib
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


def maybe_reset_dfhack_seed(
    settings: Settings,
    *,
    seed_save: str | None = None,
    runtime_save: str | None = None,
) -> None:
    """Reset the DFHack save to a pristine seed if configured.

    ``seed_save``/``runtime_save`` are per-run overrides (G6 generalization:
    a run may target a different embark than the deployment default). When
    omitted, ``FORT_GYM_SEED_SAVE`` is copied to the configured runtime save
    (defaults to ``current``) and the ``dfhack-headless`` service restarts so
    the new save is loaded.
    """

    seed_name = seed_save or settings.FORT_GYM_SEED_SAVE
    if not seed_name:
        return
    runtime_name = runtime_save or settings.FORT_GYM_RUNTIME_SAVE

    reset_save_from_seed(
        seed_name,
        runtime_name=runtime_name,
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
    seed_world = seed_dir / "world.sav"
    runtime_world = runtime_dir / "world.sav"
    if _path_is_file(seed_world):
        if not _path_is_file(runtime_world):
            raise SeedResetError("Seed reset is missing the runtime world.sav copy")
        if not _files_equal(seed_world, runtime_world):
            raise SeedResetError("Runtime world.sav differs from the pristine seed copy")

    if restart_service and host in {"127.0.0.1", "localhost"}:
        _restart_dfhack_headless(host, port, timeout_s=timeout_s)
        loadable_name = _resolve_loadable_save_name(
            seed_dir,
            saves_dir=saves_dir,
            runtime_name=runtime_name,
        )
        _load_runtime_save(loadable_name, timeout_s=max(timeout_s, 180.0))
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


def _path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        result = subprocess.run(
            ["sudo", "-n", "test", "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0


def _world_save_paths(saves_dir: Path) -> list[Path]:
    try:
        return [
            candidate / "world.sav"
            for candidate in saves_dir.iterdir()
            if candidate.is_dir() and (candidate / "world.sav").is_file()
        ]
    except OSError:
        try:
            output = subprocess.check_output(
                [
                    "sudo",
                    "-n",
                    "find",
                    str(saves_dir),
                    "-mindepth",
                    "2",
                    "-maxdepth",
                    "2",
                    "-type",
                    "f",
                    "-name",
                    "world.sav",
                    "-print0",
                ]
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SeedResetError(f"Cannot inspect save directory {saves_dir}: {exc}") from exc
        return [Path(value.decode()) for value in output.split(b"\0") if value]


def _files_equal(first: Path, second: Path) -> bool:
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        with first.open("rb") as first_handle, second.open("rb") as second_handle:
            while True:
                first_chunk = first_handle.read(1024 * 1024)
                second_chunk = second_handle.read(1024 * 1024)
                if first_chunk != second_chunk:
                    return False
                if not first_chunk:
                    return True
    except OSError:
        result = subprocess.run(
            ["sudo", "-n", "cmp", "-s", "--", str(first), str(second)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0


def pristine_seed_sha256(seed_name: str, *, dfroot: Path = DFROOT) -> str:
    """Return the byte identity used to attest repeated fixed-seed resets."""

    _validate_save_name(seed_name, label="seed")
    world_path = _resolve_seed_dir(dfroot, seed_name) / "world.sav"
    try:
        digest = hashlib.sha256()
        with world_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        try:
            output = subprocess.check_output(
                ["sudo", "-n", "sha256sum", "--", str(world_path)],
                text=True,
            )
            value = output.split()[0]
            if len(value) == 64:
                return value
        except (OSError, subprocess.CalledProcessError, IndexError) as exc:
            raise SeedResetError(f"Cannot hash pristine seed {world_path}: {exc}") from exc
    raise SeedResetError(f"Invalid SHA-256 output for pristine seed {world_path}")


def _resolve_loadable_save_name(
    seed_dir: Path,
    *,
    saves_dir: Path,
    runtime_name: str,
) -> str:
    """Resolve DF's canonical save folder after startup consumes a staging alias."""

    runtime_world = saves_dir / runtime_name / "world.sav"
    if _path_is_file(runtime_world):
        return runtime_name

    seed_world = seed_dir / "world.sav"
    if not _path_is_file(seed_world):
        raise SeedResetError(f"Seed save lacks world.sav: {seed_world}")

    matches: list[str] = []
    for candidate_world in _world_save_paths(saves_dir):
        candidate = candidate_world.parent
        try:
            _validate_save_name(candidate.name, label="canonical runtime")
        except SeedResetError:
            continue
        if _files_equal(seed_world, candidate_world):
            matches.append(candidate.name)

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SeedResetError(
            f"DF did not expose a loadable copy of seed {seed_dir.name!r} after restart"
        )
    raise SeedResetError(f"Ambiguous canonical save for seed {seed_dir.name!r}: {sorted(matches)}")


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
    "pristine_seed_sha256",
    "reset_save_from_seed",
    "reset_current_from_seed",
]
