"""Frozen runtime contract for the provisional Fort-Eval Easy P1 comparison."""

from __future__ import annotations

import hashlib
from importlib import import_module
import json
import copy
from pathlib import Path
import re
import time
from typing import Any, Dict, Mapping
from xml.etree import ElementTree

import yaml

from ..env.remote_proto import runtime_binding_digest

P1_PROTOCOL_V3 = "fort-eval-easy-p1-g7-v3"
P1_PROTOCOL_V4 = "fort-eval-easy-p1-g7-v4"
P1_PROTOCOL = "fort-eval-easy-p1-g7-v5"
P1_SEED_SAVE = "seed_region3_fresh"
P1_RUNTIME_SAVE = "region1"
P1_SEED_WORLD_SHA256 = (
    "070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d"
)
P1_MAX_STEPS = 200
P1_TICKS_PER_STEP = 2500
P1_CALIBRATION_MODEL = "dfhack-governed-scripted"
P1_LIVE_CALIBRATION_SCENARIOS = frozenset(
    {
        "owned_layout_and_provisioning",
        "death_cause_fallback",
        "sensor_dropout",
    }
)
P1_MEASUREMENT_CALIBRATION_COMPLETE = False
P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str | None = None
P1_MEASUREMENT_CALIBRATION_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "experiments"
    / "evidence"
    / "fort_eval_easy_p1_g7_v5_live_calibration.json"
)
P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "experiments" / "evidence"
)
P1_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "experiments" / "fort_eval_easy_p1_g7_v5.yaml"
)
P1_CALIBRATION_REQUIRED_REGRESSION_TESTS = frozenset(
    {
        "test_governed_partial_construction_claims_and_exact_completion",
        "test_building_evidence_is_incomplete_after_native_stage_read_failure",
        "test_operational_farm_proof_requires_the_farm_to_remain_complete",
        "test_operational_farm_proof_requires_current_crop_assignment_and_read_health",
        "test_owned_room_requires_final_geometry_function_and_native_access",
        "test_owned_room_lower_bound_survives_unrelated_component_scan_truncation",
        "test_owned_room_rejects_one_tile_claim_and_unowned_function",
        "test_owned_room_requires_exact_boundary_door_not_diagonal_proximity",
        "test_owned_floor_boundary_cannot_be_credited_as_structural_wall",
        "test_owned_order_output_is_attributed_when_it_completes_during_later_wait",
        "test_owned_output_rejects_untracked_same_family_job",
        "test_owned_output_sensor_gap_is_persistent_and_cannot_later_credit_delta",
        "test_g7_v5_inherited_seed_stock_cannot_replace_owned_brew_output",
        "test_g7_v5_operational_farm_latch_cannot_replace_final_owned_farm",
        "test_g7_v5_malformed_owned_counts_are_unknown_not_zero",
        "test_g7_v5_positive_death_count_requires_authoritative_record_details",
        "test_g7_v5_rejects_non_authoritative_death_cause_source",
        "test_g7_v5_rejects_contradictory_death_aggregates_as_invalid",
        "test_g7_v5_rejects_duplicate_death_records",
        "test_death_calibration_fixture_is_one_bounded_friendly_kill",
        "test_fort_metrics_emits_typed_constructions_and_honest_scan_flags",
        "test_fort_metrics_distinguishes_actual_caps_and_path_sample_gaps",
        "test_fort_metrics_tracks_building_scan_and_exact_boundary_membership",
        "test_calibration_protocol_never_builds_public_comparison_groups",
        "test_calibration_protocol_is_excluded_from_public_overview_and_scalar_groups",
        "test_seed_region3_attestation_fails_closed_when_zero_valued_sensors_are_missing",
        "test_final_attestation_recovers_modal_transition_after_probe_failure",
        "test_final_attestation_recovery_fails_closed_gate",
        "test_governed_viewscreen_interruption_is_degraded_and_reobserved",
        "test_final_attestation_provenance_fails_closed_gate",
        "test_calibration_scenario_never_starts_optional_provider_analysis",
        "test_remote_proto_runtime_digest_binds_actual_generated_modules",
    }
)

