#!/usr/bin/env python3
"""Build and verify the pinned G7-v5 live-calibration evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fort_gym.bench.eval import fort_eval_easy_p1 as contract


SCENARIO_ARGUMENTS = {
    "owned_layout_and_provisioning": "owned_run",
    "death_cause_fallback": "death_run",
    "sensor_dropout": "dropout_run",
}

CALIBRATION_TEST_NODE_IDS = (
    "tests/test_runner_scoring_provenance.py::test_governed_partial_construction_claims_and_exact_completion",
    "tests/test_runner_scoring_provenance.py::test_building_evidence_is_incomplete_after_native_stage_read_failure",
    "tests/test_runner_scoring_provenance.py::test_operational_farm_proof_requires_the_farm_to_remain_complete",
    "tests/test_runner_scoring_provenance.py::test_operational_farm_proof_requires_current_crop_assignment_and_read_health",
    "tests/test_runner_scoring_provenance.py::test_owned_room_requires_final_geometry_function_and_native_access",
    "tests/test_runner_scoring_provenance.py::test_owned_room_lower_bound_survives_unrelated_component_scan_truncation",
    "tests/test_runner_scoring_provenance.py::test_owned_room_rejects_one_tile_claim_and_unowned_function",
    "tests/test_runner_scoring_provenance.py::test_owned_room_requires_exact_boundary_door_not_diagonal_proximity",
    "tests/test_runner_scoring_provenance.py::test_owned_floor_boundary_cannot_be_credited_as_structural_wall",
    "tests/test_runner_scoring_provenance.py::test_owned_order_output_is_attributed_when_it_completes_during_later_wait",
    "tests/test_runner_scoring_provenance.py::test_owned_output_rejects_untracked_same_family_job",
    "tests/test_runner_scoring_provenance.py::test_owned_output_sensor_gap_is_persistent_and_cannot_later_credit_delta",
    "tests/test_g7_gate.py::test_g7_v5_inherited_seed_stock_cannot_replace_owned_brew_output",
    "tests/test_g7_gate.py::test_g7_v5_operational_farm_latch_cannot_replace_final_owned_farm",
    "tests/test_g7_gate.py::test_g7_v5_malformed_owned_counts_are_unknown_not_zero",
    "tests/test_g7_gate.py::test_g7_v5_positive_death_count_requires_authoritative_record_details",
    "tests/test_g7_gate.py::test_g7_v5_rejects_non_authoritative_death_cause_source",
    "tests/test_g7_gate.py::test_g7_v5_rejects_contradictory_death_aggregates_as_invalid",
    "tests/test_g7_gate.py::test_g7_v5_rejects_duplicate_death_records",
    "tests/test_g7_evidence.py::test_death_calibration_fixture_is_one_bounded_friendly_kill",
    "tests/test_g7_observability_hooks.py::test_fort_metrics_emits_typed_constructions_and_honest_scan_flags",
    "tests/test_g7_observability_hooks.py::test_fort_metrics_distinguishes_actual_caps_and_path_sample_gaps",
    "tests/test_g7_observability_hooks.py::test_fort_metrics_tracks_building_scan_and_exact_boundary_membership",
    "tests/test_public_research_routes.py::test_calibration_protocol_never_builds_public_comparison_groups",
    "tests/test_public_research_routes.py::test_calibration_protocol_is_excluded_from_public_overview_and_scalar_groups",
    "tests/test_fort_eval_easy_p1_runtime.py::test_seed_region3_attestation_fails_closed_when_zero_valued_sensors_are_missing",
    "tests/test_advance_ticks_external.py::test_final_attestation_recovers_modal_transition_after_probe_failure",
    "tests/test_advance_ticks_external.py::test_final_attestation_recovery_fails_closed_gate",
    "tests/test_runner_tick_lifecycle.py::test_governed_viewscreen_interruption_is_degraded_and_reobserved",
    "tests/test_runner_tick_lifecycle.py::test_final_attestation_provenance_fails_closed_gate",
    "tests/test_remote_proto_fetch.py::test_remote_proto_runtime_digest_binds_actual_generated_modules",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_summary(path: Path, *, run_id: str, scenario: str) -> dict[str, Any]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError(f"summary for {run_id} is not an object")
    required = {
        "run_id": run_id,
        "backend": "dfhack",
        "model": contract.P1_CALIBRATION_MODEL,
        "evaluation_protocol": contract.P1_PROTOCOL,
        "evaluator_version": "outcome-vector-v1+g7-v5",
        "measurement_calibration_scenario": scenario,
    }
    mismatches = {
        key: {"expected": expected, "observed": summary.get(key)}
        for key, expected in required.items()
        if summary.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"summary identity mismatch for {run_id}: {mismatches}")
    commit = str(summary.get("fort_gym_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"summary for {run_id} lacks an exact fort_gym_commit")
    runtime_proto_digest = contract.p1_remote_proto_runtime_digest()
    if runtime_proto_digest is None:
        raise ValueError("generated DFHack protobuf bindings are unavailable")
    if summary.get("remote_proto_runtime_sha256") != runtime_proto_digest:
        raise ValueError(f"summary protobuf binding mismatch for {run_id}")
    return summary


def _run_regression_suite(repo: Path, report: Path) -> None:
    declared_names = {node.rsplit("::", 1)[-1] for node in CALIBRATION_TEST_NODE_IDS}
    if declared_names != contract.P1_CALIBRATION_REQUIRED_REGRESSION_TESTS:
        raise RuntimeError("bundle-builder test list disagrees with runtime contract")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *CALIBRATION_TEST_NODE_IDS,
            f"--junitxml={report}",
        ],
        cwd=repo,
        check=True,
    )


def _require_clean_checkout_at_commit(repo: Path, expected_commit: str) -> None:
    """Bind regression proof and digests to the trace-producing checkout."""

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected_commit:
        raise RuntimeError(
            "calibration bundle checkout does not match trace commit: "
            f"HEAD={head or '<empty>'} traces={expected_commit}"
        )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if dirty.strip():
        raise RuntimeError(
            "calibration bundle requires a clean checkout at the trace commit"
        )


def _verify_bundle(bundle: dict[str, Any], *, evidence_root: Path) -> None:
    if bundle.get("manifest_semantic_sha256") != contract.p1_manifest_semantic_digest():
        raise ValueError("bundle manifest semantic digest is stale")
    if bundle.get("measurement_code_sha256") != contract.p1_measurement_code_digest():
        raise ValueError("bundle measurement code digest is stale")
    runtime_proto_digest = contract.p1_remote_proto_runtime_digest()
    if runtime_proto_digest is None:
        raise ValueError("generated DFHack protobuf bindings are unavailable")
    if bundle.get("remote_proto_runtime_sha256") != runtime_proto_digest:
        raise ValueError("bundle protobuf binding digest is stale")
    previous_root = contract.P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT
    try:
        contract.P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT = evidence_root
        if not contract._live_calibration_traces_are_bound(
            bundle.get("live_traces"),
            str(bundle.get("calibration_fort_gym_commit") or ""),
        ):
            raise ValueError(
                "live calibration traces do not satisfy the runtime contract"
            )
        if not contract._calibration_regression_report_is_bound(
            bundle.get("regression_report")
        ):
            raise ValueError("regression report does not satisfy the runtime contract")
    finally:
        contract.P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT = previous_root


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifacts-root", type=Path, default=repo / "fort_gym" / "artifacts"
    )
    parser.add_argument(
        "--evidence-root", type=Path, default=repo / "experiments" / "evidence"
    )
    parser.add_argument("--owned-run", required=True)
    parser.add_argument("--death-run", required=True)
    parser.add_argument("--dropout-run", required=True)
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.approve and not args.reviewer.strip():
        parser.error("--approve requires a non-empty --reviewer")
    runtime_proto_digest = contract.p1_remote_proto_runtime_digest()
    if runtime_proto_digest is None:
        raise ValueError("generated DFHack protobuf bindings are unavailable")

    run_ids = {
        scenario: str(getattr(args, argument))
        for scenario, argument in SCENARIO_ARGUMENTS.items()
    }
    if len(set(run_ids.values())) != len(run_ids):
        raise ValueError("each calibration scenario requires a distinct run")

    sources: list[tuple[str, str, Path, Path]] = []
    commits: set[str] = set()
    for scenario, run_id in run_ids.items():
        source = args.artifacts_root / run_id
        source_trace = source / "trace.jsonl"
        source_summary = source / "summary.json"
        if not source_trace.is_file() or not source_summary.is_file():
            raise FileNotFoundError(
                f"missing trace/summary for calibration run {run_id}"
            )
        summary = _load_summary(source_summary, run_id=run_id, scenario=scenario)
        commits.add(str(summary["fort_gym_commit"]))
        sources.append((scenario, run_id, source_trace, source_summary))
    if len(commits) != 1:
        raise ValueError(f"calibration runs use different commits: {sorted(commits)}")
    calibration_commit = next(iter(commits))
    _require_clean_checkout_at_commit(repo, calibration_commit)

    args.evidence_root.mkdir(parents=True, exist_ok=True)
    trace_items: list[dict[str, Any]] = []
    for scenario, run_id, source_trace, source_summary in sources:
        prefix = f"p1_g7_v5_{scenario}_{run_id}"
        target_trace = args.evidence_root / f"{prefix}.jsonl"
        target_summary = args.evidence_root / f"{prefix}_summary.json"
        shutil.copyfile(source_trace, target_trace)
        shutil.copyfile(source_summary, target_summary)
        item: dict[str, Any] = {
            "scenario": scenario,
            "run_id": run_id,
            "artifact": target_trace.name,
            "trace_sha256": _sha256(target_trace),
            "summary_artifact": target_summary.name,
            "summary_sha256": _sha256(target_summary),
        }
        if scenario == "sensor_dropout":
            item["sensor_field"] = "governed_owned_room_evidence_complete"
        trace_items.append(item)

    regression_report = args.evidence_root / "p1_g7_v5_measurement_regressions.xml"
    _run_regression_suite(repo, regression_report)
    bundle = {
        "schema_version": "fort-eval.measurement-calibration/v1",
        "protocol": contract.P1_PROTOCOL,
        "evaluator_version": "outcome-vector-v1+g7-v5",
        "seed_world_sha256": contract.P1_SEED_WORLD_SHA256,
        "calibration_manifest_sha256": _sha256(contract.P1_MANIFEST_PATH),
        "manifest_semantic_sha256": contract.p1_manifest_semantic_digest(),
        "measurement_code_sha256": contract.p1_measurement_code_digest(),
        "remote_proto_runtime_sha256": runtime_proto_digest,
        "calibration_fort_gym_commit": calibration_commit,
        "review_status": "approved" if args.approve else "pending",
        "reviewer": args.reviewer.strip(),
        "live_traces": trace_items,
        "regression_report": {
            "artifact": regression_report.name,
            "sha256": _sha256(regression_report),
        },
    }
    _verify_bundle(bundle, evidence_root=args.evidence_root)
    target = args.evidence_root / "fort_eval_easy_p1_g7_v5_live_calibration.json"
    target.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "bundle": str(target),
                "sha256": _sha256(target),
                "review_status": bundle["review_status"],
            }
        )
    )


if __name__ == "__main__":
    main()
