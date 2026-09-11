"""Fresh inspection condition, without changing historical model execution bounds."""

import hashlib
import json
from pathlib import Path

from fort_gym.bench.run.campaign_config import load_segment_config

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "experiments/campaigns/local_native_qwen35_year_two_reasoning_budget_v1.json"
CANDIDATE = ROOT / "experiments/campaigns/local_native_qwen35_year_two_inspection_v1.json"


def test_new_inspection_condition_changes_only_declared_interfaces_and_metadata():
    before = BASELINE.read_bytes()
    old = json.loads(before)
    new = load_segment_config(CANDIDATE, old["models"][0])
    assert new["condition_id"] == "local-native-qwen35-year-two-inspection-v1"
    assert new["decision_profile"] == "campaign_action/v2"
    assert new["observation_profile"] == "campaign_state/v3"
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    assert changed == {
        "condition_id",
        "decision_profile",
        "observation_profile",
        "hypothesis",
        "notes",
    }
    assert BASELINE.read_bytes() == before
    assert hashlib.sha256(CANDIDATE.read_bytes()).digest() != hashlib.sha256(before).digest()


def test_inspection_condition_keeps_original_seed_budget_and_local_transport():
    config = json.loads(CANDIDATE.read_text())
    assert config["starting_snapshot"] == json.loads(BASELINE.read_text())["starting_snapshot"]
    assert config["local_inference"]["transport"] == "llama-cpp-local/v1"
    assert config["local_inference"]["reasoning_budget_tokens"] == 2048
    assert config["max_output_tokens"] == 4096 and config["max_cost_usd"] == 0
    assert config["max_steps"] == 32 and config["max_segments"] == 8
    assert config["checkpoint_policy"]["interval_steps"] == 8
