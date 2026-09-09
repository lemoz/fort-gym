"""Declared subscription keyboard conditions and finite continuation windows."""

from __future__ import annotations

from pathlib import Path

from ..agent.codex_protocol import TRANSPORT
from ..agent.codex_transport import MODEL, REASONING_EFFORT
from ..agent.codex_selection import validate_selection
from ..agent.keyboard_exchange import read
from ..agent.keyboard_prompt import BASE_PROMPT, validate_prompt_profile
from ..env.native_key_catalog import NATIVE_PROFILE
from ..env.screen_observation import TEXT_PROFILE
from .keyboard_save import LEGACY_SAVE_PROFILE, SAVE_PROFILES
from .campaign_food import validate_profile
from .campaign_resources import PROFILE as RESOURCE_PROFILE


def positive(value: object, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value < 1 or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid keyboard {name}")
    return value


def validate_condition(config: dict) -> dict:
    version = config.get("schema_version")
    if version == "fortgym.codex-keyboard-condition/v1":
        if config.get("model") != MODEL or config.get("reasoning_effort") != REASONING_EFFORT:
            raise ValueError("Keyboard condition identity differs")
    elif version in ("fortgym.codex-keyboard-condition/v2", "fortgym.codex-keyboard-condition/v3"):
        validate_selection(config.get("model"), config.get("reasoning_effort"))
    else:
        raise ValueError("Keyboard condition identity differs")
    if version == "fortgym.codex-keyboard-condition/v3":
        validate_prompt_profile(config.get("prompt_profile"))
    elif "prompt_profile" in config:
        raise ValueError("Historical keyboard conditions cannot change prompt profiles")
    identities = {
        "transport": TRANSPORT,
        "control_profile": NATIVE_PROFILE,
        "observation_profile": TEXT_PROFILE,
        "advance_policy": "model_requested/v1",
        "account_admission": "fresh_read_before_each_model_invocation",
    }
    if any(config.get(key) != value for key, value in identities.items()):
        raise ValueError("Keyboard condition identity differs")
    if not isinstance(config.get("condition_id"), str) or not config["condition_id"]:
        raise ValueError("Keyboard condition identity is required")
    for key in ("api_fallback", "automatic_credit_purchase", "automatic_reset_consumption"):
        if config.get(key) is not False:
            raise ValueError("Subscription condition cannot enable fallback or purchases")
    if config.get("actual_charge_usd", "missing") is not None:
        raise ValueError("Subscription charges are unreported")
    for key in ("max_dispatches", "max_total_tokens"):
        positive(config.get(key), key)
    positive(config.get("max_advance_ticks"), "tick limit", maximum=2500)
    timeout = positive(config.get("model_timeout_seconds"), "model timeout", maximum=600)
    exchange = positive(config.get("exchange_timeout_seconds"), "exchange timeout", maximum=600)
    if exchange <= timeout:
        raise ValueError("Exchange timeout must leave room for model receipt delivery")
    positive(config.get("maximum_included_usage_percent"), "quota threshold", maximum=99)
    size = config.get("screen_size")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(value) is not int for value in size)
        or not 80 <= size[0] <= 300
        or not 25 <= size[1] <= 150
    ):
        raise ValueError("Invalid declared native display dimensions")
    return config


def load_window(condition_path: Path, window_path: Path) -> tuple[dict, dict]:
    condition, window = validate_condition(read(condition_path)), read(window_path)
    if (
        window.get("schema_version") != "fortgym.codex-keyboard-window/v1"
        or window.get("original_condition") != condition_path.name
        or not isinstance(window.get("condition_id"), str)
        or not window["condition_id"]
        or window.get("reset_memory") is not False
        or window.get("reset_usage") is not False
        or window.get("strategy_intervention") is not False
    ):
        raise ValueError("Continuation window must preserve its declared condition")
    positive(window.get("continuation_from_next_step"), "continuation cursor")
    positive(window.get("steps_per_segment"), "segment size", maximum=64)
    positive(window.get("max_segments"), "segment count", maximum=16)
    if window.get("snapshot_profile", LEGACY_SAVE_PROFILE) not in SAVE_PROFILES:
        raise ValueError("Unsupported declared snapshot profile")
    validate_profile(window.get("private_measurement_profile"))
    if window.get("runtime_rpc_transport", "cli") not in ("cli", "native-rpc"):
        raise ValueError("Unsupported declared runtime RPC transport")
    if window.get("resource_observation_profile") not in (None, RESOURCE_PROFILE):
        raise ValueError("Unsupported declared resource observation profile")
    change = window.get("prompt_change")
    if change is not None:
        if (not isinstance(change, dict) or set(change) != {
                "schema_version", "checkpoint_sha256", "next_step", "previous", "profile",
            } or change.get("schema_version") != "fortgym.keyboard-prompt-change-declaration/v1"
                or change.get("next_step") != window["continuation_from_next_step"]
                or type(change.get("next_step")) is not int
                or change.get("profile") != condition.get("prompt_profile", BASE_PROMPT)):
            raise ValueError("Invalid declared prompt change")
        validate_prompt_profile(change["previous"])
        validate_prompt_profile(change["profile"])
    extension = window.get("budget_extension")
    if extension is not None:
        if not isinstance(extension, dict) or set(extension) != {
            "max_dispatches",
            "max_total_tokens",
        }:
            raise ValueError("Invalid declared budget extension")
        for key, value in extension.items():
            positive(value, key)
    return condition, window
