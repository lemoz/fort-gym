"""Read-only, exact-evidence export of the first displayed-key model trial."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "fort_gym/artifacts/native-local-20260906/runtime-v2"
ATTEMPT = RUNTIME / "keyboard-matched-pilot-v1/keyboard-bindings-astra-r1-v1/attempt"
AUDIT_SHA = "a3c4614ea4a650b2311ac150eb712e1b393b38efc8d4eeba6e8daf2b7db871ba"
WORKTREE = ROOT / "fort_gym/artifacts/worktrees/campaign-keyboard-bindings"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    audit_path = ATTEMPT / "terminal-review.json"
    assert sha(audit_path) == AUDIT_SHA, "Terminal audit changed"
    audit = read(audit_path)
    assert audit["passed"] and audit["responses"] == 32
    for relative, expected in audit["sources"].items():
        path = (RUNTIME / relative).resolve()
        assert path.is_relative_to(RUNTIME.resolve())
        assert sha(path) == expected, f"Evidence changed: {relative}"
    sys.path.insert(0, str(WORKTREE))
    from fort_gym.bench.eval.campaign_profile import metrics_from_state
    from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint

    segment = ATTEMPT / "evidence/astra/segment-0"
    checkpoint = verify_checkpoint(segment / "checkpoint")
    assert checkpoint["sha256"] == audit["checkpoint_sha256"]
    rows = [json.loads(line) for line in (segment / "loop/trace.jsonl").read_text().splitlines()]
    timeline, cumulative = [], 0
    for index, (row, receipt) in enumerate(zip(rows, audit["receipt_reviews"], strict=True)):
        assert row["step"] == receipt["decision_index"] == index
        assert row["run_id"] == audit["campaign_id"]
        action, execute, clock = row["action"], row["execute"], row["tick_advance"]
        cumulative += clock["ticks_advanced"]
        timeline.append({
            "decision": index + 1,
            "keys": action["params"]["keys"],
            "model_intent": action["intent"],
            "input_accepted": execute["accepted"],
            "confirmed_key_presses": execute["result"]["keys_confirmed"],
            "requested_ticks": action["advance_ticks"],
            "ticks_advanced": clock["ticks_advanced"],
            "saved_elapsed_ticks": cumulative,
            "clock_error": clock.get("error"),
            "metrics": metrics_from_state(row["state_after_advance"]),
            "returned_tokens": receipt["total_tokens"],
        })
    assert cumulative == audit["saved_elapsed_ticks"] == 15500
    assert sum(row["returned_tokens"] for row in timeline) == audit["new_tokens"]
    assert sum(row["confirmed_key_presses"] for row in timeline) == audit["confirmed_key_presses"]
    assert timeline[-1]["metrics"] == audit["saved_metrics"]
    launch = read(ROOT / "experiments/evidence/keyboard_binding_trial_launch_20260911.json")
    assert launch["source_revision"] == audit["source_revision"]
    for name, expected in launch["config_sha256"].items():
        assert sha(WORKTREE / "experiments/keyboard_bindings_20260911" / name) == expected
    after = read(segment / "native-after.json")
    return {
        "schema_version": "fortgym.public-keyboard-binding-trial-result/v1",
        "campaign_id": audit["campaign_id"],
        "status": "bounded_trial_complete",
        "stop_reason": audit["stop_reason"],
        "source_revision": audit["source_revision"],
        "image_id": audit["image_id"],
        "implementation_pull_request": launch["implementation_pull_request"],
        "condition": {key: launch[key] for key in (
            "model", "reasoning_effort", "transport", "auth_mode", "control_profile",
            "prompt_profile", "condition_path", "trial_path", "config_sha256",
            "source_snapshot_receipt_sha256", "starting_boundary",
            "fresh_empty_memory_usage_history", "independent_campaign",
            "shares_original_matched_pilot_snapshot", "borrowed_old_campaign_memory",
            "operator_edited_diagnostic_copy_used", "same_condition_as_historical_matched_cohort",
            "maximum_responses")},
        "responses": audit["responses"],
        "confirmed_key_presses": audit["confirmed_key_presses"],
        "saved_elapsed_ticks": audit["saved_elapsed_ticks"],
        "ticks_per_year": 403200,
        "final_boundary": {"year": after["year"], "year_tick": after["year_tick"], "paused": after["pause_state"]},
        "initial_metrics": audit["initial_metrics"],
        "saved_metrics": audit["saved_metrics"],
        "usage": audit["usage"],
        "clock_outcomes": audit["clock_outcomes"],
        "activity": {key: value for key, value in audit["observed_activity"].items() if key != "timeline"},
        "food_measurement": {
            "complete_samples": audit["food_complete_samples"],
            "samples": audit["food_samples"],
            "final_inventory": audit["saved_food"]["inventory"],
            "model_observation": "native_screen_text/v1; private evaluator inventory is not supplied to the model",
        },
        "checkpoint_sha256": audit["checkpoint_sha256"],
        "audit": {
            "passed": True, "sha256": AUDIT_SHA, "source_sha256": audit["audit_source_sha256"],
            "provider_receipts_verified": len(audit["receipt_reviews"]),
            "provider_receipts": audit["receipt_reviews"],
            "native_cleanup_verified": audit["native_cleanup_verified"],
            "vm_teardown_verified": audit["vm_teardown_verified"],
            "shutdown": audit["shutdown"],
            "trace_sha256": sha(segment / "loop/trace.jsonl"),
            "usage_sha256": sha(segment / "loop/usage.jsonl"),
        },
        "proof_limits": {
            "fresh_final_checkpoint_reload_verified": False,
            "repeated_new_condition_trials_complete": False,
            "human_gameplay_rescue": False, "sustainability_proven": False,
            "year_two_reached": False, "strong_model_ranking_supported": False,
            "completed_production_measured": False, "completed_consumption_measured": False,
            "public_website_deployed": False, "main_merged": False,
        },
        "cost_limits": {
            "actual_model_charge_usd": None, "hardware_energy_and_app_cost_usd": None,
            "api_fallback": False, "local_model_fallback": False,
            "automatic_credit_purchase": False, "automatic_reset_consumption": False,
            "cloud_vms_created": 0,
        },
        "interpretation": [
            "Displayed keys supported autonomous menu navigation and completed construction in this single short pilot.",
            "All 32 input batches were accepted; decision 8 could not advance time inside a blocking menu. Decision 9 exited and advanced 2000 ticks.",
            "Model intentions, queued jobs and current-job samples are not completed production or successful adaptation measurements.",
            "Zero completed beds means zero placed and completed bed buildings, not zero bed items or queued jobs.",
            "Food uses the native raw-edibility predicate with argument 0, not the screen's food estimate; accessibility and production are not measured.",
            "Stock changes and a short interval with no recorded deaths do not establish sustainability.",
            "This distinct control condition must not be added to historical matched-cohort totals or treated as a causal model comparison.",
        ],
        "timeline": timeline,
        "next_experiment": "Verify a fresh reload of this save, then continue the same condition from decision 32 before widening to repeated three-model trials.",
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=True))
