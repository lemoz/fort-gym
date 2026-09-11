"""Fresh reload proof must not rewrite the original gameplay result or add progress."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / "experiments/evidence" / name).read_text())


def test_reload_retains_original_campaign_and_cumulative_outcomes():
    result = read("keyboard_binding_astra_r1_reload_20260911.json")
    prior = read("keyboard_binding_astra_r1_20260911.json")
    assert result["campaign_id"] == prior["campaign_id"]
    assert result["checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert result["source_revision"] == prior["source_revision"]
    assert result["next_step"] == prior["responses"] == 32
    assert result["committed_elapsed_ticks"] == prior["saved_elapsed_ticks"] == 15500
    assert result["restored_usage"] == prior["usage"]
    assert result["restored_metrics"] == prior["saved_metrics"]
    assert result["native_load_verified"] is result["normal_loop_restore_verified"] is True
    assert prior["proof_limits"]["fresh_final_checkpoint_reload_verified"] is False
    assert result["restored_agent_memory_configuration_prompt_and_history_unchanged"]
    assert result["latest_original_usage_journal_used"]


def test_log_exception_is_scoped_and_original_strict_failure_remains_visible():
    result = read("keyboard_binding_astra_r1_reload_20260911.json")
    assert result["original_checkpoint_unchanged"] and result["source_save_files_verified"] == 127
    delta = result["copied_save_delta"]
    assert delta["non_log_files_byte_identical"] == 126
    assert delta["appended_bytes"] == 304
    assert delta["source_prefix_unchanged"] is True
    assert delta["whole_copied_save_tree_byte_identical"] is False
    assert delta["appended_events"] == ["SC_WORLD_LOADED", "SC_MAP_LOADED"]
    assert result["audit"]["passed"] is True
    assert result["audit"]["original_strict_review_passed"] is False
    assert result["audit"]["post_hoc_scoped_review"] is True


def test_menu_reset_cleanup_and_zero_new_progress_are_explicit():
    result = read("keyboard_binding_astra_r1_reload_20260911.json")
    assert result["menu"]["saved_focus"] == "dwarfmode/Build/Type"
    assert result["menu"]["loaded_focus"] == "dwarfmode/Default"
    assert result["menu"]["focus_equal"] is result["menu"]["manual_restoration"] is False
    assert result["menu"]["full_menu_equivalence_claimed"] is False
    for key in (
        "new_model_calls",
        "new_gameplay_actions",
        "new_gameplay_ticks",
        "new_native_saves",
        "cloud_vms_created",
    ):
        assert result[key] == 0
    assert not any(result["proof_limits"].values())
    lifecycle = result["lifecycle"]
    assert lifecycle["native_cleanup_verified"] is lifecycle["vm_teardown_verified"] is True
    assert lifecycle["vm_live_observed_stopped"]
    assert lifecycle["vm_stop_returncode"] == lifecycle["guest_poweroff_returncode"] == 0


def test_later_website_ci_does_not_claim_native_or_public_acceptance():
    value = read("keyboard_binding_website_ci_20260911.json")
    assert value["source_revision"] == "c5288317b4b689e4a70ccaf979fe753aa4bb102c"
    assert value["status"] == "completed" and value["conclusion"] == "success"
    assert value["native_gameplay_proof"] is value["browser_visual_qa"] is False
    assert value["main_merged"] is value["public_website_deployed"] is False