P1_MEASUREMENT_CODE_RELATIVE_PATHS = (
    "hook/fort_metrics.lua",
    "hook/g7_evidence.lua",
    "hook/calibration_kill_one.lua",
    "hook/job_metrics.lua",
    "hook/work_metrics.lua",
    "hook/map_snapshot.lua",
    "hook/designate_rect.lua",
    "hook/build_construction.lua",
    "hook/build_workshop.lua",
    "hook/build_farm_plot.lua",
    "hook/place_furniture.lua",
    "hook/order_make.lua",
    "hook/set_farm_crop.lua",
    "hook/set_labor.lua",
    "hook/unsuspend_jobs.lua",
    "hook/prepare_keystroke_target.lua",
    "hook/view_state.lua",
    "hook/restore_view_state.lua",
    "fort_gym/bench/agent/base.py",
    "fort_gym/bench/config.py",
    "fort_gym/bench/dfhack_backend.py",
    "fort_gym/bench/dfhack_exec.py",
    "fort_gym/bench/tick_controller.py",
    "fort_gym/bench/tick_receipt.py",
    "fort_gym/bench/env/actions.py",
    "fort_gym/bench/env/dfhack_client.py",
    "fort_gym/bench/env/encoder.py",
    "fort_gym/bench/env/executor.py",
    "fort_gym/bench/env/keystroke_exec.py",
    "fort_gym/bench/env/remote_proto/__init__.py",
    "fort_gym/bench/env/remote_proto/fetch_proto.py",
    "fort_gym/bench/env/state_reader.py",
    "fort_gym/bench/run/runner.py",
    "fort_gym/bench/run/model_modes.py",
    "fort_gym/bench/run/seed_reset.py",
    "fort_gym/bench/run/storage.py",
    "fort_gym/bench/eval/fort_eval_easy_p1.py",
    "fort_gym/bench/eval/gates.py",
    "fort_gym/bench/eval/milestones.py",
    "fort_gym/bench/eval/metrics.py",
    "fort_gym/bench/eval/protocol.py",
    "fort_gym/bench/eval/rubric.py",
    "fort_gym/bench/eval/scoring.py",
    "fort_gym/bench/eval/summary.py",
    "fort_gym/bench/eval/measurement_replay.py",
    "scripts/run_p1_live_calibration.py",
    "scripts/build_p1_live_calibration_bundle.py",
)

