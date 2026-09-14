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
# Adding a result requires a reviewed public projection and an immutable commit.
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
    "matched-20260910-terra-r1": (
        "experiments/evidence/keyboard_matched_terra_r1_20260910.json",
        "9670b0e1e542df80f48abbecc39eec3f0e36ba071a0b6d0555d8f86724b92c7b",
        "91bf6838b40e019434152716c104716a26293574",
    ),
    "matched-20260910-terra-r2": (
        "experiments/evidence/keyboard_matched_terra_r2_20260910.json",
        "8f18ce3a115bc01435cf07fb699fb187a3c3003583e076442775e25b249b0b72",
        "2edbf98a301507e7ec4711dcd5fbd5bf7888bca5",
    ),
    "matched-20260910-sol-r2": (
        "experiments/evidence/keyboard_matched_sol_r2_20260910.json",
        "316a46641bb609350005ae734b74b881ad0d876b9f907fb2fc4eda1964b92ec3",
        "6531318881b6a12de8387321e02da675d299e4fb",
    ),
    "matched-20260910-astra-r2": (
        "experiments/evidence/keyboard_matched_astra_r2_20260910.json",
        "8bd2a2c69ed08ed4c8c063dd955ae793873899ad24678109404e7b4d5b5a5dfb",
        "baee24bcef343d73922175439553306e95e3b01d",
    ),
}
ORIGINAL_BINDING = "bb3c140c583c3d1462f48fe78cd3a8980713a860d512fceff337dd733f995312"
STORAGE_BINDING = "81b60b43fffdad75b1a3d9bdc7a3014a99e9890344dae532c4ba0406ed483779"
STORAGE_AMENDMENT = {
    "amendment_id": "keyboard-matched-storage-20260910",
    "data_disk_gib_before": 24, "data_disk_gib_after": 32,
    "parent_execution_sha256": ORIGINAL_BINDING,
    "plan_sha256": "7bb71cd099a1b945e8f9cafb184acfaa15ca906ffa1b57e250ac7615e9b23339",
    "operation_sha256": "9034ebaf21974e71c44b795aa7c23a5cf6f67802e9a1ff679860485f81d04b8f",
    "plan_url": "https://github.com/lemoz/fort-gym/blob/e753ab3d32a2e18ef1159f79e7810dcc963dd850/experiments/keyboard_matched_storage_amendment_20260910.json",
    "identical_host_configuration_to_first_two_trials": False,
    "source_image_seed_compute_and_gameplay_conditions_unchanged": True,
    "wall_clock_performance_comparison_excluded": True,
}


def _storage_condition(result: dict[str, Any], index: int) -> None:
    """Accept only the declared storage amendment at its declared boundary."""
    amended = index >= 2
    expected = STORAGE_BINDING if amended else ORIGINAL_BINDING
    amendment = result.get("storage_amendment")
    if result["execution"]["binding_sha256"] != expected:
        raise ValueError("Recorded trials differ in a declared matching condition")
    # JSON equality preserves boolean types (unlike Python's True == 1).
    if (json.dumps(amendment, sort_keys=True)
            != json.dumps(STORAGE_AMENDMENT if amended else None, sort_keys=True)):
        raise ValueError("Undeclared storage condition")


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
    for index, declared in enumerate(plan["execution_order"]):
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
            _storage_condition(result, index)
        trials.append(row)
    recorded = [r["result"] for r in trials if r["result"] is not None]
    if recorded:
        common_execution = ("source_revision", "image_id", "seed_receipt_sha256")
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
        "identical_host_configuration": False,
        "wall_clock_performance_comparison_supported": False,
        "limits": [
            "Storage changed from 24 to 32 GiB before Terra attempt 1. Source, image, seed, CPU, memory and gameplay settings remained unchanged; wall-clock speed is not compared.",
            "No published result does not mean not running, failed, or zero progress.",
            "These are historical decision-32 checkpoints, not completed campaigns. Saved-game continuation is reported separately.",
            "Same-seed repeated trials describe this pilot, not performance across worlds.",
            "Food counts are raw edible units; ownership and accessibility are not assessed.",
            "Stocks and job samples do not measure production or consumption rates.",
            "Subscription charges are unreported, not zero; no model ranking is established.",
        ],
    }
