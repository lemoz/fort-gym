"""Capture a completed native DF save while the campaign is paused.

This adapter runs where the DF save directory is mounted. It never resets a
seed, edits world counters, dismisses gameplay dialogs, or overwrites a snapshot.
Container callers must provide the same runtime's save mount and RPC route.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from ..dfhack_exec import run_command, run_lua_expr


class NativeSnapshotter(Protocol):
    """Capture a native save and return its verified metadata and file inventory."""

    def capture(self, destination: Path) -> dict[str, Any]: ...

_SAVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class CampaignSaveError(RuntimeError):
    """A save could not be bound to the paused action boundary."""


def save_inventory(root: Path) -> list[dict[str, Any]]:
    """Hash regular save files only; never dereference links out of the save."""
    if root.is_symlink() or not root.is_dir():
        raise CampaignSaveError("Save root must be a regular directory")
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CampaignSaveError("Save contains a symbolic link")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CampaignSaveError("Save contains a non-regular file")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise CampaignSaveError("Save changed while being read")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": after.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    if not any(record["path"] == "world.sav" and record["size_bytes"] > 0 for record in records):
        raise CampaignSaveError("Save is missing a nonempty world.sav")
    return records


def native_save_status() -> Mapping[str, Any]:
    # Keep the frozen M1b hook image unchanged. This probe uses only native,
    # read-only fields available in the attested 0.47.05-r8 runtime.
    output = run_lua_expr(
        """
local json = require('json')
if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    print(json.encode({ok = false, error = 'fortress_not_loaded'}))
    return
end
print(json.encode({
    ok = true,
    save_name = df.global.world.cur_savegame.save_dir,
    year = df.global.cur_year,
    year_tick = df.global.cur_year_tick,
    paused = df.global.pause_state,
    autosave_requested = df.global.ui.main.autosave_request,
}))
""",
        timeout=5,
    )
    result = json.loads(output)
    if not isinstance(result, dict):
        raise CampaignSaveError("Native save probe did not return a state object")
    return result


class NativeSaveSnapshotter:
    """Wait for native autosave completion, then copy and verify the save tree."""

    def __init__(
        self,
        *,
        dfroot: Path,
        status: Callable[[], Mapping[str, Any]] = native_save_status,
        request_save: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 120,
        minimum_free_bytes: int | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 600:
            raise ValueError("Save timeout must be between zero and 600 seconds")
        if minimum_free_bytes is not None and (
            type(minimum_free_bytes) is not int or minimum_free_bytes < 0
        ):
            raise ValueError("Minimum free space must be a nonnegative integer")
        self.dfroot = dfroot.resolve()
        self.status = status
        self.request_save = request_save or (lambda: run_command("quicksave", timeout=10))
        self.clock = clock
        self.sleep = sleep
        self.timeout_seconds = timeout_seconds
        self.minimum_free_bytes = minimum_free_bytes

    @staticmethod
    def _boundary(status: Mapping[str, Any]) -> tuple[str, int, int]:
        name = status.get("save_name")
        year, tick = status.get("year"), status.get("year_tick")
        if (
            status.get("ok") is not True
            or status.get("paused") is not True
            or not isinstance(name, str)
            or not _SAVE_NAME.fullmatch(name)
            or ".." in name
            or type(year) is not int
            or year < 0
            or type(tick) is not int
            or not 0 <= tick < 403200
        ):
            raise CampaignSaveError("Native checkpoint requires a paused, identified fortress")
        return name, year, tick

    @staticmethod
    def _signature(world: Path) -> tuple[int, int, int]:
        if world.is_symlink() or not world.is_file():
            raise CampaignSaveError("Native world.sav is missing or is a symbolic link")
        info = world.stat()
        return info.st_ino, info.st_size, info.st_mtime_ns

    def capture(self, destination: Path) -> dict[str, Any]:
        """Return evidence only after native completion and a verified stable copy.

        The caller must stop agent decisions/advancement for this operation.
        Failed partial copies are retained at the caller's new destination for
        diagnosis; they are not resumable checkpoints.
        """
        if destination.exists() or destination.is_symlink():
            raise CampaignSaveError("Snapshot destination already exists")
        initial = self.status()
        boundary = self._boundary(initial)
        if initial.get("autosave_requested") is not False:
            raise CampaignSaveError("Another native save is already pending or unknown")
        save_name, year, year_tick = boundary
        saves_root = self.dfroot / "data" / "save"
        source = saves_root / save_name
        if source.is_symlink() or source.resolve().parent != saves_root.resolve():
            raise CampaignSaveError("Native save path escapes the selected save directory")
        if source.resolve() in destination.resolve().parents:
            raise CampaignSaveError("Snapshot destination must be outside the live save")
        world = source / "world.sav"
        before = self._signature(world)
        self.request_save()
        deadline = self.clock() + self.timeout_seconds
        while self.clock() < deadline:
            try:
                current = self.status()
            except (OSError, RuntimeError):
                # Saving can temporarily stall RPC. Do not issue another save.
                self.sleep(0.1)
                continue
            if current.get("ok") is True:
                if self._boundary(current) != boundary:
                    raise CampaignSaveError("Fortress changed during native save")
                if current.get("autosave_requested") is False and self._signature(world) != before:
                    break
            self.sleep(0.1)
        else:
            raise CampaignSaveError("Native save completion was not observed before timeout")

        expected = save_inventory(source)
        if self.minimum_free_bytes is not None and (
            shutil.disk_usage(destination.parent).free
            - sum(record["size_bytes"] for record in expected)
            < self.minimum_free_bytes
        ):
            raise CampaignSaveError("Native snapshot would cross the declared free-space floor")
        shutil.copytree(source, destination, symlinks=True)
        actual = save_inventory(destination)
        final_deadline = self.clock() + self.timeout_seconds
        while self.clock() < final_deadline:
            try:
                final = self.status()
                break
            except (OSError, RuntimeError):
                # A completed copy is not evidence of the final native boundary.
                # Retry only the read, never repeat the save or accept stale state.
                self.sleep(0.1)
        else:
            raise CampaignSaveError("Native state could not be verified after snapshot copy")
        if (
            actual != expected
            or save_inventory(source) != expected
            or self._boundary(final) != boundary
            or final.get("autosave_requested") is not False
        ):
            raise CampaignSaveError("Native save or fortress changed during snapshot copy")
        return {
            "schema_version": "fortgym.native-save-snapshot/v1",
            "save_name": save_name,
            "year": year,
            "year_tick": year_tick,
            "paused": True,
            "files": actual,
        }