MODEL_ARMS: Dict[str, Dict[str, str]] = {
    "dfhack-governed-llm-fable5": {
        "public_label": "Claude Fable 5",
        "provider_model": "anthropic/claude-fable-5",
        "resolved_model_prefix": "anthropic/claude-5-fable-",
        "cache": "explicit_ephemeral",
    },
    "dfhack-governed-llm-gpt56-sol": {
        "public_label": "GPT-5.6 Sol",
        "provider_model": "openai/gpt-5.6-sol",
        "resolved_model_prefix": "openai/gpt-5.6-sol-",
        "cache": "automatic",
    },
}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strict_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def prompt_digest() -> str:
    from ..agent.governed_llm import (
        GOVERNED_OBSERVATION_PREAMBLE,
        GOVERNED_SYSTEM_PROMPT,
        _submit_action_tool,
    )

    payload = {
        "system": GOVERNED_SYSTEM_PROMPT,
        "observation_preamble": GOVERNED_OBSERVATION_PREAMBLE,
        "tool": _submit_action_tool(max_advance_ticks=P1_TICKS_PER_STEP),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _current_git_commit() -> str | None:
    repo = Path(__file__).resolve().parents[3]
    dot_git = repo / ".git"
    try:
        if dot_git.is_file():
            line = dot_git.read_text(encoding="utf-8").strip()
            git_dir = Path(line.removeprefix("gitdir: ")).resolve()
        else:
            git_dir = dot_git
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", head):
            return head
        ref = head.removeprefix("ref: ")
        common_dir_file = git_dir / "commondir"
        common_dir = (
            (git_dir / common_dir_file.read_text(encoding="utf-8").strip()).resolve()
            if common_dir_file.exists()
            else git_dir
        )
        value = (common_dir / ref).read_text(encoding="utf-8").strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    except OSError:
        return None


def p1_measurement_code_digest() -> str:
    """Hash every evaluator/sensor source covered by live calibration."""

    repo = Path(__file__).resolve().parents[3]
    digest = hashlib.sha256()
    for relative_path in P1_MEASUREMENT_CODE_RELATIVE_PATHS:
        path = repo / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        source = path.read_bytes()
        if path == Path(__file__).resolve():
            source = _normalized_calibration_contract_source(source)
        digest.update(source)
        digest.update(b"\0")
    return digest.hexdigest()


def p1_remote_proto_runtime_digest() -> str | None:
    """Return the exact untracked generated-binding digest for live DFHack RPCs."""

    return runtime_binding_digest()


def _normalized_calibration_contract_source(source: bytes) -> bytes:
    """Remove only the two post-calibration lock values from the source hash."""

    text = source.decode("utf-8")
    text = re.sub(
        r"^P1_MEASUREMENT_CALIBRATION_COMPLETE\s*=\s*[^\r\n]+$",
        "P1_MEASUREMENT_CALIBRATION_COMPLETE = <LOCK_VALUE>",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256:\s*str\s*\|\s*None\s*=\s*[^\r\n]+$",
        "P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str | None = <LOCK_VALUE>",
        text,
        flags=re.MULTILINE,
    )
    return text.encode("utf-8")


def p1_manifest_semantic_digest(path: Path | None = None) -> str:
    """Hash benchmark semantics while allowing the reviewed activation flip."""

    manifest_path = path or P1_MANIFEST_PATH
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("P1 manifest must be a mapping")
    normalized = copy.deepcopy(manifest)
    normalized["status"] = "<LIFECYCLE_STATUS>"
    publication = normalized.get("publication")
    if not isinstance(publication, dict):
        raise ValueError("P1 manifest publication must be a mapping")
    publication["calibration_results_public"] = "<LIFECYCLE_PUBLICATION>"
    comparability = normalized.get("comparability")
    if not isinstance(comparability, dict):
        raise ValueError("P1 manifest comparability must be a mapping")
    comparability["pair_comparison_enabled"] = "<LIFECYCLE_PAIR_ENABLED>"
    comparability["pair_comparison_reason"] = "<LIFECYCLE_PAIR_REASON>"
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _nested_mapping_has(value: Any, key: str, expected: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get(key) == expected:
            return True
        return any(_nested_mapping_has(item, key, expected) for item in value.values())
    if isinstance(value, list):
        return any(_nested_mapping_has(item, key, expected) for item in value)
    return False


def _live_calibration_traces_are_bound(value: Any, calibration_commit: str) -> bool:
    """Require scenario-specific DFHack traces and summaries, not hash-shaped claims."""

    if not isinstance(value, list):
        return False
    remote_proto_digest = p1_remote_proto_runtime_digest()
    if remote_proto_digest is None:
        return False
    artifact_root = P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT.resolve()
    required_scenarios = P1_LIVE_CALIBRATION_SCENARIOS
    verified_scenarios: set[str] = set()
    verified_run_ids: set[str] = set()
    verified_artifacts: set[Path] = set()
    for item in value:
        if not isinstance(item, dict):
            return False
        scenario = str(item.get("scenario") or "")
        run_id = str(item.get("run_id") or "")
        relative_artifact = item.get("artifact")
        relative_summary = item.get("summary_artifact")
        expected_hash = str(item.get("trace_sha256") or "")
        expected_summary_hash = str(item.get("summary_sha256") or "")
        if (
            scenario not in required_scenarios
            or not run_id
            or not isinstance(relative_artifact, str)
            or not relative_artifact
            or Path(relative_artifact).is_absolute()
            or not isinstance(relative_summary, str)
            or not relative_summary
            or Path(relative_summary).is_absolute()
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_summary_hash)
            or run_id in verified_run_ids
        ):
            return False
        artifact = (artifact_root / relative_artifact).resolve()
        summary_artifact = (artifact_root / relative_summary).resolve()
        if (
            artifact_root not in artifact.parents
            or artifact_root not in summary_artifact.parents
            or artifact in verified_artifacts
            or summary_artifact in verified_artifacts
        ):
            return False
        try:
            raw = artifact.read_bytes()
            summary_raw = summary_artifact.read_bytes()
            summary = json.loads(summary_raw)
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            return False
        if (
            hashlib.sha256(raw).hexdigest() != expected_hash
            or hashlib.sha256(summary_raw).hexdigest() != expected_summary_hash
            or not isinstance(summary, dict)
            or not rows
            or not all(
                isinstance(row, dict) and row.get("run_id") == run_id for row in rows
            )
        ):
            return False
        action_rows = [row for row in rows if isinstance(row.get("action"), dict)]
        if not action_rows or not all(
            isinstance(row.get("execute"), dict)
            and row["execute"].get("provenance") == "dfhack_governed"
            for row in action_rows
        ):
            return False
        if (
            summary.get("run_id") != run_id
            or summary.get("backend") != "dfhack"
            or summary.get("model") != P1_CALIBRATION_MODEL
            or summary.get("evaluation_protocol") != P1_PROTOCOL
            or summary.get("evaluator_version") != "outcome-vector-v1+g7-v5"
            or summary.get("remote_proto_runtime_sha256") != remote_proto_digest
            or summary.get("fort_gym_commit") != calibration_commit
            or summary.get("measurement_calibration_scenario") != scenario
            or not isinstance(summary.get("seed_attestation"), dict)
            or summary["seed_attestation"].get("eligible") is not True
        ):
            return False
        final = rows[-1]
        metrics = final.get("metrics") if isinstance(final.get("metrics"), dict) else {}
        final_state = final.get("state_after_advance")
        if not isinstance(final_state, dict):
            return False
        survival = (
            final_state.get("survival")
            if isinstance(final_state.get("survival"), dict)
            else {}
        )
        if scenario == "owned_layout_and_provisioning":
            output_by_job = metrics.get("governed_owned_output_units_by_job")
            structural = metrics.get("governed_owned_room_structural_evidence")
            owned_signatures = metrics.get("governed_owned_layout_room_signatures")
            gameplay = summary.get("gameplay_outcome")
            criteria = gameplay.get("criteria") if isinstance(gameplay, dict) else None
            if not (
                # An unrelated component can exceed the bounded exhaustive scan
                # after three owned rooms have each been observed with complete
                # local geometry, accessibility, and ownership evidence. Preserve
                # the honest exhaustive-scan flag, but bind positive calibration
                # to the directly proven lower bound just as the G7 gate does.
                metrics.get("governed_owned_layout_room_lower_bound_proven") is True
                and metrics.get("governed_owned_building_evidence_complete") is True
                and metrics.get("governed_owned_operational_farm_evidence_complete")
                is True
                and metrics.get("governed_owned_output_evidence_complete") is True
                and metrics.get(
                    "governed_owned_output_manager_orders_observed_complete"
                )
                is True
                and metrics.get("governed_owned_output_manager_orders_present") is False
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_accessible_layout_rooms")
                    )
                    or 0
                )
                >= 3
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_unique_construction_tiles")
                    )
                    or 0
                )
                >= 1
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_completed_beds")
                    )
                    or 0
                )
                >= 3
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_completed_farm_plots")
                    )
                    or 0
                )
                >= 1
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_operational_farm_plots")
                    )
                    or 0
                )
                >= 1
                and (
                    _strict_nonnegative_int(
                        metrics.get("governed_owned_completed_stills")
                    )
                    or 0
                )
                >= 1
                and isinstance(owned_signatures, list)
                and len(set(owned_signatures)) >= 3
                and isinstance(structural, dict)
                and all(
                    isinstance(structural.get(signature), dict)
                    and structural[signature].get("ownership_basis")
                    in {
                        "owned_excavation_majority",
                        "owned_construction_majority",
                        "owned_door_closure",
                    }
                    for signature in owned_signatures
                )
                and isinstance(output_by_job, dict)
                and (_strict_nonnegative_int(output_by_job.get("brew")) or 0) >= 1
                and metrics.get("governed_owned_output_attribution_scope")
                == "exact_order_job_completion_and_uncontaminated_positive_output_delta"
                and isinstance(criteria, dict)
                and all(
                    isinstance(criteria.get(name), dict)
                    and criteria[name].get("status") == "pass"
                    for name in (
                        "owned_operational_provisioning",
                        "owned_accessible_layout_rooms",
                        "initial_cohort_bed_capacity",
                    )
                )
            ):
                return False
        elif scenario == "death_cause_fallback":
            fixture = summary.get("measurement_calibration_fixture")
            fixture_events = [
                event.get("data")
                for row in rows
                for event in (
                    row.get("events") if isinstance(row.get("events"), list) else []
                )
                if isinstance(event, dict)
                and event.get("type") == "measurement_calibration_fixture"
                and isinstance(event.get("data"), dict)
            ]
            first_action = action_rows[0].get("action")
            if not (
                isinstance(fixture, dict)
                and fixture.get("ok") is True
                and fixture.get("fixture") == "dfhack_bounded_friendly_bloodloss"
                and fixture.get("target") == "citizen"
                and fixture.get("limit") == 1
                and fixture.get("method") == "blood_loss_next_tick"
                and isinstance(fixture.get("unit_id"), int)
                and isinstance(fixture.get("blood_before"), int)
                and _to_int(fixture.get("blood_before")) > 0
                and fixture.get("blood_after") == 0
                and len(fixture_events) == 1
                and all(
                    fixture_events[0].get(key) == value
                    for key, value in fixture.items()
                )
                and isinstance(first_action, dict)
                and first_action.get("type") == "WAIT"
                and _to_int(first_action.get("advance_ticks")) > 0
                and _to_int(survival.get("deaths_in_run")) >= 1
                and survival.get("death_evidence_complete") is True
                and survival.get("death_causes_known") is True
                and survival.get("measurement_calibration_mode")
                == "force_incident_death_cause"
                and _nested_mapping_has(
                    final_state,
                    "cause_source",
                    "world.incidents.all[death_id].death_cause",
                )
            ):
                return False
        else:
            sensor_field = item.get("sensor_field")
            evaluation_validity = summary.get("evaluation_validity")
            sensor_value = metrics.get(sensor_field, survival.get(sensor_field))
            fort = (
                final_state.get("fort")
                if isinstance(final_state.get("fort"), dict)
                else {}
            )
            fault = (
                fort.get("measurement_calibration_fault")
                if isinstance(fort.get("measurement_calibration_fault"), dict)
                else {}
            )
            if not (
                sensor_field == "governed_owned_room_evidence_complete"
                and sensor_value is False
                and fault
                == {
                    "sensor": "fort_metrics",
                    "field": "spaces_truncated",
                    "value": True,
                }
                and isinstance(evaluation_validity, dict)
                and evaluation_validity.get("status") == "unknown"
            ):
                return False
        verified_scenarios.add(scenario)
        verified_run_ids.add(run_id)
        verified_artifacts.update({artifact, summary_artifact})
    return verified_scenarios == required_scenarios


