"""Export audited single- or multi-segment continuations without private model memory."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "fort_gym/artifacts/native-local-20260906/runtime-v2"
WORKTREE = ROOT / "fort_gym/artifacts/worktrees/campaign-keyboard-bindings"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_condition(condition, prior):
    """Resolve the first trial's summary through its pinned condition file."""
    if prior["schema_version"] == "fortgym.public-keyboard-binding-continuation-result/v1":
        assert condition == prior["condition"]
        return
    assert prior["schema_version"] == "fortgym.public-keyboard-binding-trial-result/v1"
    summary = prior["condition"]
    assert (
        summary["condition_path"] == "experiments/keyboard_bindings_20260911/astra-condition.json"
    )
    path = (WORKTREE / summary["condition_path"]).resolve()
    assert path.is_relative_to(WORKTREE.resolve())
    assert sha(path) == summary["config_sha256"][path.name]
    assert read(path) == condition
    for key in ("model", "reasoning_effort", "transport", "control_profile", "prompt_profile"):
        assert summary[key] == condition[key]
    assert summary["starting_boundary"]["screen_size"] == condition["screen_size"]


def checkpoint_chain(native, audit, prior, condition, window):
    """Re-audit each actual saved segment and expose only public checkpoint fields."""
    if audit["schema_version"] == "fortgym.private-binding-continuation-terminal-review/v1":
        assert window["max_segments"] == 1
        return None
    from fort_gym.bench.eval.campaign_profile import metrics_from_state
    from fort_gym.bench.run.keyboard_window_checkpoint_audit import verify_window_checkpoints

    candidates = []
    for relative in audit["sources"]:
        if not relative.endswith("/checkpoint/checkpoint.json"):
            continue
        path = (RUNTIME / relative).resolve()
        assert path.is_relative_to(RUNTIME.resolve())
        if read(path)["sha256"] == prior["checkpoint_sha256"]:
            candidates.append(path.parent)
    assert len(candidates) == 1, "Exactly one bound original checkpoint is required"
    report = verify_window_checkpoints(
        native,
        candidates[0],
        condition=condition,
        window=window,
        initial_metrics=prior["saved_metrics"],
    )
    assert report["segments"] == audit["checkpoint_segments"]
    for reported, audited in (
        ("first_step", "first_step"),
        ("next_step", "responses"),
        ("new_responses", "new_responses"),
        ("new_tokens", "new_tokens"),
        ("new_saved_ticks", "new_saved_elapsed_ticks"),
        ("saved_elapsed_ticks", "saved_elapsed_ticks"),
        ("usage", "usage"),
        ("checkpoint_sha256", "checkpoint_sha256"),
        ("prior_checkpoint_sha256", "source_checkpoint_sha256"),
        ("initial_metrics", "initial_metrics"),
        ("saved_metrics", "saved_metrics"),
        ("status", "status"),
    ):
        assert report[reported] == audit[audited], f"Window checkpoint mismatch: {reported}"
    assert report["final_fresh_reload_verified"] is False
    exported = []
    for saved in report["segments"]:
        after = read(native / f"segment-{saved['segment_index']}" / "native-after.json")
        assert metrics_from_state(after) == saved["saved_metrics"]
        public = public_checkpoint(saved)
        public["final_boundary"] = {
            "year": after["year"],
            "year_tick": after["year_tick"],
            "paused": after["pause_state"],
        }
        exported.append(public)
    return exported


def public_checkpoint(saved):
    """Do not pass arbitrary private audit fields through to public manifests."""
    fields = (
        "segment_index",
        "first_step",
        "next_step",
        "new_responses",
        "new_tokens",
        "new_saved_ticks",
        "saved_elapsed_ticks",
        "usage",
        "prior_checkpoint_sha256",
        "checkpoint_sha256",
        "initial_metrics",
        "saved_metrics",
        "source_checkpoint_fresh_load_verified",
        "native_cleanup_verified",
        "final_fresh_reload_verified",
    )
    return {field: saved[field] for field in fields}


