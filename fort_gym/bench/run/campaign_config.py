"""Versioned execution bounds, separate from frozen development probes.

These are per-campaign limits, not spending authorization or an aggregate ledger.
Checkpoint configuration identity prevents a continuation from resetting them.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..agent.campaign_action_reference import action_reference
from ..agent.campaign_action_schema import LEGACY, validate_schema_profile
from ..env.campaign_encoder import PROFILES as CAMPAIGN_OBSERVATION_PROFILES
from ..env.campaign_view import DECISION_PROFILE, OBSERVATION_PROFILE
from .campaign_retention import validate_retention

DEVELOPMENT_SCHEMA = "fortgym.development-probe/v1"
ENDURANCE_SCHEMA = "fortgym.campaign-condition/v1"
LOCAL_SCHEMA = "fortgym.local-campaign-condition/v1"
PRICE_CEILING = {"prompt": 0.5, "completion": 2.0, "request": 0.0}
DEVELOPMENT_LIMITS = {
    "max_steps": 10,
    "ticks_per_step": 2000,
    "max_advance_ticks": 2500,
    "max_output_tokens": 16384,
    "max_attempts": 3,
    "max_dispatches": 12,
    "max_request_bytes": 200000,
    "max_total_tokens": 262144,
}
ENDURANCE_LIMITS = {
    **DEVELOPMENT_LIMITS,
    "max_steps": 32,
    "max_dispatches": 4096,
    "max_total_tokens": 20000000,
    "max_segments": 512,
    "segment_time_budget_seconds": 1800,
}


def read_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Campaign configuration must be an object")
    return value


def validate_bounds(
    config: dict, model: str, *, endurance: bool = False, local: bool = False
) -> dict:
    schema = LOCAL_SCHEMA if local else ENDURANCE_SCHEMA if endurance else DEVELOPMENT_SCHEMA
    if config.get("schema_version") != schema:
        raise ValueError(
            "Unsupported campaign configuration"
            if endurance
            else "Unsupported development configuration"
        )
    models = config.get("models")
    if (
        not isinstance(models, list)
        or not models
        or any(not isinstance(item, str) or not item.strip() for item in models)
        or len(set(models)) != len(models)
        or model not in models
        or model.lower().startswith("anthropic/")
    ):
        raise ValueError("Model is not declared in this development configuration")
    retention = validate_retention(config)
    limits = ENDURANCE_LIMITS if endurance or local else DEVELOPMENT_LIMITS
    if retention is not None:
        limits = {**limits, "segment_time_budget_seconds": 7200}
    for key, maximum in limits.items():
        if type(config.get(key)) is not int or not 1 <= config[key] <= maximum:
            raise ValueError(f"Invalid bounded development setting: {key}")
    if retention is not None and retention["interval_steps"] > config["max_steps"]:
        raise ValueError("Periodic checkpoint interval exceeds segment steps")
    cost, maximum_cost = config.get("max_cost_usd"), 20 if endurance else 2
    if local:
        if type(cost) not in (float, int) or cost != 0 or "provider_max_price" in config:
            raise ValueError("Local conditions declare zero metered provider charges, not prices")
        validate_local_settings(config, model)
        return config
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or not 0 < cost <= maximum_cost
    ):
        raise ValueError(f"Campaign returned-cost cap must be at most ${maximum_cost}")
    if config.get("provider_max_price") != PRICE_CEILING:
        raise ValueError("This development probe requires the declared low-price ceiling")
    return config


def validate_local_settings(config: dict, model: str) -> None:
    from ..agent.campaign_llama_identity import TRANSPORT, validate_llama_settings

    local = config.get("local_inference")
    if (
        not isinstance(local, dict)
        or not isinstance(local.get("transport"), str)
        or local["transport"] not in {"ollama-local/v1", TRANSPORT}
    ):
        raise ValueError("Unsupported local campaign transport")
    runtime_profile = local.get("runtime_profile", "standard_f16/v1")
    if not isinstance(runtime_profile, str) or runtime_profile not in {
        "standard_f16/v1",
        "flash_q8/v1",
    }:
        raise ValueError("Unsupported local server runtime profile")
    if config["max_attempts"] != 1:
        raise ValueError("Local transport does not silently retry a failed inference")
    if "reasoning_budget_tokens" in local and local["transport"] != TRANSPORT:
        raise ValueError("A reasoning budget requires the pinned llama.cpp transport")
    prompt_contract = local.get("prompt_contract", "grammar_only/v1")
    if not isinstance(prompt_contract, str) or prompt_contract not in {
        "grammar_only/v1",
        "visible_action_contract/v1",
    }:
        raise ValueError("Unsupported local prompt contract")
    reference = local.get("action_reference", "none")
    action_reference(reference)
    if reference != "none" and prompt_contract != "visible_action_contract/v1":
        raise ValueError("An action reference requires the visible action contract")
    action_schema = validate_schema_profile(local.get("action_schema", LEGACY))
    if action_schema != LEGACY and prompt_contract != "visible_action_contract/v1":
        raise ValueError("A typed action schema requires the visible action contract")
    packing = local.get("prompt_packing", "none")
    if not isinstance(packing, str) or packing not in {
        "none",
        "bounded_history/v1",
        "bounded_history_corrections/v1",
    }:
        raise ValueError("Unsupported local prompt packing")
    if packing != "none" and prompt_contract != "visible_action_contract/v1":
        raise ValueError("Packed campaigns require the visible action contract")
    # A declared long, periodically saved llama.cpp run may allow slow local
    # generation to finish. Historical conditions retain their original ceiling.
    maximum_timeout = (
        600 if local["transport"] == TRANSPORT and validate_retention(config) is not None else 180
    )
    for key, lower, upper in (
        ("context_tokens", 4096, 32768),
        ("timeout_seconds", 1, maximum_timeout),
        ("seed", 0, 2147483647),
    ):
        if type(local.get(key)) is not int or not lower <= local[key] <= upper:
            raise ValueError(f"Invalid local inference setting: {key}")
    if local["transport"] == TRANSPORT:
        validate_llama_settings(config)
    elif local.get("server_version") != "0.5.11":
        raise ValueError(
            "This local transport supports the verified pre-cloud Ollama 0.5.11 runtime"
        )
    if any("cloud" in item.lower() for item in config["models"]):
        raise ValueError("Local model conditions cannot name cloud routing aliases")
    temperature = local.get("temperature")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not 0 <= temperature <= 2
    ):
        raise ValueError("Invalid local inference temperature")
    digests = local.get("model_digests")
    if (
        not isinstance(digests, dict)
        or set(digests) != set(config["models"])
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            for digest in digests.values()
        )
    ):
        raise ValueError("Bind every declared local model to its exact manifest digest")


def decision_time_reserve(config: dict) -> int:
    """Scheduling allowance, not a promise about provider/network wall time.

    Each provider attempt can make an initial call and two compatibility calls.
    Every grammar attempt can exercise that path. Workers use a 60-second provider
    timeout; allow five seconds per dispatch for backoff and 60 for native work.
    The independent worker deadline still handles a stalled native call or network."""
    if config.get("schema_version") == LOCAL_SCHEMA:
        from ..agent.campaign_llama_identity import TRANSPORT

        local = config["local_inference"]
        if local["transport"] == TRANSPORT:
            # At most 13 history projections plus a refreshed preflight per round.
            # Include the initial decision preview and bounded identity/count calls.
            context_checks = (config["schema_attempts"] + 1) * 14
            return (
                context_checks * (6 + local["token_count_timeout_seconds"])
                + config["schema_attempts"] * (local["timeout_seconds"] + 6)
                + 60
            )
        return config["schema_attempts"] * (config["local_inference"]["timeout_seconds"] + 5) + 60
    return 3 * config["max_attempts"] * config["schema_attempts"] * 65 + 60


def load_segment_config(path: Path, model: str) -> dict:
    from ..env.workshop_placement import STRICT_FLOOR, validate_policy
    from .campaign_advance import ACCEPTED_ONLY, POLICIES

    config = read_config(path)
    endurance = config.get("schema_version") == ENDURANCE_SCHEMA
    local = config.get("schema_version") == LOCAL_SCHEMA
    validate_bounds(config, model, endurance=endurance, local=local)
    condition = config.get("condition_id")
    if (
        config.get("runner") != "campaign-loop/v1"
        or not isinstance(condition, str)
        or not condition.strip()
        or len(condition) > 128
    ):
        raise ValueError("Campaign segments require their own declared runner condition")
    profiles = (
        config.get("decision_profile", "governed_review/v1"),
        config.get("observation_profile", "governed_review/v1"),
    )
    exploratory_profiles = {
        ("campaign_action/v1", profile)
        for profile in CAMPAIGN_OBSERVATION_PROFILES
        if profile != OBSERVATION_PROFILE
    }
    exploratory_profiles.add((DECISION_PROFILE, OBSERVATION_PROFILE))
    if not all(isinstance(profile, str) for profile in profiles) or profiles not in {
        ("governed_review/v1", "governed_review/v1"),
        *exploratory_profiles,
    }:
        raise ValueError("Unsupported or mismatched campaign profiles")
    if profiles in exploratory_profiles and (
        type(config.get("schema_attempts")) is not int or not 1 <= config["schema_attempts"] <= 3
    ):
        raise ValueError("Campaign schema_attempts must be one to three")
    advance_policy = config.get("advance_policy", ACCEPTED_ONLY)
    if not isinstance(advance_policy, str) or advance_policy not in POLICIES:
        raise ValueError("Unsupported campaign advance policy")
    if advance_policy != ACCEPTED_ONLY and profiles not in exploratory_profiles:
        raise ValueError("Requested-time policy requires exploratory campaign profiles")
    placement_policy = validate_policy(config.get("workshop_placement_policy", STRICT_FLOOR))
    if placement_policy != STRICT_FLOOR and profiles not in exploratory_profiles:
        raise ValueError("Workshop ground policy requires exploratory campaign profiles")
    if endurance or local:
        if profiles not in exploratory_profiles:
            raise ValueError("Endurance conditions require exploratory campaign profiles")
        if config["segment_time_budget_seconds"] <= decision_time_reserve(config):
            raise ValueError("Segment time budget must fit the declared decision retry allowance")
    return config
