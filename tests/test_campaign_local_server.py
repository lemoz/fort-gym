"""Temporary server launch declarations, never real process or model starts."""

import json

import pytest

from scripts.campaign_local_server import server_environment
from fort_gym.bench.run.campaign_config import load_segment_config
from tests.test_campaign_local import CONFIG, MODEL


@pytest.mark.parametrize(
    "profile,flash,cache_type",
    [(None, "0", "f16"), ("standard_f16/v1", "0", "f16"), ("flash_q8/v1", "1", "q8_0")],
)
def test_declared_profile_controls_only_temporary_loopback_server(
    tmp_path, profile, flash, cache_type
):
    config = json.loads(CONFIG.read_text())
    if profile is not None:
        config["local_inference"]["runtime_profile"] = profile
    env = server_environment(
        config,
        cache=tmp_path,
        port=11439,
        inherited={
            "HOME": "/existing/home",
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "private-key",
            "HTTPS_PROXY": "https://private-proxy",
            "OLLAMA_HOST": "0.0.0.0:11434",
            "OLLAMA_MODELS": "/unrelated/cache",
            "OLLAMA_MAX_LOADED_MODELS": "99",
        },
    )
    assert env["HOME"] == "/existing/home" and env["OLLAMA_HOST"] == "127.0.0.1:11439"
    assert env["OLLAMA_MODELS"] == str(tmp_path.resolve())
    assert env["OLLAMA_FLASH_ATTENTION"] == flash and env["OLLAMA_KV_CACHE_TYPE"] == cache_type
    assert env["OLLAMA_MAX_LOADED_MODELS"] == env["OLLAMA_NUM_PARALLEL"] == "1"
    assert "private-key" not in json.dumps(env) and "private-proxy" not in json.dumps(env)
    assert "OPENAI_API_KEY" not in env and "HTTPS_PROXY" not in env


@pytest.mark.parametrize("profile", [False, [], None, "unknown"])
def test_invalid_runtime_profile_fails_config_validation(tmp_path, profile):
    config = json.loads(CONFIG.read_text())
    config["local_inference"]["runtime_profile"] = profile
    path = tmp_path / "condition.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="runtime profile"):
        load_segment_config(path, MODEL)


@pytest.mark.parametrize("port", [True, 80, 5000, 11434, 65536])
def test_default_production_and_invalid_ports_are_not_used(tmp_path, port):
    with pytest.raises(ValueError, match="dedicated"):
        server_environment(json.loads(CONFIG.read_text()), cache=tmp_path, port=port, inherited={})


def test_missing_cache_never_falls_back_to_application_home(tmp_path):
    with pytest.raises(FileNotFoundError):
        server_environment(
            json.loads(CONFIG.read_text()), cache=tmp_path / "missing", port=11439, inherited={}
        )
    assert not (tmp_path / "missing").exists()


def test_qwen14_candidate_declares_cache_without_changing_frozen_ground_condition():
    candidate_path = CONFIG.parent / "local_native_qwen14_flash_q8_v1.json"
    candidate = load_segment_config(candidate_path, "qwen2.5:14b-instruct-q4_K_M")
    ground = json.loads((CONFIG.parent / "local_native_workshop_ground_v1.json").read_text())
    assert "runtime_profile" not in ground["local_inference"]
    assert candidate["local_inference"]["runtime_profile"] == "flash_q8/v1"
    assert candidate["local_inference"]["model_digests"] == {
        "qwen2.5:14b-instruct-q4_K_M": "7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6"
    }
    for key in (
        "decision_profile",
        "observation_profile",
        "advance_policy",
        "schema_attempts",
        "max_dispatches",
        "max_total_tokens",
        "max_request_bytes",
        "max_output_tokens",
        "max_advance_ticks",
        "workshop_placement_policy",
    ):
        assert candidate[key] == ground[key]
    for key in ("context_tokens", "prompt_contract", "prompt_packing", "seed", "temperature"):
        assert candidate["local_inference"][key] == ground["local_inference"][key]
