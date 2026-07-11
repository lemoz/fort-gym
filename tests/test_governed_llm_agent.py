from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest

import fort_gym.bench.agent.governed_llm  # noqa: F401 - registration side effect
from fort_gym.bench.agent.base import AGENT_FACTORIES
from fort_gym.bench.agent.governed_llm import (
    DEFAULT_ADVANCE_TICKS,
    GOVERNED_ACTION_TYPES,
    GOVERNED_SYSTEM_PROMPT,
    MAX_OBJECTIVE_LENGTH,
    DFHackGovernedLLMAgent,
    _submit_action_tool,
)
from fort_gym.bench.env.actions import normalized_action_fingerprint, parse_action
from fort_gym.bench.api.schemas import ModelType
from fort_gym.bench.api.server import OPTIONAL_AGENT_MODULES
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import (
    ASSISTED_DFHACK_ACTIONS,
    GOVERNED_DFHACK_ACTIONS,
    GOVERNED_DFHACK_MODELS,
    _is_governed_dfhack_model,
    _is_keystroke_model,
)


def _submit_action_response(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_submit",
                            function=SimpleNamespace(
                                name="submit_action",
                                arguments=json.dumps(payload),
                            ),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _text_action_response(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload), tool_calls=None)
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class _FakeCompletions:
    def __init__(self, responses: list[Any] | None = None, error: Exception | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses = list(responses or [])
        self.error = error

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses: list[Any] | None = None, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses, error))


def _agent(
    responses: list[Any] | None = None,
    error: Exception | None = None,
    *,
    max_attempts: int = 1,
    model_override: str | None = "openai/gpt-5.5",
) -> DFHackGovernedLLMAgent:
    agent = DFHackGovernedLLMAgent(
        api_key="test-key",
        max_attempts=max_attempts,
        memory_path=None,
        model_override=model_override,
    )
    agent._client = _FakeClient(responses, error)
    return agent


