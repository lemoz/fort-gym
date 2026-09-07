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
from ..agent.campaign_keyboard import (
    SUBSCRIPTION_COST_BASIS,
    SubscriptionAdmissionPause,
    initial_usage as initial_subscription_usage,
    validate_usage,
)
from ..agent.standard_input import parse_response as parse_keyboard_response
from ..env.native_key_catalog import NATIVE_PROFILE
from ..env.screen_observation import TEXT_PROFILE, encode_screen
from ..agent.campaign_local import LocalOutputLimitPause
from ..agent.governed_llm import GovernedBudgetCapError
from ..env.campaign_view import (
    OBSERVATION_PROFILE as INSPECTION_PROFILE,
    parse_campaign_action,
    validate_map_read,
    view_selection,
)
from ..env.campaign_encoder import PROFILES as CAMPAIGN_OBSERVATION_PROFILES
from ..env.campaign_encoder import encode_campaign_observation
from ..env.encoder import encode_observation
from ..eval.campaign import TICKS_PER_YEAR
from ..tick_receipt import (
    MAX_REQUEST_OVERSHOOT_TICKS,
    validate_clean_interruption_receipt,
)
from .campaign_advance import ACCEPTED_ONLY, MODEL_REQUESTED, POLICIES, requested_ticks
from .campaign_checkpoint import create_checkpoint, verify_checkpoint
from .campaign_save import NativeSnapshotter
from .keyboard_clock import SCHEMA as MENU_DEFERRAL_SCHEMA, validate_menu_deferral


class CampaignEnvironment(Protocol):
    """Each operation returns with native gameplay paused."""

    def observe(self) -> dict[str, Any]: ...

    def screen(self) -> str: ...

    def screen_capture(self) -> dict: ...

    def inspect_map(self, selection: dict | None) -> dict: ...

    def apply(self, action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]: ...

    def advance(self, ticks: int, state: dict[str, Any]) -> tuple[dict, dict]: ...


class CampaignPreDispatchPause(GovernedBudgetCapError):
    """A read-only preflight stopped before the decision/usage transaction began."""

    decision_started = False


class CampaignAdmissionPause(CampaignPreDispatchPause):
    """A decision transaction settled without any model or native dispatch."""

    decision_started = True


