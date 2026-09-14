"""Infrastructure acceptance must not advance the campaign or rewrite its failure."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_status_stack_acceptance_is_separate_from_campaign_progress():
    folder = ROOT / "experiments/evidence"
    value = json.loads((folder / "native_status_stack_acceptance_20260908.json").read_text())
    failure = json.loads((folder / (value["parent_failure_record"] + ".json")).read_text())
    assert value["schema_version"] == "fortgym.native-status-stack-acceptance-summary/v1"
    assert value["status"] == "native_save_reload_verified"
    assert value["independent_audit_passed"] is True
    assert len(value["independent_audit_sha256"]) == 64
    assert value["source_revision"] == "d795ed6e2889fc9cc61bb38b6d23b7a0feed27ff"
    assert value["reproduction"]["screen_focus"] == "dfhack/lua/status_overlay"
    assert value["reproduction"]["legacy_rejected_before_save"] is True
    assert failure["failure"]["underlying_stack_cause"] == "unverified"  # immutable original
    acceptance = value["acceptance"]
    assert acceptance["save_verified"] is acceptance["fresh_reload_verified"] is True
    assert acceptance["full_stack_identity_unchanged"] is acceptance["teardown_verified"] is True
    assert acceptance["gameplay_ticks"] == acceptance["model_calls"] == 0
    assert acceptance["native_save_calls"] == 1
    assert acceptance["private_food_measurement"] is False
    campaign = value["campaign"]
    assert campaign["new_checkpoint_created"] is campaign["new_restart_performed"] is False
    assert campaign["last_verified_checkpoint_cursor"] == failure["last_verified_checkpoint_cursor"]
    assert campaign["retained_elapsed_ticks"] == failure["progress"]["checkpointed_elapsed_ticks"]
    assert campaign["accounted_model_responses"] == failure["progress"]["accounted_model_responses"]
    assert campaign["campaign_tokens"] == failure["usage"]["campaign_tokens"]
    assert campaign["all_attempt_tokens"] == failure["usage"]["all_attempt_tokens"]
    assert campaign["unsaved_window_o_ticks"] == failure["progress"]["unsaved_new_native_ticks"]
    assert campaign["year_two_reached"] is False
    assert value["cost"]["metered_inference_charge_usd"] == "0"
    assert value["cost"]["other_cost_usd"] is None
