"""Validate the new experimental condition without running a game or model."""

from pathlib import Path

from fort_gym.bench.run.campaign_config import load_segment_config

ROOT = Path(__file__).resolve().parents[1]
MODEL = "fort-gym-qwen35-9b-q4-03b74727a860"


def test_local_year_two_condition_is_distinct_and_uses_existing_model():
    config = load_segment_config(
        ROOT / "experiments/campaigns/local_native_qwen35_year_two_v1.json", MODEL
    )
    old = load_segment_config(ROOT / "experiments/campaigns/local_native_llama_long_v2.json", MODEL)
    assert config["condition_id"] != old["condition_id"]
    assert config["local_inference"]["enable_thinking"] is False
    assert old["local_inference"]["enable_thinking"] is True
    assert config["max_output_tokens"] == 4096
    assert old["max_output_tokens"] == 2048
    assert config["local_inference"]["model_digests"] == old["local_inference"]["model_digests"]
    assert config["max_cost_usd"] == 0
    assert config["checkpoint_policy"]["interval_steps"] == 8


def test_year_two_condition_declares_start_and_sufficient_tick_envelope():
    config = load_segment_config(
        ROOT / "experiments/campaigns/local_native_qwen35_year_two_v1.json", MODEL
    )
    assert config["starting_snapshot"] == {
        "receipt_sha256": "eaf5fa5a40014719e6c313f33497740e536a8faa1c90a84c4e09dcc380ac0595",
        "year": 30,
        "year_tick": 16801,
        "provenance": "local_native_save_smoke_43a53762",
    }
    # Feasibility of the declared envelope is not evidence of model performance.
    assert config["max_steps"] * config["max_segments"] * config["max_advance_ticks"] > 403200
