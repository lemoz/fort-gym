"""The longer window must extend, not reset or relabel, its audited campaign."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "experiments/keyboard_binding_continuation_20260911/window-96-256.json"
PREP = ROOT / "experiments/evidence/keyboard_binding_window_96_256_preparation_20260911.json"


def records():
    preparation = json.loads(PREP.read_text())
    source = ROOT / preparation["source_result"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == preparation["source_result_sha256"]
    assert hashlib.sha256(WINDOW.read_bytes()).hexdigest() == preparation["window_sha256"]
    return json.loads(WINDOW.read_text()), preparation, json.loads(source.read_text())


def test_five_segments_extend_exact_prior_save_and_counters():
    window, prep, prior = records()
    assert window["continuation_from_next_step"] == prior["responses"] == 96
    assert window["continuation_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert window["accounted_responses_before_window"] == prior["usage"]["accounted_responses"]
    assert window["returned_tokens_before_window"] == prior["usage"]["total_tokens"]
    assert window["saved_elapsed_ticks_before_window"] == prior["saved_elapsed_ticks"]
    assert window["expected_campaign_id"] == prep["campaign_id"] == prior["campaign_id"]
    assert window["steps_per_segment"] == 32 and window["max_segments"] == 5
    assert window["window_end_decision"] == 96 + 32 * 5 == 256


def test_condition_and_cumulative_limits_are_not_extended():
    window, prep, prior = records()
    for key in ("reset_memory", "reset_usage", "strategy_intervention"):
        assert window[key] is False
    assert not ({"restart", "prompt_change", "budget_extension"} & window.keys())
    assert window["condition_id"] == prior["condition"]["condition_id"]
    assert prep["bounds"]["model"] == prior["condition"]["model"] == "gpt-6-astra"
    assert prep["bounds"]["reasoning_effort"] == prior["condition"]["reasoning_effort"] == "medium"
    assert (
        prep["bounds"]["cumulative_dispatch_limit_unchanged"]
        == prior["condition"]["max_dispatches"]
    )
    assert (
        prep["bounds"]["cumulative_token_limit_unchanged"] == prior["condition"]["max_total_tokens"]
    )


def test_preparation_does_not_claim_native_success_or_free_usage():
    _, prep, _ = records()
    assert prep["status"] == "prepared_not_started"
    assert prep["proof_limits"]["new_model_calls"] == prep["proof_limits"]["new_game_ticks"] == 0
    for key in (
        "new_native_load_verified",
        "sustainability_proven",
        "year_two_proven_by_this_preparation",
        "matched_model_ranking_supported",
        "main_merged",
        "public_website_deployed",
    ):
        assert prep["proof_limits"][key] is False
    assert prep["bounds"]["reported_actual_model_charge_usd"] is None
    assert prep["bounds"]["mandatory_teardown"] is True
    for key in (
        "cloud_vm_creation",
        "disk_growth",
        "evidence_deletion",
        "paid_api_fallback",
        "local_model_fallback",
        "automatic_usage_reset",
    ):
        assert prep["bounds"][key] is False
    assert (
        prep["binding"]["maximum_responses_per_start"] == prep["bounds"]["new_responses_max"] == 160
    )
    serialized = json.dumps(prep)
    assert "/Users/" not in serialized and "memory_update" not in serialized
