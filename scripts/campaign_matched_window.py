"""Prepare a decision-32-to-64 window from an exact audited public trial record.

This emits configuration only. It does not load a game, call a model, or admit a
VM. The native runner still verifies the actual checkpoint and its usage prefix.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_trial_config import load_trial

PROJECT = Path(__file__).resolve().parents[1]
PLAN = PROJECT / "experiments/keyboard_matched_pilot_20260910"
PLAN_SHA = "a724c04c94e27976820cb7fc8b071b7a15cd42973e69d3eb9a185bd97c632098"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(result_path: Path, expected_sha256: str) -> dict:
    """Bind one ordinary continuation to its own settled first-window result."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("An exact public result digest is required")
    result = read(result_path)
    if sha(result_path) != expected_sha256 or sha(PLAN / "cohort.json") != PLAN_SHA:
        raise ValueError("Result or cohort content differs from the declared digest")
    plan = read(PLAN / "cohort.json")
    rows = [
        row for row in plan["execution_order"] if row["campaign_id"] == result.get("campaign_id")
    ]
    if len(rows) != 1:
        raise ValueError("Result is outside the declared cohort")
    row = rows[0]
    condition_path, trial_path = PLAN / row["condition"], PLAN / row["trial"]
    condition, trial = load_trial(condition_path, trial_path)
    execution = result["execution"]
    if (
        result.get("schema_version") != "fortgym.public-matched-keyboard-result/v1"
        or result.get("cohort_id") != plan["cohort_id"]
        or result.get("model") != row["model"]
        or type(result.get("replicate")) is not int
        or result["replicate"] != row["replicate"]
        or execution["cohort_plan_sha256"] != PLAN_SHA
        or execution["condition_file_sha256"] != sha(condition_path)
        or execution["trial_file_sha256"] != sha(trial_path)
        or execution["seed_receipt_sha256"] != trial["source_snapshot_receipt_sha256"]
        or any(
            result.get(k) != condition[k]
            for k in (
                "model",
                "reasoning_effort",
                "control_profile",
                "observation_profile",
                "screen_size",
                "prompt_profile",
            )
        )
    ):
        raise ValueError("Recorded source or model condition differs from the cohort")
    if (
        result.get("status") != "completed"
        or result.get("stop_reason") != "segment_limit"
        or type(result.get("responses")) is not int
        or result["responses"] != 32
        or type(result.get("response_limit")) is not int
        or result["response_limit"] != 32
        or any(
            result.get(k) is not True
            for k in (
                "checkpoint_verified",
                "native_cleanup_verified",
                "vm_teardown_verified",
                "initial_memory_empty",
            )
        )
        or any(result.get(k) is not False for k in ("human_gameplay_rescue", "inherited_usage"))
        or type(result.get("new_native_save_losses")) is not int
        or result["new_native_save_losses"] != 0
        or type(result.get("saved_elapsed_ticks")) is not int
        or result["saved_elapsed_ticks"] < 0
    ):
        raise ValueError("Continuation requires an audited, settled 32-response first window")
    for key in ("checkpoint_sha256", "audit_sha256"):
        if not isinstance(result.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", result[key]):
            raise ValueError("Continuation requires exact checkpoint and audit digests")
    usage = result["usage"]
    if (
        any(
            type(usage.get(k)) is not int or usage[k] != 32
            for k in ("accounted_responses", "dispatched_requests")
        )
        or type(usage.get("returned_tokens")) is not int
        or not 0 < usage["returned_tokens"] < condition["max_total_tokens"]
        or condition["max_dispatches"] < 64
    ):
        raise ValueError("Settled usage and unchanged continuation allowance are required")
    return {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "condition_id": row["campaign_id"] + "-continue-32-64",
        "original_condition": row["condition"],
        "continuation_from_next_step": 32,
        "continuation_checkpoint_sha256": result["checkpoint_sha256"],
        "steps_per_segment": 32,
        "max_segments": 1,
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
        **{
            key: trial[key]
            for key in (
                "snapshot_profile",
                "runtime_rpc_transport",
                "private_measurement_profile",
                "private_measurement_timeout_seconds",
                "resource_observation_profile",
            )
        },
        "host_read_policy": "owned_exchange_reads_three_attempts_with_private_receipts/v1",
        "container_init_required": True,
        "expected_campaign_id": row["campaign_id"],
        "source_result_sha256": expected_sha256,
        "source_audit_sha256": result["audit_sha256"],
        "source_native_revision": execution["source_revision"],
        "source_image_id": execution["image_id"],
        "saved_elapsed_ticks_before_window": result["saved_elapsed_ticks"],
        "accounted_responses_before_window": 32,
        "returned_tokens_before_window": usage["returned_tokens"],
        "hypothesis": "Under unchanged model, input and observation settings, another equal 32-decision window tests whether an independently started agent adapts to its current menus and establishes observable fortress work. Compare saved outcomes at decision 64 without per-model tuning.",
        "continuity_note": "Resume this attempt's own exact native save, memory, configuration, prompt history and complete trace/usage prefixes. A fresh native load must match before further play. Do not restart from the seed, borrow another attempt, clear a menu or rescue gameplay.",
        "budget_note": "At most 32 additional responses, retaining the existing 1280-dispatch and 40000000-token campaign ceilings. No budget extension or reservation is implied. Fresh subscription admission before each call, no API/local fallback or credit/reset purchase, one local VM at a time and mandatory teardown.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--result-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.result, args.result_sha256), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
