"""Offline prompt, courier, and checkpoint boundaries for character reference."""

import hashlib
from pathlib import Path
import sys

import pytest

from fort_gym.bench.agent import keyboard_decision
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import digest, read
from fort_gym.bench.agent.keyboard_prompt import (
    BASE_PROMPT,
    CHARACTER_CONTRACT,
    CHARACTER_PROMPT,
    MEMORY_CONTRACT,
    MEMORY_PROMPT,
)
from fort_gym.bench.env.native_key_catalog import LEGACY_PROFILE, NATIVE_PROFILE, NATIVE_KEYS
from fort_gym.bench.env.screen_observation import TEXT_PROFILE
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_decision import response
from tests.test_keyboard_prompt import condition, declaration, run_segment, selection
from tests.test_keyboard_runtime import saved as saved


def capture(monkeypatch):
    calls = []

    def transport(prompt, schema, **options):
        calls.append((prompt, schema, options))
        return {
            "accepted": True,
            "response": response(),
            "run_directory": str(options["artifact_root"]),
        }

    monkeypatch.setattr(keyboard_decision, "request_decision", transport)
    return calls


def request(output, profile, **options):
    return keyboard_decision.request_keyboard_decision(
        {"width": 1, "height": 1, "tiles": [[65, 7, 0]], "hidden": "not for the model"},
        executable=Path(sys.executable),
        artifact_root=output,
        allowance_check=lambda: {},
        memory="retained fixture memory",
        feedback={"accepted": True},
        prompt_profile=profile,
        **options,
    )


@pytest.mark.parametrize(
    "profile,control,observation,expected",
    [
        (
            BASE_PROMPT,
            LEGACY_PROFILE,
            "native_screen_tiles/v1",
            "5d25c3abb6a4d81dc63c00343193ad1d3052d316e7533db44bf5e4dc56f0bc99",
        ),
        (
            BASE_PROMPT,
            NATIVE_PROFILE,
            TEXT_PROFILE,
            "ba89a06927ccb1b59d38975f9ca2b70aff3735f2f149284444a2212cf7c56e2f",
        ),
        (
            MEMORY_PROMPT,
            LEGACY_PROFILE,
            "native_screen_tiles/v1",
            "bbbabf0413b43dcf7f7d2d85ace7e564800c36d003888d11a78e427029903a25",
        ),
        (
            MEMORY_PROMPT,
            NATIVE_PROFILE,
            TEXT_PROFILE,
            "5ca7c4a3165f7d8f8acdaa0cb1084d33d95d30566419114daa89a1422370eda6",
        ),
    ],
)
def test_historical_prompt_bytes_are_frozen(
    tmp_path, monkeypatch, profile, control, observation, expected
):
    # Recorded from parent 4590fc1 before adding the new opt-in profile.
    calls = capture(monkeypatch)
    request(tmp_path, profile, control_profile=control, observation_profile=observation)
    assert hashlib.sha256(calls[0][0].encode()).hexdigest() == expected


def test_new_profile_adds_only_generic_reference(tmp_path, monkeypatch):
    calls, results = capture(monkeypatch), []
    for index, profile in enumerate((MEMORY_PROMPT, CHARACTER_PROMPT)):
        output = tmp_path / str(index)
        output.mkdir()
        results.append(
            request(
                output,
                profile,
                control_profile=NATIVE_PROFILE,
                observation_profile=TEXT_PROFILE,
            )
        )
    baseline, changed = (call[0] for call in calls)
    assert changed.replace("\n" + CHARACTER_CONTRACT + "\n", "") == baseline
    assert changed.count(CHARACTER_CONTRACT) == changed.count(MEMORY_CONTRACT) == 1
    assert calls[0][1] == calls[1][1]
    assert "not for the model" not in changed
    assert results[0]["screen_sha256"] == results[1]["screen_sha256"]
    assert results[0]["action"] == results[1]["action"] == response()
    assert results[1]["prompt_profile"] == CHARACTER_PROMPT
    assert results[1]["native_action_dispatched"] is False
    for char in "aA0":
        assert f"STRING_A{ord(char):03d}" in CHARACTER_CONTRACT
        assert f"STRING_A{ord(char):03d}" in NATIVE_KEYS


def test_legacy_controls_reject_character_profile_before_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        keyboard_decision,
        "request_decision",
        lambda *a, **k: pytest.fail("Incompatible controls reached the model"),
    )
    with pytest.raises(ValueError, match="requires the native_keyboard/v2"):
        request(tmp_path, CHARACTER_PROMPT, control_profile=LEGACY_PROFILE)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra"])
def test_courier_binds_new_profile_and_preserves_model_keys(tmp_path, monkeypatch, model):
    calls = []
    action = {**response(), "params": {"keys": ["CUSTOM_A", "STRING_A097", "STRING_A065"]}}

    def transport(prompt, schema, **options):
        calls.append((prompt, options))
        return {"accepted": True, "response": action, "run_directory": str(tmp_path)}

    monkeypatch.setattr(keyboard_decision, "request_decision", transport)
    selected = {**selection(), "model": model, "prompt_profile": CHARACTER_PROMPT}
    value, _ = answer_request(
        selected,
        directory=tmp_path,
        condition={**condition(CHARACTER_PROMPT), "model": model},
        executable=Path(sys.executable),
        allowance_check=lambda: {},
    )
    assert value["request_sha256"] == digest(selected)
    assert value["request_sha256"] != digest({**selected, "prompt_profile": MEMORY_PROMPT})
    assert value["result"]["action"] == action
    assert value["result"]["prompt_profile"] == CHARACTER_PROMPT
    assert calls[0][1]["model"] == model
    assert calls[0][1]["reasoning_effort"] == "medium"
    assert CHARACTER_CONTRACT in calls[0][0]


def test_saved_memory_profile_needs_explicit_character_change(tmp_path, saved):
    checkpoint, usage, tick = saved
    first = tmp_path / "memory"
    _, env, _ = run_segment(first, checkpoint, usage, tick, change=declaration(checkpoint))
    checkpoint, usage = first / "checkpoint", first / "loop/usage.jsonl"
    before, manifest = read(checkpoint / "agent.json"), verify_checkpoint(checkpoint)
    with pytest.raises(ValueError, match="without a declared change"):
        run_segment(
            tmp_path / "undeclared", checkpoint, usage, env.tick, config=condition(CHARACTER_PROMPT)
        )
    assert not (tmp_path / "undeclared").exists()
    change = {
        **declaration(checkpoint),
        "previous": MEMORY_PROMPT,
        "profile": CHARACTER_PROMPT,
    }
    result, _, agent = run_segment(
        tmp_path / "character",
        checkpoint,
        usage,
        env.tick,
        change=change,
        config=condition(CHARACTER_PROMPT),
        callback=lambda *args: {**decision(*args), "prompt_profile": CHARACTER_PROMPT},
    )
    assert result["checkpoint_verified"] is True
    assert result["first_step"] == manifest["payload"]["next_step"]
    assert agent.memory == before["memory"] + "xx"
    assert agent.usage["total_tokens"] == before["usage"]["total_tokens"] + 200
    assert agent.prompt_changes[:-1] == before["prompt_changes"]
    assert agent.prompt_changes[-1]["checkpoint_sha256"] == manifest["sha256"]
    assert agent.prompt_profile == CHARACTER_PROMPT
