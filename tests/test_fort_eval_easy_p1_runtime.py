from __future__ import annotations

import pytest

from fort_gym.bench.eval.fort_eval_easy_p1 import (
    P1_PROTOCOL,
    P1_SEED_WORLD_SHA256,
    attest_seed_region3,
    p1_integrity_attestation,
    p1_usage_is_publishable,
    resolved_model_digest,
    validate_p1_declaration,
)


def _initial_state() -> dict:
    return {
        "time": 16801,
        "population": 7,
        "pause_state": True,
        "stocks": {"food": 45, "drink": 60, "wealth": 9},
        "dead": 0,
        "hostiles": False,
        "risks": [],
        "work": {"workshop_count": 0},
        "fort": {
            "player_buildings": 0,
            "constructions": 0,
            "functional_rooms": 0,
            "nearby_trees": {"total": 213},
        },
        "crew": {
            "farm_plots": 0,
            "citizens": {
                "mining_labor": 1,
                "woodcutting_labor": 1,
                "carpentry_labor": 1,
            },
            "seeds": [{"token": "MUSHROOM_HELMET_PLUMP", "count": 5}],
        },
        "survival": {
            "active": True,
            "food_produced_in_run": 0,
            "drink_produced_in_run": 0,
            "deaths_in_run": 0,
        },
    }


def test_seed_region3_attestation_accepts_frozen_start() -> None:
    result = attest_seed_region3(
        _initial_state(),
        runtime_save="fortgym_runtime",
        seed_world_sha256=P1_SEED_WORLD_SHA256,
    )

    assert result["eligible"] is True
    assert result["failed_checks"] == []
    assert result["observed"]["nearby_trees"] == 213


def test_seed_region3_attestation_fails_closed_on_prior_world_change() -> None:
    state = _initial_state()
    state["fort"]["player_buildings"] = 1
    state["stocks"]["food"] = 44

    result = attest_seed_region3(
        state,
        runtime_save="fortgym_runtime",
        seed_world_sha256=P1_SEED_WORLD_SHA256,
    )

    assert result["eligible"] is False
    assert result["failed_checks"] == ["food", "no_fort_structures"]


def test_p1_declaration_requires_exact_arm_seed_and_budget() -> None:
    validate_p1_declaration(
        protocol=P1_PROTOCOL,
        backend="dfhack",
        model="dfhack-governed-llm-gpt56-sol",
        seed_save="seed_region3_fresh",
        runtime_save="region1",
        preserve_save=False,
        max_steps=200,
        ticks_per_step=2500,
    )

    with pytest.raises(ValueError, match="ticks_per_step must be 2500"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="region1",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2000,
        )

    with pytest.raises(ValueError, match="runtime_save must be region1"):
        validate_p1_declaration(
            protocol=P1_PROTOCOL,
            backend="dfhack",
            model="dfhack-governed-llm-gpt56-sol",
            seed_save="seed_region3_fresh",
            runtime_save="other-runtime",
            preserve_save=False,
            max_steps=200,
            ticks_per_step=2500,
        )


def test_non_p1_declaration_is_unchanged() -> None:
    validate_p1_declaration(
        protocol="fort-eval-easy-v1",
        backend="mock",
        model="random",
        seed_save=None,
        runtime_save=None,
        preserve_save=False,
        max_steps=1,
        ticks_per_step=1,
    )


def test_p1_usage_requires_cache_and_provider_truth() -> None:
    usage = {
        "calls": 200,
        "models": ["openai/gpt-5.6-sol"],
        "resolved_models": ["openai/gpt-5.6-sol-20260709"],
        "providers": ["OpenAI"],
        "generation_ids": [f"gen-{index}" for index in range(200)],
        "generation_metadata": [
            {
                "id": f"gen-{index}",
                "model": "openai/gpt-5.6-sol-20260709",
                "provider_name": "OpenAI",
                "total_cost": 0.01,
                "native_tokens_prompt": 5000,
                "native_tokens_completion": 500,
                "status": "available",
            }
            for index in range(200)
        ],
        "calls_missing_cost": 0,
        "calls_missing_resolved_model": 0,
        "cached_tokens": 900_000,
        "generation_telemetry_complete": True,
    }

    assert p1_usage_is_publishable(model="dfhack-governed-llm-gpt56-sol", usage=usage)
    assert "providers=OpenAI" in resolved_model_digest(
        model="dfhack-governed-llm-gpt56-sol", usage=usage
    )

    usage["cached_tokens"] = 0
    assert not p1_usage_is_publishable(
        model="dfhack-governed-llm-gpt56-sol", usage=usage
    )

    usage["cached_tokens"] = 900_000
    usage["resolved_models"] = ["openai/gpt-5.5"]
    assert not p1_usage_is_publishable(
        model="dfhack-governed-llm-gpt56-sol", usage=usage
    )


def test_p1_integrity_attestation_rejects_harness_terminal_failure() -> None:
    assert p1_integrity_attestation(None, run_failed=False) == {
        "schema_version": "fort-eval.integrity-attestation/v1",
        "status": "pass",
        "terminal_reason": None,
    }

    failed = p1_integrity_attestation(
        {"code": "tick_request_attestation_failed", "requested_ticks": 2500},
        run_failed=True,
    )
    assert failed["status"] == "fail"
    assert failed["terminal_reason"]["code"] == "tick_request_attestation_failed"

    aborted = p1_integrity_attestation(None, run_failed=True)
    assert aborted["status"] == "fail"
    assert aborted["terminal_reason"] == {
        "code": "run_aborted_without_terminal_reason"
    }
