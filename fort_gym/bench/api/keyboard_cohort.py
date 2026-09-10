"""Immutable, public-only records for the declared matched keyboard cohort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = "experiments/keyboard_matched_pilot_20260910/cohort.json"
PLAN_SHA256 = "a724c04c94e27976820cb7fc8b071b7a15cd42973e69d3eb9a185bd97c632098"
PLAN_REVISION = "1bc49b9675b1c82ad502bbd6d8461c9cdbf077e9"
# Adding a result requires a reviewed public projection and a data-only commit.
# Never discover files from native artifact directories or accept request paths.
RESULTS = {
    "matched-20260910-astra-r1": (
        "experiments/evidence/keyboard_matched_astra_r1_20260910.json",
        "59e3fe7a4a3edddcf6a6d1264c748237868b87f71a345d66e2c72c4c183906a1",
        "1dfb7e8250fd1dcea9410ebd3ea9d334d6bf7ce6",
    ),
    "matched-20260910-sol-r1": (
        "experiments/evidence/keyboard_matched_sol_r1_20260910.json",
        "0b213a6074777eb5d016cb885bb3df296c4096a8c47e88e43f443eec04142fda",
        "c0e37c1dc1bc90706396071798514673ac9abd5c",
    ),
}


def _read(relative: str, expected: str) -> dict[str, Any]:
    path = PROJECT_ROOT / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
        raise ValueError("Public cohort file is missing or invalid")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Public cohort content differs from its reviewed digest")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Public cohort record must be an object")
    return value


def _link(path: str, revision: str) -> str:
    return f"https://github.com/lemoz/fort-gym/blob/{revision}/{path}"


def keyboard_cohort() -> dict[str, Any]:
    """Return declared slots, preserving absent results as null, never zero."""
    plan = _read(PLAN_PATH, PLAN_SHA256)
    trials = []
    for declared in plan["execution_order"]:
        identity = declared["campaign_id"]
        row = {"campaign_id": identity, "model": declared["model"],
               "replicate": declared["replicate"], "reasoning_effort": "medium",
               "publication_state": "no_published_result", "result": None,
               "evidence_url": None, "evidence_sha256": None}
        if identity in RESULTS:
            path, digest, revision = RESULTS[identity]
            result = _read(path, digest)
            if (result["schema_version"] != "fortgym.public-matched-keyboard-result/v1"
                    or result["campaign_id"] != identity
                    or result["model"] != declared["model"]
                    or result["replicate"] != declared["replicate"]
                    or result["cohort_id"] != plan["cohort_id"]
                    or result["execution"]["cohort_plan_sha256"] != PLAN_SHA256
                    or result["execution"]["seed_receipt_sha256"]
                    != plan["source_snapshot_receipt_sha256"]):
                raise ValueError("Public result does not match the declared trial")
            row.update(publication_state="recorded", result=result,
                       evidence_url=_link(path, revision), evidence_sha256=digest)
        trials.append(row)
    recorded = [r["result"] for r in trials if r["result"] is not None]
    if recorded:
        common_execution = ("source_revision", "image_id", "seed_receipt_sha256", "binding_sha256")
        common_conditions = ("reasoning_effort", "control_profile", "observation_profile",
                             "screen_size", "prompt_profile", "response_limit")
        for result in recorded:
            if (any(result["execution"][key] != recorded[0]["execution"][key]
                    for key in common_execution)
                    or any(result[key] != recorded[0][key] for key in common_conditions)):
                raise ValueError("Recorded trials differ in a declared matching condition")
    return {
        "schema_version": "fortgym.public-keyboard-cohort/v1",
        "cohort_id": plan["cohort_id"], "hypothesis": plan["hypothesis"],
        "plan_url": _link(PLAN_PATH, PLAN_REVISION), "plan_sha256": PLAN_SHA256,
        "trials": trials, "recorded_trials": len(recorded), "declared_trials": len(trials),
        "initial_response_limit": plan["stages"]["initial_segment_responses"],
        "year_two_elapsed_ticks": plan["stages"]["year_two_elapsed_ticks"],
        "matched_initial_windows_complete": len(recorded) == len(trials)
        and all(r["responses"] == plan["stages"]["initial_segment_responses"] for r in recorded),
        "strong_ranking_supported": False, "live_owner_status_included": False,
        "limits": [
            "No published result does not mean not running, failed, or zero progress.",
            "A completed 32-response window is not a completed campaign; continuation is pending.",
            "Same-seed repeated trials describe this pilot, not performance across worlds.",
            "Food counts are raw edible units; ownership and accessibility are not assessed.",
            "Stocks and job samples do not measure production or consumption rates.",
            "Subscription charges are unreported, not zero; no model ranking is established.",
        ],
    }
