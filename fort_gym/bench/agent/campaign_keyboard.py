"""Persistent keyboard policy; the caller supplies its credential-owning transport."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import hashlib
import json
from typing import Any

from ..env.native_key_catalog import CAMPAIGN_KEYBOARD_PROFILES, NATIVE_PROFILE
from ..env.display_key_catalog import BINDING_PROFILE, BINDINGS_SHA256
from ..env.screen_observation import TEXT_PROFILE, encode_screen, raw_screen
from .base import Agent
from .campaign_budget import BUDGET_KEYS, effective_budget
from .codex_transport import MODEL, REASONING_EFFORT, CodexTransportError
from .codex_selection import validate_selection
from .codex_protocol import TRANSPORT
from .governed_llm import GovernedBudgetCapError
from .standard_input import parse_response
from .keyboard_rejection import rejected_receipt
from .keyboard_prompt import BASE_PROMPT, ORIGIN_SCHEMA, effective_prompt, declared_prompt_change

SUBSCRIPTION_COST_BASIS = "codex_subscription_charge_unreported/v1"


class SubscriptionAdmissionPause(GovernedBudgetCapError):
    """A fresh host account check explicitly prevented the model invocation."""


def initial_usage() -> dict:
    return dict(
        total_tokens=0,
        returned_responses=0,
        accounted_responses=0,
        dispatched_requests=0,
        total_cost_usd=None,
        cost_basis=SUBSCRIPTION_COST_BASIS,
    )


def validate_usage(usage: dict) -> None:
    if not isinstance(usage, dict) or set(usage) != set(initial_usage()):
        raise ValueError("Invalid subscription usage fields")
    if usage["cost_basis"] != SUBSCRIPTION_COST_BASIS or usage["total_cost_usd"] is not None:
        raise ValueError("Subscription charge is unreported, not zero or an API estimate")
    for key in ("total_tokens", "returned_responses", "accounted_responses", "dispatched_requests"):
        if type(usage[key]) is not int or usage[key] < 0:
            raise ValueError("Invalid subscription usage counter")
    if (
        not usage["dispatched_requests"]
        >= usage["returned_responses"]
        == usage["accounted_responses"]
    ):
        raise ValueError("Subscription responses are not accounted")


class CodexKeyboardAgent(Agent):
    """Memory and usage survive native checkpoints; only the model chooses keys."""

    def __init__(
        self,
        *,
        decision: Callable[[dict, str, dict | None], dict],
        max_dispatches: int,
        max_total_tokens: int,
        max_advance_ticks: int = 2000,
        model: str = MODEL,
        reasoning_effort: str = REASONING_EFFORT,
        control_profile: str = NATIVE_PROFILE,
    ) -> None:
        validate_selection(model, reasoning_effort)
        if control_profile not in CAMPAIGN_KEYBOARD_PROFILES:
            raise ValueError("Unsupported keyboard campaign control profile")
        for value in (max_dispatches, max_total_tokens):
            if type(value) is not int or value < 1:
                raise ValueError("Positive cumulative keyboard budgets are required")
        if type(max_advance_ticks) is not int or not 1 <= max_advance_ticks <= 2500:
            raise ValueError("Invalid keyboard advance bound")
        self.configuration: dict[str, Any] = dict(
            model=model,
            reasoning_effort=reasoning_effort,
            transport=TRANSPORT,
            control_profile=control_profile,
            observation_profile=TEXT_PROFILE,
            max_dispatches=max_dispatches,
            max_total_tokens=max_total_tokens,
            max_advance_ticks=max_advance_ticks,
        )
        self.decision = decision
        if control_profile == BINDING_PROFILE:
            self.configuration["bindings_sha256"] = BINDINGS_SHA256
        self.campaign_id: str | None = None
        self.memory = ""
        self.usage = initial_usage()
        self.events: list[dict] = []
        self.budget_extensions: list[dict] = []
        self.prompt_changes: list[dict] = []

    @property
    def prompt_profile(self) -> str:
        return effective_prompt(self.prompt_changes, self.usage)

    def change_prompt(self, declaration: dict, *, profile: str,
                      checkpoint_sha256: str, next_step: int) -> dict:
        if self.campaign_id is None or self.events:
            raise ValueError("Prompt change requires a settled campaign")
        change = declared_prompt_change(
            self.export_campaign_state(), declaration, profile=profile,
            checkpoint_sha256=checkpoint_sha256, next_step=next_step,
        )
        assert change is not None
        self.prompt_changes.append(change)
        return deepcopy(change)

    def initialize_prompt(self, *, profile: str, source_snapshot_receipt_sha256: str) -> dict:
        """Declare a fresh trial's initial prompt, never relabel existing play.

        The first lineage entry is explicitly a snapshot-bound origin, not a
        checkpoint change. Historical agents with no origin still start at v1.
        """
        if (self.campaign_id is not None or self.memory or self.events
                or self.usage != initial_usage() or self.budget_extensions or self.prompt_changes):
            raise ValueError("Initial prompt requires a fresh unused keyboard agent")
        origin = {
            "schema_version": ORIGIN_SCHEMA, "profile": profile,
            "source_snapshot_receipt_sha256": source_snapshot_receipt_sha256,
            "usage": {"dispatched_requests": 0, "total_tokens": 0},
        }
        effective_prompt([origin], self.usage)
        self.prompt_changes.append(origin)
        return deepcopy(origin)

    def set_campaign_context(self, *, campaign_id: str) -> None:
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("Keyboard campaign identity is required")
        if self.campaign_id not in (None, campaign_id):
            raise ValueError("Cannot move an agent between campaigns")
        self.campaign_id = campaign_id

    def export_campaign_state(self) -> dict:
        return deepcopy(
            dict(
                schema_version="fortgym.codex-keyboard-agent/v1",
                campaign_id=self.campaign_id,
                configuration=self.configuration,
                memory=self.memory,
                usage=self.usage,
                **({"budget_extensions": self.budget_extensions} if self.budget_extensions else {}),
                **({"prompt_changes": self.prompt_changes} if self.prompt_changes else {}),
            )
        )

    def restore_campaign_state(self, data: dict, *, campaign_id: str) -> None:
        if self.usage != initial_usage() or self.memory or self.events or self.budget_extensions or self.prompt_changes:
            raise ValueError("Restore requires a fresh keyboard agent")
        expected = self.export_campaign_state()
        if (
            not isinstance(data, dict)
            or set(data) - {"budget_extensions", "prompt_changes"} != set(expected)
            or data["schema_version"] != expected["schema_version"]
            or data["configuration"] != self.configuration
            or data["campaign_id"] != campaign_id
            or not isinstance(data["memory"], str)
        ):
            raise ValueError("Keyboard checkpoint configuration or identity differs")
        validate_usage(data["usage"])
        extensions = deepcopy(data.get("budget_extensions", []))
        effective_budget(self.configuration, extensions, data["usage"])
        changes = deepcopy(data.get("prompt_changes", []))
        effective_prompt(changes, data["usage"])
        self.set_campaign_context(campaign_id=campaign_id)
        self.memory, self.usage = data["memory"], deepcopy(data["usage"])
        self.budget_extensions = extensions
        self.prompt_changes = changes

    def extend_budget(
        self, *, checkpoint_sha256: str, max_dispatches: int, max_total_tokens: int
    ) -> dict:
        """Declare a larger allowance after a verified, settled checkpoint resume.

        The caller supplies that checkpoint's manifest digest. Original condition,
        memory, usage and journal identity stay unchanged. Future checkpoints bind
        this append-only history alongside the complete agent state.
        """
        if self.campaign_id is None or self.events:
            raise ValueError("Budget extension requires a settled campaign")
        limits = effective_budget(self.configuration, self.budget_extensions, self.usage)
        extension = dict(
            schema_version="fortgym.campaign-budget-extension/v1",
            checkpoint_sha256=checkpoint_sha256,
            previous=limits,
            limits=dict(zip(BUDGET_KEYS, (max_dispatches, max_total_tokens))),
            usage_at_extension={
                key: self.usage[key] for key in ("dispatched_requests", "total_tokens")
            },
        )
        proposed = [*self.budget_extensions, extension]
        effective_budget(self.configuration, proposed, self.usage)
        self.budget_extensions = proposed
        return deepcopy(extension)

    def preflight_decision(self, obs_text: str, obs_json: dict) -> None:
        if self.campaign_id is None:
            raise ValueError("Keyboard campaign identity is unset")
        raw_screen(obs_json["screen_capture"])
        limits = effective_budget(self.configuration, self.budget_extensions, self.usage)
        if self.usage["dispatched_requests"] >= limits["max_dispatches"]:
            raise GovernedBudgetCapError("Cumulative subscription dispatch limit reached")
        if self.usage["total_tokens"] >= limits["max_total_tokens"]:
            raise GovernedBudgetCapError("Cumulative returned-token limit reached")

    def decide(self, obs_text: str, obs_json: dict) -> dict:
        self.preflight_decision(obs_text, obs_json)
        # The transport records request intent before launching. If it loses a
        # final receipt, this invocation remains unresolved and is never replayed.
        self.usage["dispatched_requests"] += 1
        result = self.decision(
            raw_screen(obs_json["screen_capture"]),
            self.memory,
            deepcopy(obs_json.get("last_action_feedback")),
        )
        self.events.append({"type": "codex_keyboard_decision", "receipt": deepcopy(result)})
        receipt = result.get("transport_receipt")
        if not isinstance(receipt, dict):
            raise CodexTransportError("Missing subscription usage receipt", result)
        if receipt.get("dispatched") is False:
            self.usage["dispatched_requests"] -= 1
            admission = receipt.get("admission")
            if (
                receipt.get("accepted") is False
                and set(receipt) == {"accepted", "dispatched", "admission"}
                and isinstance(admission, dict)
                and admission.get("allowed") is False
                and admission.get("basis") == "fresh_codex_app_server_account_read/v1"
            ):
                raise SubscriptionAdmissionPause("Subscription allowance stopped model admission")
        tokens = receipt.get("total_tokens")
        screen_hash = hashlib.sha256(
            json.dumps(
                encode_screen(obs_json["screen_capture"], TEXT_PROFILE),
                allow_nan=False,
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if type(tokens) is int and tokens >= 0 and receipt.get("usage"):
            self.usage["total_tokens"] += tokens
            self.usage["returned_responses"] += 1
            self.usage["accounted_responses"] += 1
        if (
            receipt.get("accepted") is not True
            or receipt.get("dispatched") is not True
            or receipt.get("model_requested") != self.configuration["model"]
            or receipt.get("reasoning_effort_requested") != self.configuration["reasoning_effort"]
            or receipt.get("auth_mode") != "chatgpt"
            or receipt.get("transport") != TRANSPORT
            or receipt.get("reported_charge_usd") is not None
            or result.get("control_profile") != self.configuration["control_profile"]
            or result.get("observation_profile") != TEXT_PROFILE
            or result.get("screen_sha256") != screen_hash
            or result.get("prompt_profile", BASE_PROMPT) != self.prompt_profile
            or type(tokens) is not int
            or tokens < 0
            or not receipt.get("usage")
        ):
            raise CodexTransportError("Keyboard decision or subscription identity failed", result)
        validate_usage(self.usage)
        if result.get("action_grammar_valid") is not True:
            if (
                result.get("action_grammar_valid") is not False
                or result.get("action") is not None
                or result.get("native_action_dispatched") is not False
                or result.get("error") != "Keyboard keys must be supported native interface events"
                or receipt.get("usage_complete") is not True
                or type(receipt.get("native_game_commands")) is not int
                or receipt.get("native_game_commands") != 0
                or receipt.get("timed_out") is not False
                or receipt.get("interrupted") is not False
            ):
                raise CodexTransportError("Keyboard rejection lacks complete non-execution proof", result)
            raise rejected_receipt(
                result, screen_sha256=screen_hash,
                max_advance_ticks=self.configuration["max_advance_ticks"],
                model=self.configuration["model"],
                reasoning_effort=self.configuration["reasoning_effort"],
                control_profile=self.configuration["control_profile"],
            )
        action = parse_response(
            result["action"],
            max_advance_ticks=self.configuration["max_advance_ticks"],
            control_profile=self.configuration["control_profile"],
        )
        self.memory = action["memory_update"]
        return action

    def pop_tool_events(self) -> list[dict]:
        events, self.events = self.events, []
        return events
