"""Retain audited prompt metadata across a game rollback, never failed-branch memory."""

from copy import deepcopy
import hashlib
from pathlib import Path

from ..agent.keyboard_exchange import read
from ..agent.keyboard_prompt import declared_prompt_change, effective_prompt


def inspect_restart_initial(checkpoint: Path, segment: Path, result: dict) -> dict:
    """Reconstruct the initial state from the save and original restart/change records."""
    from .keyboard_unavailable_restart import digest, restart_history

    saved = read(checkpoint / "agent.json")
    initial = read(segment / "agent-before.json")
    expected = deepcopy(saved)
    history = restart_history(
        checkpoint,
        segment,
        {
            "source_result_sha256": digest(segment / "result.json"),
        },
    )
    inherited = read(checkpoint / "runner.json").get("discontinuities", [])
    if len(history) > len(inherited):
        expected = restart_prompt_state(saved, history[-1])
        expected["usage"] = deepcopy(history[-1]["retained_usage"])
    elif (segment / "restart.json").exists():
        raise ValueError("Restart artifact is absent from the source loss history")
    change = result.get("prompt_change")
    if change is not None:
        if (
            not isinstance(change, dict)
            or not isinstance(change.get("profile"), str)
            or read(segment / "prompt-change.json") != change
        ):
            raise ValueError("Restart prompt change lacks matching retained evidence")
        manifest = read(checkpoint / "checkpoint.json")
        declaration = {
            key: change.get(key)
            for key in (
                "checkpoint_sha256",
                "next_step",
                "previous",
                "profile",
            )
        }
        declaration["schema_version"] = "fortgym.keyboard-prompt-change-declaration/v1"
        validated = declared_prompt_change(
            expected,
            declaration,
            profile=change["profile"],
            checkpoint_sha256=manifest["sha256"],
            next_step=manifest["payload"]["next_step"],
        )
        if validated != change:
            raise ValueError("Restart prompt change differs from its original usage boundary")
        expected["prompt_changes"] = [*expected.get("prompt_changes", []), change]
    elif (segment / "prompt-change.json").exists():
        raise ValueError("Restart has an unrecorded prompt-change artifact")
    if initial != expected:
        raise ValueError("Restart changed checkpoint memory, configuration or prompt history")
    return initial


def inspect_restart_prompt(
    checkpoint: Path,
    segment: Path,
    result: dict,
    returned: dict,
    tail: list[dict],
    failed_decision: dict,
) -> dict:
    """Retain only the original prompt history and the matching response profiles."""
    initial = inspect_restart_initial(checkpoint, segment, result)
    if any(
        returned.get(key) != value
        for key, value in initial.items()
        if key not in {"usage", "memory"}
    ) or set(returned) != set(initial):
        raise ValueError("Restart changed checkpoint memory, configuration or prompt history")
    changes = initial.get("prompt_changes", [])
    profile = effective_prompt(changes, initial["usage"])
    if effective_prompt(returned.get("prompt_changes", []), returned["usage"]) != profile:
        raise ValueError("Restart returned prompt history differs")
    from ..agent.keyboard_prompt import BASE_PROMPT

    decisions: list[dict] = []
    for row in tail:
        events = [
            event.get("data", {})
            for event in row.get("events", [])
            if event.get("type") == "tool_call"
        ]
        current = [
            event["receipt"] for event in events if event.get("type") == "codex_keyboard_decision"
        ]
        if len(current) != 1:
            raise ValueError("Restart trace lacks one prompt-profile receipt per decision")
        decisions.extend(current)
    if any(
        decision.get("prompt_profile", BASE_PROMPT) != profile
        for decision in [*decisions, failed_decision]
    ):
        raise ValueError("Restart decision profile differs from retained prompt history")
    return {
        "retained_prompt_changes": deepcopy(changes),
        "source_prompt_state_sha256": hashlib.sha256(
            (segment / "agent-before.json").read_bytes()
        ).hexdigest(),
    }


def restart_prompt_state(state: dict, record: dict | None) -> dict:
    """Use audited metadata for preflight and restore; all gameplay memory stays saved."""
    result = deepcopy(state)
    if record is None or "retained_prompt_changes" not in record:
        return result
    old, retained = state.get("prompt_changes", []), record["retained_prompt_changes"]
    usage = record["retained_usage"]
    effective_prompt(retained, usage)
    if retained[: len(old)] != old or any(
        usage[key] < state["usage"][key]
        for key in (
            "dispatched_requests",
            "returned_responses",
            "accounted_responses",
            "total_tokens",
        )
    ):
        raise ValueError("Restart cannot erase prompt or usage history")
    result["usage"] = deepcopy(usage)
    if retained:
        result["prompt_changes"] = deepcopy(retained)
    return result