class CampaignNoActionPause(RuntimeError):
    """An accounted output stop with a verified unchanged native boundary."""

    terminal_code = "campaign_output_token_limit"


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
    counters: tuple[str, ...] = ("total_tokens", "returned_responses", "accounted_responses")
    if "dispatched_requests" in current:
        if type(current["dispatched_requests"]) is not int or current["dispatched_requests"] < 0:
            raise ValueError("Invalid checkpoint dispatch counter")
        if current["dispatched_requests"] < current["returned_responses"]:
            raise ValueError("Checkpoint dispatch count is below returned responses")
        counters += ("dispatched_requests",)
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
        no_action = record.get("outcome") == "accounted_no_action/v1"
        cancelled = record.get("outcome") == "subscription_not_dispatched/v1"
        if record.get("step") != pending_step or (
            record.get("decision_returned") is not True and not no_action and not cancelled
        ):
            raise ValueError("Failed or mismatched decision has unresolved provider usage")
        pending = False
        usage = record["usage"]
        if cancelled:
            if (
                current.get("cost_basis") != SUBSCRIPTION_COST_BASIS
                or record.get("decision_returned") is not False
                or record.get("model_dispatched") is not False
                or record.get("native_action_dispatched") is not False
                or usage != (last_usage if last_usage is not None else initial_subscription_usage())
                or not isinstance(record.get("native_boundary"), dict)
            ):
                raise ValueError("Cancelled subscription decision changed usage or lacks proof")
            _clock(record["native_boundary"])
        if no_action:
            if (
                record.get("decision_returned") is not False
                or record.get("native_action_dispatched") is not False
                or record.get("reason") != "output_token_limit"
                or not isinstance(record.get("native_boundary"), dict)
                or type(usage.get("dispatched_requests")) is not int
                or usage["dispatched_requests"] < 1
                or usage.get("dispatched_requests") != usage.get("returned_responses")
                or (
                    last_usage is not None
                    and usage["returned_responses"] <= last_usage["returned_responses"]
                )
            ):
                raise ValueError("No-action pause does not establish accounted non-execution")
            _clock(record["native_boundary"])
        for key in counters:
            if type(usage.get(key)) is not int or usage[key] < 0:
                raise ValueError("Invalid returned usage counter")
            if last_usage is not None and usage[key] < last_usage[key]:
                raise ValueError("Usage journal counter regressed")
        if usage["returned_responses"] != usage["accounted_responses"]:
            raise ValueError("Returned provider usage remains unaccounted")
        if "dispatched_requests" in current and (
            usage["dispatched_requests"] < usage["returned_responses"]
        ):
            raise ValueError("Usage journal dispatch count is below returned responses")
        subscription = current.get("cost_basis") == SUBSCRIPTION_COST_BASIS
        if subscription:
            validate_usage(current)
            validate_usage(usage)
        elif usage.get("cost_basis") == SUBSCRIPTION_COST_BASIS:
            raise ValueError("Usage cost basis changed")
        elif not isinstance(usage.get("total_cost_usd"), str):
            raise ValueError("Usage cost must retain its decimal string")
        if not subscription:
            cost = Decimal(usage["total_cost_usd"])
            if not cost.is_finite() or cost < 0:
                raise ValueError("Invalid returned model cost")
            if last_usage is not None and cost < Decimal(last_usage["total_cost_usd"]):
                raise ValueError("Usage journal cost regressed")
        last_usage = usage
    if pending:
        raise ValueError("Interrupted model decision has unresolved provider usage")
    if last_usage is not None:
        for key in counters:
            current[key] = max(current[key], last_usage[key])
        if current.get("cost_basis") != SUBSCRIPTION_COST_BASIS:
            current["total_cost_usd"] = str(
                max(Decimal(current["total_cost_usd"]), Decimal(last_usage["total_cost_usd"]))
            )
    return current


