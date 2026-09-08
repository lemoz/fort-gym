"""Native campaign adapter for a caller-owned, already loaded isolated runtime.

No provisioning, reset, strategy, inventory injection, or scoring lifecycle. The
runtime owner must load a verified save before constructing this adapter and tear
down the owned process after closing it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..dfhack_backend import _hook_path, ensure_paused_external
from ..dfhack_exec import DFHackError, run_lua_expr, run_lua_file
from ..env.actions import INTERACT_ALLOWED_VIEWSCREEN_TYPES
from ..env.campaign_keyboard import (
    HELPER_CONTROL_PROFILE,
    execute_campaign_keys,
)
from ..env.native_key_catalog import KEYBOARD_PROFILES, NATIVE_PROFILE
from ..env.dfhack_client import DFHackClient
from ..env.executor import Executor
from ..env.screen_observation import raw_screen
from ..env.state_reader import StateReader
from ..env.campaign_view import MAP_SCHEMA, view_selection
from ..env.workshop_placement import (
    NATIVE_GROUND,
    STRICT_FLOOR,
    policy_observation,
    validate_policy,
)
from .campaign_save import native_save_status
from .keyboard_clock import BLOCKING_FOCI, SCHEMA as MENU_DEFERRAL_SCHEMA, validate_menu_deferral
from .keyboard_clock_timeout import (
    SCHEMA as CLOCK_UNAVAILABLE_SCHEMA, validate_clock_unavailable, validate_zero_tick_timeout,
)


def read_campaign_fort_metrics() -> dict[str, Any]:
    """Read versioned campaign structures without changing historical scoring hooks."""
    try:
        return run_lua_file(_hook_path("campaign_fort_metrics_v1.lua"), timeout=10.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def read_campaign_job_metrics() -> dict[str, Any]:
    """Read campaign crew detail without a runner-authored target rectangle."""
    try:
        return run_lua_file(_hook_path("campaign_job_metrics_v1.lua"), timeout=5.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


class NativeCampaignEnvironment:
    """Reuse the existing legal executor, keeping all campaign state in the loop."""

    def __init__(
        self,
        *,
        expected_dfroot: Path,
        workshop_placement_policy: str = STRICT_FLOOR,
        max_advance_ticks: int = 2000,
        control_profile: str = HELPER_CONTROL_PROFILE,
    ) -> None:
        if type(max_advance_ticks) is not int or not 1 <= max_advance_ticks <= 2500:
            raise ValueError("Invalid campaign tick limit")
        if control_profile not in (HELPER_CONTROL_PROFILE, *KEYBOARD_PROFILES):
            raise ValueError("Invalid campaign control profile")
        self.control_profile = control_profile
        self.max_advance_ticks = max_advance_ticks
        self.workshop_placement_policy = validate_policy(workshop_placement_policy)
        self.expected_dfroot = expected_dfroot.resolve()
        self._verify_runtime()
        settings = get_settings()
        self.client = DFHackClient(host=settings.DFHACK_HOST, port=settings.DFHACK_PORT)
        self.client.connect()
        self.executor = Executor(
            dfhack_client=self.client,
            allow_assisted_dig_completion=False,
            workshop_placement_policy=self.workshop_placement_policy,
        )
        try:
            if ensure_paused_external(timeout=2.5, attempts=2).get("ok") is not True:
                raise RuntimeError("Native campaign could not verify paused startup")
            self.client.set_work_metrics_global_only(True)
            self.observe()
        except BaseException:
            self.client.close()
            raise

    def _verify_runtime(self) -> None:
        observed = json.loads(
            run_lua_expr("print(require('json').encode({dfroot = dfhack.getDFPath()}))", timeout=5)
        )
        if Path(observed["dfroot"]).resolve() != self.expected_dfroot:
            raise RuntimeError("Campaign RPC does not identify the expected isolated runtime")

    def observe(self) -> dict[str, Any]:
        self._verify_runtime()
        native = dict(native_save_status())
        if native.get("ok") is not True or native.get("paused") is not True:
            raise RuntimeError("Native campaign observation is not a loaded paused fortress")
        state = StateReader.from_dfhack(self.client, require_native=True)
        state.update(
            year=native["year"],
            year_tick=native["year_tick"],
            pause_state=native["paused"],
            time=native["year_tick"],
        )
        state["campaign_observation_quality"] = {
            "schema_version": "fortgym.campaign-observation-quality/v2",
            "native_population_and_stock_value_types_validated": True,
            "population_source": "active living native citizens",
            "stock_sources": "see stock_observations; missing source or completeness is unknown",
            "stock_validation_scope": "nonnegative integer values, not freshness or accessibility",
            "food_drink_flow_measurement": "unavailable",
            "structure_and_crew_measurement": "fortgym.campaign-native-metrics/v1",
        }
        state["fort"] = read_campaign_fort_metrics()
        state["crew"] = read_campaign_job_metrics()
        if self.workshop_placement_policy == NATIVE_GROUND:
            state["workshop_placement"] = policy_observation()
        # No G7 event monitor is started/reset here. Stock and structure observations
        # are retained directly; production/consumption rates remain unavailable
        # until a campaign-scoped native measurement lifecycle is implemented.
        return state

    def screen(self) -> str:
        self._verify_runtime()
        return self.client.get_screen_text(include_visual_hints=True)

    def screen_capture(self) -> dict:
        """Read actual tiles at a stable paused boundary, without internal metrics.

        This checks the loaded fortress and calendar around CopyScreen. It does
        not force a render or prove that a frame reflects a just-dispatched key.
        The keyboard executor still owns UI-transition/freshness validation.
        """
        self._verify_runtime()

        def boundary() -> tuple[str, int, int]:
            state = native_save_status()
            name, year, tick = state.get("save_name"), state.get("year"), state.get("year_tick")
            if (
                state.get("ok") is not True
                or state.get("paused") is not True
                or not isinstance(name, str)
                or not name
                or type(year) is not int
                or year < 0
                or type(tick) is not int
                or not 0 <= tick < 403200
            ):
                raise RuntimeError("Native screen capture requires a paused, identified fortress")
            return name, year, tick

        before = boundary()
        capture = raw_screen(self.client.get_screen())
        if boundary() != before:
            raise RuntimeError("Native screen capture crossed a fortress or calendar boundary")
        self._verify_runtime()
        return capture

    def inspect_map(self, selection: dict | None) -> dict:
        """Read only the model-selected terrain window, without changing native UI."""
        self._verify_runtime()
        args = []
        if selection is not None:
            selected = view_selection(selection)
            args = [str(n) for n in [*selected["origin"], *selected["size"]]]
        try:
            return run_lua_file(_hook_path("campaign_map_view_v1.lua"), *args, timeout=5.0)
        except (DFHackError, OSError) as exc:
            return {"schema_version": MAP_SCHEMA, "ok": False, "error": str(exc)}

    def apply(self, action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        self._verify_runtime()
        if getattr(self, "control_profile", HELPER_CONTROL_PROFILE) in KEYBOARD_PROFILES:
            if action.get("type") != "KEYSTROKE":
                return {
                    "accepted": False,
                    "why": "The native keyboard condition does not expose DFHack shortcuts",
                    "command_mutation": "not_attempted",
                }
            params = action.get("params")
            return execute_campaign_keys(
                params.get("keys") if isinstance(params, dict) else None,
                expected_dfroot=self.expected_dfroot,
                year=state.get("year"),
                year_tick=state.get("year_tick"),
                control_profile=self.control_profile,
            )
        viewscreen = state.get("viewscreen_type")
        if (
            state.get("pause_state") is True
            and viewscreen in INTERACT_ALLOWED_VIEWSCREEN_TYPES
            and action.get("type") != "INTERACT"
        ):
            # A model can make an invalid choice on a dialog and try again.
            # Do not send a world command, advance a blocked clock, or choose
            # a dialog option for it. The next decision gets this rejection.
            return {
                "accepted": False,
                "why": (
                    f"Native dialog {viewscreen!r} blocks simulation; choose an "
                    "allowed INTERACT operation with advance_ticks=0."
                ),
                "command_mutation": "not_attempted",
                "simulation_blocked_by": viewscreen,
            }
        execution = self.executor.apply(action, backend="dfhack", state=state, allow_interact=True)
        # Executor's result-less rejections are Python validation branches before
        # native dispatch. Every dispatched helper (including INTERACT) returns a
        # nested result; its native write-phase receipt must speak for itself.
        if execution.get("accepted") is False and "result" not in execution:
            execution = {**execution, "command_mutation": "not_attempted"}
        return execution

    def advance(self, ticks: int, state: dict[str, Any]) -> tuple[dict, dict]:
        if type(ticks) is not int or not 0 <= ticks <= self.max_advance_ticks:
            raise ValueError("Advance exceeds the declared campaign tick limit")
        before = self.observe()
        if ticks == 0:
            return before, {"ok": True, "ticks_advanced": 0, "skipped": True}
        if getattr(self, "control_profile", HELPER_CONTROL_PROFILE) == NATIVE_PROFILE:
            # This v2 clock fix does not change the historical v1 condition.
            # An empty keyboard batch is a read-only, runtime/calendar-bound
            # probe. Never press Escape or alter a model-selected menu here.
            def probe() -> dict:
                execution = execute_campaign_keys(
                    [], expected_dfroot=self.expected_dfroot,
                    year=before.get("year"), year_tick=before.get("year_tick"),
                    control_profile=self.control_profile,
                )
                if execution.get("accepted") is not True:
                    raise RuntimeError("Keyboard clock preflight could not attest native UI")
                return execution["result"]["native_receipts"][0]["after"]

            initial = probe()
            if initial.get("focus") in BLOCKING_FOCI:
                after = self.observe()
                receipt = {
                    "schema_version": MENU_DEFERRAL_SCHEMA,
                    "ok": False, "deferred": True, "error": "blocking_native_menu",
                    "requested": ticks, "ticks_advanced": 0,
                    "clock_dispatched": False, "timeout": False,
                    "native_before": initial, "native_after": probe(),
                }
                error = validate_menu_deferral(
                    receipt, requested_ticks=ticks, before=state, after=after
                )
                if error is not None:
                    raise RuntimeError(error)
                return after, receipt
        self.client.advance(
            ticks,
            interrupt_on_viewscreen_transition=True,
            viewscreen_before=str(before.get("viewscreen_type") or "unknown"),
            max_advance_ticks=self.max_advance_ticks,
        )
        after, receipt = self.observe(), dict(self.client.last_tick_info)
        if (
            getattr(self, "control_profile", HELPER_CONTROL_PROFILE) == NATIVE_PROFILE
            and validate_zero_tick_timeout(receipt, requested_ticks=ticks, state=after) is None
        ):
            # Retain the failed operation verbatim and attest its settled native
            # boundary. Do not retry, choose a key, or report requested time as real.
            receipt = {
                **receipt, "schema_version": CLOCK_UNAVAILABLE_SCHEMA,
                "clock_unavailable": True, "clock_dispatched": True,
                "native_before": initial, "native_after": probe(),
            }
            error = validate_clock_unavailable(
                receipt, requested_ticks=ticks, before=state, after=after,
            )
            if error is not None:
                raise RuntimeError(error)
        return after, receipt

    def close(self) -> None:
        self.client.close()