def _calibration_regression_report_is_bound(value: Any) -> bool:
    """Require the exhaustive edge-case suite, not reviewer-entered booleans."""

    if not isinstance(value, dict):
        return False
    relative_artifact = value.get("artifact")
    expected_hash = str(value.get("sha256") or "")
    if (
        not isinstance(relative_artifact, str)
        or not relative_artifact
        or Path(relative_artifact).is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
    ):
        return False
    artifact_root = P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT.resolve()
    artifact = (artifact_root / relative_artifact).resolve()
    if artifact_root not in artifact.parents:
        return False
    try:
        raw = artifact.read_bytes()
        root = ElementTree.fromstring(raw)
    except (OSError, ElementTree.ParseError):
        return False
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        return False
    passed: set[str] = set()
    for case in root.iter("testcase"):
        name = str(case.get("name") or "")
        if name not in P1_CALIBRATION_REQUIRED_REGRESSION_TESTS:
            continue
        if any(case.find(tag) is not None for tag in ("failure", "error", "skipped")):
            return False
        if name in passed:
            return False
        passed.add(name)
    return passed == P1_CALIBRATION_REQUIRED_REGRESSION_TESTS


def p1_measurement_calibration_is_complete() -> bool:
    """Require a pinned, reviewed live-DFHack calibration artifact to unlock v5."""

    expected = P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256
    if not P1_MEASUREMENT_CALIBRATION_COMPLETE or not expected:
        return False
    try:
        raw = P1_MEASUREMENT_CALIBRATION_EVIDENCE_PATH.read_bytes()
        evidence = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return False
    observed = hashlib.sha256(raw).hexdigest()
    live_traces = evidence.get("live_traces") if isinstance(evidence, dict) else None
    regression_report = (
        evidence.get("regression_report") if isinstance(evidence, dict) else None
    )
    remote_proto_digest = p1_remote_proto_runtime_digest()
    return bool(
        observed == expected
        and remote_proto_digest is not None
        and evidence.get("protocol") == P1_PROTOCOL
        and evidence.get("evaluator_version") == "outcome-vector-v1+g7-v5"
        and evidence.get("seed_world_sha256") == P1_SEED_WORLD_SHA256
        and evidence.get("manifest_semantic_sha256") == p1_manifest_semantic_digest()
        and evidence.get("measurement_code_sha256") == p1_measurement_code_digest()
        and evidence.get("remote_proto_runtime_sha256") == remote_proto_digest
        and re.fullmatch(
            r"[0-9a-f]{40}",
            str(evidence.get("calibration_fort_gym_commit") or ""),
        )
        and evidence.get("review_status") == "approved"
        and isinstance(evidence.get("reviewer"), str)
        and bool(evidence["reviewer"].strip())
        and _live_calibration_traces_are_bound(
            live_traces, str(evidence.get("calibration_fort_gym_commit") or "")
        )
        and _calibration_regression_report_is_bound(regression_report)
    )