def _plan_control(
    *,
    review_due: bool = True,
    request_id: str = "0:initial",
    prior_objective: str = "",
    previous_step: int = -1,
    previous_verdict: str = "unknown",
    previous_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_outcome = None
    if previous_step >= 0:
        previous_outcome = {
            "progressed": "gameplay_state_changed",
            "partial": "partial_mutation",
            "rejected": "rejected",
            "no_progress": "action_accepted_without_tracked_state_change",
        }.get(previous_verdict)
    previous_action = previous_action or {"type": "WAIT", "params": {}}
    control = {
        "review_due": review_due,
        "request_id": request_id,
        "reasons": ["initial"] if review_due and not prior_objective else [],
        "prior_objective": prior_objective,
        "previous_step": previous_step,
        "previous_outcome": previous_outcome,
        "previous_verdict": previous_verdict,
        "previous_action_fingerprint": (
            normalized_action_fingerprint(parse_action(previous_action))
            if previous_step >= 0
            else ""
        ),
        "actions_since_review": 0,
        "review_interval": 5,
    }
    previous = (
        "No previous action attempt"
        if previous_step < 0
        else (
            f"step={previous_step} outcome={previous_outcome} "
            f"expected_review_verdict={previous_verdict} "
            f"fingerprint={control['previous_action_fingerprint'][:12]}"
        )
    )
    evidence_contents = [
        f"AGENT PLAN CONTROL: review_due={'yes' if review_due else 'no'} "
        f"request_id={request_id}",
        (
            "Plan review reasons: initial"
            if review_due and not prior_objective
            else "Plan review reasons: none"
        ),
        f"Previous action attempt for review: {previous}",
        "Time: tick 100",
    ]
    control["allowed_evidence_lines"] = [
        f"E{index}: {line}" for index, line in enumerate(evidence_contents)
    ]
    control["previous_evidence_excerpt"] = previous
    control["previous_evidence_id"] = "E2"
    control["plan_evidence_ids"] = ["E0", "E3"]
    return control


def _reviewed_action_payload(
    *,
    control: dict[str, Any] | None = None,
    objective: str = "Build durable shelter.",
    decision: str | None = None,
) -> dict[str, Any]:
    control = control or _plan_control()
    if decision is None:
        if control["review_due"]:
            decision = "continue" if control["prior_objective"] else "establish"
        else:
            decision = "not_due"
    previous_evidence = control["previous_evidence_id"]
    plan_evidence = control["plan_evidence_ids"]
    return {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
        "intent": "designate the starter room",
        "objective": objective,
        "plan_step": "Dig the starter room.",
        "expected_simulation_result": "Walls become designated and miners begin work.",
        "last_action_review": {
            "previous_step": control["previous_step"],
            "verdict": control["previous_verdict"],
            "evidence": [previous_evidence],
            "retry_same_action": False,
            "lesson": "Use the observed result before choosing the next action.",
        },
        "plan_review": {
            "request_id": control["request_id"],
            "decision": decision,
            "prior_objective": control["prior_objective"],
            "objective": objective,
            "evidence": plan_evidence,
            "reason": "The current observation supports this next step.",
            "steps": ["Dig shelter.", "Build production."],
        },
        "advance_ticks": 800,
    }


def _review_observation(control: dict[str, Any]) -> str:
    return "\n".join(control["allowed_evidence_lines"])


def test_governed_system_prompt_teaches_wall_construction() -> None:
    assert "Wall" in GOVERNED_SYSTEM_PROMPT
    assert "x2" in GOVERNED_SYSTEM_PROMPT


def test_governed_system_prompt_distinguishes_dead_shrubs() -> None:
    assert "ShrubDead cannot be gathered" in GOVERNED_SYSTEM_PROMPT
    assert "choose a different build footprint" in GOVERNED_SYSTEM_PROMPT
    assert "gathered plants are brewable" not in GOVERNED_SYSTEM_PROMPT


def test_openrouter_transport_defaults_to_three_attempts(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_MAX_ATTEMPTS", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert get_settings().OPENROUTER_MAX_ATTEMPTS == 3
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_deployment_template_keeps_three_transport_attempts() -> None:
    template = (
        Path(__file__).parents[1]
        / "infra/ansible/roles/fortgym/templates/fort-gym.env.j2"
    ).read_text(encoding="utf-8")

    assert (
        "OPENROUTER_MAX_ATTEMPTS={{ lookup('env','OPENROUTER_MAX_ATTEMPTS') "
        "| default('3', true) }}"
    ) in template


def test_governed_submit_tool_requires_agent_review_contract() -> None:
    parameters = _submit_action_tool()["function"]["parameters"]

    assert "last_action_review" in parameters["required"]
    assert "plan_review" in parameters["required"]
    assert parameters["properties"]["last_action_review"]["additionalProperties"] is False
    assert parameters["properties"]["plan_review"]["properties"]["decision"]["enum"] == [
        "not_due",
        "establish",
        "continue",
        "revise",
    ]
    assert parameters["properties"]["last_action_review"]["properties"]["evidence"][
        "minItems"
    ] == 1
    assert parameters["properties"]["plan_review"]["properties"]["evidence"][
        "minItems"
    ] == 2
    assert "reason" not in parameters["properties"]["plan_review"]["required"]
    assert "next_step" not in parameters["properties"]["plan_review"]["properties"]
    assert parameters["properties"]["objective"]["maxLength"] == 160
    assert parameters["properties"]["plan_review"]["properties"]["objective"]["maxLength"] == 160
    assert "do not include changing counts" in GOVERNED_SYSTEM_PROMPT
    assert "REVIEW EVIDENCE CHOICES" in GOVERNED_SYSTEM_PROMPT
    assert "Channel is the legal vertical-access control" in GOVERNED_SYSTEM_PROMPT
    assert "normal dig aimed directly at a hidden lower z-level" in GOVERNED_SYSTEM_PROMPT
    assert "completed channel access reveals" in GOVERNED_SYSTEM_PROMPT
    assert "only a visible `#` lower-level glyph is a candidate" in GOVERNED_SYSTEM_PROMPT
    assert "mixing one candidate wall with any ramp or blank rejects" in GOVERNED_SYSTEM_PROMPT
    assert "floor directly below an open channel shaft" in GOVERNED_SYSTEM_PROMPT
    assert "`plot_subterranean=true` and offered-crop readback" in GOVERNED_SYSTEM_PROMPT
    assert "Additional FarmPlots also consume no material" in GOVERNED_SYSTEM_PROMPT
    assert "zero active PlantSeeds jobs can mean the" in GOVERNED_SYSTEM_PROMPT
    assert "target_walk_group_connectivity=connected|disconnected|unknown" in GOVERNED_SYSTEM_PROMPT


def test_review_evidence_accepts_only_exact_catalog_ids() -> None:
    observation = (
        "E0: Previous action attempt for review: No previous action attempt\n"
        "E1: Run resource flow: food produced=0, consumed=38; "
        "drink produced=0, consumed=60"
    )

    assert (
        DFHackGovernedLLMAgent._matching_evidence_line("E0", observation)
        == "E0: Previous action attempt for review: No previous action attempt"
    )
    assert DFHackGovernedLLMAgent._matching_evidence_line("E1", observation) is not None
    assert DFHackGovernedLLMAgent._matching_evidence_line("0", observation) is None
    assert DFHackGovernedLLMAgent._matching_evidence_line("100", observation) is None
    assert DFHackGovernedLLMAgent._matching_evidence_line("E0: Previous", observation) is None
    assert DFHackGovernedLLMAgent._normalized_prior_objective("none") == ""
    assert DFHackGovernedLLMAgent._normalized_prior_objective("") == ""
    assert DFHackGovernedLLMAgent._normalized_prior_objective("Build shelter") == "build shelter"


def test_governed_system_prompt_requires_build_target_preflight() -> None:
    assert "unoccupied open-floor tile" in GOVERNED_SYSTEM_PROMPT
    assert "Before submitting any BUILD" in GOVERNED_SYSTEM_PROMPT
    assert (
        "`W`, `#`, `T`, `b`, `t`, `c`, `d`, `w`, `o`, `x`, `i`, `,`, `s`, `p`, `@`, or `~`"
        in GOVERNED_SYSTEM_PROMPT
    )
    assert "o=other occupied" in GOVERNED_SYSTEM_PROMPT
    assert "i=frozen liquid that can thaw" in GOVERNED_SYSTEM_PROMPT
    assert "carpenter_build_site_rect" not in GOVERNED_SYSTEM_PROMPT
    assert "runner-authored footprint" not in GOVERNED_SYSTEM_PROMPT
    assert "Furniture positions" in GOVERNED_SYSTEM_PROMPT
    assert "Failed tiles" in GOVERNED_SYSTEM_PROMPT
    assert "Do not retry a rejected target" in GOVERNED_SYSTEM_PROMPT
    assert "the params are the real control and must target the tile you describe" in GOVERNED_SYSTEM_PROMPT


def test_governed_system_prompt_requires_parallel_and_stall_review() -> None:
    assert "Dwarves and jobs run in parallel" in GOVERNED_SYSTEM_PROMPT
    assert "unassigned queued job occupies nobody" in GOVERNED_SYSTEM_PROMPT
    assert "Any legal action with positive advance_ticks" in GOVERNED_SYSTEM_PROMPT
    assert "lets all existing\njobs progress" in GOVERNED_SYSTEM_PROMPT
    assert "At every due plan review, compare all of the factual branches" in GOVERNED_SYSTEM_PROMPT
    assert "A branch marked `below`" in GOVERNED_SYSTEM_PROMPT
    assert "Never describe either as complete or sustainable" in GOVERNED_SYSTEM_PROMPT
    assert "`no_neglect_observed` only when its run-scoped evidence is complete" in GOVERNED_SYSTEM_PROMPT
    assert "run-scoped death evidence" in GOVERNED_SYSTEM_PROMPT
    assert "classify a coordinate or footprint as\nstalled" in GOVERNED_SYSTEM_PROMPT
    assert "Command acceptance is\nnot action success" in GOVERNED_SYSTEM_PROMPT
    assert "created job that vanished without matching output is no progress" in GOVERNED_SYSTEM_PROMPT
    assert "Adding another copy creates a distinct job" in GOVERNED_SYSTEM_PROMPT
    assert "Choose the next\nobjective and action yourself" in GOVERNED_SYSTEM_PROMPT


def test_governed_system_prompt_distinguishes_room_ring_from_wall_mass() -> None:
    assert "hollow ring around at least one untouched passable interior tile" in GOVERNED_SYSTEM_PROMPT
    assert "a solid block of W tiles encloses no space" in GOVERNED_SYSTEM_PROMPT
    assert "construction count alone is not room progress" in GOVERNED_SYSTEM_PROMPT
    assert "or a filled rectangle when optional x2/y2 are given" in GOVERNED_SYSTEM_PROMPT
    assert "with at most 10 total tiles" in GOVERNED_SYSTEM_PROMPT
    assert "setting both x2 and y2 to different coordinates fills the whole rectangle" in GOVERNED_SYSTEM_PROMPT


def test_governed_system_prompt_describes_still_and_brew_mechanic_only() -> None:
    # Still rides the existing BUILD action type, brew rides ORDER -- no new
    # governed type for either.
    assert '"CarpenterWorkshop"|"Still"' in GOVERNED_SYSTEM_PROMPT
    assert "brew orders need brewable plants in stock and empty barrels" in GOVERNED_SYSTEM_PROMPT
    assert "drink is what dwarves actually consume" in GOVERNED_SYSTEM_PROMPT
    assert "brew (the brewing reaction) needs a built Still" in GOVERNED_SYSTEM_PROMPT
    # no new governed action type was introduced for Still/brew


def test_governed_system_prompt_describes_farm_plot_mechanic_only() -> None:
    # FarmPlot rides the existing BUILD action type (no new governed type)
    assert '"Still"|"FarmPlot"' in GOVERNED_SYSTEM_PROMPT
    assert "farming labor" in GOVERNED_SYSTEM_PROMPT
    assert "brewable/cookable" in GOVERNED_SYSTEM_PROMPT
    assert "consumes no material item" in GOVERNED_SYSTEM_PROMPT
    assert "A one-tile lower-floor FarmPlot is a valid probe" in GOVERNED_SYSTEM_PROMPT
    assert "chamber size alone is not a reason to continue excavating" in GOVERNED_SYSTEM_PROMPT
    assert "choose the target yourself from the current lower-level map" in GOVERNED_SYSTEM_PROMPT
    assert "use the completed plot readback" in GOVERNED_SYSTEM_PROMPT
    assert "94,95,160" not in GOVERNED_SYSTEM_PROMPT
    # FarmPlot-as-BUILD predates the FARM crop-selection action; both now exist
    assert GOVERNED_ACTION_TYPES == (
        "DIG",
        "BUILD",
        "ORDER",
        "UNSUSPEND",
        "FARM",
        "LABOR",
        "WAIT",
        "INTERACT",
    )


def test_governed_action_types_include_unsuspend() -> None:
    assert GOVERNED_ACTION_TYPES == (
        "DIG",
        "BUILD",
        "ORDER",
        "UNSUSPEND",
        "FARM",
        "LABOR",
        "WAIT",
        "INTERACT",
    )
    assert (
        "UNSUSPEND" in _submit_action_tool()["function"]["parameters"]["properties"]["type"]["enum"]
    )


def test_governed_action_types_include_farm() -> None:
    # FARM is its own governed action type (not a BUILD/DIG rider)
    assert "FARM" in GOVERNED_ACTION_TYPES
    assert "FARM" in _submit_action_tool()["function"]["parameters"]["properties"]["type"]["enum"]


def test_governed_system_prompt_describes_farm_crop_mechanic_only() -> None:
    # factual engine mechanics only, no strategy advice
    assert "FARM: params" in GOVERNED_SYSTEM_PROMPT
    assert "crop_not_offered" in GOVERNED_SYSTEM_PROMPT
    assert "surface_crop_options_unverified" in GOVERNED_SYSTEM_PROMPT
    assert "farming labor plants a matching seed" in GOVERNED_SYSTEM_PROMPT
    assert "native offered crops separately" in GOVERNED_SYSTEM_PROMPT
    assert "Every requested season must list the token" in GOVERNED_SYSTEM_PROMPT
    assert "farm_plot_not_built" in GOVERNED_SYSTEM_PROMPT
    assert "only after that plot reaches its maximum stage" in GOVERNED_SYSTEM_PROMPT
    assert "crop_not_growable_here" not in GOVERNED_SYSTEM_PROMPT


def test_farm_wired_into_provenance_gates() -> None:
    # FARM must earn governed credit for the governed model, and be
    # zeroed/blocked like the others when a non-governed dfhack model emits it.
    assert "FARM" in GOVERNED_DFHACK_ACTIONS
    assert "FARM" in ASSISTED_DFHACK_ACTIONS


def test_governed_system_prompt_describes_unsuspend_mechanic_only() -> None:
    assert "UNSUSPEND" in GOVERNED_SYSTEM_PROMPT
    assert "suspended" in GOVERNED_SYSTEM_PROMPT
    # factual mechanic description only, no gameplay-strategy advice
    assert "does not complete the job" in GOVERNED_SYSTEM_PROMPT


def test_unsuspend_wired_into_provenance_gates() -> None:
    # UNSUSPEND must earn governed credit for the governed model...
    assert "UNSUSPEND" in GOVERNED_DFHACK_ACTIONS
    # ...and be zeroed/blocked like DIG/BUILD/ORDER when a non-governed
    # dfhack model emits it (never silently uncredited AND unblocked).
    assert "UNSUSPEND" in ASSISTED_DFHACK_ACTIONS


def test_governed_action_types_and_tool_include_labor() -> None:
    assert "LABOR" in GOVERNED_ACTION_TYPES
    assert "LABOR" in _submit_action_tool()["function"]["parameters"]["properties"]["type"]["enum"]


def test_governed_system_prompt_describes_labor_mechanic_only() -> None:
    assert "LABOR" in GOVERNED_SYSTEM_PROMPT
    # factual mechanic: jobs are only taken by citizens with the matching labor
    assert "matching labor enabled" in GOVERNED_SYSTEM_PROMPT
    # flips one labor on one citizen and completes no work itself
    assert "completes no work itself" in GOVERNED_SYSTEM_PROMPT
    # the citizens observation lists ids and enabled labors
    assert "Citizens line lists each citizen id" in GOVERNED_SYSTEM_PROMPT
    # whitelist named factually
    assert "brewing" in GOVERNED_SYSTEM_PROMPT
    assert "herbalism" in GOVERNED_SYSTEM_PROMPT


def test_labor_wired_into_provenance_gates() -> None:
    # LABOR must earn governed credit for the governed model...
    assert "LABOR" in GOVERNED_DFHACK_ACTIONS
    # ...and be zeroed/blocked like the other dfhack actions for non-governed
    # models emitting it (never silently uncredited AND unblocked).
    assert "LABOR" in ASSISTED_DFHACK_ACTIONS


def test_governed_system_prompt_describes_gather_mechanic_only() -> None:
    # gather rides the existing DIG action type (no new governed type) —
    # it must appear in the DIG kind enum and be taught as a mechanic only.
    assert '"dig"|"channel"|"chop"|"gather"' in GOVERNED_SYSTEM_PROMPT
    assert "herbalism" in GOVERNED_SYSTEM_PROMPT
    assert "brewable" in GOVERNED_SYSTEM_PROMPT
    # no new governed action type was introduced for gather
    assert GOVERNED_ACTION_TYPES == (
        "DIG",
        "BUILD",
        "ORDER",
        "UNSUSPEND",
        "FARM",
        "LABOR",
        "WAIT",
        "INTERACT",
    )
def test_governed_interact_tool_and_prompt_are_bounded_and_paused() -> None:
    tool = _submit_action_tool()["function"]["parameters"]

    assert GOVERNED_ACTION_TYPES[-1] == "INTERACT"
    assert "INTERACT" in tool["properties"]["type"]["enum"]
    assert (
        '"confirm"|"cancel"|"up"|"down"|"left"|"right"|"finish_topic_meeting"'
        in GOVERNED_SYSTEM_PROMPT
    )
    assert '"topic_option_a"|...|"topic_option_h"' in GOVERNED_SYSTEM_PROMPT
    assert '"a - Begin discussion" requires topic_option_a' in GOVERNED_SYSTEM_PROMPT
    assert '"a - Finish peeking in on conversation"' in GOVERNED_SYSTEM_PROMPT
    assert "`viewscreen_storesst` is a blocking Wealth/Stocks screen" in GOVERNED_SYSTEM_PROMPT
    assert "submit only INTERACT cancel" in GOVERNED_SYSTEM_PROMPT
    assert "observes one screen after that input" in GOVERNED_SYSTEM_PROMPT
    assert "paused interface or dialog" in GOVERNED_SYSTEM_PROMPT
    assert "INTERACT must use 0" in GOVERNED_SYSTEM_PROMPT


def test_governed_interact_rejects_omitted_ticks_instead_of_repairing_it() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "INTERACT",
                    "params": {"operation": "cancel"},
                    "intent": "dismiss the current dialog",
                }
            )
        ]
    )

    action = agent.decide("obs", {})

    assert action["type"] == "WAIT"
    assert action["advance_ticks"] == DEFAULT_ADVANCE_TICKS
    assert "invalid action payload" in action["intent"]


