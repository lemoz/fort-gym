"""Build public equal-decision comparisons from explicitly indexed result files.

This is a reporting reader, not a native-game verifier. Reviewed immutable
records enter through the index; absent records never imply a failed run.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

METRICS = (
    "population",
    "recorded_dead_citizens",
    "food_stock",
    "drink_stock",
    "completed_beds",
    "completed_workshops",
    "completed_farms",
    "functional_rooms",
    "stone_stock",
    "wood_stock",
)
OUTCOMES = {"saved", "budget_limited_pause", "infrastructure_failure", "gameplay_collapse"}
MAX_BYTES = 1024 * 1024


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON evidence key")
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON evidence number: {value}")


def _integer(value: Any, name: str, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Invalid {name}")
    return value


def _hash(value: Any, length: int = 64) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"[a-f0-9]{{{length}}}", value):
        raise ValueError("Invalid evidence digest or revision")
    return value


def read_evidence_object(root: Path, relative: str, expected: str | None = None) -> dict[str, Any]:
    """Read one bounded project-relative object, optionally checking its exact digest."""
    if not isinstance(relative, str):
        raise ValueError("Evidence path must be project-relative")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative:
        raise ValueError("Evidence path must be project-relative")
    path = root / relative
    if path.is_symlink() or path.resolve() != root.resolve() / parts:
        raise ValueError("Evidence path cannot traverse a symlink")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Evidence file is missing or oversized")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("Evidence file is oversized")
    if expected is not None and hashlib.sha256(data).hexdigest() != _hash(expected):
        raise ValueError("Evidence bytes differ from the reviewed digest")
    value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("Evidence must be a JSON object")
    return value


def _reference(root: Path, reference: dict[str, Any]) -> tuple[dict[str, Any], str]:
    path = reference["path"]
    if not re.fullmatch(r"experiments/[A-Za-z0-9_./-]+\.json", path):
        raise ValueError("Public evidence must be an experiments JSON file")
    value = read_evidence_object(root, path, reference["sha256"])
    revision = _hash(reference["revision"], 40)
    return value, f"https://github.com/lemoz/fort-gym/blob/{revision}/{path}"


def _storage_note(root: Path, value: dict[str, Any], boundary: int) -> dict[str, Any] | None:
    details = value.get("evidence_details", {})
    if not isinstance(details, dict):
        raise ValueError("Invalid result evidence details")
    if "storage_amendment" not in details:
        return None
    digest = "eeb3fa8b08234819247b4dec7ecf50fda9f137fd57cabe07d1426d968d15116e"
    declaration = read_evidence_object(
        root, "experiments/keyboard_comparison_storage_amendment_20260912.json", digest
    )
    expected = {**declaration["storage_binding"], "declaration_sha256": digest}
    if (
        json.dumps(details["storage_amendment"], sort_keys=True, allow_nan=False)
        != json.dumps(expected, sort_keys=True, allow_nan=False)
        or expected["campaign_id"] != value["campaign_id"]
        or expected["target_next_step"] != boundary
    ):
        raise ValueError("Storage amendment differs from its declared campaign and window")
    return {
        "schema_version": "fortgym.public-comparison-storage-note/v1",
        "first_step": expected["first_step"],
        "target_next_step": boundary,
        "disk_gib_before": expected["disk_gib_before"],
        "disk_gib_after": expected["disk_gib_after"],
        "other_conditions_unchanged": True,
        "declaration_sha256": digest,
    }


def _result(
    value: dict[str, Any],
    plan: dict[str, Any],
    declared: dict[str, Any],
    hashes: dict[str, str],
    boundary: int,
    root: Path,
) -> dict[str, Any]:
    matching = {
        "schema_version": "fortgym.public-displayed-key-result/v1",
        "cohort_id": plan["cohort_id"],
        "campaign_id": declared["id"],
        "model": plan["models"][declared["model"]],
        "replicate": declared["replicate"],
        "reasoning_effort": "medium",
        "source_revision": plan["native_source_revision"],
        "image_id": plan["native_image"],
        "seed_receipt_sha256": plan["seed_receipt_sha256"],
        "condition_file_sha256": hashes[declared["condition"]],
        "trial_file_sha256": hashes[declared["trial"]],
        "response_limit": boundary,
        "human_gameplay_rescue": False,
    }
    # Canonical JSON distinguishes booleans from integers when matching declarations.
    if any(
        json.dumps(value.get(key), sort_keys=True) != json.dumps(expected, sort_keys=True)
        for key, expected in matching.items()
    ):
        raise ValueError("Result differs from the declared comparison condition")
    if value.get("status") not in OUTCOMES:
        raise ValueError("Result has no settled outcome classification")
    responses = value.get("responses")
    if responses is not None:
        _integer(responses, "response count", boundary)
    tokens = value.get("returned_tokens")
    if tokens is not None:
        _integer(tokens, "returned tokens")
    cost = value.get("reported_charge_usd")
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ValueError("Invalid reported charge")
    for key in ("native_teardown_verified", "vm_teardown_verified"):
        if type(value.get(key)) is not bool:
            raise ValueError("Missing teardown classification")
    audit_sha = _hash(value.get("terminal_audit_sha256"))
    saved = value.get("checkpoint")
    checkpoint = None
    if saved is not None:
        cursor = _integer(saved["next_step"], "saved decision", boundary)
        if responses is None or cursor > responses:
            raise ValueError("Checkpoint exceeds accounted responses")
        metrics = {}
        for key in METRICS:
            number = saved["metrics"].get(key)
            metrics[key] = None if number is None else _integer(number, key)
        checkpoint = {
            "next_step": cursor,
            "sha256": _hash(saved["sha256"]),
            "saved_elapsed_ticks": _integer(saved["saved_elapsed_ticks"], "saved elapsed ticks"),
            "metrics": metrics,
        }
    if value["status"] == "saved" and (
        checkpoint is None
        or checkpoint["next_step"] != boundary
        or responses != boundary
        or tokens is None
        or not value["native_teardown_verified"]
        or not value["vm_teardown_verified"]
    ):
        raise ValueError("A saved boundary requires exact responses, checkpoint and teardown")
    result = {
        "status": value["status"],
        "response_limit": boundary,
        "responses": responses,
        "returned_tokens": tokens,
        "reported_charge_usd": cost,
        "checkpoint": checkpoint,
        "terminal_audit_sha256": audit_sha,
        "native_teardown_verified": value["native_teardown_verified"],
        "vm_teardown_verified": value["vm_teardown_verified"],
    }
    note = _storage_note(root, value, boundary)
    if note is not None:
        result["storage_amendment"] = note
    return result


def read_comparison(root: Path, index_path: str, *, boundary: int) -> dict[str, Any]:
    """Project all declared slots, including missing, paused and failed attempts.

    The index explicitly pins every public record and declaration by digest and
    commit. No native artifact discovery, provider call, or publication occurs.
    """
    index = read_evidence_object(root, index_path)
    if index.get("schema_version") != "fortgym.public-displayed-key-index/v1":
        raise ValueError("Unsupported comparison index")
    plan, plan_url = _reference(root, index["cohort"])
    if plan.get("schema_version") != "fortgym.displayed-key-comparison/v1":
        raise ValueError("Unsupported cohort declaration")
    _integer(boundary, "comparison boundary")
    if boundary == 0 or boundary not in plan["common_decision_boundaries"]:
        raise ValueError("Boundary is not declared for this cohort")
    rows = plan["sequence"]
    identities = [row["id"] for row in rows]
    if not rows or len(set(identities)) != len(rows):
        raise ValueError("Cohort identities must be unique")
    if set(index["results"]) - set(identities):
        raise ValueError("Index includes an undeclared campaign")
    expected_repeats = _integer(plan["replicates_per_model"], "replicate count")
    for row in rows:
        if _integer(row["replicate"], "replicate", expected_repeats) == 0:
            raise ValueError("Replicate must be positive")
    if not expected_repeats or set(plan["models"]) != {row["model"] for row in rows}:
        raise ValueError("Cohort model declarations differ")
    for model in plan["models"]:
        if sorted(row["replicate"] for row in rows if row["model"] == model) != list(
            range(1, expected_repeats + 1)
        ):
            raise ValueError("Every model needs its declared replicate slots")
    shared_conditions = []
    shared_trials = []
    hashes = index["config_sha256"]
    directory = str(PurePosixPath(index["cohort"]["path"]).parent)
    for row in rows:
        for key in ("condition", "trial"):
            if not re.fullmatch(r"[A-Za-z0-9_-]+\.json", row[key]):
                raise ValueError("Trial configuration must stay beside its declaration")
        condition = read_evidence_object(
            root, directory + "/" + row["condition"], hashes[row["condition"]]
        )
        trial = read_evidence_object(root, directory + "/" + row["trial"], hashes[row["trial"]])
        if (
            condition.pop("model") != plan["models"][row["model"]]
            or condition.pop("condition_id", None) is None
        ):
            raise ValueError("Condition model differs from its declared slot")
        if trial.pop("original_condition") != row["condition"]:
            raise ValueError("Trial refers to another model's condition")
        if trial["source_snapshot_receipt_sha256"] != plan["seed_receipt_sha256"]:
            raise ValueError("Trial starts from a different seed")
        for key, expected in {
            "reasoning_effort": "medium",
            "control_profile": plan["shared_control_profile"],
            "observation_profile": plan["shared_observation_profile"],
            "prompt_profile": plan["shared_prompt_profile"],
            "screen_size": plan["screen_size"],
            "bindings_sha256": plan["bindings_sha256"],
        }.items():
            if condition.get(key) != expected:
                raise ValueError("Condition differs from the declared shared interface")
        shared_conditions.append(json.dumps(condition, sort_keys=True, allow_nan=False))
        shared_trials.append(json.dumps(trial, sort_keys=True, allow_nan=False))
    if len(set(shared_conditions)) != 1 or len(set(shared_trials)) != 1:
        raise ValueError("Models differ in more than their declared selection")
    projected = []
    for row in rows:
        references = index["results"].get(row["id"], {})
        if set(references) - {str(number) for number in plan["common_decision_boundaries"]}:
            raise ValueError("Index contains an undeclared decision boundary")
        reference = references.get(str(boundary))
        result = None
        url = None
        if reference is not None:
            value, url = _reference(root, reference)
            result = _result(value, plan, row, hashes, boundary, root)
        projected.append(
            {
                "campaign_id": row["id"],
                "model": plan["models"][row["model"]],
                "replicate": row["replicate"],
                "reasoning_effort": "medium",
                "publication_state": "recorded" if result is not None else "no_published_result",
                "result": result,
                "evidence_url": url,
                "evidence_sha256": reference["sha256"] if reference else None,
            }
        )
    recorded = [row["result"] for row in projected if row["result"] is not None]
    report: dict[str, Any] = {
        "schema_version": "fortgym.public-displayed-key-comparison/v1",
        "cohort_id": plan["cohort_id"],
        "comparison_boundary": boundary,
        "plan_url": plan_url,
        "plan_sha256": index["cohort"]["sha256"],
        "declared_attempts": len(rows),
        "recorded_attempts": len(recorded),
        "outcome_counts": dict(Counter(row["status"] for row in recorded)),
        "all_attempts_reported": len(recorded) == len(rows),
        "all_saved_boundaries_reached": len(recorded) == len(rows)
        and all(row["status"] == "saved" for row in recorded),
        "trials": projected,
        "strong_ranking_supported": False,
        "live_status_included": False,
        "production_rates": None,
        "consumption_rates": None,
        "limits": [
            "No published result does not imply not running, failed, or zero progress.",
            "A saved decision boundary is not a successful campaign or a functioning fortress.",
            "Same decision limits do not imply equal tokens, elapsed game time or wall-clock time.",
            "Stocks and sampled jobs do not measure production, consumption or accessibility.",
            "Single-seed repeats are preliminary evidence, not a strong model ranking.",
            "Unknown measurements and unreported subscription charges remain null, not zero.",
        ],
    }
    if any("storage_amendment" in row for row in recorded):
        report["limits"].append(
            "A declared storage-capacity amendment is marked on its affected result; "
            "VM storage configurations are not identical across these windows."
        )
    return report