def build(audit_sha, *, owner_name, source_result, source_sha, reviewer_name="terminal_review.py"):
    """Export a fully audited same-campaign window from explicit retained sources."""
    assert re.fullmatch(r"[0-9a-f]{64}", audit_sha)
    assert re.fullmatch(r"[0-9a-f]{64}", source_sha)
    assert re.fullmatch(r"terminal_review(?:_v[0-9]+)?\.py", reviewer_name)
    assert re.fullmatch(r"keyboard-bindings-astra-r1-[0-9]+-[0-9]+-v[0-9]+", owner_name)
    assert re.fullmatch(
        r"keyboard_binding_astra_r1(?:_continuation_[0-9]+_[0-9]+)?_[0-9]{8}\.json", source_result
    )
    OWNER = RUNTIME / "keyboard-matched-pilot-v1" / owner_name
    ATTEMPT = OWNER / "attempt"
    PRIOR_RESULT = ROOT / "experiments/evidence" / source_result
    PRIOR_RESULT_SHA = source_sha
    assert sha(PRIOR_RESULT) == PRIOR_RESULT_SHA
    prior = read(PRIOR_RESULT)
    first_step = prior["responses"]
    assert type(first_step) is int and first_step > 0
    audit_path = ATTEMPT / "terminal-review.json"
    assert sha(audit_path) == audit_sha
    audit = read(audit_path)
    assert audit["passed"] is True and audit["first_step"] == first_step
    assert audit["schema_version"] in {
        "fortgym.private-binding-continuation-terminal-review/v1",
        "fortgym.private-binding-window-terminal-review/v1",
    }
    for relative, expected in audit["sources"].items():
        path = (RUNTIME / relative).resolve()
        assert path.is_relative_to(RUNTIME.resolve())
        assert sha(path) == expected, f"Evidence changed: {relative}"
    assert sha(PRIOR_RESULT) == PRIOR_RESULT_SHA
    prior = read(PRIOR_RESULT)
    assert prior["checkpoint_sha256"] == audit["source_checkpoint_sha256"]
    assert audit["campaign_id"] == prior["campaign_id"]
    assert audit["responses"] == first_step + audit["new_responses"]
    assert (
        audit["saved_elapsed_ticks"]
        == prior["saved_elapsed_ticks"] + audit["new_saved_elapsed_ticks"]
    )
    assert audit["usage"]["total_tokens"] == prior["usage"]["total_tokens"] + audit["new_tokens"]
    sys.path.insert(0, str(WORKTREE))
    from fort_gym.bench.eval.campaign_profile import metrics_from_state
    from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint

    native = ATTEMPT / "evidence/astra"
    condition, window = read(native / "condition.json"), read(native / "window.json")
    verify_condition(condition, prior)
    saved_checkpoints = checkpoint_chain(native, audit, prior, condition, window)
    last_index = saved_checkpoints[-1]["segment_index"] if saved_checkpoints is not None else 0
    segment = native / f"segment-{last_index}"
    checkpoint = verify_checkpoint(segment / "checkpoint")
    assert checkpoint["sha256"] == audit["checkpoint_sha256"]
    assert checkpoint["payload"]["parent_sha256"] == (
        saved_checkpoints[-1]["prior_checkpoint_sha256"]
        if saved_checkpoints is not None
        else prior["checkpoint_sha256"]
    )
    rows = [json.loads(line) for line in (segment / "loop/trace.jsonl").read_text().splitlines()]
    timeline, cumulative = [], prior["saved_elapsed_ticks"]
    for index, (row, receipt) in enumerate(
        zip(rows[first_step:], audit["receipt_reviews"], strict=True)
    ):
        assert row["step"] == index + first_step and receipt["decision_index"] == index
        assert row["run_id"] == audit["campaign_id"]
        action, execute, clock = row["action"], row["execute"], row["tick_advance"]
        cumulative += clock["ticks_advanced"]
        timeline.append(
            {
                "decision": row["step"] + 1,
                "keys": action["params"]["keys"] if action else [],
                "model_intent": action["intent"] if action else None,
                "input_accepted": execute["accepted"],
                "confirmed_key_presses": execute.get("result", {}).get("keys_confirmed", 0),
                "requested_ticks": action["advance_ticks"] if action else 0,
                "ticks_advanced": clock["ticks_advanced"],
                "saved_elapsed_ticks": cumulative,
                "clock_error": clock.get("error"),
                "metrics": metrics_from_state(row["state_after_advance"]),
                "returned_tokens": receipt["total_tokens"],
            }
        )
    assert cumulative == audit["saved_elapsed_ticks"]
    assert len(timeline) == audit["new_responses"] == audit["responses"] - first_step
    assert sum(row["returned_tokens"] for row in timeline) == audit["new_tokens"]
    assert sum(row["confirmed_key_presses"] for row in timeline) == audit["confirmed_key_presses"]
    if timeline:
        assert timeline[-1]["metrics"] == audit["saved_metrics"]
    owner = read(ATTEMPT / "result.json")
    condition = read(ATTEMPT / "evidence/astra/condition.json")
    verify_condition(condition, prior)
    window = read(ATTEMPT / "evidence/astra/window.json")
    assert window["continuation_from_next_step"] == first_step
    assert window["continuation_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert all(
        window[name] is False for name in ("reset_memory", "reset_usage", "strategy_intervention")
    )
    assert all(name not in window for name in ("restart", "prompt_change", "budget_extension"))
    assert sha(OWNER / "operator.py") == owner["binding"]["operator_sha256"]
    assert (
        sha(
            ROOT
            / "experiments/keyboard_binding_continuation_20260911"
            / f"window-{first_step}-{owner['target_next_step']}.json"
        )
        == owner["binding"]["window_sha256"]
    )
    assert sha(OWNER / reviewer_name) == audit["audit_source_sha256"]
    after = read(segment / "native-after.json")
    result = {
        "schema_version": "fortgym.public-keyboard-binding-continuation-result/v1",
        "campaign_id": audit["campaign_id"],
        "status": audit["status"],
        "stop_reason": audit["stop_reason"],
        "source_revision": audit["source_revision"],
        "image_id": audit["image_id"],
        "implementation_pull_request": "https://github.com/lemoz/fort-gym/pull/159",
        "declaration_revision": owner["declaration_revision"],
        "condition": condition,
        "window": read(ATTEMPT / "evidence/astra/window.json"),
        "source_result_path": str(PRIOR_RESULT.relative_to(ROOT)),
        "source_result_sha256": PRIOR_RESULT_SHA,
        "source_checkpoint_sha256": prior["checkpoint_sha256"],
        "checkpoint_sha256": audit["checkpoint_sha256"],
        "first_step": first_step,
        "responses": audit["responses"],
        "new_responses": audit["new_responses"],
        "new_confirmed_key_presses": audit["confirmed_key_presses"],
        "saved_elapsed_ticks": audit["saved_elapsed_ticks"],
        "new_saved_elapsed_ticks": audit["new_saved_elapsed_ticks"],
        "ticks_per_year": 403200,
        "final_boundary": {
            "year": after["year"],
            "year_tick": after["year_tick"],
            "paused": after["pause_state"],
        },
        "initial_metrics": audit["initial_metrics"],
        "saved_metrics": audit["saved_metrics"],
        "new_tokens": audit["new_tokens"],
        "usage": audit["usage"],
        "new_clock_outcomes": audit["clock_outcomes"],
        "activity": {
            key: value
            for key, value in (audit["observed_activity"] or {}).items()
            if key != "timeline"
        },
        "food_measurement": {
            "complete_samples": audit["food_complete_samples"],
            "samples": audit["food_samples"],
            "final_inventory": audit["saved_food"]["inventory"],
            "model_observation": "native_screen_text/v1; private evaluator inventory is not supplied to the model",
        },
        "audit": {
            "passed": True,
            "sha256": audit_sha,
            "source_sha256": audit["audit_source_sha256"],
            "provider_receipts_verified": len(audit["receipt_reviews"]),
            "provider_receipts": audit["receipt_reviews"],
            "native_cleanup_verified": True,
            "vm_teardown_verified": True,
            "shutdown": audit["shutdown"],
            "trace_sha256": sha(segment / "loop/trace.jsonl"),
            "usage_sha256": sha(segment / "loop/usage.jsonl"),
        },
        "proof_limits": {
            "same_campaign_own_save_continuation": True,
            "memory_or_usage_reset": False,
            "prompt_or_budget_changed": False,
            "fresh_final_checkpoint_reload_verified": False,
            "same_condition_as_historical_matched_cohort": False,
            "human_gameplay_rescue": False,
            "sustainability_proven": False,
            "year_two_reached": audit["saved_elapsed_ticks"] >= 403200,
            "strong_model_ranking_supported": False,
            "completed_production_measured": False,
            "completed_consumption_measured": False,
            "public_website_deployed": False,
            "main_merged": False,
        },
        "cost_limits": {
            "actual_model_charge_usd": None,
            "hardware_energy_and_app_cost_usd": None,
            "api_fallback": False,
            "local_model_fallback": False,
            "automatic_credit_purchase": False,
            "automatic_reset_consumption": False,
            "cloud_vms_created": 0,
        },
        "timeline": timeline,
        "interpretation": [
            "This is one continuation of the displayed-key pilot, not another independent replicate.",
            "Completed beds count placed and completed bed buildings, not carried items or queued jobs.",
            "Stock changes, intentions and sampled active jobs are not measured completed production or sustainability.",
            "Keep this control condition separate from historical native-event-name model comparisons.",
        ],
    }
    if saved_checkpoints is not None:
        result["checkpoint_segments"] = saved_checkpoints
        result["audit"]["saved_checkpoints_verified"] = len(saved_checkpoints)
        result["audit"]["source_checkpoint_fresh_load_verified"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--owner-name", required=True)
    parser.add_argument("--source-result", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reviewer-name", default="terminal_review.py")
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.audit_sha256,
                owner_name=args.owner_name,
                source_result=args.source_result,
                source_sha=args.source_sha256,
                reviewer_name=args.reviewer_name,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