def test_governed_llm_is_registered_and_model_gated() -> None:
    assert "dfhack-governed-llm" in AGENT_FACTORIES
    assert "dfhack-governed-llm" in GOVERNED_DFHACK_MODELS
    assert OPTIONAL_AGENT_MODULES["dfhack-governed-llm"] == "fort_gym.bench.agent.governed_llm"
    assert "dfhack-governed-llm" in get_args(ModelType)
    assert _is_governed_dfhack_model("dfhack-governed-llm") is True
    assert _is_keystroke_model("dfhack-governed-llm") is False


def test_decide_returns_normalized_governed_action_and_writes_plan() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "DIG",
                    "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
                    "intent": "designate the starter room",
                    "objective": "Open interior shelter",
                    "plan_step": "dig starter room",
                    "advance_ticks": 800,
                }
            )
        ],
        model_override="openai/gpt-5.5",
    )
    action = agent.decide("Time: tick 100", {"work": {}})
    assert action["type"] == "DIG"
    assert action["params"]["area"] == [50, 35, 0]
    assert action["advance_ticks"] == 800
    assert agent._memory.gameplay_plan["objective"] == "Open interior shelter"
    assert agent._memory.gameplay_plan["current_step"] == "dig starter room"
    request = agent._client.chat.completions.requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "submit_action"}}
    assert "parallel_tool_calls" not in request


