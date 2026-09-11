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
