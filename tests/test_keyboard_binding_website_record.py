"""Keep website acceptance separate from native play, browser QA and deployment."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def record():
    return json.loads(
        (ROOT / "experiments/evidence/keyboard_binding_website_20260911.json").read_text()
    )


def test_website_record_matches_published_native_result_without_relabeling_it():
    value = record()
    result = json.loads(
        (ROOT / "experiments/evidence/keyboard_binding_astra_r1_20260911.json").read_text()
    )
    pilot = value["displayed_key_pilot"]
    assert value["campaign_id"] == result["campaign_id"]
    assert pilot["responses"] == result["responses"] == pilot["decision_rows"]
    assert pilot["saved_elapsed_ticks"] == result["saved_elapsed_ticks"]
    assert pilot["returned_tokens"] == result["usage"]["total_tokens"]
    assert pilot["separate_from_historical_cohort"] is True
    assert pilot["unknown_charge_shown_as_zero"] is False
    assert pilot["fresh_final_reload_claimed"] is False


def test_full_test_retry_and_real_http_evidence_have_bounded_scope():
    value = record()
    verification = value["verification"]
    assert verification["full_suite"]["passed"] == 4974
    assert verification["full_suite"]["failed"] == 0
    assert verification["first_sandbox_limited_suite"]["failed"] == 1
    assert verification["first_sandbox_limited_suite"]["source_unchanged_for_successful_rerun"]
    assert verification["http_acceptance_passed"] is True
    assert len(verification["historical_routes_byte_identical"]) == 4
    assert verification["globally_clean_static_checks"] is False
    assert not any(value["proof_limits"].values())
    assert value["model_calls"] == value["game_vm_starts"] == value["cloud_vms_created"] == 0


def test_preview_feed_fix_preserves_evidence_and_validation():
    repair = record()["preview_feed_repair"]
    assert repair["prior_http_status"] == 503 and repair["current_http_status"] == 200
    assert repair["published_campaign_snapshots"] == 11
    assert repair["original_directory_unchanged"] is True
    assert repair["generic_feed_validation_weakened"] is False
