"""Integrity of versioned projections; native proof comes from their audits."""

import hashlib
import json
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / "experiments/evidence"
RESULT = "keyboard_matched_astra_r1_continuation_32_64_20260910.json"
ASTRA_TWO_RESULT = "keyboard_matched_astra_r2_continuation_32_64_20260910.json"
SOL_RESULT = "keyboard_matched_sol_r1_continuation_32_64_20260910.json"
SOL_TWO_RESULT = "keyboard_matched_sol_r2_continuation_32_64_20260910.json"
TERRA_RESULT = "keyboard_matched_terra_r1_continuation_32_64_20260910.json"
TERRA_TWO_RESULT = "keyboard_matched_terra_r2_continuation_32_64_20260910.json"
WEBSITE = "keyboard_matched_continuation_website_20260910.json"
SAVED_WEBSITE = "keyboard_matched_saved_windows_website_20260910.json"
ENDURANCE = "keyboard_matched_endurance_preparation_20260910.json"
ENDURANCE_DELIVERY = "keyboard_matched_endurance_delivery_20260911.json"
ENDURANCE_LAUNCH = "keyboard_matched_astra_r1_endurance_launch_20260911.json"
ASTRA_ENDURANCE = "keyboard_matched_astra_r1_continuation_64_128_20260911.json"
SOL_ENDURANCE = "keyboard_matched_sol_r1_continuation_64_128_20260911.json"
TERRA_ENDURANCE = "keyboard_matched_terra_r1_continuation_64_128_20260911.json"
TERRA_TWO_ENDURANCE = "keyboard_matched_terra_r2_continuation_64_128_20260911.json"
ENDURANCE_RECORDS_CODE = "keyboard_matched_endurance_records_code_20260911.json"
ENDURANCE_RECORDS_WEBSITE = "keyboard_matched_endurance_records_website_20260911.json"
ENDURANCE_COHORT_WEBSITE = "keyboard_matched_endurance_cohort_website_20260911.json"