def test_glm52_uses_validated_json_transport() -> None:
    agent = _agent(
        [
            _text_action_response(
                {
                    "type": "WAIT",
                    "params": {},
                    "intent": "advance real work",
                    "advance_ticks": 1000,
                }
            )
        ],
        model_override="z-ai/glm-5.2",
    )

    action = agent.decide("Time: tick 100", {})

    assert action["type"] == "WAIT"
    request = agent._client.chat.completions.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "tools" not in request
    assert "tool_choice" not in request
    assert "parallel_tool_calls" not in request
    assert request["messages"][-1]["role"] == "user"
    assert "Use JSON objects for last_action_review and plan_review" in request["messages"][-1][
        "content"
    ]


def test_glm52_json_transport_preserves_review_correction_feedback() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    del invalid["plan_review"]["objective"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent(
        [_text_action_response(invalid), _text_action_response(valid)],
        model_override="z-ai/glm-5.2",
    )

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    second_request = agent._client.chat.completions.requests[1]
    assert "plan_review.objective" in second_request["messages"][-2]["content"]
    assert "Transport requirement" in second_request["messages"][-1]["content"]
    assert second_request["response_format"] == {"type": "json_object"}


def test_glm52_json_transport_repeats_distinct_evidence_contract_on_each_correction() -> None:
    control = _plan_control(
        review_due=False,
        request_id="24:none",
        prior_objective="Build durable shelter.",
        previous_step=23,
        previous_verdict="progressed",
    )
    control["allowed_evidence_lines"].extend(
        f"E{index}: Terminal observation fact {index}" for index in range(4, 24)
    )
    first = _reviewed_action_payload(control=control)
    first["plan_review"]["request_id"] = "wrong"
    first["plan_review"]["evidence"] = []
    second = _reviewed_action_payload(control=control)
    second["plan_review"]["evidence"] = ["copied observation text"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent(
        [
            _text_action_response(first),
            _text_action_response(second),
            _text_action_response(valid),
        ],
        model_override="z-ai/glm-5.2",
    )

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["evidence"] == ["E0", "E3"]
    expected_ids = [f"E{index}" for index in range(24)]
    for request in agent._client.chat.completions.requests[1:]:
        correction = request["messages"][-2]["content"]
        assert '"plan_request_id": "24:none"' in correction
        assert (
            f'"allowed_evidence_ids": {json.dumps(expected_ids)}'
            in correction
        )
        assert (
            f'"allowed_evidence_lines": '
            f'{json.dumps(control["allowed_evidence_lines"])}'
            in correction
        )
        assert "at least two distinct allowed_evidence_ids" in correction
        assert "Transport requirement:" in request["messages"][-1]["content"]


def test_review_contract_establishes_initial_agent_owned_plan() -> None:
    control = _plan_control()
    payload = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(payload)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["last_action_review"]["verdict"] == "unknown"
    assert action["plan_review"]["decision"] == "establish"
    assert len(agent._client.chat.completions.requests) == 1
    assert agent._memory.gameplay_plan["objective"] == "Build durable shelter."
    assert agent._memory.gameplay_plan["steps"] == ["Dig shelter.", "Build production."]


def test_review_contract_gets_exactly_one_model_correction() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["last_action_review"]["verdict"] = "progressed"
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    assert len(agent._client.chat.completions.requests) == 2
    events = agent.pop_tool_events()
    assert sum(event["tool"] == "governed_llm.review_contract_retry" for event in events) == 1


def test_review_contract_correction_includes_exact_rejected_payload() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    del invalid["plan_review"]["objective"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]
    assert correction["role"] == "user"
    assert json.dumps(invalid, ensure_ascii=True, sort_keys=True) in correction["content"]
    assert "plan_review.objective is required" in correction["content"]
    assert "No game ticks have advanced" in correction["content"]
    assert '"allowed_evidence_ids"' not in correction["content"]
    assert '"allowed_evidence_lines"' not in correction["content"]


def test_review_contract_correction_uses_evidence_id_terminology() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["plan_review"]["evidence"] = []
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "plan_review.evidence must contain at least one allowed evidence id (E#)" in correction
    assert (
        "plan_review.evidence requires at least two distinct allowed evidence ids (E#)"
        in correction
    )
    assert '"allowed_evidence_ids": ["E0", "E1", "E2", "E3"]' in correction
    assert '"allowed_evidence_lines": ["E0: AGENT PLAN CONTROL:' in correction
    assert "Evidence fields must contain only E# identifiers" in correction
    assert "observation-grounded excerpt" not in correction


def test_review_contract_decision_correction_is_focused_and_omits_evidence_catalog() -> None:
    control = _plan_control(
        review_due=True,
        request_id="32:same_objective_stalled_2",
        prior_objective="Build durable shelter.",
        previous_step=31,
        previous_verdict="no_progress",
    )
    invalid = _reviewed_action_payload(control=control, decision="revise")
    valid = _reviewed_action_payload(control=control, decision="continue")
    agent = _agent([_text_action_response(invalid), _text_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "continue"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "Required decision repair" in correction
    assert "plan_review.decision exactly to 'continue'" in correction
    assert '"allowed_evidence_ids"' not in correction
    assert '"allowed_evidence_lines"' not in correction


def test_due_not_due_decision_gets_exact_continue_repair() -> None:
    control = _plan_control(
        review_due=True,
        request_id="35:periodic_5",
        prior_objective="Build durable shelter.",
        previous_step=34,
        previous_verdict="progressed",
    )
    invalid = _reviewed_action_payload(control=control, decision="not_due")
    valid = _reviewed_action_payload(control=control, decision="continue")
    agent = _agent([_text_action_response(invalid), _text_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "continue"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "due plan review must continue or revise the prior objective" in correction
    assert "plan_review.decision exactly to 'continue'" in correction


def test_current_state_fact_error_includes_evidence_catalog() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["plan_review"]["evidence"] = ["E0", "E1"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_text_action_response(invalid), _text_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["evidence"] == ["E0", "E3"]
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "must quote at least one current game-state fact" in correction
    assert '"allowed_evidence_ids": ["E0", "E1", "E2", "E3"]' in correction
    assert '"allowed_evidence_lines": ["E0: AGENT PLAN CONTROL:' in correction


def test_review_contract_normalizes_identical_overlong_objectives_locally() -> None:
    control = _plan_control()
    overlong = _reviewed_action_payload(
        control=control,
        objective=("Excavate protected underground farm space " * 5).strip(),
    )
    agent = _agent([_submit_action_response(overlong)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert len(action["objective"]) <= MAX_OBJECTIVE_LENGTH
    assert action["objective"] == action["plan_review"]["objective"]
    assert len(agent._client.chat.completions.requests) == 1
    event = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "governed_llm.objective_length_normalized"
    )
    assert event["output"]["original_length"] > MAX_OBJECTIVE_LENGTH
    assert event["output"]["normalized_length"] == len(action["objective"])


def test_review_contract_does_not_collapse_different_overlong_objectives() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(
        control=control,
        objective="x" * (MAX_OBJECTIVE_LENGTH + 1),
    )
    invalid["plan_review"]["objective"] = "y" * (MAX_OBJECTIVE_LENGTH + 1)
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["objective"] == valid["objective"]
    assert len(agent._client.chat.completions.requests) == 2
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "objective must be at most 160 characters" in correction
    assert "plan_review.objective must be at most 160 characters" in correction
    assert not any(
        event["tool"] == "governed_llm.objective_length_normalized"
        for event in agent.pop_tool_events()
    )


def test_review_contract_correction_reports_all_attempt7_style_errors() -> None:
    repeated_action = {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
    }
    control = _plan_control(
        review_due=False,
        request_id="17:none",
        prior_objective="Build durable shelter.",
        previous_step=16,
        previous_verdict="progressed",
        previous_action=repeated_action,
    )
    invalid = _reviewed_action_payload(control=control)
    invalid["last_action_review"]["verdict"] = "rejected"
    invalid["last_action_review"]["retry_same_action"] = False
    del invalid["plan_review"]["objective"]
    valid = _reviewed_action_payload(control=control)
    valid["last_action_review"]["retry_same_action"] = True
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["last_action_review"]["retry_same_action"] is True
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "last_action_review.verdict does not match" in correction
    assert "last_action_review.retry_same_action must match" in correction
    assert "plan_review.objective is required" in correction
    events = agent.pop_tool_events()
    retry = next(event for event in events if event["tool"] == "governed_llm.review_contract_retry")
    assert len(retry["output"]["errors"]) == 3
    assert not any(event["tool"] == "governed_llm.fallback_wait" for event in events)


def test_review_contract_recomputes_retry_flag_after_corrected_action_changes() -> None:
    repeated_action = {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
    }
    control = _plan_control(
        review_due=False,
        request_id="17:none",
        prior_objective="Build durable shelter.",
        previous_step=16,
        previous_verdict="progressed",
        previous_action=repeated_action,
    )
    invalid = _reviewed_action_payload(control=control)
    corrected = _reviewed_action_payload(control=control)
    corrected["type"] = "WAIT"
    corrected["params"] = {}
    agent = _agent([_submit_action_response(invalid), _submit_action_response(corrected)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "WAIT"
    assert action["last_action_review"]["retry_same_action"] is False
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "expected true" in correction


def test_review_contract_combines_action_parse_and_review_errors() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["params"] = {"area": [50, 35, 0]}
    invalid["last_action_review"]["verdict"] = "progressed"
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "invalid action payload" in correction
    assert "last_action_review.verdict does not match" in correction
    retry = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "governed_llm.review_contract_retry"
    )
    assert len(retry["output"]["errors"]) == 2


def test_review_contract_fingerprint_ignores_invalid_nonexecution_metadata() -> None:
    repeated_action = {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
    }
    control = _plan_control(
        review_due=False,
        request_id="17:none",
        prior_objective="Build durable shelter.",
        previous_step=16,
        previous_verdict="progressed",
        previous_action=repeated_action,
    )
    invalid = _reviewed_action_payload(control=control)
    invalid["intent"] = 123
    invalid["last_action_review"]["retry_same_action"] = False
    valid = _reviewed_action_payload(control=control)
    valid["last_action_review"]["retry_same_action"] = True
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["last_action_review"]["retry_same_action"] is True
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "invalid action payload" in correction
    assert "intent is required" in correction
    assert "last_action_review.retry_same_action must match" in correction


def test_review_contract_combines_illegal_type_and_review_errors() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["type"] = "HACK"
    invalid["last_action_review"]["verdict"] = "progressed"
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert "illegal action type: HACK" in correction
    assert "last_action_review.verdict does not match" in correction


def test_due_plan_review_requires_two_distinct_factual_lines() -> None:
    control = _plan_control()
    invalid = _reviewed_action_payload(control=control)
    invalid["plan_review"]["evidence"] = ["E3", "E3"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "establish"
    retry = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "governed_llm.review_contract_retry"
    )
    assert retry["output"]["error"] == "plan_review.evidence must cite distinct factual lines"


def test_not_due_plan_review_requires_two_distinct_factual_lines() -> None:
    control = _plan_control(
        review_due=False,
        request_id="24:none",
        prior_objective="Build durable shelter.",
        previous_step=23,
        previous_verdict="progressed",
    )
    invalid = _reviewed_action_payload(control=control)
    invalid["plan_review"]["evidence"] = ["E3", "E3"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "not_due"
    retry = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "governed_llm.review_contract_retry"
    )
    assert retry["output"]["error"] == "plan_review.evidence must cite distinct factual lines"


def test_review_contract_requires_last_action_evidence_to_cite_its_outcome() -> None:
    control = _plan_control(
        review_due=False,
        request_id="5:none",
        prior_objective="Build durable shelter.",
        previous_step=4,
        previous_verdict="progressed",
    )
    invalid = _reviewed_action_payload(control=control)
    invalid["last_action_review"]["evidence"] = ["E3"]
    valid = _reviewed_action_payload(control=control)
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["last_action_review"]["evidence"] == [control["previous_evidence_id"]]
    assert len(agent._client.chat.completions.requests) == 2
    events = agent.pop_tool_events()
    retry = next(event for event in events if event["tool"] == "governed_llm.review_contract_retry")
    assert retry["output"]["error"] == (
        "last_action_review.evidence must include required evidence id 'E2'"
    )


def test_review_contract_binds_retry_flag_to_normalized_action() -> None:
    repeated_action = {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
    }
    control = _plan_control(
        review_due=False,
        request_id="5:none",
        prior_objective="Build durable shelter.",
        previous_step=4,
        previous_verdict="rejected",
        previous_action=repeated_action,
    )
    invalid = _reviewed_action_payload(control=control)
    valid = _reviewed_action_payload(control=control)
    valid["last_action_review"]["retry_same_action"] = True
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["last_action_review"]["retry_same_action"] is True
    events = agent.pop_tool_events()
    retry = next(event for event in events if event["tool"] == "governed_llm.review_contract_retry")
    assert "retry_same_action must match" in retry["output"]["error"]


def test_review_contract_fails_before_gameplay_after_bad_correction() -> None:
    control = _plan_control()
    first = _reviewed_action_payload(control=control)
    second = _reviewed_action_payload(control=control)
    third = _reviewed_action_payload(control=control)
    first["plan_review"]["evidence"] = ["invented evidence"]
    second["plan_review"]["evidence"] = ["still invented"]
    third["plan_review"]["evidence"] = ["invented again"]
    agent = _agent(
        [
            _submit_action_response(first),
            _submit_action_response(second),
            _submit_action_response(third),
        ]
    )

    with pytest.raises(RuntimeError, match="failed before gameplay after two corrections"):
        agent.decide(
            _review_observation(control),
            {"agent_plan_control": control},
        )

    assert agent._pending is None
    events = agent.pop_tool_events()
    assert sum(event["tool"] == "governed_llm.review_contract_retry" for event in events) == 2
    assert not any(event["tool"] == "governed_llm.fallback_wait" for event in events)


def test_review_control_provider_failure_does_not_advance_with_fallback_wait() -> None:
    control = _plan_control()
    agent = _agent(error=RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="failed before gameplay"):
        agent.decide(
            _review_observation(control),
            {"agent_plan_control": control},
        )

    assert agent._pending is None
    assert not any(
        event["tool"] == "governed_llm.fallback_wait" for event in agent.pop_tool_events()
    )


def test_review_control_retries_transient_provider_failure_without_gameplay() -> None:
    control = _plan_control()
    payload = _reviewed_action_payload(control=control)
    agent = _agent(
        [RuntimeError("provider timeout"), _submit_action_response(payload)],
        max_attempts=2,
    )

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["type"] == "DIG"
    assert len(agent._client.chat.completions.requests) == 2
    transport_events = [
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "openrouter.chat.completions.create"
    ]
    assert transport_events[0]["output"]["retrying"] is True


def test_review_contract_allows_agent_to_revise_objective_when_not_due() -> None:
    control = _plan_control(
        review_due=False,
        request_id="5:none",
        prior_objective="Build durable shelter.",
        previous_step=4,
        previous_verdict="progressed",
    )
    payload = _reviewed_action_payload(
        control=control,
        objective="Close the drink-production loop.",
        decision="revise",
    )
    agent = _agent([_submit_action_response(payload)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["objective"] == "Close the drink-production loop."
    assert action["plan_review"]["decision"] == "revise"
    assert agent._memory.gameplay_plan["objective"] == "Close the drink-production loop."


def test_review_correction_states_required_decision_for_objective_change() -> None:
    control = _plan_control(
        review_due=False,
        request_id="33:none",
        prior_objective="Place a Still on verified open floor.",
        previous_step=32,
        previous_verdict="rejected",
    )
    invalid = _reviewed_action_payload(
        control=control,
        objective="Build a FarmPlot on verified open floor.",
        decision="continue",
    )
    valid = _reviewed_action_payload(
        control=control,
        objective="Build a FarmPlot on verified open floor.",
        decision="revise",
    )
    agent = _agent([_submit_action_response(invalid), _submit_action_response(valid)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "revise"
    correction = agent._client.chat.completions.requests[1]["messages"][-1]["content"]
    assert '"required_plan_decision_for_submitted_objective": "revise"' in correction
    assert '"submitted_objective_matches_prior": false' in correction
    assert '"submitted_plan_decision": "continue"' in correction


def test_review_contract_allows_voluntary_continue_when_not_due() -> None:
    control = _plan_control(
        review_due=False,
        request_id="5:none",
        prior_objective="Build durable shelter.",
        previous_step=4,
        previous_verdict="progressed",
    )
    payload = _reviewed_action_payload(control=control, decision="continue")
    agent = _agent([_submit_action_response(payload)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "continue"


def test_not_due_plan_review_may_omit_reason() -> None:
    control = _plan_control(
        review_due=False,
        request_id="5:none",
        prior_objective="Build durable shelter.",
        previous_step=4,
        previous_verdict="progressed",
    )
    payload = _reviewed_action_payload(control=control)
    payload["plan_review"].pop("reason")
    agent = _agent([_submit_action_response(payload)])

    action = agent.decide(
        _review_observation(control),
        {"agent_plan_control": control},
    )

    assert action["plan_review"]["decision"] == "not_due"
    assert "reason" not in action["plan_review"]


def test_not_due_review_advances_memory_plan_step_without_recording_review() -> None:
    initial_control = _plan_control()
    initial = _reviewed_action_payload(control=initial_control)
    repeated_action = {
        "type": "DIG",
        "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
    }
    next_control = _plan_control(
        review_due=False,
        request_id="1:none",
        prior_objective="Build durable shelter.",
        previous_step=0,
        previous_verdict="progressed",
        previous_action=repeated_action,
    )
    next_action = _reviewed_action_payload(control=next_control)
    next_action["plan_step"] = "Build the first production workshop."
    next_action["last_action_review"]["retry_same_action"] = True
    agent = _agent(
        [_submit_action_response(initial), _submit_action_response(next_action)]
    )

    agent.decide(
        _review_observation(initial_control),
        {"agent_plan_control": initial_control},
    )
    revision = agent._memory.gameplay_plan["revision"]
    agent.decide(
        _review_observation(next_control),
        {"agent_plan_control": next_control},
    )

    assert agent._memory.gameplay_plan["current_step"] == next_action["plan_step"]
    assert agent._memory.gameplay_plan["revision"] == revision
    assert agent._memory.plan_reviews == []


def test_order_qty_alias_and_missing_advance_ticks_normalized() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "ORDER",
                    "params": {"job": "bed", "qty": 2},
                    "intent": "queue beds",
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "ORDER"
    assert action["params"]["quantity"] == 2
    assert action["advance_ticks"] == 1000


def test_illegal_action_type_falls_back_to_wait() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "KEYSTROKE",
                    "params": {"keys": ["LEAVESCREEN"]},
                    "intent": "press a key",
                    "advance_ticks": 0,
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "WAIT"
    assert action["advance_ticks"] == 1000
    assert agent._memory.failed_attempts


def test_llm_call_failure_falls_back_to_wait() -> None:
    agent = _agent(error=RuntimeError("boom"))
    action = agent.decide("obs", {})
    assert action["type"] == "WAIT"
    assert action["advance_ticks"] == 1000
    events = agent.pop_tool_events()
    assert any(event["tool"] == "governed_llm.fallback_wait" for event in events)


def test_previous_outcome_recorded_in_memory() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "DIG",
                    "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
                    "intent": "designate the starter room",
                    "advance_ticks": 1000,
                }
            ),
            _submit_action_response(
                {
                    "type": "WAIT",
                    "params": {},
                    "intent": "let miners work",
                    "advance_ticks": 1000,
                }
            ),
        ]
    )
    agent.decide("Time: tick 100", {})
    agent.decide("Last Action: REJECTED - tile not accessible\nTime: tick 1100", {})
    assert len(agent._memory.recent_steps) == 1
    assert agent._memory.recent_steps[0].result.startswith("Last Action: REJECTED")
    assert any("rejected" in item["label"].lower() for item in agent._memory.failed_attempts)


def test_memory_update_with_coordinates_becomes_poi() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "CarpenterWorkshop", "x": 58, "y": 35, "z": 0},
                    "intent": "place workshop",
                    "memory_update": "workshop site @ 58,35,0: flat observed floor",
                    "advance_ticks": 1000,
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "BUILD"
    assert agent._memory.pois
    poi = agent._memory.pois[-1]
    assert poi["label"] == "workshop site"
    assert (poi["x"], poi["y"], poi["z"]) == (58, 35, 0)


def test_memory_persists_across_agent_instances(tmp_path: Any) -> None:
    memory_file = tmp_path / "governed_llm_memory.json"

    agent_a = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=str(memory_file)
    )
    agent_a._client = _FakeClient(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "CarpenterWorkshop", "x": 1, "y": 2, "z": 3},
                    "intent": "place workshop",
                    "memory_update": "site @ 1,2,3: good floor",
                    "advance_ticks": 1000,
                }
            )
        ]
    )
    agent_a.decide("obs", {})
    assert memory_file.is_file()

    agent_b = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=str(memory_file)
    )
    context = agent_b._memory.get_context()
    assert "site" in context


def test_failed_attempt_labels_carry_kind_and_position() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "Wall", "x": 94, "y": 91, "z": 177},
                    "intent": "wall the bedroom",
                    "advance_ticks": 1000,
                }
            ),
            _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "wait", "advance_ticks": 1000}
            ),
        ]
    )
    agent.decide("Time: tick 100", {})
    agent.decide("Last Action: REJECTED - too_far_from_fort\nTime: tick 1100", {})
    labels = [item["label"] for item in agent._memory.failed_attempts]
    assert any("BUILD Wall at (94,91) rejected" == label for label in labels)


