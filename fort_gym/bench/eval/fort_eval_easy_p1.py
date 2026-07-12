"""Frozen runtime contract for the provisional Fort-Eval Easy P1 comparison."""

from __future__ import annotations

import hashlib
from importlib import import_module
import json
import time
from typing import Any, Dict, Mapping

P1_PROTOCOL = "fort-eval-easy-p1-g7-v3"
P1_SEED_SAVE = "seed_region3_fresh"
P1_RUNTIME_SAVE = "region1"
P1_SEED_WORLD_SHA256 = "070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d"
P1_MAX_STEPS = 200
P1_TICKS_PER_STEP = 2500

MODEL_ARMS: Dict[str, Dict[str, str]] = {
    "dfhack-governed-llm-fable5": {
        "public_label": "Claude Fable 5",
        "provider_model": "anthropic/claude-fable-5",
        "resolved_model_prefix": "anthropic/claude-5-fable-",
        "cache": "explicit_ephemeral",
    },
    "dfhack-governed-llm-gpt56-sol": {
        "public_label": "GPT-5.6 Sol",
        "provider_model": "openai/gpt-5.6-sol",
        "resolved_model_prefix": "openai/gpt-5.6-sol-",
        "cache": "automatic",
    },
}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def prompt_digest() -> str:
    from ..agent.governed_llm import (
        GOVERNED_OBSERVATION_PREAMBLE,
        GOVERNED_SYSTEM_PROMPT,
        _submit_action_tool,
    )

    payload = {
        "system": GOVERNED_SYSTEM_PROMPT,
        "observation_preamble": GOVERNED_OBSERVATION_PREAMBLE,
        "tool": _submit_action_tool(max_advance_ticks=P1_TICKS_PER_STEP),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_p1_declaration(
    *,
    protocol: str | None,
    backend: str,
    model: str,
    seed_save: str | None,
    runtime_save: str | None,
    preserve_save: bool,
    max_steps: int,
    ticks_per_step: int,
) -> None:
    if protocol != P1_PROTOCOL:
        return
    mismatches = []
    if backend != "dfhack":
        mismatches.append("backend must be dfhack")
    if model not in MODEL_ARMS:
        mismatches.append("model is not a declared P1 arm")
    if seed_save != P1_SEED_SAVE:
        mismatches.append(f"seed_save must be {P1_SEED_SAVE}")
    if runtime_save != P1_RUNTIME_SAVE:
        mismatches.append(f"runtime_save must be {P1_RUNTIME_SAVE}")
    if preserve_save:
        mismatches.append("preserve_save must be false")
    if max_steps != P1_MAX_STEPS:
        mismatches.append(f"max_steps must be {P1_MAX_STEPS}")
    if ticks_per_step != P1_TICKS_PER_STEP:
        mismatches.append(f"ticks_per_step must be {P1_TICKS_PER_STEP}")
    if mismatches:
        raise ValueError("invalid Fort-Eval Easy P1 declaration: " + "; ".join(mismatches))


def attest_seed_region3(
    state: Mapping[str, Any],
    *,
    runtime_save: str | None,
    seed_world_sha256: str | None = None,
) -> Dict[str, Any]:
    stocks = state.get("stocks") if isinstance(state.get("stocks"), Mapping) else {}
    work = state.get("work") if isinstance(state.get("work"), Mapping) else {}
    fort = state.get("fort") if isinstance(state.get("fort"), Mapping) else {}
    crew = state.get("crew") if isinstance(state.get("crew"), Mapping) else {}
    citizens = crew.get("citizens") if isinstance(crew.get("citizens"), Mapping) else {}
    survival = state.get("survival") if isinstance(state.get("survival"), Mapping) else {}
    nearby_trees = fort.get("nearby_trees") if isinstance(fort.get("nearby_trees"), Mapping) else {}
    seeds = crew.get("seeds") if isinstance(crew.get("seeds"), list) else []
    plump_count = sum(
        _to_int(seed.get("count"))
        for seed in seeds
        if isinstance(seed, Mapping) and seed.get("token") == "MUSHROOM_HELMET_PLUMP"
    )
    checks = {
        "pristine_seed_digest": seed_world_sha256 == P1_SEED_WORLD_SHA256,
        "paused": state.get("pause_state") is True,
        "initial_tick": _to_int(state.get("time")) == 16801,
        "population": _to_int(state.get("population")) == 7,
        "food": _to_int(stocks.get("food")) == 45,
        "drink": _to_int(stocks.get("drink")) == 60,
        "initial_wealth": _to_int(stocks.get("wealth")) == 9,
        "no_deaths": _to_int(state.get("dead")) == 0,
        "no_hostiles": state.get("hostiles") is False,
        "no_risks": list(state.get("risks") or []) == [],
        "no_workshops": _to_int(work.get("workshop_count")) == 0,
        "no_farm_plots": _to_int(crew.get("farm_plots")) == 0,
        "no_fort_structures": all(
            _to_int(fort.get(key)) == 0
            for key in ("player_buildings", "constructions", "functional_rooms")
        ),
        "nearby_timber": _to_int(nearby_trees.get("total")) >= 200,
        "plump_helmet_spawn": plump_count >= 5,
        "miner_available": _to_int(citizens.get("mining_labor")) >= 1,
        "woodcutter_available": _to_int(citizens.get("woodcutting_labor")) >= 1,
        "carpenter_available": _to_int(citizens.get("carpentry_labor")) >= 1,
        "clean_g7_ledger": (
            survival.get("active") is True
            and _to_int(survival.get("food_produced_in_run")) == 0
            and _to_int(survival.get("drink_produced_in_run")) == 0
            and _to_int(survival.get("deaths_in_run")) == 0
        ),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    return {
        "schema_version": "fort-eval.seed-attestation/v1",
        "seed_save": P1_SEED_SAVE,
        "runtime_save": runtime_save,
        "seed_world_sha256": seed_world_sha256,
        "eligible": not failed,
        "checks": checks,
        "failed_checks": failed,
        "observed": {
            "tick": _to_int(state.get("time")),
            "population": _to_int(state.get("population")),
            "food": _to_int(stocks.get("food")),
            "drink": _to_int(stocks.get("drink")),
            "nearby_trees": _to_int(nearby_trees.get("total")),
            "plump_helmet_spawn": plump_count,
        },
    }


def p1_summary_metadata(*, model: str, fort_gym_commit: str | None) -> Dict[str, Any]:
    arm = MODEL_ARMS[model]
    model_digest = (
        f"openrouter:{arm['provider_model']}|reasoning=max|max_tokens=128000|"
        f"vision=on|memory=off|cache={arm['cache']}"
    )
    return {
        "public_label": arm["public_label"],
        "task_id": "g7_survival",
        "task_version": "g7-v3",
        "seed_split": "fixed_seed_pilot",
        "mechanics_digest": "df-51.11+governed-semantic-dfhack-v1",
        "observation_digest": "governed_structured_state_v1+fort_minimap_vision_v1",
        "action_digest": "legal_semantic_dfhack_v1",
        "budget_digest": "max_steps_200_ticks_per_step_2500",
        "model_digest": model_digest,
        "prompt_digest": prompt_digest(),
        "memory_digest": "memory_off",
        "fort_gym_commit": fort_gym_commit,
        "df_version": "df-51.11",
        "evaluator_version": "score-v5+g7-v3",
    }


def resolved_model_digest(*, model: str, usage: Mapping[str, Any]) -> str:
    arm = MODEL_ARMS[model]
    resolved = ",".join(sorted(str(item) for item in usage.get("resolved_models") or []))
    providers = ",".join(sorted(str(item) for item in usage.get("providers") or []))
    return (
        f"openrouter:{arm['provider_model']}|resolved={resolved or 'unavailable'}|"
        f"providers={providers or 'unavailable'}|reasoning=max|max_tokens=128000|"
        f"vision=on|memory=off|cache={arm['cache']}"
    )


def p1_usage_is_publishable(*, model: str, usage: Mapping[str, Any]) -> bool:
    arm = MODEL_ARMS[model]
    resolved_models = list(usage.get("resolved_models") or [])
    generation_ids = list(usage.get("generation_ids") or [])
    calls = _to_int(usage.get("calls"))
    generations = list(usage.get("generation_metadata") or [])
    return bool(
        calls > 0
        and list(usage.get("models") or []) == [arm["provider_model"]]
        and resolved_models
        and all(
            str(resolved).startswith(arm["resolved_model_prefix"])
            for resolved in resolved_models
        )
        and list(usage.get("providers") or [])
        and len(generation_ids) == calls
        and len(generations) == calls
        and all(
            str(generation.get("model") or "").startswith(
                arm["resolved_model_prefix"]
            )
            for generation in generations
        )
        and _to_int(usage.get("calls_missing_cost")) == 0
        and _to_int(usage.get("calls_missing_resolved_model")) == 0
        and _to_int(usage.get("cached_tokens")) > 0
        and usage.get("generation_telemetry_complete") is True
    )


def p1_integrity_attestation(
    terminal_failure_reason: Mapping[str, Any] | None,
    *,
    run_failed: bool,
) -> Dict[str, Any]:
    """Separate benchmark/task failure from invalid harness execution."""

    valid = terminal_failure_reason is None and not run_failed
    failure_reason = terminal_failure_reason
    if failure_reason is None and run_failed:
        failure_reason = {"code": "run_aborted_without_terminal_reason"}
    return {
        "schema_version": "fort-eval.integrity-attestation/v1",
        "status": "pass" if valid else "fail",
        "terminal_reason": (
            dict(failure_reason) if failure_reason is not None else None
        ),
    }


def enrich_openrouter_usage(
    usage: Mapping[str, Any],
    *,
    api_key: str | None,
    base_url: str,
) -> Dict[str, Any]:
    """Resolve provider accounting after a run, when generation rows are durable."""

    enriched = dict(usage)
    generation_ids = list(usage.get("generation_ids") or [])
    if not api_key:
        enriched["generation_telemetry_complete"] = False
        enriched["generation_telemetry_error"] = "OPENROUTER_API_KEY unavailable"
        return enriched
    httpx = import_module("httpx")
    generations = []
    for generation_id in generation_ids:
        try:
            response = None
            for attempt in range(3):
                response = httpx.get(
                    f"{base_url.rstrip('/')}/generation",
                    params={"id": generation_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if response.status_code not in {404, 429, 500, 502, 503, 504}:
                    break
                time.sleep(attempt + 1)
            if response is None:
                raise RuntimeError("generation lookup was not attempted")
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict):
                raise ValueError("invalid generation payload")
            generations.append(
                {
                    "id": generation_id,
                    "model": data.get("model"),
                    "provider_name": data.get("provider_name") or data.get("provider"),
                    "total_cost": data.get("total_cost"),
                    "cache_discount": data.get("cache_discount"),
                    "native_tokens_prompt": data.get("native_tokens_prompt"),
                    "native_tokens_completion": data.get("native_tokens_completion"),
                    "status": "available",
                }
            )
        except Exception as exc:
            generations.append(
                {
                    "id": generation_id,
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                    "message": str(exc)[:240],
                }
            )
    available = [
        item
        for item in generations
        if item["status"] == "available"
        and item.get("model")
        and item.get("provider_name")
        and item.get("total_cost") is not None
        and item.get("native_tokens_prompt") is not None
        and item.get("native_tokens_completion") is not None
    ]
    enriched["generation_metadata"] = generations
    enriched["providers"] = sorted(
        {str(item["provider_name"]) for item in available if item.get("provider_name")}
    )
    enriched["provider_total_cost_usd"] = round(
        sum(float(item.get("total_cost") or 0.0) for item in available), 8
    )
    enriched["provider_cache_discount_usd"] = round(
        sum(float(item.get("cache_discount") or 0.0) for item in available), 8
    )
    enriched["generation_telemetry_complete"] = (
        len(available) == len(generation_ids) == _to_int(usage.get("calls"))
    )
    enriched["generation_telemetry_unavailable"] = len(generations) - len(available)
    return enriched


__all__ = [
    "MODEL_ARMS",
    "P1_MAX_STEPS",
    "P1_PROTOCOL",
    "P1_RUNTIME_SAVE",
    "P1_SEED_SAVE",
    "P1_SEED_WORLD_SHA256",
    "P1_TICKS_PER_STEP",
    "attest_seed_region3",
    "enrich_openrouter_usage",
    "p1_integrity_attestation",
    "p1_summary_metadata",
    "p1_usage_is_publishable",
    "prompt_digest",
    "resolved_model_digest",
    "validate_p1_declaration",
]