def validate_p1_declaration(
    *,
    protocol: str | None,
    backend: str,
    model: str,
    seed_save: str | None,
    runtime_save: str | None,
    preserve_save: bool,
    max_steps: int,
    ticks_per_step: int,
    measurement_calibration_scenario: str | None = None,
) -> None:
    if measurement_calibration_scenario is not None and protocol != P1_PROTOCOL:
        raise ValueError(
            "measurement calibration scenarios require the Fort-Eval Easy P1 "
            "G7-v5 protocol"
        )
    if protocol in {P1_PROTOCOL_V3, P1_PROTOCOL_V4}:
        frozen_version = protocol.rsplit("g7-", 1)[-1]
        raise ValueError(
            f"Fort-Eval Easy P1 G7-{frozen_version} is frozen and "
            "no longer launchable; use G7-v5"
        )
    if protocol != P1_PROTOCOL:
        return
    mismatches = []
    if backend != "dfhack":
        mismatches.append("backend must be dfhack")
    if measurement_calibration_scenario is not None:
        if measurement_calibration_scenario not in P1_LIVE_CALIBRATION_SCENARIOS:
            mismatches.append("measurement calibration scenario is not declared")
        if model != P1_CALIBRATION_MODEL:
            mismatches.append(
                f"measurement calibration model must be {P1_CALIBRATION_MODEL}"
            )
    elif model not in MODEL_ARMS:
        mismatches.append("model is not a declared P1 arm")
    if seed_save != P1_SEED_SAVE:
        mismatches.append(f"seed_save must be {P1_SEED_SAVE}")
    if runtime_save != P1_RUNTIME_SAVE:
        mismatches.append(f"runtime_save must be {P1_RUNTIME_SAVE}")
    if preserve_save:
        mismatches.append("preserve_save must be false")
    if max_steps != P1_MAX_STEPS:
        mismatches.append(f"max_steps must be {P1_MAX_STEPS}")
    if ticks_per_step != P1_TICKS_PER_STEP:
        mismatches.append(f"ticks_per_step must be {P1_TICKS_PER_STEP}")
    if mismatches:
        raise ValueError(
            "invalid Fort-Eval Easy P1 declaration: " + "; ".join(mismatches)
        )
    if measurement_calibration_scenario is not None:
        # This is the only bootstrap path. It exercises the exact live DFHack
        # sensors with a deterministic, provider-free policy and remains
        # ineligible for publication. Normal model-arm launches stay locked.
        return
    if not p1_measurement_calibration_is_complete():
        raise ValueError(
            "Fort-Eval Easy P1 G7-v5 is calibration-only and cannot be launched "
            "until the owned-room and authoritative-death sensors pass live DFHack "
            "validation"
        )


