"""Published continuation accounting, distinct from fresh native gameplay proof."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"


def records():
    return (
        json.loads((EVIDENCE / "keyboard_binding_astra_r1_20260911.json").read_text()),
        json.loads(
            (EVIDENCE / "keyboard_binding_astra_r1_continuation_32_64_20260911.json").read_text()
        ),
    )


def test_continuation_is_not_a_new_or_historical_cohort_attempt():
    prior, result = records()
    assert result["campaign_id"] == prior["campaign_id"]
    assert result["source_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert result["condition"]["control_profile"] == "native_keyboard_bindings/v1"
    assert result["condition"]["model"] == "gpt-6-astra"
    assert result["condition"]["reasoning_effort"] == "medium"
    limits = result["proof_limits"]
    assert limits["same_campaign_own_save_continuation"] is True
    for key in (
        "same_condition_as_historical_matched_cohort",
        "memory_or_usage_reset",
        "prompt_or_budget_changed",
        "human_gameplay_rescue",
        "strong_model_ranking_supported",
    ):
        assert limits[key] is False


def test_all_new_responses_time_and_tokens_reconcile():
    prior, result = records()
    rows = result["timeline"]
    assert result["first_step"] == prior["responses"] == 32
    assert len(rows) == result["new_responses"] <= 32
    assert result["responses"] == prior["responses"] + len(rows)
    assert [row["decision"] for row in rows] == list(range(33, result["responses"] + 1))
    assert sum(row["returned_tokens"] for row in rows) == result["new_tokens"]
    assert result["usage"]["total_tokens"] == prior["usage"]["total_tokens"] + result["new_tokens"]
    assert sum(row["ticks_advanced"] for row in rows) == result["new_saved_elapsed_ticks"]
    assert (
        result["saved_elapsed_ticks"]
        == prior["saved_elapsed_ticks"] + result["new_saved_elapsed_ticks"]
    )
    assert sum(row["confirmed_key_presses"] for row in rows) == result["new_confirmed_key_presses"]
    assert result["audit"]["provider_receipts_verified"] == len(rows)
    assert result["usage"]["accounted_responses"] == result["responses"]


def test_saved_metrics_and_calendar_match_last_committed_boundary():
    prior, result = records()
    start, end = prior["final_boundary"], result["final_boundary"]
    assert end["paused"] is True
    delta = (end["year"] - start["year"]) * 403200 + end["year_tick"] - start["year_tick"]
    assert delta == result["new_saved_elapsed_ticks"]
    if result["timeline"]:
        assert result["saved_metrics"] == result["timeline"][-1]["metrics"]
        assert result["timeline"][-1]["saved_elapsed_ticks"] == result["saved_elapsed_ticks"]
    assert result["audit"]["native_cleanup_verified"] is True
    assert result["audit"]["vm_teardown_verified"] is True


def test_unreported_costs_and_unproven_outcomes_remain_explicit():
    _, result = records()
    assert result["usage"]["total_cost_usd"] is None
    assert result["cost_limits"]["actual_model_charge_usd"] is None
    assert result["cost_limits"]["cloud_vms_created"] == 0
    assert result["cost_limits"]["api_fallback"] is False
    assert result["cost_limits"]["automatic_reset_consumption"] is False
    for key in (
        "sustainability_proven",
        "completed_production_measured",
        "completed_consumption_measured",
        "fresh_final_checkpoint_reload_verified",
        "public_website_deployed",
        "main_merged",
    ):
        assert result["proof_limits"][key] is False


def test_public_result_contains_no_private_paths_or_memory():
    _, result = records()
    serialized = json.dumps(result)
    assert "/Users/" not in serialized and "memory_update" not in serialized
    assert "prompt.txt" not in serialized and "codex-decision-" not in serialized
