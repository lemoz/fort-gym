"""Read-only, descriptive comparison of declared terminal controls-study manifests.

This checks manifest consistency, not original native execution. Missing results
are unknown outcomes, not failures or zeroes. It never ranks models or controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

METRICS = (
    "population",
    "recorded_dead_citizens",
    "completed_beds",
    "completed_workshops",
    "completed_farms",
    "food_stock",
    "drink_stock",
    "functional_rooms",
    "wood_stock",
    "stone_stock",
)
PROOF_FLAGS = (
    "checkpoint_verified",
    "parent_64_checkpoint_fresh_reload_verified",
    "memory_usage_and_history_preserved",
    "original_inputs_unchanged",
    "unchanged_model_prompt_controls_and_resources",
    "no_human_gameplay_rescue",
    "teardown_verified",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def count(value: object) -> bool:
    return type(value) is int and value >= 0


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw, parse_constant=reject_constant)
    require(isinstance(value, dict), f"Expected an object: {path.name}")
    return value, hashlib.sha256(raw).hexdigest()


def endpoint(value: dict, study: dict, study_sha: str) -> dict:
    require(
        value.get("schema_version") == "fortgym.selected-workshop-attempt-result/v2",
        "Expected a terminal v2 attempt manifest, not live progress",
    )
    for key in ("study_id", "source_revision", "image", "model", "reasoning_effort"):
        require(value.get(key) == study[key], f"Declared {key} differs")
    require(value.get("study_declaration_sha256") == study_sha, "Study hash differs")
    campaign = value.get("campaign_id")
    require(campaign in study["order"], "Attempt is not in the declared order")
    pair, condition = value.get("pair"), value.get("condition")
    require(
        count(pair) and pair > 0 and condition in ("keyboard", "shortcuts"),
        "Invalid pair or condition",
    )
    require(campaign == f"{study['study_id']}-p{pair}-{condition}", "Attempt identity differs")
    require(
        value.get("condition_sha256")
        == study["condition_file_sha256"][f"{condition}-condition.json"],
        "Condition hash differs",
    )
    bound = study["bounds"]["max_dispatches_per_attempt"]
    require(
        value.get("status") == "saved"
        and count(value.get("model_responses"))
        and count(value.get("comparison_boundary"))
        and value["model_responses"] == value.get("comparison_boundary") == bound,
        "Attempt has not reached the common saved boundary",
    )
    require(all(value.get(key) is True for key in PROOF_FLAGS), "Required proof flag is absent")
    require(
        type(value.get("final_checkpoint_fresh_reload_verified")) is bool,
        "Final reload verification must be boolean",
    )
    for key in ("audit_sha256", "checkpoint_manifest_sha256", "checkpoint_file_sha256"):
        require(
            isinstance(value.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None,
            f"Missing or invalid {key}",
        )
    tokens, ticks = value.get("returned_tokens"), value.get("saved_elapsed_ticks")
    require(
        count(tokens) and tokens <= study["bounds"]["max_returned_tokens_per_attempt"],
        "Returned-token boundary differs",
    )
    require(count(ticks), "Invalid elapsed ticks")
    raw_metrics = value.get("saved_metrics")
    require(isinstance(raw_metrics, dict), "Saved metrics are absent")
    metrics = {key: raw_metrics.get(key) for key in METRICS}
    require(all(item is None or count(item) for item in metrics.values()), "Invalid saved metric")
    charge = value.get("reported_charge_usd")
    require(
        charge is None or (type(charge) in (int, float) and math.isfinite(charge) and charge >= 0),
        "Invalid reported charge",
    )
    actions = value.get("action_counts", {})
    require(
        isinstance(actions, dict) and isinstance(actions.get("clock"), dict),
        "Action summary or clock is absent",
    )
    action_ticks = actions["clock"].get("advanced_ticks")
    require(
        count(actions.get("decisions"))
        and count(action_ticks)
        and actions["decisions"] == bound
        and action_ticks == ticks,
        "Action totals contradict the saved endpoint",
    )
    return dict(
        campaign_id=campaign,
        pair=pair,
        condition=condition,
        model=value["model"],
        reasoning_effort=value["reasoning_effort"],
        responses=bound,
        returned_tokens=tokens,
        saved_elapsed_ticks=ticks,
        metrics=metrics,
        reported_charge_usd=charge,
        audit_sha256=value["audit_sha256"],
        final_checkpoint_fresh_reload_verified=value.get("final_checkpoint_fresh_reload_verified"),
    )


def summarize(study_path: Path, result_paths: list[Path]) -> dict:
    """Summarize supplied immutable endpoints; never discover or write files."""
    study, study_sha = read_json(study_path)
    require(
        study.get("schema_version") == "fortgym.selected-workshop-study-runtime-declaration/v2",
        "Expected a declared v2 controls study",
    )
    order = study.get("order")
    require(
        isinstance(order, list) and order and all(isinstance(item, str) for item in order),
        "Invalid study order",
    )
    require(len(order) == len(set(order)), "Duplicate declared attempt")
    require(
        count(study["bounds"]["max_dispatches_per_attempt"])
        and study["bounds"]["max_dispatches_per_attempt"] > 0,
        "Invalid response boundary",
    )
    require(
        count(study["bounds"]["max_returned_tokens_per_attempt"])
        and study["bounds"]["max_returned_tokens_per_attempt"] > 0,
        "Invalid token boundary",
    )
    declared: dict[int, dict[str, str]] = {}
    for campaign in order:
        match = re.fullmatch(
            re.escape(study["study_id"]) + r"-p([1-9][0-9]*)-(keyboard|shortcuts)", campaign
        )
        require(match is not None, "Invalid declared pair identity")
        declared.setdefault(int(match[1]), {})[match[2]] = campaign
    require(
        all(set(pair) == {"keyboard", "shortcuts"} for pair in declared.values()),
        "Each declared pair needs both conditions",
    )
    supplied = {}
    for path in result_paths:
        value, sha = read_json(path)
        row = endpoint(value, study, study_sha)
        campaign = row["campaign_id"]
        require(campaign not in supplied, "Duplicate supplied attempt")
        supplied[campaign] = dict(row, result_file=path.name, result_sha256=sha)
    pairs = []
    for pair, identities in sorted(declared.items()):
        rows = {condition: supplied.get(campaign) for condition, campaign in identities.items()}
        complete = all(row is not None for row in rows.values())
        delta = None
        if complete:
            keyboard, shortcuts = rows["keyboard"], rows["shortcuts"]
            left = dict(
                keyboard["metrics"],
                returned_tokens=keyboard["returned_tokens"],
                saved_elapsed_ticks=keyboard["saved_elapsed_ticks"],
            )
            right = dict(
                shortcuts["metrics"],
                returned_tokens=shortcuts["returned_tokens"],
                saved_elapsed_ticks=shortcuts["saved_elapsed_ticks"],
            )
            delta = {
                key: None if left[key] is None or right[key] is None else left[key] - right[key]
                for key in left
            }
        pairs.append(
            dict(
                pair=pair,
                both_terminal_manifests_supplied=complete,
                results=rows,
                keyboard_minus_shortcuts=delta,
            )
        )
    selected = [supplied[campaign] for campaign in order if campaign in supplied]
    charges = [row["reported_charge_usd"] for row in selected]
    known = [charge for charge in charges if charge is not None]
    missing = [campaign for campaign in order if campaign not in supplied]
    return dict(
        schema_version="fortgym.selected-workshop-cohort-summary/v1",
        study_id=study["study_id"],
        source_revision=study["source_revision"],
        image=study["image"],
        model=study["model"],
        reasoning_effort=study["reasoning_effort"],
        study_declaration_sha256=study_sha,
        common_response_boundary=study["bounds"]["max_dispatches_per_attempt"],
        supplied_attempts=len(supplied),
        declared_attempts=len(order),
        missing_results=missing,
        missing_result_meaning="terminal result not supplied; final outcome unknown, not counted as failure",
        all_declared_terminal_manifests_supplied=not missing,
        pairs=pairs,
        returned_tokens_in_supplied_results=sum(row["returned_tokens"] for row in selected),
        reported_charge_usd_for_supplied_results=sum(known)
        if charges and len(known) == len(charges)
        else None,
        known_reported_charge_subtotal_usd=sum(known) if known else None,
        results_with_unreported_charge=len(charges) - len(known),
        native_audit_performed=False,
        ranking_performed=False,
        sustainability_assessed=False,
        goal_completion_assessed=False,
        note="Descriptive manifest comparison. Equal decisions do not imply equal elapsed ticks, "
        "tokens or wall time. Repeated policies on one seed are not independent worlds. "
        "Original native audits, unsupplied outcomes and website delivery remain separate evidence.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--result", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        value = summarize(args.study, args.result)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(value, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
