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
from ..dfhack_backend import ensure_paused_external, read_fort_metrics, read_job_metrics
from ..dfhack_exec import run_lua_expr
from ..env.dfhack_client import DFHackClient
from ..env.executor import Executor
from ..env.state_reader import StateReader
from ..env.workshop_placement import (
    NATIVE_GROUND,
    STRICT_FLOOR,
    policy_observation,
    validate_policy,
)
from .campaign_save import native_save_status


class NativeCampaignEnvironment:
    """Reuse the existing legal executor, keeping all campaign state in the loop."""

    def __init__(
        self,
        *,
        expected_dfroot: Path,
        workshop_placement_policy: str = STRICT_FLOOR,
        max_advance_ticks: int = 2000,
    ) -> None:
        if type(max_advance_ticks) is not int or not 1 <= max_advance_ticks <= 2500:
            raise ValueError("Invalid campaign tick limit")
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
        }
        state["fort"] = read_fort_metrics()
        state["crew"] = read_job_metrics()
        if self.workshop_placement_policy == NATIVE_GROUND:
            state["workshop_placement"] = policy_observation()
        # No G7 event monitor is started/reset here. Stock and structure observations
        # are retained directly; production/consumption rates remain unavailable
        # until a campaign-scoped native measurement lifecycle is implemented.
        return state

    def screen(self) -> str:
        self._verify_runtime()
        return self.client.get_screen_text(include_visual_hints=True)

    def apply(self, action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        self._verify_runtime()
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
        self.client.advance(
            ticks,
            interrupt_on_viewscreen_transition=True,
            viewscreen_before=str(before.get("viewscreen_type") or "unknown"),
            max_advance_ticks=self.max_advance_ticks,
        )
        return self.observe(), dict(self.client.last_tick_info)

    def close(self) -> None:
        self.client.close()