def attest_seed_region3(
    state: Mapping[str, Any],
    *,
    runtime_save: str | None,
    seed_world_sha256: str | None = None,
) -> Dict[str, Any]:
    stocks = state.get("stocks") if isinstance(state.get("stocks"), Mapping) else {}
    work = state.get("work") if isinstance(state.get("work"), Mapping) else {}
    fort = state.get("fort") if isinstance(state.get("fort"), Mapping) else {}
    crew = state.get("crew") if isinstance(state.get("crew"), Mapping) else {}
    citizens = crew.get("citizens") if isinstance(crew.get("citizens"), Mapping) else {}
    survival = (
        state.get("survival") if isinstance(state.get("survival"), Mapping) else {}
    )
    nearby_trees = (
        fort.get("nearby_trees")
        if isinstance(fort.get("nearby_trees"), Mapping)
        else {}
    )
    seeds = crew.get("seeds") if isinstance(crew.get("seeds"), list) else None
    plump_counts = [
        _strict_nonnegative_int(seed.get("count"))
        for seed in seeds or []
        if isinstance(seed, Mapping) and seed.get("token") == "MUSHROOM_HELMET_PLUMP"
    ]
    plump_count = (
        sum(value for value in plump_counts if value is not None)
        if seeds is not None
        and plump_counts
        and all(value is not None for value in plump_counts)
        else None
    )
    tick = _strict_nonnegative_int(state.get("time"))
    population = _strict_nonnegative_int(state.get("population"))
    food = _strict_nonnegative_int(stocks.get("food"))
    drink = _strict_nonnegative_int(stocks.get("drink"))
    wealth = _strict_nonnegative_int(stocks.get("wealth"))
    dead = _strict_nonnegative_int(state.get("dead"))
    workshop_count = _strict_nonnegative_int(work.get("workshop_count"))
    farm_plots = _strict_nonnegative_int(crew.get("farm_plots"))
    structure_counts = [
        _strict_nonnegative_int(fort.get(key))
        for key in ("player_buildings", "constructions", "functional_rooms")
    ]
    nearby_tree_count = _strict_nonnegative_int(nearby_trees.get("total"))
    mining_labor = _strict_nonnegative_int(citizens.get("mining_labor"))
    woodcutting_labor = _strict_nonnegative_int(citizens.get("woodcutting_labor"))
    carpentry_labor = _strict_nonnegative_int(citizens.get("carpentry_labor"))
    food_produced = _strict_nonnegative_int(survival.get("food_produced_in_run"))
    drink_produced = _strict_nonnegative_int(survival.get("drink_produced_in_run"))
    deaths_in_run = _strict_nonnegative_int(survival.get("deaths_in_run"))
    checks = {
        "pristine_seed_digest": seed_world_sha256 == P1_SEED_WORLD_SHA256,
        "paused": state.get("pause_state") is True,
        "initial_tick": tick == 16801,
        "population": population == 7,
        "food": food == 45,
        "drink": drink == 60,
        "initial_wealth": wealth == 9,
        "no_deaths": dead == 0,
        "no_hostiles": state.get("hostiles") is False,
        "no_risks": isinstance(state.get("risks"), list) and state.get("risks") == [],
        "no_workshops": workshop_count == 0,
        "no_farm_plots": farm_plots == 0,
        "no_fort_structures": all(value == 0 for value in structure_counts),
        "nearby_timber": nearby_tree_count is not None and nearby_tree_count >= 200,
        "plump_helmet_spawn": plump_count is not None and plump_count >= 5,
        "miner_available": mining_labor is not None and mining_labor >= 1,
        "woodcutter_available": (
            woodcutting_labor is not None and woodcutting_labor >= 1
        ),
        "carpenter_available": carpentry_labor is not None and carpentry_labor >= 1,
        "clean_g7_ledger": (
            survival.get("active") is True
            and food_produced == 0
            and drink_produced == 0
            and deaths_in_run == 0
        ),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    return {
        "schema_version": "fort-eval.seed-attestation/v1",
        "seed_save": P1_SEED_SAVE,
        "runtime_save": runtime_save,
        "seed_world_sha256": seed_world_sha256,
        "eligible": not failed,
        "checks": checks,
        "failed_checks": failed,
        "observed": {
            "tick": tick,
            "population": population,
            "food": food,
            "drink": drink,
            "nearby_trees": nearby_tree_count,
            "plump_helmet_spawn": plump_count,
        },
    }


def p1_summary_metadata(
    *,
    model: str,
    fort_gym_commit: str | None,
    measurement_calibration_scenario: str | None = None,
) -> Dict[str, Any]:
    remote_proto_digest = p1_remote_proto_runtime_digest()
    if measurement_calibration_scenario is not None:
        if model != P1_CALIBRATION_MODEL:
            raise ValueError("measurement calibration requires the scripted model")
        return {
            "public_label": "Scripted live measurement calibration",
            "task_id": "g7_survival",
            "task_version": "g7-v5",
            "seed_split": "fixed_seed_pilot",
            "mechanics_digest": "df-51.11+governed-semantic-dfhack-v1",
            "observation_digest": (
                "governed_structured_state_v3_owned_layout+fort_minimap_vision_v1"
            ),
            "action_digest": "legal_semantic_dfhack_v1",
            "budget_digest": "max_steps_200_ticks_per_step_2500",
            "model_digest": "scripted:dfhack-governed-scripted|provider=none",
            "prompt_digest": "scripted-calibration-no-model-prompt",
            "memory_digest": "memory_off",
            "fort_gym_commit": fort_gym_commit or _current_git_commit(),
            "df_version": "df-51.11",
            "evaluator_version": "outcome-vector-v1+g7-v5",
            "remote_proto_runtime_sha256": remote_proto_digest,
            "measurement_calibration_scenario": measurement_calibration_scenario,
        }
    arm = MODEL_ARMS[model]
    model_digest = (
        f"openrouter:{arm['provider_model']}|reasoning=max|max_tokens=128000|"
        f"vision=on|memory=off|cache={arm['cache']}"
    )
    return {
        "public_label": arm["public_label"],
        "task_id": "g7_survival",
        "task_version": "g7-v5",
        "seed_split": "fixed_seed_pilot",
        "mechanics_digest": "df-51.11+governed-semantic-dfhack-v1",
        "observation_digest": "governed_structured_state_v3_owned_layout+fort_minimap_vision_v1",
        "action_digest": "legal_semantic_dfhack_v1",
        "budget_digest": "max_steps_200_ticks_per_step_2500",
        "model_digest": model_digest,
        "prompt_digest": prompt_digest(),
        "memory_digest": "memory_off",
        "fort_gym_commit": fort_gym_commit,
        "df_version": "df-51.11",
        "evaluator_version": "outcome-vector-v1+g7-v5",
        "remote_proto_runtime_sha256": remote_proto_digest,
    }


def resolved_model_digest(*, model: str, usage: Mapping[str, Any]) -> str:
    arm = MODEL_ARMS[model]
    resolved = ",".join(
        sorted(str(item) for item in usage.get("resolved_models") or [])
    )
    providers = ",".join(sorted(str(item) for item in usage.get("providers") or []))
    return (
        f"openrouter:{arm['provider_model']}|resolved={resolved or 'unavailable'}|"
        f"providers={providers or 'unavailable'}|reasoning=max|max_tokens=128000|"
        f"vision=on|memory=off|cache={arm['cache']}"
    )


def p1_usage_is_publishable(*, model: str, usage: Mapping[str, Any]) -> bool:
    arm = MODEL_ARMS[model]
    resolved_models = list(usage.get("resolved_models") or [])
    generation_ids = list(usage.get("generation_ids") or [])
    calls = _to_int(usage.get("calls"))
    generations = list(usage.get("generation_metadata") or [])
    return bool(
        calls > 0
        and list(usage.get("models") or []) == [arm["provider_model"]]
        and resolved_models
        and all(
            str(resolved).startswith(arm["resolved_model_prefix"])
            for resolved in resolved_models
        )
        and list(usage.get("providers") or [])
        and len(generation_ids) == calls
        and len(generations) == calls
        and all(
            str(generation.get("model") or "").startswith(arm["resolved_model_prefix"])
            for generation in generations
        )
        and _to_int(usage.get("calls_missing_cost")) == 0
        and _to_int(usage.get("calls_missing_resolved_model")) == 0
        and usage.get("generation_telemetry_complete") is True
    )


def p1_evaluation_is_publishable(
    *,
    evaluation_validity: Mapping[str, Any],
    provenance_completeness: Mapping[str, Any],
) -> bool:
    """Require valid, complete evidence while still allowing gameplay failures."""

    return bool(
        evaluation_validity.get("status") == "pass"
        and provenance_completeness.get("status") == "pass"
    )


def p1_task_verdict(
    *, gameplay_outcome: Mapping[str, Any], terminal_class: str | None
) -> str:
    """Return the gameplay verdict while preserving valid task failures."""

    if terminal_class == "task_failure":
        return "fail"
    status = str(gameplay_outcome.get("status") or "unknown")
    return status if status in {"pass", "fail", "unknown"} else "unknown"


def p1_integrity_attestation(
    terminal_failure_reason: Mapping[str, Any] | None,
    *,
    run_failed: bool,
) -> Dict[str, Any]:
    """Separate valid model/task terminal outcomes from invalid execution."""

    valid_task_terminal_codes = {
        "provider_content_filter",
        "governed_decision_error",
        "governed_review_contract_exhausted",
        "interaction_unchanged_screen_loop",
        "interaction_budget_exhausted",
    }
    terminal_code = str((terminal_failure_reason or {}).get("code") or "")
    task_failure = terminal_code in valid_task_terminal_codes
    valid = (terminal_failure_reason is None and not run_failed) or task_failure
    failure_reason = terminal_failure_reason
    if failure_reason is None and run_failed:
        failure_reason = {"code": "run_aborted_without_terminal_reason"}
    return {
        "schema_version": "fort-eval.integrity-attestation/v1",
        "status": "pass" if valid else "fail",
        "terminal_class": (
            "task_failure"
            if task_failure
            else "completed"
            if valid
            else "invalid_execution"
        ),
        "terminal_reason": (
            dict(failure_reason) if failure_reason is not None else None
        ),
    }


def enrich_openrouter_usage(
    usage: Mapping[str, Any],
    *,
    api_key: str | None,
    base_url: str,
) -> Dict[str, Any]:
    """Resolve provider accounting after a run, when generation rows are durable."""

    enriched = dict(usage)
    generation_ids = list(usage.get("generation_ids") or [])
    if not api_key:
        enriched["generation_telemetry_complete"] = False
        enriched["generation_telemetry_error"] = "OPENROUTER_API_KEY unavailable"
        return enriched
    httpx = import_module("httpx")
    retry_delays = (1.0, 2.0, 4.0, 8.0)
    pending = set(generation_ids)
    generation_records: Dict[str, Dict[str, Any]] = {}
    generation_errors: Dict[str, Exception] = {}
    lookup_attempts: Dict[str, int] = {
        str(generation_id): 0 for generation_id in generation_ids
    }
    for round_index in range(len(retry_delays) + 1):
        for generation_id in list(pending):
            lookup_attempts[generation_id] += 1
            try:
                response = httpx.get(
                    f"{base_url.rstrip('/')}/generation",
                    params={"id": generation_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                response.raise_for_status()
                body = response.json()
                data = body.get("data") if isinstance(body, dict) else None
                if not isinstance(data, dict):
                    raise ValueError("invalid generation payload")
                generation_records[generation_id] = {
                    "id": generation_id,
                    "model": data.get("model"),
                    "provider_name": data.get("provider_name") or data.get("provider"),
                    "total_cost": data.get("total_cost"),
                    "cache_discount": data.get("cache_discount"),
                    "native_tokens_prompt": data.get("native_tokens_prompt"),
                    "native_tokens_completion": data.get("native_tokens_completion"),
                    "status": "available",
                    "lookup_attempts": lookup_attempts[generation_id],
                }
                pending.remove(generation_id)
                generation_errors.pop(generation_id, None)
            except Exception as exc:
                generation_errors[generation_id] = exc
        if pending and round_index < len(retry_delays):
            time.sleep(retry_delays[round_index])

    generations = []
    for generation_id in generation_ids:
        record = generation_records.get(generation_id)
        if record is not None:
            generations.append(record)
            continue
        lookup_error = generation_errors.get(generation_id)
        if lookup_error is None:
            lookup_error = RuntimeError("generation lookup was not attempted")
        generations.append(
            {
                "id": generation_id,
                "status": "unavailable",
                "reason": type(lookup_error).__name__,
                "message": str(lookup_error)[:240],
                "lookup_attempts": lookup_attempts.get(generation_id, 0),
            }
        )
    available = [
        item
        for item in generations
        if item["status"] == "available"
        and item.get("model")
        and item.get("provider_name")
        and item.get("total_cost") is not None
        and item.get("native_tokens_prompt") is not None
        and item.get("native_tokens_completion") is not None
    ]
    enriched["generation_metadata"] = generations
    enriched["resolved_models"] = sorted(
        {str(item["model"]) for item in available if item.get("model")}
    )
    enriched["providers"] = sorted(
        {str(item["provider_name"]) for item in available if item.get("provider_name")}
    )
    enriched["calls_missing_cost"] = sum(
        item.get("status") != "available" or item.get("total_cost") is None
        for item in generations
    )
    enriched["calls_missing_resolved_model"] = sum(
        item.get("status") != "available" or not item.get("model")
        for item in generations
    )
    enriched["provider_total_cost_usd"] = round(
        sum(float(item.get("total_cost") or 0.0) for item in available), 8
    )
    enriched["provider_cache_discount_usd"] = round(
        sum(float(item.get("cache_discount") or 0.0) for item in available), 8
    )
    enriched["generation_telemetry_complete"] = (
        len(available) == len(generation_ids) == _to_int(usage.get("calls"))
    )
    enriched["generation_telemetry_unavailable"] = len(generations) - len(available)
    return enriched


__all__ = [
    "MODEL_ARMS",
    "P1_CALIBRATION_MODEL",
    "P1_CALIBRATION_REQUIRED_REGRESSION_TESTS",
    "P1_LIVE_CALIBRATION_SCENARIOS",
    "P1_MAX_STEPS",
    "P1_MEASUREMENT_CALIBRATION_COMPLETE",
    "P1_MEASUREMENT_CALIBRATION_ARTIFACT_ROOT",
    "P1_MEASUREMENT_CALIBRATION_EVIDENCE_PATH",
    "P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256",
    "P1_MEASUREMENT_CODE_RELATIVE_PATHS",
    "P1_PROTOCOL",
    "P1_PROTOCOL_V3",
    "P1_PROTOCOL_V4",
    "P1_RUNTIME_SAVE",
    "P1_SEED_SAVE",
    "P1_SEED_WORLD_SHA256",
    "P1_TICKS_PER_STEP",
    "attest_seed_region3",
    "enrich_openrouter_usage",
    "p1_evaluation_is_publishable",
    "p1_integrity_attestation",
    "p1_measurement_calibration_is_complete",
    "p1_measurement_code_digest",
    "p1_remote_proto_runtime_digest",
    "p1_manifest_semantic_digest",
    "p1_summary_metadata",
    "p1_task_verdict",
    "p1_usage_is_publishable",
    "prompt_digest",
    "resolved_model_digest",
    "validate_p1_declaration",
]