def test_vision_agent_attaches_minimap_image() -> None:
    agent = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=None, vision=True
    )
    agent._client = _FakeClient(
        [
            _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "look around", "advance_ticks": 1000}
            )
        ]
    )

    agent.decide(
        "obs",
        {"fort": {"map_rows": ["..WWW..", "..W.W.."], "map_origin": [90, 87, 177]}},
    )

    request = agent._client.chat.completions.requests[0]
    content = request["messages"][1]["content"]
    assert isinstance(content, list)
    kinds = [part.get("type") for part in content]
    assert kinds == ["text", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_variants_registered_in_all_gates() -> None:
    for name in (
        "dfhack-governed-llm-glm5v",
        "dfhack-governed-llm-gpt55-vision",
        "dfhack-governed-llm-kimi-vision",
        "dfhack-governed-llm-minimax-vision",
    ):
        assert name in AGENT_FACTORIES
        assert name in GOVERNED_DFHACK_MODELS
        assert name in get_args(ModelType)
        assert OPTIONAL_AGENT_MODULES[name] == "fort_gym.bench.agent.governed_llm"
        assert _is_keystroke_model(name) is False


def test_glm5v_variant_has_governed_review_output_headroom(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        agent = AGENT_FACTORIES["dfhack-governed-llm-glm5v"]()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert isinstance(agent, DFHackGovernedLLMAgent)
    assert agent._model == "z-ai/glm-5v-turbo"
    assert agent._vision is True
    assert agent._max_tokens == 1024


def test_glm52_variant_has_json_correction_output_headroom(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        agent = AGENT_FACTORIES["dfhack-governed-llm-glm52"]()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert isinstance(agent, DFHackGovernedLLMAgent)
    assert agent._model == "z-ai/glm-5.2"
    assert agent._vision is False
    assert agent._max_tokens == 1024


def test_tool_choice_degrades_to_auto_on_provider_rejection() -> None:
    class _PickyCompletions:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.requests.append(kwargs)
            if kwargs.get("tool_choice") != "auto":
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': 'Tool choice must be auto'}}"
                )
            return _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "ok", "advance_ticks": 1000}
            )

    agent = DFHackGovernedLLMAgent(
        api_key="test-key",
        max_attempts=1,
        memory_path=None,
        model_override="openai/gpt-5.5",
    )
    picky = _PickyCompletions()
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=picky))

    action = agent.decide("obs", {})

    assert action["type"] == "WAIT"
    assert action["intent"] == "ok"  # real model response, not a fallback
    assert picky.requests[0]["tool_choice"] != "auto"
    assert picky.requests[1]["tool_choice"] == "auto"
    events = agent.pop_tool_events()
    assert any(e["tool"] == "governed_llm.tool_choice_degraded" for e in events)


