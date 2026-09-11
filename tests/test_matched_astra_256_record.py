"""Public record integrity; the independent native audit supplies runtime proof."""

import hashlib
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "experiments/evidence"
RESULT = "keyboard_matched_astra_r1_continuation_128_256_20260911.json"


def read(name):
    return json.loads((EVIDENCE / name).read_bytes())


def test_exact_record_excludes_private_inputs_and_preserves_source_binding():
    raw = (EVIDENCE / RESULT).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "a61dd8db4bb61b4bf5639e94ec58647423a27e1a73f9e08397af157db51e685e"
    )
    for forbidden in (b"/Users/", b'"/evidence/', b'"memory":', b'"screen":', b'"account_id":'):
        assert forbidden not in raw
    value = json.loads(raw)
    assert value["schema_version"] == "fortgym.public-matched-keyboard-continuation/v1"
    assert value["execution"]["source_revision"] == "1bc49b9675b1c82ad502bbd6d8461c9cdbf077e9"
    assert value["execution"]["declaration_revision"] == "4590fc1828365c44c9a4d3be728b4168ded5c514"
    assert (
        value["execution"]["window_sha256"]
        == "9fa3b4160f5df536a9f65cb33b00d9dcb4e28660acab8b789729434a6621a61a"
    )
    assert (
        value["checkpoint_sha256"]
        == "3225df254ea574ba8d477b6f166112a8defd4ae383a68cade433eac37e078342"
    )
    assert (
        value["audit_sha256"] == "03ff01cbc906d2f286d874981c8fe1c387c5b9580091ad0a09b1b19ea8aa23ee"
    )


def test_own_parent_midpoint_and_cumulative_results_reconcile():
    value = read(RESULT)
    parent_name = "keyboard_matched_astra_r1_continuation_64_128_20260911.json"
    parent = read(parent_name)
    midpoint = read("keyboard_matched_astra_r1_midpoint_192_20260911.json")
    assert value["campaign_id"] == parent["campaign_id"] == midpoint["campaign_id"]
    assert value["prior_checkpoint_sha256"] == parent["checkpoint_sha256"]
    assert (
        value["source_result_sha256"]
        == hashlib.sha256((EVIDENCE / parent_name).read_bytes()).hexdigest()
    )
    assert value["initial_metrics"] == parent["saved_metrics"]
    assert (value["start_decision"], value["next_decision"], value["new_responses"]) == (
        128,
        256,
        128,
    )
    assert value["saved_elapsed_ticks"] == parent["saved_elapsed_ticks"] + 84000 == 135400
    assert value["new_saved_ticks"] == 84000
    usage = value["usage"]
    assert usage["new_returned_tokens"] == 5874925
    assert (
        usage["campaign_returned_tokens"]
        == parent["usage"]["campaign_returned_tokens"] + 5874925
        == 10419162
    )
    assert usage["campaign_accounted_responses"] == 256
    assert usage["reported_charge_usd"] is None
    timeline = value["new_window_timeline"]
    assert [p["decision"] for p in timeline] == list(range(129, 257))
    assert timeline[63]["campaign_elapsed_ticks"] == midpoint["saved_elapsed_ticks"] == 89400
    assert timeline[63]["metrics"] == midpoint["saved_metrics"]
    assert all(p["campaign_elapsed_ticks"] == 51400 + p["new_elapsed_ticks"] for p in timeline)
    assert timeline[-1]["campaign_elapsed_ticks"] == value["saved_elapsed_ticks"]
    assert timeline[-1]["metrics"] == value["saved_metrics"]