@pytest.mark.parametrize(
    "filename,expected",
    [
        (RESULT, "2c8abe1f7135d94ed27aea51e18ebc59e0599205caf3f268f4480b0e377f3d29"),
        (ASTRA_TWO_RESULT, "b5b195022876f8342c26e97634a8645cfb8beb885475a493187dc5fff7d90f1e"),
        (SOL_RESULT, "a624a9687257157aa91029d950ca1735a0e8f1baaa224cb66bba7efac50a1dbd"),
        (SOL_TWO_RESULT, "2f261d841808126b4f26cb55dcd47faae36ed37a7310c71648fae0fc531f26da"),
        (TERRA_RESULT, "e81a20836eb6959a529b657a72339bca2e299203c73188006fb32d682c734e11"),
        (TERRA_TWO_RESULT, "1966bf1e8229e8fbfd7a161d84c78da272dd3f5c9aa86040f59a8baa415ef1b8"),
        (WEBSITE, "c5cb272a0b62646fa6c495d5157b68a51a758544fc9c538bd715bf08dbf3f8c9"),
        (SAVED_WEBSITE, "a2d9a1ef556697a734c425a6c9c8571069d409719bd9d86ef16477926d79b57f"),
        (ENDURANCE, "46a6320ca1c2a23045a5d98df4d7ae30992d10e36e810b774df8f842e29939d9"),
        (ENDURANCE_DELIVERY, "d465e575ce547461a878b845d82ca073440d8da47a7d90aaaeaa3c4cd39a5059"),
        (ENDURANCE_LAUNCH, "631758a6b511a120b30c12e0767d1f714657351a5baf31eeccc92769cb644a27"),
        (ASTRA_ENDURANCE, "cb9cc0c5af8f158848493b1e7b3bb79f4f4736f185fbf7ce96fb157095e1d145"),
        (SOL_ENDURANCE, "a155f9c940e242de32d216e9795291dc2093299b64ce57760b722ee7a0a33491"),
        (TERRA_ENDURANCE, "3e833f88a813192f3c3190847e551439c34c7741d5bb87443d156cd244fc0b4f"),
        (TERRA_TWO_ENDURANCE, "858276b6da253f86d08f6ee8fba4ce6cd7eb28cce2005f3c6fbb67aa7b2bf3a6"),
        (
            ENDURANCE_RECORDS_CODE,
            "c74715355b8c0a9fde359e21ec685af7d4e65c9f6952c05d3e88350b58e1cf93",
        ),
        (
            ENDURANCE_RECORDS_WEBSITE,
            "b673956ff1d5aa9686a9e796072fcfc63b80f4bfc7cc002090cdbd1999ee8626",
        ),
        (
            ENDURANCE_COHORT_WEBSITE,
            "8b4e277cb61b500b6f3155f74886465739025d31dc04f316421f0806ad9fb75f",
        ),
    ],
)
def test_exact_versioned_projections_and_private_state_exclusion(filename, expected):
    raw = (EVIDENCE / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    for forbidden in (b"/Users/", b'"/evidence/', b'"memory":', b'"screen":', b'"account_id":'):
        assert forbidden not in raw


def test_saved_continuation_separates_new_work_from_its_own_baseline():
    record = json.loads((EVIDENCE / RESULT).read_bytes())
    assert record["schema_version"] == "fortgym.public-matched-keyboard-continuation/v1"
    assert record["campaign_id"] == "matched-20260910-astra-r1"
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (
        32,
        64,
        32,
    )
    assert (
        record["saved_elapsed_ticks_before_window"] + record["new_saved_ticks"]
        == record["saved_elapsed_ticks"]
        == 18200
    )
    usage = record["usage"]
    assert usage["new_returned_tokens"] == 1425155
    assert (
        usage["returned_tokens_before_window"] + usage["new_returned_tokens"]
        == usage["campaign_returned_tokens"]
        == 2468751
    )
    assert usage["campaign_accounted_responses"] == 64 and usage["reported_charge_usd"] is None
    assert (
        record["prior_checkpoint_sha256"]
        == "f6d0975f4af1ca532d83df98bc426f5b164815f1ff35dab7202d559bf0ca53fd"
    )
    assert (
        record["checkpoint_sha256"]
        == "b3e4b087b1ea36759cd8023b58645d5f741d1db617982cb1014637d8bf33ba50"
    )
    timeline = record["new_window_timeline"]
    assert [point["decision"] for point in timeline] == list(range(33, 65))
    for point in timeline:
        assert point["campaign_elapsed_ticks"] == 11200 + point["new_elapsed_ticks"]
    assert timeline[-1]["campaign_elapsed_ticks"] == 18200
    assert timeline[-1]["metrics"] == record["saved_metrics"]
    assert record["initial_metrics"]["completed_workshops"] == 1
    assert record["saved_metrics"]["completed_workshops"] == 3
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["final_fresh_reload_verified"] is False
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["year_two_reached"] is record["sustainability_established"] is False
    assert record["human_gameplay_rescue"] is False and record["new_native_save_losses"] == 0
    assert record["new_window_clock_outcomes"] == {
        "blocking_native_menu": 1,
        "no_error": 29,
        "timeout_waiting_for_ticks": 2,
    }


def test_astra_128_save_retains_development_and_supply_changes_without_sustainability_claim():
    record = json.loads((EVIDENCE / ASTRA_ENDURANCE).read_bytes())
    parent = json.loads((EVIDENCE / RESULT).read_bytes())
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (
        64,
        128,
        64,
    )
    assert record["prior_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert (
        record["checkpoint_sha256"]
        == "bff0afda99c39e25fe9db7aeb01db77ab6a819cb20c5d82670a2188952cceec2"
    )
    assert record["initial_metrics"] == parent["saved_metrics"]
    assert (
        record["saved_elapsed_ticks"]
        == parent["saved_elapsed_ticks"] + record["new_saved_ticks"]
        == 51400
    )
    assert record["new_saved_ticks"] == 33200
    usage = record["usage"]
    assert usage["new_returned_tokens"] == 2075486
    assert (
        usage["campaign_returned_tokens"]
        == parent["usage"]["campaign_returned_tokens"] + 2075486
        == 4544237
    )
    assert usage["campaign_accounted_responses"] == 128 and usage["reported_charge_usd"] is None
    metrics = record["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (
        metrics["completed_beds"],
        metrics["completed_farms"],
        metrics["completed_workshops"],
    ) == (5, 2, 3)
    assert (metrics["food_stock"], metrics["drink_stock"]) == (29, 121)
    assert [row["decision"] for row in record["new_window_timeline"]] == list(range(65, 129))
    assert record["new_window_timeline"][-1]["metrics"] == metrics
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False
    assert record["year_two_reached"] is record["human_gameplay_rescue"] is False
    assert record["new_window_clock_outcomes"] == {"blocking_native_menu": 3, "no_error": 61}


def test_sol_128_save_separates_observed_digging_from_completed_development():
    record = json.loads((EVIDENCE / SOL_ENDURANCE).read_bytes())
    parent = json.loads((EVIDENCE / SOL_RESULT).read_bytes())
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (
        64,
        128,
        64,
    )
    assert record["prior_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert (
        record["checkpoint_sha256"]
        == "5c8e263dcdbf12908eb33d7317eaa1f88545d3a6d0c4fbd151fe69224e391b3f"
    )
    assert record["initial_metrics"] == parent["saved_metrics"]
    assert (
        record["saved_elapsed_ticks"]
        == parent["saved_elapsed_ticks"] + record["new_saved_ticks"]
        == 20000
    )
    assert record["new_saved_ticks"] == 14500
    assert record["usage"]["new_returned_tokens"] == 2029214
    assert (
        record["usage"]["campaign_returned_tokens"]
        == parent["usage"]["campaign_returned_tokens"] + 2029214
        == 3522467
    )
    metrics = record["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (
        metrics["completed_beds"],
        metrics["completed_farms"],
        metrics["completed_workshops"],
    ) == (0, 0, 0)
    assert (metrics["food_stock"], metrics["drink_stock"]) == (50, 60)
    assert record["new_window_activity"]["boundaries_with_job_type"]["Dig"] == 56
    assert [row["decision"] for row in record["new_window_timeline"]] == list(range(65, 129))
    assert record["new_window_timeline"][-1]["metrics"] == metrics
    assert record["new_window_clock_outcomes"] == {"no_error": 64}
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False
    assert record["year_two_reached"] is record["human_gameplay_rescue"] is False
    assert record["usage"]["reported_charge_usd"] is None


def test_terra_128_records_zero_gameplay_progress_without_infrastructure_failure():
    record = json.loads((EVIDENCE / TERRA_ENDURANCE).read_bytes())
    parent = json.loads((EVIDENCE / TERRA_RESULT).read_bytes())
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (
        64, 128, 64
    )
    assert record["status"] == "completed" and record["stop_reason"] == "segment_limit"
    assert record["prior_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert record["new_saved_ticks"] == 0
    assert record["saved_elapsed_ticks"] == parent["saved_elapsed_ticks"] == 13000
    assert record["saved_metrics"] == record["initial_metrics"] == parent["saved_metrics"]
    assert record["usage"]["new_returned_tokens"] == 1333731
    assert record["usage"]["campaign_returned_tokens"] == 2871632
    assert record["usage"]["campaign_accounted_responses"] == 128
    assert record["usage"]["reported_charge_usd"] is None
    assert [row["decision"] for row in record["new_window_timeline"]] == list(range(65, 129))
    assert all(row["new_elapsed_ticks"] == 0 for row in record["new_window_timeline"])
    assert all(row["accepted"] is True for row in record["new_window_timeline"])
    assert record["new_window_clock_outcomes"] == {"no_error": 64}
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False
    assert record["year_two_reached"] is record["human_gameplay_rescue"] is False


def test_terra_second_128_save_retains_supply_decline_and_rejected_key():
    record = json.loads((EVIDENCE / TERRA_TWO_ENDURANCE).read_bytes())
    parent = json.loads((EVIDENCE / TERRA_TWO_RESULT).read_bytes())
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (64, 128, 64)
    assert record["prior_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert record["new_saved_ticks"] == 13500
    assert record["saved_elapsed_ticks"] == parent["saved_elapsed_ticks"] + 13500 == 32500
    assert record["usage"]["new_returned_tokens"] == 1843767
    assert record["usage"]["campaign_returned_tokens"] == 4109237
    assert record["usage"]["campaign_accounted_responses"] == 128
    assert record["usage"]["reported_charge_usd"] is None
    metrics = record["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (metrics["completed_beds"], metrics["completed_farms"], metrics["completed_workshops"]) == (0, 0, 0)
    assert metrics["drink_stock"] == 53 < parent["saved_metrics"]["drink_stock"]
    assert metrics["food_stock"] == 50
    assert record["new_window_clock_outcomes"] == {"no_error": 63, "unsupported_native_keys": 1}
    assert [row["decision"] for row in record["new_window_timeline"]] == list(range(65, 129))
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False
    assert record["year_two_reached"] is record["human_gameplay_rescue"] is False


def test_recorded_history_code_delivery_does_not_claim_a_running_replacement_or_game_result():
    record = json.loads((EVIDENCE / ENDURANCE_RECORDS_CODE).read_bytes())
    assert record["source_revision"] == record["ci"]["head_sha"]
    assert record["ci"]["status"] == "completed" and record["ci"]["conclusion"] == "success"
    assert record["local_tests"] == {"passed": 4803, "skipped": 10}
    assert record["ci"]["passed"] == 4665 and record["ci"]["skipped"] == 148
    assert record["registered_endurance_windows"] == 0
    assert record["native_owner_changed"] is record["running_preview_changed"] is False
    assert record["new_gameplay_result_included"] is record["year_two_goal_complete"] is False
    assert record["public_deployment"] is record["main_merge"] is False


def test_actual_endurance_website_keeps_saved_and_live_results_separate():
    record = json.loads((EVIDENCE / ENDURANCE_RECORDS_WEBSITE).read_bytes())
    assert record["passed"] is True
    assert record["source_revision"] == record["website_revision"] == record["ci"]["head_sha"]
    assert record["ci"]["conclusion"] == "success" and record["ci"]["status"] == "completed"
    assert record["local_tests"] == {"passed": 4804, "skipped": 10}
    assert record["historical_and_decision_64_records_unchanged"] is True
    assert record["recorded_endurance_windows"] == 1
    assert record["recorded_endurance_boundaries"] == 64
    assert record["latest_saved_responses"] == 448
    assert record["latest_saved_tokens"] == 13479220
    live = record["live_observation"]
    assert live["campaign_id"] == "matched-20260910-sol-r1"
    assert live["responses"] == 27 and live["campaign_returned_responses"] == 91
    assert live["new_save_verified"] is False and live["source_checkpoint_verified"] is True
    assert live["reported_charge_usd"] is None
    assert record["admin_disabled"] is True
    assert (
        record["browser_visual_qa"] is record["public_deployment"] is record["main_merge"] is False
    )
    assert record["model_calls_by_verifier"] == record["game_ticks_by_verifier"] == 0
    assert record["year_two_goal_complete"] is False


def test_two_record_website_preserves_prior_history_and_provisional_terra_snapshot():
    record = json.loads((EVIDENCE / ENDURANCE_COHORT_WEBSITE).read_bytes())
    assert record["passed"] is True
    assert (
        record["source_revision"]
        == record["website_revision"]
        == record["ci"]["head_sha"]
        == "942011284488e8b700682549bf391e2b0f7e128c"
    )
    assert record["ci"]["conclusion"] == "success" and record["ci"]["status"] == "completed"
    assert record["local_tests"] == {"passed": 4805, "skipped": 10}
    assert record["ci"]["passed"] == 4667 and record["ci"]["skipped"] == 148
    assert record["historical_and_decision_64_records_unchanged"] is True
    assert record["previous_audited_endurance_windows_retained"] is True
    assert record["recorded_endurance_windows"] == 2
    assert record["recorded_endurance_boundaries"] == 128
    assert record["latest_saved_responses"] == 512
    assert record["latest_saved_tokens"] == 15508434
    live = record["live_observation"]
    assert live["campaign_id"] == "matched-20260910-terra-r1"
    assert live["responses"] == 53 and live["campaign_returned_responses"] == 117
    assert live["new_save_verified"] is False and live["source_checkpoint_verified"] is True
    assert live["reported_charge_usd"] is None
    assert record["admin_disabled"] is True
    assert (
        record["browser_visual_qa"] is record["public_deployment"] is record["main_merge"] is False
    )
    assert record["model_calls_by_verifier"] == record["game_ticks_by_verifier"] == 0
    assert record["year_two_goal_complete"] is False


def test_endurance_delivery_does_not_claim_more_gameplay():
    record = json.loads((EVIDENCE / ENDURANCE_DELIVERY).read_bytes())
    assert record["artifact_kind"] == "runtime_and_website_readiness"
    assert record["all_six_inputs_verified"] is True
    assert record["runtime_revision"] == record["runtime_ci"]["head_sha"]
    assert record["website_revision"] == record["website_ci"]["head_sha"]
    assert record["runtime_ci"]["conclusion"] == record["website_ci"]["conclusion"] == "success"
    assert record["recorded_continuation_windows"] == 6
    assert record["recorded_continuation_boundaries"] == 192
    assert record["campaign_accounted_responses"] == 384
    assert record["reported_model_charge_usd"] is None
    assert record["next_feed_status_at_prelaunch_http_acceptance"] == "not_connected"
    assert record["new_gameplay_result_included"] is record["year_two_goal_complete"] is False


def test_real_endurance_launch_is_provisional_not_a_final_save():
    record = json.loads((EVIDENCE / ENDURANCE_LAUNCH).read_bytes())
    live = record["observation"]
    assert record["artifact_kind"] == "active_continuation_observation"
    assert (live["start_decision"], live["end_decision"], live["response_limit"]) == (64, 128, 64)
    assert live["responses"] == 2 and live["unsettled_claims"] == 1
    assert live["campaign_returned_responses"] == 64 + live["responses"]
    assert live["campaign_returned_tokens"] == 2468751 + live["returned_tokens"]
    assert live["source_checkpoint_verified"] is True and live["new_save_verified"] is False
    assert record["first_response_review"]["total_tokens"] == 52304
    assert record["first_response_review"]["api_credentials_inherited"] is False
    assert record["final_native_audit_completed"] is record["vm_teardown_verified"] is False
    assert record["new_gameplay_result_included"] is record["year_two_goal_complete"] is False


def test_website_receipt_is_historical_http_proof_not_deployment_or_gameplay():
    record = json.loads((EVIDENCE / WEBSITE).read_bytes())
    assert record["passed"] is True
    assert record["recorded_trials"] == 6 and record["recorded_decision_boundaries"] == 192
    assert (
        record["website_revision"]
        == record["ci"]["head_sha"]
        == "19b1027ae680f6eee5dc277fd288f673dd436d45"
    )
    assert record["ci"]["conclusion"] == "success"
    assert record["local_tests"] == {"passed": 4586, "skipped": 10}
    assert record["prior_surfaces_unchanged"] is record["admin_disabled"] is True
    assert record["browser_visual_qa"] is record["public_deployment"] is False
    assert record["new_model_calls"] == record["new_game_ticks"] == 0
    live = record["live_observation"]
    assert live["campaign_id"] == "matched-20260910-sol-r1"
    assert live["saved_elapsed_ticks_before_window"] == 2500
    assert live["new_save_verified"] is False and live["source_checkpoint_verified"] is True


def test_sol_continuation_retains_its_own_save_and_unimproved_development():
    record = json.loads((EVIDENCE / SOL_RESULT).read_bytes())
    assert record["campaign_id"] == "matched-20260910-sol-r1"
    assert (
        record["prior_checkpoint_sha256"]
        == "c0451cad5686e59d86e2436a6534f75b419c99117a8cefb67651444d3b3bac5b"
    )
    assert (
        record["checkpoint_sha256"]
        == "abe16a8c5cdd9c3447c3f9443d8e79843552c60e715a0d8fbbecfa447f247020"
    )
    assert record["new_responses"] == 32 and record["next_decision"] == 64
    assert record["new_saved_ticks"] == 3000 and record["saved_elapsed_ticks"] == 5500
    assert record["usage"]["new_returned_tokens"] == 700489
    assert record["usage"]["campaign_returned_tokens"] == 1493253
    assert record["saved_metrics"]["population"] == 7
    for key in (
        "recorded_dead_citizens",
        "completed_workshops",
        "completed_farms",
        "completed_beds",
    ):
        assert record["saved_metrics"][key] == 0
    assert record["new_window_clock_outcomes"] == {"no_error": 32}
    assert record["new_window_timeline"][-1]["campaign_elapsed_ticks"] == 5500
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False


def test_terra_saved_outcome_preserves_unsupported_key_evidence():
    record = json.loads((EVIDENCE / TERRA_RESULT).read_bytes())
    assert record["campaign_id"] == "matched-20260910-terra-r1"
    assert record["new_responses"] == 32 and record["next_decision"] == 64
    assert record["new_saved_ticks"] == 6000 and record["saved_elapsed_ticks"] == 13000
    assert record["usage"]["new_returned_tokens"] == 678838
    assert record["usage"]["campaign_returned_tokens"] == 1537901
    assert (
        record["checkpoint_sha256"]
        == "86657110d8c1ba674f5a3da8ce2e058c9e691af31c924bbd97eedeaa9096ae89"
    )
    assert record["new_window_clock_outcomes"] == {"no_error": 31, "unsupported_native_keys": 1}
    assert record["new_window_timeline"][-1]["campaign_elapsed_ticks"] == 13000
    assert record["saved_metrics"]["population"] == 7
    assert record["saved_metrics"]["completed_workshops"] == 0
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True


def test_terra_second_continuation_keeps_its_independent_checkpoint():
    record = json.loads((EVIDENCE / TERRA_TWO_RESULT).read_bytes())
    assert record["campaign_id"] == "matched-20260910-terra-r2"
    assert (record["start_decision"], record["next_decision"]) == (32, 64)
    assert record["new_responses"] == 32
    assert record["new_saved_ticks"] == 10000 and record["saved_elapsed_ticks"] == 19000
    assert record["usage"]["new_returned_tokens"] == 1159955
    assert record["usage"]["campaign_returned_tokens"] == 2265470
    assert record["prior_checkpoint_sha256"] == (
        "41bd368d393813d9176c51f9dc8313ce9f9dfefe8516934ef6aaa8ffca868fd5"
    )
    assert record["checkpoint_sha256"] == (
        "4b291937cc0a70a063d8a1987baafe99a3a48014ac5df7dbc4dd7c41f4fac837"
    )
    assert record["saved_metrics"]["population"] == 7
    assert record["saved_metrics"]["completed_workshops"] == 0
    assert record["new_window_clock_outcomes"] == {"no_error": 30, "timeout_waiting_for_ticks": 2}
    assert record["new_window_timeline"][-1]["campaign_elapsed_ticks"] == 19000
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False


def test_sol_second_continuation_does_not_borrow_the_first_attempt():
    record = json.loads((EVIDENCE / SOL_TWO_RESULT).read_bytes())
    assert record["campaign_id"] == "matched-20260910-sol-r2"
    assert (record["start_decision"], record["next_decision"], record["new_responses"]) == (
        32,
        64,
        32,
    )
    assert record["new_saved_ticks"] == 7500 and record["saved_elapsed_ticks"] == 12700
    assert record["usage"]["new_returned_tokens"] == 807647
    assert record["usage"]["campaign_returned_tokens"] == 1661362
    assert record["prior_checkpoint_sha256"] == (
        "7995463aa877ed87ec4cefdbce9bd7530bd395376e81f1ec0377b6b4c18391e0"
    )
    assert record["checkpoint_sha256"] == (
        "8951a2fb2ede2b71e5f6831c9c1088eb02163ca6b719696d6c1365447e37777b"
    )
    assert record["saved_metrics"]["population"] == 7
    assert record["saved_metrics"]["completed_workshops"] == 0
    assert record["new_window_clock_outcomes"] == {"no_error": 31, "timeout_waiting_for_ticks": 1}
    assert record["new_window_timeline"][-1]["campaign_elapsed_ticks"] == 12700
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False


def test_saved_website_receipt_keeps_initial_and_continued_results_distinct():
    record = json.loads((EVIDENCE / SAVED_WEBSITE).read_bytes())
    assert record["passed"] is True
    assert record["website_revision"] == "c6f9c42aecdb05b09e7e698c68d893332cefd4e3"
    assert (
        record["recorded_initial_trials"] == 6
        and record["recorded_initial_decision_boundaries"] == 192
    )
    assert (
        record["recorded_continuation_windows"] == 3
        and record["recorded_continuation_boundaries"] == 96
    )
    assert record["saved_continuation_data_matches_reviewed_source"] is True
    assert record["prior_surfaces_unchanged"] is True
    assert record["local_tests"] == {"passed": 4630, "skipped": 10}
    assert record["live_observation"]["campaign_id"] == "matched-20260910-terra-r2"
    assert record["live_observation"]["new_save_verified"] is False
    assert record["public_deployment"] is record["browser_visual_qa"] is False


def test_endurance_preparation_is_remote_tested_configuration_not_gameplay():
    record = json.loads((EVIDENCE / ENDURANCE).read_bytes())
    assert record["passed"] is True
    assert (
        record["source_revision"]
        == record["ci"]["headSha"]
        == ("74d75bb6410384de8cc72809d535eb7bc10a398d")
    )
    assert record["ci"]["status"] == "completed" and record["ci"]["conclusion"] == "success"
    assert record["local_tests"] == {"passed": 4694, "skipped": 10}
    assert record["focused_tests"] == 89
    assert record["comparison_decision_boundaries"] == [32, 64, 128, 256, 512, 1024, 1280]
    assert record["new_model_calls_by_preparation"] == record["new_game_ticks_by_preparation"] == 0
    assert all(
        record[key] is False
        for key in (
            "all_six_inputs_ready",
            "private_input_validation_included",
            "native_reload_executed",
            "launch_admitted",
            "public_deployment",
            "main_merge",
            "goal_complete",
        )
    )
    windows = record["prepared_windows"]
    assert len(windows) == 4 and len({w["checkpoint_sha256"] for w in windows}) == 4
    for window in windows:
        assert (window["from_decision"], window["to_decision"]) == (64, 128)
        assert window["comparison_target_decision"] == 128
        assert window["steps_per_segment"] == 64 and window["max_segments"] == 1
        assert len(window["source_result_chain_sha256"]) == 2


def test_astra_second_continuation_retains_development_and_actual_recording_date():
    record = json.loads((EVIDENCE / ASTRA_TWO_RESULT).read_bytes())
    assert record["campaign_id"] == "matched-20260910-astra-r2"
    assert record["recorded_date_utc"] == "2026-09-11"
    assert record["new_responses"] == 32 and record["next_decision"] == 64
    assert record["new_saved_ticks"] == 10500 and record["saved_elapsed_ticks"] == 19500
    assert record["usage"]["new_returned_tokens"] == 988433
    assert record["usage"]["campaign_returned_tokens"] == 1976997
    assert record["prior_checkpoint_sha256"] == (
        "66582a3d8fa05b8e8379456054fcc56786ef4a88214500aedfe9e8f4cea43679"
    )
    assert record["checkpoint_sha256"] == (
        "a969fa5389bf450583172f086b6eb122d78039436f6427965abbfe5e6f34a3b1"
    )
    metrics = record["saved_metrics"]
    assert metrics["population"] == 7 and metrics["recorded_dead_citizens"] == 0
    assert metrics["completed_beds"] == 3 and metrics["completed_workshops"] == 2
    assert metrics["completed_farms"] == 1 and metrics["functional_rooms"] is None
    assert record["new_window_clock_outcomes"] == {
        "blocking_native_menu": 2,
        "no_error": 29,
        "timeout_waiting_for_ticks": 1,
    }
    assert record["source_checkpoint_fresh_load_verified"] is True
    assert record["final_fresh_reload_verified"] is record["sustainability_established"] is False
    assert record["native_cleanup_verified"] is record["vm_teardown_verified"] is True


def test_complete_six_64_decision_records_reconcile_without_a_ranking_claim():
    names = (RESULT, SOL_RESULT, TERRA_RESULT, TERRA_TWO_RESULT, SOL_TWO_RESULT, ASTRA_TWO_RESULT)
    records = [json.loads((EVIDENCE / name).read_bytes()) for name in names]
    assert len({r["campaign_id"] for r in records}) == 6
    assert all(r["next_decision"] == 64 for r in records)
    assert sum(r["usage"]["campaign_accounted_responses"] for r in records) == 384
    assert sum(r["usage"]["campaign_returned_tokens"] for r in records) == 11403734
    assert all(r["usage"]["reported_charge_usd"] is None for r in records)
    assert all(
        r["matched_comparison_complete"] is r["sustainability_established"] is False
        for r in records
    )
