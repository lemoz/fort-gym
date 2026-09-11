"""Versioned keyboard instructions and checkpoint-bound prompt changes."""

from copy import deepcopy
import re

BASE_PROMPT = "native_keyboard_prompt/v1"
MEMORY_PROMPT = "native_keyboard_memory_replacement/v1"
CHARACTER_PROMPT = "native_keyboard_character_reference/v1"
ORIGIN_SCHEMA = "fortgym.keyboard-prompt-origin/v1"
MEMORY_CONTRACT = """Your retained memory is the only scratchpad carried between decisions. Each
decision is a fresh model request, not a continuation of the previous conversation.
memory_update completely replaces the previous retained memory; it is not appended
or merged. Include anything you want to retain for the next decision. An empty
memory_update clears the retained memory. The current screen and previous input
receipt are supplied separately on every decision."""

CHARACTER_CONTRACT = """Native command events and literal character events are distinct inputs.
CUSTOM_A is a named command event, not an alias for typing the character 'a'.
For printable ASCII characters, STRING_A### uses the three-digit decimal character
code: 'a' is STRING_A097, 'A' is STRING_A065, and '0' is STRING_A048.
Character case matters. Use character events where the interface expects literal
characters and named command events where it expects commands. A displayed letter
alone does not identify which event a menu handles. Check the next captured screen
and input receipt to see what changed; accepted input does not prove its intended
menu effect. Keys are passed exactly as named, without automatic conversion."""


def validate_prompt_profile(value: object) -> str:
    if not isinstance(value, str) or value not in (BASE_PROMPT, MEMORY_PROMPT, CHARACTER_PROMPT):
        raise ValueError("Unsupported keyboard prompt profile")
    return value


def effective_prompt(changes: list, usage: dict) -> str:
    """Keep prior prompt changes and their accounted-usage boundaries intact."""
    if not isinstance(changes, list):
        raise ValueError("Prompt changes must be a list")
    profile = BASE_PROMPT
    previous = dict(dispatched_requests=0, total_tokens=0)
    for index, change in enumerate(changes):
        if isinstance(change, dict) and change.get("schema_version") == ORIGIN_SCHEMA:
            if (
                index != 0
                or set(change) != {"schema_version", "profile", "source_snapshot_receipt_sha256", "usage"}
                or not isinstance(change["source_snapshot_receipt_sha256"], str)
                or re.fullmatch("[a-f0-9]{64}", change["source_snapshot_receipt_sha256"]) is None
                or not isinstance(change["usage"], dict)
                or set(change["usage"]) != set(previous)
                or any(type(change["usage"].get(key)) is not int or change["usage"][key] != 0
                       for key in previous)
            ):
                raise ValueError("Prompt origin must identify the unused starting snapshot")
            profile = validate_prompt_profile(change["profile"])
            continue
        if not isinstance(change, dict) or set(change) != {
            "schema_version", "checkpoint_sha256", "next_step", "previous", "profile", "usage",
        }:
            raise ValueError("Invalid prompt change fields")
        validate_prompt_profile(change["profile"])
        counts = change["usage"]
        if (
            change["schema_version"] != "fortgym.keyboard-prompt-change/v1"
            or change["previous"] != profile or change["profile"] == profile
            or not isinstance(change["checkpoint_sha256"], str)
            or re.fullmatch("[a-f0-9]{64}", change["checkpoint_sha256"]) is None
            or type(change["next_step"]) is not int or change["next_step"] < 0
            or not isinstance(counts, dict) or set(counts) != set(previous)
            or any(type(counts[k]) is not int or not previous[k] <= counts[k] <= usage[k]
                   for k in previous)
        ):
            raise ValueError("Prompt change lineage or usage differs")
        previous, profile = counts, change["profile"]
    return profile


def declared_prompt_change(state: dict, declaration: dict | None, *, profile: str,
                          checkpoint_sha256: str, next_step: int) -> dict | None:
    """Require an explicit change from the actual saved prompt before inference."""
    validate_prompt_profile(profile)
    previous = effective_prompt(state.get("prompt_changes", []), state["usage"])
    if declaration is None:
        if previous != profile:
            raise ValueError("Prompt profile differs without a declared change")
        return None
    expected = {
        "schema_version": "fortgym.keyboard-prompt-change-declaration/v1",
        "checkpoint_sha256": checkpoint_sha256, "next_step": next_step,
        "previous": previous, "profile": profile,
    }
    if (not isinstance(declaration, dict) or declaration != expected
            or type(declaration.get("next_step")) is not int or previous == profile):
        raise ValueError("Declared prompt change does not match the saved boundary")
    change = {
        **expected, "schema_version": "fortgym.keyboard-prompt-change/v1",
        "usage": {k: state["usage"][k] for k in ("dispatched_requests", "total_tokens")},
    }
    effective_prompt([*state.get("prompt_changes", []), change], state["usage"])
    return deepcopy(change)