def test_development_and_failures_do_not_become_sustainability_or_ranking():
    value = read(RESULT)
    metrics = value["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (
        metrics["completed_beds"],
        metrics["completed_farms"],
        metrics["completed_workshops"],
    ) == (8, 2, 3)
    assert (metrics["food_stock"], metrics["drink_stock"]) == (34, 199)
    assert metrics["functional_rooms"] is metrics["wood_stock"] is metrics["stone_stock"] is None
    assert value["new_window_clock_outcomes"] == {
        "blocking_native_menu": 3,
        "no_error": 123,
        "timeout_waiting_for_ticks": 2,
    }
    assert value["status"] == "completed" and value["stop_reason"] == "segment_limit"
    for key in (
        "checkpoint_verified",
        "source_checkpoint_fresh_load_verified",
        "memory_preserved_at_start",
        "native_cleanup_verified",
        "vm_teardown_verified",
    ):
        assert value[key] is True
    for key in (
        "final_fresh_reload_verified",
        "year_two_reached",
        "sustainability_established",
        "human_gameplay_rescue",
        "prompt_change",
        "budget_extension",
        "matched_comparison_complete",
    ):
        assert value[key] is False
    assert value["new_native_save_losses"] == 0
    assert value["production_rates"] is value["consumption_rates"] is None
    assert (
        value["shutdown"]["guest_poweroff_returncode"]
        == value["shutdown"]["vm_stop_returncode"]
        == 0
    )
    assert (
        value["food"]["complete_after_action_samples"]
        == value["food"]["after_action_samples"]
        == 128
    )
    assert value["new_window_activity"]["observed_boundaries"] == 128
    assert value["resources"]["oom_kills"] == 0


def test_website_receipt_binds_pushed_source_and_preserves_the_older_page_assets():
    filename = "keyboard_matched_astra_256_website_20260911.json"
    raw = (EVIDENCE / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "49ec045b626f164f927ca517bc3a1fe60609d28bd415e5ffbac018d3e6eacdc8"
    )
    for private in (b"/Users/", b'"memory":', b'"screen":', b'"account_id":', b'"owner_pid":'):
        assert private not in raw
    value = json.loads(raw)
    previous = read("keyboard_matched_live_v2_website_20260911.json")
    assert value["passed"] is True
    assert value["website_revision"] == value["ci"]["head_sha"] == (
        "ff350f024957af964bca3d50e1166cbffd139d8e"
    )
    assert value["ci"]["status"] == "completed" and value["ci"]["conclusion"] == "success"
    assert value["pull_request"] == "https://github.com/lemoz/fort-gym/pull/158"
    assert value["local_tests"] == {"passed": 4963, "skipped": 10}
    assert value["routes"] == previous["routes"]
    assert value["prior_preview_revision"] == previous["website_revision"]
    assert value["historical_surfaces_and_six_128_windows_unchanged"] is True
    assert value["existing_html_and_javascript_unchanged"] is True
    assert value["recorded_endurance_windows"] == 7
    assert value["recorded_endurance_boundaries"] == 512
    assert value["latest_saved_responses"] == 896
    assert value["latest_saved_tokens"] == 28581994
    for key in ("main_merge", "public_deployment", "browser_visual_qa", "year_two_goal_complete"):
        assert value[key] is False
    assert value["model_calls_by_verifier"] == value["game_ticks_by_verifier"] == 0


def test_website_links_saved_result_without_promoting_the_stale_observer():
    delivery = read("keyboard_matched_astra_256_website_20260911.json")
    observed = delivery["live_observation"]
    saved = read(RESULT)
    assert delivery["new_result_sha256"] == hashlib.sha256((EVIDENCE / RESULT).read_bytes()).hexdigest()
    assert observed["status"] == "stale"
    assert observed["campaign_id"] == saved["campaign_id"]
    assert observed["prior_checkpoint_sha256"] == saved["prior_checkpoint_sha256"]
    assert observed["start_decision"] == 128
    assert observed["saved_elapsed_ticks_before_window"] == 51400
    assert observed["returned_tokens_before_window"] == 4544237
    assert observed["responses"] == saved["new_responses"] == 128
    assert observed["campaign_returned_tokens"] == saved["usage"]["campaign_returned_tokens"]
    assert observed["campaign_elapsed_ticks_lower_bound"] == 133400
    assert saved["saved_elapsed_ticks"] == observed["campaign_elapsed_ticks_lower_bound"] + 2000
    assert observed["new_save_verified"] is False
    assert observed["source_checkpoint_verified"] is True
    assert observed["reported_charge_usd"] is None
    assert observed["audited_result_url"] == (
        "https://github.com/lemoz/fort-gym/blob/4bb97d6c4fe3b5a1f8acc7d416c46817bcff5100/"
        "experiments/evidence/" + RESULT
    )
