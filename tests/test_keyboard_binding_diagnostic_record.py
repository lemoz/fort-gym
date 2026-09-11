"""Published evidence integrity, separate from the native execution itself."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "experiments/evidence/keyboard_binding_native_diagnostic_20260911.json"


def read():
    return json.loads(RESULT.read_bytes())


def test_published_sources_are_exact_and_no_private_world_is_embedded():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "38167d9bbb79e0bb7a141ed7fad71bc3ed30c9d0a581d7c5404c8fde4d8bfb81"
    )
    for token in (b"/Users/", b'"screen":', b'"memory":', b'"account_id":', b'"owner_pid":'):
        assert token not in raw
    result = read()
    assert len(result["diagnostic_sources"]) == 4
    for relative, expected in result["diagnostic_sources"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    assert result["experiment_source_revision"].startswith("a095d13dc")


def test_control_comparison_reports_real_job_changes_not_only_input_acceptance():
    result = read()
    custom, bed, barrel, select, enter = result["arms"]
    assert [row["arm"] for row in result["arms"]] == [
        "custom_b",
        "binding_b",
        "binding_v",
        "native_select",
        "binding_enter",
    ]
    assert custom["new_jobs"] == []
    assert [job["type"] for job in bed["new_jobs"]] == ["ConstructBed"]
    assert [job["type"] for job in barrel["new_jobs"]] == ["MakeBarrel"]
    assert select["new_jobs"] == enter["new_jobs"]
    assert [job["type"] for job in enter["new_jobs"]] == ["MakeShield"]
    assert [len(row["native_events"]) for row in result["arms"]] == [1, 41, 28, 1, 8]
    assert all(row["native_input_calls"] == 1 for row in result["arms"])
    assert {"CUSTOM_B", "STRING_A098", "HOTKEY_CARPENTER_BED"} <= set(bed["native_events"])
    assert "HOTKEY_CARPENTER_BARREL" in barrel["native_events"]
    assert "SELECT" in enter["native_events"]
    assert all(row["existing_jobs"] == custom["existing_jobs"] for row in result["arms"])
    assert custom["before_focus"] == custom["after_focus"]
    assert all(row["after_focus"].endswith("/Workshop/Job") for row in result["arms"][1:])


def test_experimental_pass_does_not_rewrite_previous_failure_or_scored_conditions():
    result = read()
    prior = result["prior_diagnostic"]
    raw = (ROOT / prior["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == prior["sha256"]
    assert json.loads(raw)["original_full_frame_acceptance_passed"] is False
    assert prior["original_full_frame_acceptance_passed"] is False
    assert result["predeclared_native_acceptance_passed"] is True
    assert result["original_owner_status"] == "passed"
    assert result["original_container_exit_code"] == 0
    assert result["menu_comparison_scope"]["basis"].startswith("predeclared_")
    assert result["campaign_control_profiles_changed"] is False
    assert result["model_comparison_conditions_changed"] is False
    assert result["physical_keyboard_equivalence_verified"] is False
    assert result["gameplay_improvement_verified"] is False


def test_native_copies_and_teardown_are_not_scored_campaign_progress():
    result = read()
    source = json.loads((ROOT / result["source_result_path"]).read_bytes())
    assert result["checkpoint_sha256"] == source["checkpoint_sha256"]
    assert result["source_revision"] == source["execution"]["source_revision"]
    assert result["image_id"] == source["execution"]["image_id"]
    assert result["source_checkpoint_unchanged"] is True
    assert result["native_cleanup_verified"] is result["vm_teardown_verified"] is True
    assert result["operator_ui_setup"] is True
    assert result["autonomous_gameplay"] is result["new_scored_campaign_checkpoint"] is False
    assert result["model_calls"] == result["native_saves_requested"] == 0
    assert result["observed_elapsed_ticks"] == result["cloud_vms_created"] == 0
    assert result["hardware_energy_and_app_cost_usd"] is None
    assert result["binding_events_validated"] == 1579
    assert result["bindings_sha256"] == (
        "8176d2bd7a8d96f6bb12feb654519a8361a6f262363b84ec48963be832cb7efd"
    )
    assert all(row["source_calendar"] == [30, 152201] for row in result["arms"])
    assert all(row["menu_sidebar_tiles_equal"] for row in result["arms"])
