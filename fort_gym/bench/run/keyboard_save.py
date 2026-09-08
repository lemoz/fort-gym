"""Explicitly selected menu-preserving native snapshots; legacy saves unchanged."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..dfhack_exec import run_lua_expr
from .campaign_save import CampaignSaveError, NativeSaveSnapshotter, native_save_status
from ..env.screen_observation import raw_screen
from .keyboard_save_lua import MENU_IDENTITY_SAVE_LUA, MENU_SAVE_LUA, MENU_SETTLED_IDENTITY_SAVE_LUA
from .keyboard_save_probe import (
    MENU_IDENTITY_PROBE_LUA, validate_identity_probe, validate_menu_stack,
    validate_settled_identity, validate_ui_identity,
)

LEGACY_SAVE_PROFILE = "native_quicksave/v1"
MENU_SAVE_PROFILE = "native_menu_preserving_save/v1"
MENU_IDENTITY_SAVE_PROFILE = "native_menu_preserving_save/v2"
MENU_SETTLED_IDENTITY_SAVE_PROFILE = "native_menu_preserving_save/v3"
SEMANTIC_SAVE_PROFILES = (MENU_IDENTITY_SAVE_PROFILE, MENU_SETTLED_IDENTITY_SAVE_PROFILE)
SAVE_PROFILES = (LEGACY_SAVE_PROFILE, MENU_SAVE_PROFILE, *SEMANTIC_SAVE_PROFILES)


def validate_menu_save(receipt: Any, dfroot: Path, *, profile: str = MENU_SAVE_PROFILE) -> dict:
    """Require one completed, identified save with unchanged native/menu state."""
    if profile not in (MENU_SAVE_PROFILE, *SEMANTIC_SAVE_PROFILES):
        raise CampaignSaveError("Unsupported menu save profile")
    version = profile.rsplit("/", 1)[1]
    if not isinstance(receipt, dict) or (
        receipt.get("schema_version") != "fortgym.native-menu-save/" + version
        or any(
            receipt.get(key) is not True
            for key in (
                "ok",
                "menu_stack_restored",
                "backup_setting_restored",
            )
        )
        or "error" in receipt
        or type(receipt.get("gameplay_keys_sent")) is not int
        or receipt["gameplay_keys_sent"] != 0
        or type(receipt.get("native_logic_calls_requested")) is not int
        or receipt["native_logic_calls_requested"] != 1
        or not isinstance(receipt.get("dfhack_version"), str)
        or not receipt["dfhack_version"]
    ):
        raise CampaignSaveError("Native menu save receipt is invalid")
    before, after = receipt.get("native_before"), receipt.get("native_after")
    if not isinstance(before, dict) or not isinstance(after, dict) or before != after:
        raise CampaignSaveError("Native menu save boundary changed")
    for boundary in (before, after):
        if boundary.get("dfroot") != str(dfroot.resolve()) or (
            boundary.get("autosave_requested") is not False
        ):
            raise CampaignSaveError("Native menu save runtime or completion differs")
        NativeSaveSnapshotter._boundary({**boundary, "ok": True})
    validate_menu_stack(receipt.get("original_stack"))
    if profile in SEMANTIC_SAVE_PROFILES:
        for key in ("ui_before", "ui_after"):
            validate_ui_identity(receipt.get(key))
    if profile == MENU_IDENTITY_SAVE_PROFILE:
        if receipt["ui_before"] != receipt["ui_after"]:
            raise CampaignSaveError("Native menu identity changed during save")
    if profile == MENU_SETTLED_IDENTITY_SAVE_PROFILE:
        validate_settled_identity(receipt, dfroot)
    return receipt


class MenuPreservingSnapshotter:
    """Save without menu dismissal, and retain the verified operational receipt.

    Callers must keep the native process paused and suspend model decisions.
    A failed operation is never retried; any copied files remain forensic only.
    """

    def __init__(
        self,
        *,
        dfroot: Path,
        screen_capture: Callable[[], dict],
        minimum_free_bytes: int | None = None,
        profile: str = MENU_SAVE_PROFILE,
        observe: Callable[[], dict] | None = None,
        status: Callable[[], Mapping[str, Any]] = native_save_status,
        execute: Callable[..., str] = run_lua_expr,
    ) -> None:
        self.dfroot = dfroot.resolve()
        if profile not in (MENU_SAVE_PROFILE, *SEMANTIC_SAVE_PROFILES):
            raise ValueError("Unsupported native menu save profile")
        if profile in SEMANTIC_SAVE_PROFILES and not callable(observe):
            raise ValueError("Semantic menu saving requires recorded world observations")
        self.profile, self.observe = profile, observe
        if any(ord(char) < 32 for char in str(self.dfroot)):
            raise ValueError("Snapshot runtime path contains control characters")
        self.screen_capture, self.execute = screen_capture, execute
        self.receipt: dict | None = None
        self.attempt: dict[str, Any] = {}
        self.snapshotter = NativeSaveSnapshotter(
            dfroot=self.dfroot,
            status=status,
            request_save=self._request,
            minimum_free_bytes=minimum_free_bytes,
        )

    def _identity_probe(self, key: str) -> dict:
        expression = "local expected_root = " + json.dumps(str(self.dfroot), ensure_ascii=False)
        raw = self.execute(expression + "\n" + MENU_IDENTITY_PROBE_LUA, timeout=5)
        self.attempt[key + "_raw"] = raw
        try:
            probe = validate_identity_probe(json.loads(raw), self.dfroot)
        except (TypeError, ValueError) as error:
            raise CampaignSaveError("Native menu identity probe returned malformed JSON") from error
        self.attempt[key] = probe
        return probe

    def _request(self) -> None:
        expression = "local expected_root = " + json.dumps(str(self.dfroot), ensure_ascii=False)
        operation = {
            MENU_SAVE_PROFILE: MENU_SAVE_LUA,
            MENU_IDENTITY_SAVE_PROFILE: MENU_IDENTITY_SAVE_LUA,
            MENU_SETTLED_IDENTITY_SAVE_PROFILE: MENU_SETTLED_IDENTITY_SAVE_LUA,
        }[self.profile]
        settled = self.profile == MENU_SETTLED_IDENTITY_SAVE_PROFILE
        before = self._identity_probe("identity_before") if settled else None
        raw = self.execute(expression + "\n" + operation, timeout=120)
        # Retain the unvalidated response before semantic validation can raise.
        # It is private diagnostic evidence, never a verified save receipt.
        self.attempt["save_operation_raw"] = raw
        after = self._identity_probe("identity_after") if settled else None
        try:
            receipt = json.loads(raw)
            if settled and isinstance(receipt, dict):
                receipt = {**receipt, "identity_before": before, "identity_after": after}
            self.receipt = validate_menu_save(receipt, self.dfroot, profile=self.profile)
            self.attempt["save_operation"] = self.receipt
        except (TypeError, ValueError) as error:
            raise CampaignSaveError("Native menu save returned malformed JSON") from error

    def capture(self, destination: Path) -> dict[str, Any]:
        self.receipt = None
        self.attempt = {"schema_version": "fortgym.native-menu-save-attempt/v1"}
        semantic = self.profile in SEMANTIC_SAVE_PROFILES
        world_bytes = None
        if semantic:
            assert self.observe is not None
            world_bytes = json.dumps(self.observe(), sort_keys=True, allow_nan=False).encode()
            self.attempt["world_before"] = json.loads(world_bytes)
        before = self.screen_capture()
        screen_bytes = json.dumps(before, sort_keys=True, allow_nan=False).encode()
        self.attempt["screen_before"] = json.loads(screen_bytes)
        try:
            native = self.snapshotter.capture(destination)
        except Exception:
            # The native save may already have completed when receipt validation
            # fails. Read the aftermath without retrying or masking that failure.
            captures = {"screen_after": self.screen_capture}
            if semantic and self.observe is not None:
                captures["world_after"] = self.observe
            for key, capture in captures.items():
                try:
                    self.attempt[key] = json.loads(
                        json.dumps(capture(), sort_keys=True, allow_nan=False)
                    )
                except Exception as error:
                    self.attempt.setdefault("capture_errors", {})[key] = type(error).__name__
            raise
        self.attempt["copied_native_save"] = native
        after = self.screen_capture()
        after_bytes = json.dumps(after, sort_keys=True, allow_nan=False).encode()
        self.attempt["screen_after"] = json.loads(after_bytes)
        if self.receipt is None or (not semantic and after_bytes != screen_bytes):
            raise CampaignSaveError("Native screen changed during menu-preserving save")
        if semantic:
            before_grid, after_grid = raw_screen(before), raw_screen(after)
            if (before_grid["width"], before_grid["height"]) != (after_grid["width"], after_grid["height"]):
                raise CampaignSaveError("Native screen dimensions changed during save")
            assert self.observe is not None
            world_after = json.dumps(self.observe(), sort_keys=True, allow_nan=False).encode()
            self.attempt["world_after"] = json.loads(world_after)
            if world_after != world_bytes:
                raise CampaignSaveError("Recorded world observations changed during save")
        boundary = self.receipt["native_before"]
        if any(
            native[key] != boundary[key] for key in ("save_name", "year", "year_tick", "paused")
        ):
            raise CampaignSaveError("Native menu receipt differs from copied save")
        return {
            **native,
            "snapshot_profile": self.profile,
            "save_operation": self.receipt,
            "screen_unchanged": after_bytes == screen_bytes,
            "screen_sha256": hashlib.sha256(screen_bytes).hexdigest(),
            **({"screen_after_sha256": hashlib.sha256(after_bytes).hexdigest(),
                "world_observations_unchanged": True, "ui_identity_unchanged": True}
               if semantic else {}),
        }