class CampaignLoop:
    """One serial campaign with durable action or accounted no-action boundaries."""

    def __init__(
        self,
        *,
        campaign_id: str,
        agent: Agent,
        environment: CampaignEnvironment,
        output: Path,
        max_advance_ticks: int = 2000,
        observation_profile: str = "governed_review/v1",
        advance_policy: str = ACCEPTED_ONLY,
    ) -> None:
        if type(max_advance_ticks) is not int or not 1 <= max_advance_ticks <= 2500:
            raise ValueError("Invalid campaign advance limit")
        keyboard = observation_profile == TEXT_PROFILE
        if observation_profile not in (
            "governed_review/v1",
            TEXT_PROFILE,
            *CAMPAIGN_OBSERVATION_PROFILES,
        ):
            raise ValueError("Unsupported campaign observation profile")
        if observation_profile == INSPECTION_PROFILE and not callable(
            getattr(environment, "inspect_map", None)
        ):
            raise ValueError("Inspection profile requires the native read-only map capability")
        if advance_policy not in POLICIES:
            raise ValueError("Unsupported campaign advance policy")
        if (
            advance_policy != ACCEPTED_ONLY
            and observation_profile not in CAMPAIGN_OBSERVATION_PROFILES
            and not keyboard
        ):
            raise ValueError("Requested-time policy requires factual campaign observations")
        agent.set_campaign_context(campaign_id=campaign_id)
        initial = agent.export_campaign_state()
        if keyboard and (
            not callable(getattr(environment, "screen_capture", None))
            or getattr(environment, "control_profile", None) != NATIVE_PROFILE
            or initial["configuration"].get("control_profile") != NATIVE_PROFILE
            or initial["configuration"].get("observation_profile") != TEXT_PROFILE
            or initial["configuration"].get("max_advance_ticks") != max_advance_ticks
        ):
            raise ValueError("Keyboard observation, agent and native control profiles must match")
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.agent, self.environment, self.output = agent, environment, output
        self.campaign_id, self.max_advance_ticks = campaign_id, max_advance_ticks
        self.observation_profile = observation_profile
        self.observation_view: dict | None = None
        self.advance_policy = advance_policy
        self.trace = output / "trace.jsonl"
        self.journal = output / "usage.jsonl"
        self.next_step = 0
        self.committed_elapsed_ticks: int | None = 0
        self.history: list[dict] = []
        self.last_result: dict | None = None
        self.parent: Path | None = None
        self.at_boundary = False
        self.failed = False
        self.failure_context: dict = {}
        self.no_action_boundary: dict | None = None
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
        except CampaignNoActionPause:
            try:
                _append(
                    self.output / "pauses.jsonl",
                    {
                        "type": "accounted_no_action/v1",
                        "step": self.next_step,
                        "reason": "output_token_limit",
                        "decision_started": True,
                        "native_action_dispatched": False,
                        "native_boundary": self.no_action_boundary,
                        "events": self.agent.pop_tool_events(),
                    },
                )
            except BaseException:
                self.failed = True
                self.at_boundary = False
                raise
            self.at_boundary = True
            raise
        except CampaignPreDispatchPause as error:
            _append(
                self.output / "pauses.jsonl",
                {
                    "step": self.next_step,
                    "reason": str(error),
                    "decision_started": error.decision_started,
                    **({"events": self.agent.pop_tool_events()} if error.decision_started else {}),
                },
            )
            raise
        except BaseException as error:
            self.at_boundary = False
            self.failed = True
            _append(
                self.output / "failures.jsonl",
                {
                    "step": self.next_step,
                    "error_type": type(error).__name__,
                    "message": str(error),
                    # Failed decisions have no committed trace row. Retain their
                    # raw response/usage diagnostics privately, not as gameplay.
                    "events": self.agent.pop_tool_events(),
                    **self.failure_context,
                },
            )
            raise

    def _step(self) -> dict:
        from .runner import _action_history_entry

        self.failure_context = {}
        self.no_action_boundary = None
        before = self.environment.observe()
        start = _clock(before)
        if self.observation_profile == INSPECTION_PROFILE:
            self._observe_map(before, self.observation_view)
        keyboard = self.observation_profile == TEXT_PROFILE
        if keyboard:
            capture = self.environment.screen_capture()
            screen = json.dumps(encode_screen(capture, TEXT_PROFILE), ensure_ascii=False)
            feedback = None
            if self.last_result is not None:
                native = self.last_result.get("result", {})
                feedback = {
                    "accepted": self.last_result.get("accepted"),
                    "reason": self.last_result.get("why"),
                    "keys_confirmed": native.get("keys_confirmed"),
                    "command_mutation": native.get("command_mutation"),
                }
                if "tick_feedback" in self.last_result:
                    feedback["simulation"] = deepcopy(self.last_result["tick_feedback"])
            observation = {
                "observation_profile": TEXT_PROFILE,
                "screen_capture": capture,
                "last_action_feedback": feedback,
            }
            text = screen
        else:
            screen = self.environment.screen()
        if not keyboard and self.observation_profile in CAMPAIGN_OBSERVATION_PROFILES:
            # Dialog legality depends on the screen just read at this paused boundary.
            before["screen_text"] = screen
            text, observation = encode_campaign_observation(
                before,
                screen_text=screen,
                action_history=self.history,
                last_action_result=self.last_result,
                model_requested_time=self.advance_policy == MODEL_REQUESTED,
                profile=self.observation_profile,
                committed_elapsed_ticks=self.committed_elapsed_ticks,
                completed_decisions=self.next_step,
            )
        elif not keyboard:
            text, observation = encode_observation(
                before,
                screen_text=screen,
                action_history=self.history,
                last_action_result=self.last_result,
                governed=True,
            )
        preflight_state = deepcopy(self.agent.export_campaign_state())
        try:
            self.agent.preflight_decision(text, observation)
        except GovernedBudgetCapError as error:
            if self.agent.export_campaign_state() != preflight_state:
                raise ValueError("Decision preflight mutated campaign state") from error
            raise CampaignPreDispatchPause(str(error)) from error
        if self.agent.export_campaign_state() != preflight_state:
            raise ValueError("Decision preflight mutated campaign state")
        # From here, a failed decision may have dispatched or mutated memory.
        # A typed, fully-accounted output limit can settle a new no-action boundary;
        # all other exceptions retain the existing uncertain-decision behavior.
        self.at_boundary = False
        _append(self.journal, {"type": "decision_started", "step": self.next_step})
        returned = False
        no_action = None
        cancelled = None
        try:
            raw_action = self.agent.decide(text, observation)
            returned = True
        except SubscriptionAdmissionPause as error:
            if not keyboard or self.agent.export_campaign_state() != preflight_state:
                raise ValueError("Admission pause changed campaign state") from error
            after_decision = self.environment.observe()
            if _clock(after_decision) != start or (
                after_decision.get("viewscreen_type") != before.get("viewscreen_type")
            ):
                raise ValueError("Native boundary changed during admission") from error
            cancelled = {key: before[key] for key in ("year", "year_tick", "pause_state")}
        except LocalOutputLimitPause as error:
            usage = self.agent.export_campaign_state()["usage"]
            previous_usage = preflight_state["usage"]
            counts = [
                usage.get(key)
                for key in ("dispatched_requests", "returned_responses", "accounted_responses")
            ]
            if (
                any(type(value) is not int or value < 1 for value in counts)
                or len(set(counts)) != 1
                or counts[0] <= previous_usage.get("returned_responses", -1)
            ):
                raise ValueError("Output-limited decision has unresolved model usage") from error
            after_decision = self.environment.observe()
            if _clock(after_decision) != start or (
                after_decision.get("viewscreen_type") != before.get("viewscreen_type")
            ):
                raise ValueError(
                    "Native state changed during an output-limited decision"
                ) from error
            no_action = {key: before[key] for key in ("year", "year_tick", "pause_state")}
            if "viewscreen_type" in before:
                no_action["viewscreen_type"] = before["viewscreen_type"]
        finally:
            _append(
                self.journal,
                {
                    "type": "decision_finished",
                    "step": self.next_step,
                    "decision_returned": returned,
                    "usage": self.agent.export_campaign_state()["usage"],
                    **(
                        {
                            "outcome": "subscription_not_dispatched/v1",
                            "model_dispatched": False,
                            "native_action_dispatched": False,
                            "native_boundary": cancelled,
                        }
                        if cancelled is not None
                        else {}
                    ),
                    **(
                        {
                            "outcome": "accounted_no_action/v1",
                            "reason": "output_token_limit",
                            "native_action_dispatched": False,
                            "native_boundary": no_action,
                        }
                        if no_action is not None
                        else {}
                    ),
                },
            )
        if cancelled is not None:
            current = self.agent.export_campaign_state()
            if reconciled_usage(current, self.journal.read_bytes()) != current["usage"]:
                raise ValueError("Cancelled subscription usage does not reconcile")
            self.at_boundary = True
            raise CampaignAdmissionPause("Subscription allowance stopped model admission")
        if no_action is not None:
            current = self.agent.export_campaign_state()
            if reconciled_usage(current, self.journal.read_bytes()) != current["usage"]:
                raise ValueError("Output-limited decision usage does not reconcile")
            if self.next_step == 0 and not self.trace.exists():
                with self.trace.open("xb") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
            self.no_action_boundary = no_action
            raise CampaignNoActionPause("Accounted output limit before a native action")
        allow_view = self.observation_profile == INSPECTION_PROFILE
        action = (
            parse_keyboard_response(
                raw_action, max_advance_ticks=self.max_advance_ticks, control_profile=NATIVE_PROFILE
            )
            if keyboard
            else parse_campaign_action(
                raw_action, max_advance_ticks=self.max_advance_ticks, allow_view=allow_view
            )
        )
        if action.get("type") not in {
            "DIG",
            "BUILD",
            "ORDER",
            "UNSUSPEND",
            "FARM",
            "LABOR",
            "WAIT",
            "INTERACT",
            *(["VIEW"] if allow_view else []),
            *(["KEYSTROKE"] if keyboard else []),
        }:
            raise ValueError("Campaign action is outside the declared governed interface")
        ticks = action.get("advance_ticks")
        if type(ticks) is not int or not 0 <= ticks <= self.max_advance_ticks:
            raise ValueError("Model action has no valid bounded advance_ticks")
        next_view = self.observation_view
        if action["type"] == "VIEW":
            native_read = validate_map_read(
                self.environment.inspect_map(action["params"]), action["params"], before
            )
            accepted = native_read.get("ok") is True
            execution = {
                "accepted": accepted,
                "command_mutation": "not_attempted",
                "observation_changed": accepted,
                "result": {**native_read, "command_mutation": "not_attempted"},
            }
            if accepted:
                next_view = view_selection(action["params"])
            else:
                execution["why"] = native_read.get("error", "Native map inspection unavailable")
        else:
            execution = self.environment.apply(action, before)
        self.failure_context = {"action": action, "execute": execution}
        if keyboard and execution.get("accepted") is not True:
            native = execution.get("result", {})
            if native.get("command_mutation") != "not_attempted":
                raise ValueError(
                    "Keyboard input outcome is partial or unknown; no replay or clock step"
                )
        requested = requested_ticks(ticks, execution, self.advance_policy)
        after, receipt = self.environment.advance(requested, before)
        self.failure_context = {
            **self.failure_context,
            "tick_receipt": receipt,
            "requested_ticks": requested,
            "native_before": {
                key: before.get(key)
                for key in ("year", "year_tick", "pause_state", "viewscreen_type")
            },
            "native_after": {
                key: after.get(key)
                for key in ("year", "year_tick", "pause_state", "viewscreen_type")
            },
        }
        end = _clock(after)
        actual = receipt.get("ticks_advanced")
        maximum = (
            min(self.max_advance_ticks, requested + MAX_REQUEST_OVERSHOOT_TICKS) if requested else 0
        )
        if type(actual) is not int or actual < 0 or end - start != actual or actual > maximum:
            raise ValueError("Native time disagrees with the action's tick receipt")
        menu_deferral = "deferred" in receipt or receipt.get("schema_version") == MENU_DEFERRAL_SCHEMA
        if menu_deferral and (
            not keyboard
            or validate_menu_deferral(
                receipt, requested_ticks=requested, before=before, after=after
            ) is not None
        ):
            raise ValueError("Native menu deferral is not an attested unchanged boundary")
        if (
            receipt.get("ok") is not True
            and not menu_deferral
            and validate_clean_interruption_receipt(
                receipt,
                requested_ticks=requested,
                state_after_apply=before,
                state_after_advance=after,
            )
            is not None
        ):
            raise ValueError("Native tick operation did not finish or interrupt cleanly")
        if keyboard:
            # Factual control feedback only; no private stock/crew metrics or
            # prescribed recovery key is supplied to the campaign model.
            execution = {
                **execution,
                "tick_feedback": {
                    "requested_ticks": requested,
                    "ticks_advanced": actual,
                    "deferred": receipt.get("deferred") is True,
                    "reason": receipt.get("error"),
                },
            }
        if allow_view:
            self._observe_map(after, next_view)
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
        self.observation_view = deepcopy(next_view)
        self.history = (self.history + [history])[-12:]
        self.last_result = execution
        self.next_step += 1
        if self.committed_elapsed_ticks is not None:
            self.committed_elapsed_ticks += actual
        self.at_boundary = True
        return row

    def _observe_map(self, state: dict, selection: dict | None) -> None:
        native_read = validate_map_read(self.environment.inspect_map(selection), selection, state)
        state["map_view"] = {"selection": deepcopy(selection), "native": native_read}

    def checkpoint(
        self,
        destination: Path,
        *,
        snapshotter: NativeSnapshotter,
        code_revision: str,
        advance_parent: bool = True,
    ) -> dict:
        if not self.at_boundary:
            raise ValueError("Campaign is not at a settled action boundary")
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
                "observation_profile": self.observation_profile,
                "advance_policy": self.advance_policy,
                **(
                    {"observation_view": deepcopy(self.observation_view)}
                    if self.observation_profile == INSPECTION_PROFILE
                    else {}
                ),
            },
            usage_path=self.journal,
            no_action_boundary=self.no_action_boundary,
            pauses_path=self.output / "pauses.jsonl"
            if self.no_action_boundary is not None
            else None,
        )
        if advance_parent:
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
        observation_profile: str | None = None,
        advance_policy: str | None = None,
        budget_extension: dict | None = None,
    ) -> CampaignLoop:
        """Resume after the caller loads the verified game into its isolated runtime.

        The original run's latest journal is required, not just its older checkpoint
        copy, so post-checkpoint provider charges are retained. No action is replayed.
        """
        manifest = verify_checkpoint(checkpoint)
        if manifest["schema_version"] not in {
            "fortgym.campaign-checkpoint/v2",
            "fortgym.campaign-checkpoint/v3",
        }:
            raise ValueError("Checkpoint does not contain complete campaign-loop state")
        payload = manifest["payload"]
        state = json.loads((checkpoint / "agent.json").read_text())
        runner = json.loads((checkpoint / "runner.json").read_text())
        if runner.get("schema_version") != "fortgym.campaign-loop/v1":
            raise ValueError("Unsupported campaign runner state")
        saved_profile = runner.get("observation_profile", "governed_review/v1")
        if observation_profile is not None and observation_profile != saved_profile:
            raise ValueError("Requested observation profile differs from checkpoint")
        saved_view = None
        if saved_profile == INSPECTION_PROFILE:
            if "observation_view" not in runner:
                raise ValueError("Inspection checkpoint is missing its selected view")
            if runner["observation_view"] is not None:
                saved_view = view_selection(runner["observation_view"])
        saved_advance = runner.get("advance_policy", ACCEPTED_ONLY)
        if advance_policy is not None and advance_policy != saved_advance:
            raise ValueError("Requested advance policy differs from checkpoint")
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
            observation_profile=saved_profile,
            advance_policy=saved_advance,
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
        # Reconstruct once from the digest-bound canonical prefix, not from a
        # public report or requested ticks. Each subsequent commit adds its receipt.
        from ..eval.campaign import read_campaign_progress

        progress = read_campaign_progress(instance.trace)
        if (
            payload["next_step"] == 0
            and manifest["schema_version"] == "fortgym.campaign-checkpoint/v3"
        ):
            # A settled decision may precede the campaign's first game action.
            # The v3 verifier binds its genuinely empty trace and initial cursor.
            instance.committed_elapsed_ticks = 0
        else:
            with instance.trace.open() as stream:
                origin = json.loads(stream.readline())
            instance.committed_elapsed_ticks = (
                progress["elapsed_ticks"] if origin.get("step") == 0 else None
            )
        instance.parent = checkpoint
        instance.observation_view = saved_view
        instance.at_boundary = True
        if budget_extension is not None:
            from ..agent.campaign_keyboard import CodexKeyboardAgent

            if not isinstance(agent, CodexKeyboardAgent) or set(budget_extension) != {
                "max_dispatches",
                "max_total_tokens",
            }:
                raise ValueError("Unsupported campaign budget extension")
            agent.extend_budget(checkpoint_sha256=manifest["sha256"], **budget_extension)
        return instance