def test_reasoning_disable_degrades_when_provider_requires_reasoning() -> None:
    class _ReasoningCompletions:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.requests.append(kwargs)
            if "extra_body" in kwargs:
                raise RuntimeError("Error code: 400 - Reasoning is mandatory for this endpoint")
            return _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "ok", "advance_ticks": 1000}
            )

    agent = DFHackGovernedLLMAgent(api_key="test-key", max_attempts=1, memory_path=None)
    picky = _ReasoningCompletions()
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=picky))

    action = agent.decide("obs", {})

    assert action["intent"] == "ok"
    assert "extra_body" in picky.requests[0]
    assert "extra_body" not in picky.requests[1]
    events = agent.pop_tool_events()
    assert any(e["tool"] == "governed_llm.reasoning_enabled_degraded" for e in events)


def test_action_parsed_from_text_when_no_tool_call() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "Let me reason about this... The workshop needs beds.\n"
                        '{"type": "ORDER", "params": {"job": "bed", "quantity": 3},'
                        ' "intent": "queue beds", "advance_ticks": 1000}'
                    ),
                    tool_calls=None,
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    agent = _agent([response])

    action = agent.decide("obs", {})

    assert action["type"] == "ORDER"
    assert action["params"]["quantity"] == 3
    events = agent.pop_tool_events()
    assert any(e["tool"] == "governed_llm.text_payload_fallback" for e in events)


def test_max_tokens_override_reaches_the_request() -> None:
    agent = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=None, max_tokens=4096
    )
    agent._client = _FakeClient(
        [
            _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "ok", "advance_ticks": 1000}
            )
        ]
    )

    agent.decide("obs", {})

    assert agent._client.chat.completions.requests[0]["max_tokens"] == 4096
