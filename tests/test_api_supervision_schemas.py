from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from fort_gym.bench.api.schemas import (
    JobCreate,
    RunCreateRequest,
    SupervisedProviderPolicy,
)


def test_supervised_provider_policy_has_positive_default_on_caps() -> None:
    policy = SupervisedProviderPolicy(
        model="openai/test-model",
        provider_name="OpenAI",
    )

    assert policy.route == "openrouter"
    assert policy.max_total_tokens == 128_000
    assert policy.max_cost_usd == 25.0
    assert math.isfinite(policy.max_cost_usd)


@pytest.mark.parametrize(
    "override",
    [
        {"max_total_tokens": 0},
        {"max_cost_usd": 0},
        {"max_cost_usd": float("inf")},
        {"max_cost_usd": float("nan")},
        {"route": "direct"},
    ],
)
def test_supervised_provider_policy_rejects_missing_or_unbounded_authority(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SupervisedProviderPolicy(
            model="openai/test-model",
            provider_name="OpenAI",
            **override,
        )


def test_run_and_job_requests_reject_provider_credentials() -> None:
    provider = {
        "model": "openai/test-model",
        "provider_name": "OpenAI",
        "api_key": "must-not-enter-request-contract",
    }

    with pytest.raises(ValidationError):
        RunCreateRequest(
            backend="dfhack",
            supervision_mode="m1b-process",
            provider=provider,
        )
    with pytest.raises(ValidationError):
        JobCreate(
            backend="dfhack",
            n=2,
            parallelism=2,
            max_steps=20,
            supervision_mode="m1b-process",
            provider=provider,
        )


def test_job_request_carries_reproducible_run_inputs() -> None:
    request = JobCreate(
        backend="dfhack",
        model="dfhack-governed-scripted",
        n=8,
        parallelism=8,
        preserve_save=False,
        seed_save="seed_region3_fresh",
        runtime_save_prefix="m1b-co8",
        evaluation_protocol="fort-eval-easy-v1",
        max_steps=20,
        supervision_mode="m1b-process",
    )

    assert request.n == 8
    assert request.parallelism == 8
    assert request.seed_save == "seed_region3_fresh"
    assert request.runtime_save_prefix == "m1b-co8"
    assert request.evaluation_protocol == "fort-eval-easy-v1"


def test_legacy_job_defaults_and_capacity_remain_compatible() -> None:
    request = JobCreate()
    larger_legacy = JobCreate(n=12, parallelism=3)

    assert request.n == 10
    assert request.parallelism == 2
    assert larger_legacy.n == 12
    assert larger_legacy.supervision_mode is None


@pytest.mark.parametrize(
    "factory,payload",
    [
        (RunCreateRequest, {"unknown_field": True}),
        (JobCreate, {"unknown_field": True}),
        (
            RunCreateRequest,
            {
                "supervision_mode": "m1b-process",
                "safe": False,
            },
        ),
        (
            RunCreateRequest,
            {
                "supervision_mode": "m1b-process",
                "safe": "yes",
            },
        ),
        (
            RunCreateRequest,
            {
                "supervision_mode": "m1b-process",
                "runtime_save": "exact-save",
            },
        ),
        (
            JobCreate,
            {
                "supervision_mode": "m1b-process",
                "n": 3,
                "parallelism": 2,
                "max_steps": 20,
            },
        ),
        (
            JobCreate,
            {
                "supervision_mode": "m1b-process",
                "n": 1,
                "parallelism": 1,
                "max_steps": 20,
                "safe": 1,
            },
        ),
    ],
)
def test_supervision_schemas_fail_closed_on_ambiguous_requests(
    factory, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        factory(**payload)


def test_supervised_run_distinguishes_runtime_prefix_from_legacy_exact_save() -> None:
    supervised = RunCreateRequest(
        backend="mock",
        model="fake",
        supervision_mode="m1b-process",
        runtime_save_prefix="fault-cohort",
    )
    legacy = RunCreateRequest(runtime_save="exact-save")

    assert supervised.runtime_save is None
    assert supervised.runtime_save_prefix == "fault-cohort"
    assert legacy.runtime_save == "exact-save"
    assert legacy.runtime_save_prefix is None


@pytest.mark.parametrize(
    "factory,payload",
    [
        (
            RunCreateRequest,
            {
                "backend": "mock",
                "model": "fake",
                "supervision_mode": "m1b-process",
            },
        ),
        (
            JobCreate,
            {
                "backend": "mock",
                "model": "fake",
                "n": 1,
                "parallelism": 1,
                "max_steps": 20,
                "supervision_mode": "m1b-process",
            },
        ),
    ],
)
def test_supervised_safe_requires_a_literal_true_json_boolean(
    factory, payload: dict[str, object]
) -> None:
    accepted = factory.model_validate_json(json.dumps({**payload, "safe": True}))
    assert accepted.safe is True

    for invalid in (False, 1, "true", "yes"):
        with pytest.raises(ValidationError):
            factory.model_validate_json(json.dumps({**payload, "safe": invalid}))


def test_legacy_safe_json_coercion_remains_compatible() -> None:
    run = RunCreateRequest.model_validate_json('{"safe":"false"}')
    job = JobCreate.model_validate_json('{"safe":1}')

    assert run.supervision_mode is None
    assert run.safe is False
    assert job.supervision_mode is None
    assert job.safe is True
