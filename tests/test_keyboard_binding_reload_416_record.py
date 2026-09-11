"""Validate the public reload record; native acceptance is its separately retained audit."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "experiments/evidence/keyboard_binding_astra_r1_reload_416_20260911.json"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reload_links_unchanged_year_two_result_and_usage():
    record = read(RECORD)
    previous_path = ROOT / record["prior_trial_result_path"]
    previous = read(previous_path)
    assert sha(previous_path) == record["prior_trial_result_sha256"]
    assert record["checkpoint_sha256"] == previous["checkpoint"]["sha256"]
    assert record["source_revision"] == previous["source_revision"]
    assert record["next_step"] == previous["next_step"] == 416
    assert record["committed_elapsed_ticks"] == previous["saved_elapsed_ticks"] == 429845
    assert record["restored_metrics"] == previous["saved_metrics"]
    assert record["restored_usage"] == previous["cumulative_usage"]
    assert record["restored_usage"]["accounted_responses"] == 448
    assert record["restored_usage"]["total_tokens"] == 11866456
    assert previous["checkpoint"]["final_fresh_reload_verified"] is False
    assert record["native_load_verified"] is record["normal_loop_restore_verified"] is True


def test_reload_binds_public_predeclared_sources():
    record = read(RECORD)
    assert sha(ROOT / record["fixture_path"]) == record["fixture_sha256"]
    audit = record["audit"]
    assert sha(ROOT / audit["review_source_path"]) == audit["review_source_sha256"]
    assert sha(ROOT / "experiments/keyboard_binding_reload_20260911/review_log_delta.py") == audit["log_classifier_sha256"]
    assert audit["predeclared_exact_load_log_review"] is True
    assert audit["post_hoc_acceptance_relaxation"] is False


def test_reload_preserves_file_and_menu_proof_limits():
    record = read(RECORD)
    delta = record["copied_save_delta"]
    assert record["source_save_files_verified"] == 127
    assert delta["non_log_files_byte_identical"] == 126
    assert delta["source_prefix_unchanged"] is True
    assert delta["whole_copied_save_tree_byte_identical"] is False
    assert delta["appended_bytes"] == 304
    assert delta["appended_events"] == ["SC_WORLD_LOADED", "SC_MAP_LOADED"]
    assert record["menu"]["loaded_focus"] == "dwarfmode/Default"
    assert record["menu"]["focus_equal"] is False
    assert record["menu"]["manual_restoration"] is False
    assert record["menu"]["full_menu_equivalence_claimed"] is False


def test_reload_is_not_new_gameplay_or_a_new_model_trial():
    record = read(RECORD)
    for key in ("new_model_calls", "new_gameplay_actions", "new_gameplay_ticks",
                "new_native_saves", "cloud_vms_created"):
        assert type(record[key]) is int and record[key] == 0
    assert record["proof_limits"]["additional_autonomous_play"] is False
    assert record["proof_limits"]["full_goal_complete"] is False
    assert record["proof_limits"]["public_website_deployed"] is False
    assert record["lifecycle"]["vm_live_observed_stopped"] is True
    assert record["resources"]["future_runs_require_fresh_capacity_check"] is True
