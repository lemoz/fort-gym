"""Checkpointable campaign execution, separate from frozen benchmark scoring.

The environment owns native controls and observations. This loop owns all Python
continuation state: action feedback, cursor, trace, agent state, and usage journal.
No strategy, automatic success stop, score threshold, or gameplay rescue lives here.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from ..agent.base import Agent
from ..env.actions import parse_action
from ..env.encoder import encode_observation
from ..eval.campaign import TICKS_PER_YEAR
from ..tick_receipt import MAX_REQUEST_OVERSHOOT_TICKS, validate_clean_interruption_receipt
from .campaign_checkpoint import create_checkpoint, verify_checkpoint
from .campaign_save import NativeSaveSnapshotter


class CampaignEnvironment(Protocol):
    """Each operation returns with native gameplay paused."""

    def observe(self) -> dict[str, Any]:
        ...

    def screen(self) -> str:
        ...

    def apply(self, action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        ...

    def advance(self, ticks: int, state: dict[str, Any]) -> tuple[dict, dict]:
        ...


def _append(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _clock(state: dict) -> int:
    year, tick = state.get("year"), state.get("year_tick")
    if type(year) is not int or year < 0 or type(tick) is not int or not 0 <= tick < TICKS_PER_YEAR:
        raise ValueError("Campaign observation lacks a valid native calendar")
    if state.get("pause_state") is not True:
        raise ValueError("Campaign boundary is not paused")
    return year * TICKS_PER_YEAR + tick


def _configuration(state: dict) -> str:
    return hashlib.sha256(json.dumps(state["configuration"], sort_keys=True).encode()).hexdigest()


def reconciled_usage(checkpoint: dict, journal: bytes) -> dict:
    """Keep charges from later decisions even when restoring an older game save.

    An interrupted provider dispatch cannot silently become a free request.
    Malformed, cross-campaign, regressing, or unaccounted usage remains unresolved.
    This reconciles returned usage, not a provider invoice.
    """
    if not journal.endswith(b"\n"):
        raise ValueError("Usage journal has an incomplete final record")
    records = [json.loads(line) for line in journal.splitlines()]
    expected = {
        "type": "campaign_journal",
        "campaign_id": checkpoint["campaign_id"],
        "configuration_sha256": _configuration(checkpoint),
    }
    if not records or records[0] != expected:
        raise ValueError("Usage journal does not identify this campaign configuration")
    current = deepcopy(checkpoint["usage"])
    pending = False
    pending_step = None
    last_usage = None
    for record in records[1:]:
        if record.get("type") == "decision_started" and not pending:
            if type(record.get("step")) is not int or record["step"] < 0:
                raise ValueError("Invalid decision step")
            pending_step = record["step"]
            pending = True
            continue
        if record.get("type") != "decision_finished" or not pending:
            raise ValueError("Usage journal decision sequence is invalid")
        if record.get("step") != pending_step or record.get("decision_returned") is not True:
            raise ValueError("Failed or mismatched decision has unresolved provider usage")
        pending = False
        usage = record["usage"]
        for key in ("total_tokens", "returned_responses", "accounted_responses"):
            if type(usage.get(key)) is not int or usage[key] < 0:
                raise ValueError("Invalid returned usage counter")
            if last_usage is not None and usage[key] < last_usage[key]:
                raise ValueError("Usage journal counter regressed")
        if usage["returned_responses"] != usage["accounted_responses"]:
            raise ValueError("Returned provider usage remains unaccounted")
        if not isinstance(usage.get("total_cost_usd"), str):
            raise ValueError("Usage cost must retain its decimal string")
        cost = Decimal(usage["total_cost_usd"])
        if not cost.is_finite() or cost < 0:
            raise ValueError("Invalid returned model cost")
        if last_usage is not None and cost < Decimal(last_usage["total_cost_usd"]):
            raise ValueError("Usage journal cost regressed")
        last_usage = usage
    if pending:
        raise ValueError("Interrupted model decision has unresolved provider usage")
    if last_usage is not None:
        for key in ("total_tokens", "returned_responses", "accounted_responses"):
            current[key] = max(current[key], last_usage[key])
        current["total_cost_usd"] = str(
            max(Decimal(current["total_cost_usd"]), Decimal(last_usage["total_cost_usd"]))
        )
    return current


class CampaignLoop:
    """One serial campaign. Checkpoint only after a durable action boundary."""

    def __init__(
        self,
        *,
        campaign_id: str,
        agent: Agent,
        environment: CampaignEnvironment,
        output: Path,
        max_advance_ticks: int = 2000,
    ) -> None:
        if type(max_advance_ticks) is not int or not 1 <= max_advance_ticks <= 2500:
            raise ValueError("Invalid campaign advance limit")
        agent.set_campaign_context(campaign_id=campaign_id)
        initial = agent.export_campaign_state()
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.agent, self.environment, self.output = agent, environment, output
        self.campaign_id, self.max_advance_ticks = campaign_id, max_advance_ticks
        self.trace = output / "trace.jsonl"
        self.journal = output / "usage.jsonl"
        self.next_step = 0
        self.history: list[dict] = []
        self.last_result: dict | None = None
        self.parent: Path | None = None
        self.at_boundary = False
        self.failed = False
        _append(
            self.journal,
            {
                "type": "campaign_journal",
                "campaign_id": campaign_id,
                "configuration_sha256": _configuration(initial),
            },
        )

    def step(self) -> dict:
        """Execute only this model's new decision; pending checkpoint actions are reviews."""
        if self.failed:
            raise RuntimeError("Failed campaign execution requires verified checkpoint recovery")
        try:
            return self._step()
        except BaseException:
            self.failed = True
            raise

    def _step(self) -> dict:
        from .runner import _action_history_entry

        self.at_boundary = False
        before = self.environment.observe()
        start = _clock(before)
        screen = self.environment.screen()
        text, observation = encode_observation(
            before,
            screen_text=screen,
            action_history=self.history,
            last_action_result=self.last_result,
            governed=True,
        )
        _append(self.journal, {"type": "decision_started", "step": self.next_step})
        returned = False
        try:
            raw_action = self.agent.decide(text, observation)
            returned = True
        finally:
            _append(
                self.journal,
                {
                    "type": "decision_finished",
                    "step": self.next_step,
                    "decision_returned": returned,
                    "usage": self.agent.export_campaign_state()["usage"],
                },
            )
        action = parse_action(raw_action, max_advance_ticks=self.max_advance_ticks)
        if action.get("type") not in {
            "DIG",
            "BUILD",
            "ORDER",
            "UNSUSPEND",
            "FARM",
            "LABOR",
            "WAIT",
            "INTERACT",
        }:
            raise ValueError("Campaign action is outside the declared governed interface")
        ticks = action.get("advance_ticks")
        if type(ticks) is not int or not 0 <= ticks <= self.max_advance_ticks:
            raise ValueError("Model action has no valid bounded advance_ticks")
        execution = self.environment.apply(action, before)
        requested = ticks if execution.get("accepted") is True else 0
        after, receipt = self.environment.advance(requested, before)
        end = _clock(after)
        actual = receipt.get("ticks_advanced")
        maximum = (
            min(self.max_advance_ticks, requested + MAX_REQUEST_OVERSHOOT_TICKS) if requested else 0
        )
        if type(actual) is not int or actual < 0 or end - start != actual or actual > maximum:
            raise ValueError("Native time disagrees with the action's tick receipt")
        if (
            receipt.get("ok") is not True
            and validate_clean_interruption_receipt(
                receipt,
                requested_ticks=requested,
                state_after_apply=before,
                state_after_advance=after,
            )
            is not None
        ):
            raise ValueError("Native tick operation did not finish or interrupt cleanly")
        tick_info = {
            **receipt,
            "start_year": before["year"],
            "start_tick": before["year_tick"],
            "end_year": after["year"],
            "end_tick": after["year_tick"],
        }
        history = _action_history_entry(
            step=self.next_step,
            action=action,
            requested_ticks=requested,
            tick_info=tick_info,
            execute_result=execution,
            state_before=before,
            advance_state=after,
            metrics_snapshot={},
        )
        row = {
            "run_id": self.campaign_id,
            "step": self.next_step,
            "observation": observation,
            "observation_text": text,
            "screen_text": screen,
            "action": action,
            "execute": execution,
            "state_after_advance": after,
            "tick_advance": tick_info,
            "events": [
                {
                    "type": "tool_call",
                    "data": {
                        **event,
                        "run_id": self.campaign_id,
                        "step": self.next_step,
                    },
                }
                for event in self.agent.pop_tool_events()
            ],
            "campaign_mode": True,
        }
        _append(self.trace, row)
        self.history = (self.history + [history])[-12:]
        self.last_result = execution
        self.next_step += 1
        self.at_boundary = True
        return row

    def checkpoint(
        self, destination: Path, *, snapshotter: NativeSaveSnapshotter, code_revision: str
    ) -> dict:
        if not self.at_boundary:
            raise ValueError("Campaign is not at a committed action boundary")
        result = create_checkpoint(
            destination,
            campaign_id=self.campaign_id,
            agent=self.agent,
            snapshotter=snapshotter,
            trace_path=self.trace,
            last_committed_step=self.next_step - 1,
            code_revision=code_revision,
            parent=self.parent,
            runner_state={
                "schema_version": "fortgym.campaign-loop/v1",
                "history": self.history,
                "last_result": self.last_result,
                "max_advance_ticks": self.max_advance_ticks,
            },
            usage_path=self.journal,
        )
        self.parent = destination
        return result

    @classmethod
    def resume(
        cls,
        checkpoint: Path,
        *,
        agent: Agent,
        environment: CampaignEnvironment,
        output: Path,
        latest_usage_path: Path,
    ) -> CampaignLoop:
        """Resume after the caller loads the verified game into its isolated runtime.

        The original run's latest journal is required, not just its older checkpoint
        copy, so post-checkpoint provider charges are retained. No action is replayed.
        """
        manifest = verify_checkpoint(checkpoint)
        if manifest["schema_version"] != "fortgym.campaign-checkpoint/v2":
            raise ValueError("Checkpoint does not contain complete campaign-loop state")
        payload = manifest["payload"]
        state = json.loads((checkpoint / "agent.json").read_text())
        runner = json.loads((checkpoint / "runner.json").read_text())
        if runner.get("schema_version") != "fortgym.campaign-loop/v1":
            raise ValueError("Unsupported campaign runner state")
        latest = latest_usage_path.read_bytes()
        if not latest.startswith((checkpoint / "usage.jsonl").read_bytes()):
            raise ValueError("Latest usage journal does not extend this checkpoint")
        state["usage"] = reconciled_usage(state, latest)
        loaded = environment.observe()
        saved = payload["native_save"]
        if _clock(loaded) != saved["year"] * TICKS_PER_YEAR + saved["year_tick"]:
            raise ValueError("Loaded native calendar differs from checkpoint")
        instance = cls(
            campaign_id=payload["campaign_id"],
            agent=agent,
            environment=environment,
            output=output,
            max_advance_ticks=runner["max_advance_ticks"],
        )
        agent.restore_campaign_state(state, campaign_id=payload["campaign_id"])
        # The new journal's header is identical; replace only this newly-created
        # owned file before exposing the resumed loop to callers.
        with instance.journal.open("wb") as stream:
            stream.write(latest)
            stream.flush()
            os.fsync(stream.fileno())
        with instance.trace.open("xb") as stream:
            stream.write((checkpoint / "trace.jsonl").read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        instance.history = runner["history"]
        instance.last_result = runner["last_result"]
        instance.next_step = payload["next_step"]
        instance.parent = checkpoint
        instance.at_boundary = True
        return instance
