"""Integrity of versioned projections; native proof comes from their audits."""

import hashlib
import json
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / "experiments/evidence"
RESULT = "keyboard_matched_astra_r1_continuation_32_64_20260910.json"
SOL_RESULT = "keyboard_matched_sol_r1_continuation_32_64_20260910.json"
SOL_TWO_RESULT = "keyboard_matched_sol_r2_continuation_32_64_20260910.json"
TERRA_RESULT = "keyboard_matched_terra_r1_continuation_32_64_20260910.json"
TERRA_TWO_RESULT = "keyboard_matched_terra_r2_continuation_32_64_20260910.json"
WEBSITE = "keyboard_matched_continuation_website_20260910.json"
SAVED_WEBSITE = "keyboard_matched_saved_windows_website_20260910.json"


@pytest.mark.parametrize(
    "filename,expected",
    [
        (RESULT, "2c8abe1f7135d94ed27aea51e18ebc59e0599205caf3f268f4480b0e377f3d29"),
        (SOL_RESULT, "a624a9687257157aa91029d950ca1735a0e8f1baaa224cb66bba7efac50a1dbd"),
        (SOL_TWO_RESULT, "2f261d841808126b4f26cb55dcd47faae36ed37a7310c71648fae0fc531f26da"),
        (TERRA_RESULT, "e81a20836eb6959a529b657a72339bca2e299203c73188006fb32d682c734e11"),
        (TERRA_TWO_RESULT, "1966bf1e8229e8fbfd7a161d84c78da272dd3f5c9aa86040f59a8baa415ef1b8"),
        (WEBSITE, "c5cb272a0b62646fa6c495d5157b68a51a758544fc9c538bd715bf08dbf3f8c9"),
        (SAVED_WEBSITE, "a2d9a1ef556697a734c425a6c9c8571069d409719bd9d86ef16477926d79b57f"),
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
