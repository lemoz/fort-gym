#!/usr/bin/env python3
"""Summarize a private M1a evidence tree without mutating raw artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def strip_runtime_identity(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_runtime_identity(item)
            for key, item in value.items()
            if key not in {"run_id", "elapsed_ms"}
        }
    if isinstance(value, list):
        return [strip_runtime_identity(item) for item in value]
    return value


def differing_paths(left: Any, right: Any, prefix: str = "", depth: int = 2) -> list[str]:
    if left == right:
        return []
    if depth > 0 and isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(differing_paths(left[key], right[key], child, depth - 1))
        return paths
    return [prefix or "$"]


def numeric_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "min": None,
            "median": None,
            "mean": None,
            "sample_sd": None,
            "max": None,
        }
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
        "max": max(values),
    }


def mib(value: str) -> float:
    number = float(value[:-3])
    unit = value[-3:]
    if unit == "KiB":
        return number / 1024
    if unit == "MiB":
        return number
    if unit == "GiB":
        return number * 1024
    raise ValueError(f"unsupported memory unit: {unit}")


def load_runs(root: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(root.rglob("run-summary.json")):
        record = json.loads(path.read_text())
        relative = path.relative_to(root)
        parts = relative.parts
        record["batch_id"] = parts[0] if len(parts) > 0 else None
        record["cohort"] = parts[1] if len(parts) > 1 else None
        record["attempt"] = parts[2] if len(parts) > 2 else None
        record["relative_path"] = relative.as_posix()
        record["run_summary_sha256"] = sha256_file(path)
        container_dir = path.parent / "container"
        seed_manifest = container_dir / "seed_tree.manifest.sha256"
        seed_world = container_dir / "seed_world.sha256"
        entrypoint_attestation = container_dir / "entrypoint_attestation.json"
        runtime_readiness = container_dir / "runtime_readiness.json"
        if seed_manifest.is_file():
            record["seed_tree_manifest_sha256"] = seed_manifest.read_text().split()[0]
        if seed_world.is_file():
            record["seed_world_sha256"] = seed_world.read_text().split()[0]
        if entrypoint_attestation.is_file():
            record["entrypoint_attestation"] = json.loads(
                entrypoint_attestation.read_text()
            )
        if runtime_readiness.is_file():
            record["runtime_readiness"] = json.loads(runtime_readiness.read_text())
        trace_paths = sorted(path.parent.glob("harness/*/trace.jsonl"))
        if len(trace_paths) == 1:
            trace_path = trace_paths[0]
            trace = [
                json.loads(line)
                for line in trace_path.read_text().splitlines()
                if line.strip()
            ]
            normalized_trace = [
                strip_runtime_identity(
                    {
                        "step": row.get("step"),
                        "action": row.get("action"),
                        "tick_advance": row.get("tick_advance"),
                        "state_after_advance": row.get("state_after_advance"),
                    }
                )
                for row in trace
            ]
            record["step_zero_state_sha256"] = canonical_sha256(
                strip_runtime_identity(trace[0].get("observation"))
            )
            record["terminal_state_sha256"] = canonical_sha256(
                strip_runtime_identity(trace[-1].get("state_after_advance"))
            )
            record["normalized_trace_sha256"] = canonical_sha256(normalized_trace)
            record["_normalized_trace"] = normalized_trace
            record["normalized_step_sha256"] = [
                canonical_sha256(row) for row in normalized_trace
            ]
            record["tick_overshoot"] = sum(
                int(row.get("tick_advance", {}).get("ticks_advanced", 0))
                - int(row.get("tick_advance", {}).get("requested", 0))
                for row in trace
            )
            record["raw_trace_sha256"] = sha256_file(trace_path)
        runs.append(record)
    return runs


def cohort_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    ticks_per_second = [float(item["ticks_per_second"]) for item in records]
    ticks_advanced = [float(item["ticks_advanced"]) for item in records]
    tick_overshoot = [
        float(item["tick_overshoot"])
        for item in records
        if "tick_overshoot" in item
    ]
    divergences: list[dict[str, Any]] = []
    if records and "normalized_step_sha256" in records[0]:
        reference = records[0]["normalized_step_sha256"]
        reference_trace = records[0]["_normalized_trace"]
        for item in records[1:]:
            observed = item.get("normalized_step_sha256", [])
            first = next(
                (
                    index
                    for index, (left, right) in enumerate(zip(reference, observed))
                    if left != right
                ),
                None,
            )
            if first is None and len(reference) != len(observed):
                first = min(len(reference), len(observed))
            divergences.append(
                {
                    "attempt": item.get("attempt"),
                    "first_divergent_step": first,
                    "first_divergent_paths": (
                        differing_paths(
                            reference_trace[first],
                            item["_normalized_trace"][first],
                        )[:30]
                        if first is not None
                        and first < len(reference_trace)
                        and first < len(item.get("_normalized_trace", []))
                        else []
                    ),
                }
            )
    return {
        "accepted_runs": len(records),
        "ticks_per_second": numeric_stats(ticks_per_second),
        "ticks_advanced": numeric_stats(ticks_advanced),
        "tick_overshoot": numeric_stats(tick_overshoot),
        "provider_calls_total": sum(int(item["provider_calls"]) for item in records),
        "provider_cost_usd_total": sum(
            float(item["provider_cost_usd"]) for item in records
        ),
        "seed_tree_manifest_sha256": sorted(
            {
                str(item["seed_tree_manifest_sha256"])
                for item in records
                if "seed_tree_manifest_sha256" in item
            }
        ),
        "seed_world_sha256": sorted(
            {
                str(item["seed_world_sha256"])
                for item in records
                if "seed_world_sha256" in item
            }
        ),
        "seed_copy_equal_count": sum(
            item.get("entrypoint_attestation", {}).get("seed_copy_equal") is True
            for item in records
        ),
        "runtime_ready_count": sum(
            item.get("runtime_readiness", {}).get("rpc_ready") is True
            and item.get("runtime_readiness", {}).get("map_ready") is True
            for item in records
        ),
        "provider_credentials_absent_count": sum(
            item.get("entrypoint_attestation", {}).get("provider_credentials")
            is False
            for item in records
        ),
        "unique_action_sequence_sha256": sorted(
            {str(item["action_sequence_sha256"]) for item in records}
        ),
        "unique_step_zero_state_sha256": sorted(
            {
                str(item["step_zero_state_sha256"])
                for item in records
                if "step_zero_state_sha256" in item
            }
        ),
        "unique_terminal_state_sha256": sorted(
            {
                str(item["terminal_state_sha256"])
                for item in records
                if "terminal_state_sha256" in item
            }
        ),
        "unique_normalized_trace_sha256": sorted(
            {
                str(item["normalized_trace_sha256"])
                for item in records
                if "normalized_trace_sha256" in item
            }
        ),
        "first_divergence_from_first_run": divergences,
        "runs": [
            {
                "attempt": item["attempt"],
                "run_id": item["run_id"],
                "ticks_advanced": item["ticks_advanced"],
                "tick_elapsed_ms": item["tick_elapsed_ms"],
                "ticks_per_second": item["ticks_per_second"],
                "provider_calls": item["provider_calls"],
                "provider_cost_usd": item["provider_cost_usd"],
                "seed_tree_manifest_sha256": item.get(
                    "seed_tree_manifest_sha256"
                ),
                "seed_world_sha256": item.get("seed_world_sha256"),
                "dfhack_port": item.get("entrypoint_attestation", {}).get(
                    "dfhack_port"
                ),
                "seed_copy_equal": item.get("entrypoint_attestation", {}).get(
                    "seed_copy_equal"
                ),
                "rpc_ready": item.get("runtime_readiness", {}).get("rpc_ready"),
                "map_ready": item.get("runtime_readiness", {}).get("map_ready"),
                "action_sequence_sha256": item["action_sequence_sha256"],
                "step_zero_state_sha256": item.get("step_zero_state_sha256"),
                "terminal_state_sha256": item.get("terminal_state_sha256"),
                "normalized_trace_sha256": item.get("normalized_trace_sha256"),
                "tick_overshoot": item.get("tick_overshoot"),
                "raw_trace_sha256": item.get("raw_trace_sha256"),
                "run_summary_sha256": item["run_summary_sha256"],
                "relative_path": item["relative_path"],
            }
            for item in records
        ],
    }


def cohort_resource_summaries(root: Path) -> dict[str, dict[str, Any]]:
    cohorts: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("resource-samples.txt")):
        relative = path.relative_to(root)
        key = "/".join(relative.parts[:2])
        result = {
            "peak_container_cpu_percent": 0.0,
            "peak_container_memory_mib": 0.0,
            "peak_df_process_cpu_percent": 0.0,
            "peak_df_process_rss_mib": 0.0,
            "peak_harness_process_cpu_percent": 0.0,
            "peak_harness_process_rss_mib": 0.0,
            "peak_container_writable_layer_bytes": 0,
        }
        for line in path.read_text(errors="replace").splitlines():
            fields = line.split("\t")
            if line.startswith("fortgym-m1a-") and len(fields) >= 3:
                try:
                    result["peak_container_cpu_percent"] = max(
                        result["peak_container_cpu_percent"],
                        float(fields[1].rstrip("%")),
                    )
                except ValueError:
                    pass
                usage = fields[2].split(" / ", maxsplit=1)[0]
                try:
                    result["peak_container_memory_mib"] = max(
                        result["peak_container_memory_mib"], mib(usage)
                    )
                except (ValueError, IndexError):
                    pass
            if line.rstrip().endswith("./libs/Dwarf_Fortress"):
                fields = line.split()
                if len(fields) >= 4:
                    try:
                        result["peak_df_process_cpu_percent"] = max(
                            result["peak_df_process_cpu_percent"], float(fields[2])
                        )
                        result["peak_df_process_rss_mib"] = max(
                            result["peak_df_process_rss_mib"], int(fields[3]) / 1024
                        )
                    except ValueError:
                        pass
            if "/venv/bin/fort-gym experiment" in line:
                fields = line.split(maxsplit=6)
                if len(fields) >= 4:
                    try:
                        result["peak_harness_process_cpu_percent"] = max(
                            result["peak_harness_process_cpu_percent"],
                            float(fields[2]),
                        )
                        result["peak_harness_process_rss_mib"] = max(
                            result["peak_harness_process_rss_mib"],
                            int(fields[3]) / 1024,
                        )
                    except ValueError:
                        pass
        for inspect_path in path.parent.glob("*/container-inspect.after.json"):
            try:
                inspect = json.loads(inspect_path.read_text())[0]
                result["peak_container_writable_layer_bytes"] = max(
                    result["peak_container_writable_layer_bytes"],
                    int(inspect.get("SizeRw") or 0),
                )
            except (IndexError, TypeError, ValueError, json.JSONDecodeError):
                pass
        cohorts[key] = result
    return cohorts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    root = args.evidence_root.resolve()
    runs = load_runs(root)
    by_cohort: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = f"{run['batch_id']}/{run['cohort']}"
        by_cohort.setdefault(key, []).append(run)

    cohorts = {
        key: cohort_summary(records)
        for key, records in sorted(by_cohort.items())
    }
    baseline_candidates = sorted(
        key for key in cohorts if key.endswith("/matrix-n1")
    )
    baseline_key = baseline_candidates[-1] if baseline_candidates else None
    baseline = (
        cohorts[baseline_key]["ticks_per_second"]["mean"]
        if baseline_key is not None
        else None
    )
    for cohort in cohorts.values():
        minimum = cohort["ticks_per_second"]["min"]
        cohort["minimum_ticks_per_second_gate_89_1"] = bool(
            minimum is not None and minimum >= 89.1
        )
        cohort["worst_degradation_from_n1_percent"] = (
            (baseline - minimum) / baseline * 100
            if baseline is not None and minimum is not None
            else None
        )

    e0_records = [run for run in runs if str(run["cohort"]).startswith("e0-a")]
    e0_replacement_records = [
        run
        for run in runs
        if str(run["cohort"]).startswith("e0-replacement-")
    ]
    primary_plan_paths = sorted(root.rglob("e0-attempt-plan.tsv"))
    primary_planned = 0
    for path in primary_plan_paths:
        primary_planned += max(len(path.read_text().splitlines()) - 1, 0)
    cohort_resources = cohort_resource_summaries(root)
    resource_values = list(cohort_resources.values())
    result = {
        "schema": "fortgym.environment-layer.m1a-summary/v1",
        "evidence_root": str(root),
        "run_summary_count": len(runs),
        "provider_calls_total": sum(int(run["provider_calls"]) for run in runs),
        "provider_cost_usd_total": sum(
            float(run["provider_cost_usd"]) for run in runs
        ),
        "n1_baseline_cohort": baseline_key,
        "n1_baseline_ticks_per_second": baseline,
        "cohorts": cohorts,
        "e0_attempt_accounting": {
            "primary_planned": primary_planned,
            "primary_accepted": len(e0_records),
            "primary_infrastructure_aborts": primary_planned - len(e0_records),
            "post_failure_engineering_replacements": len(e0_replacement_records),
        },
        "e0_conditional_replay_dispersion": cohort_summary(e0_records),
        "e0_engineering_with_replacement": cohort_summary(
            e0_records + e0_replacement_records
        ),
        "resources": {
            "sample_files": len(cohort_resources),
            "peak_container_cpu_percent": max(
                (item["peak_container_cpu_percent"] for item in resource_values),
                default=0.0,
            ),
            "peak_container_memory_mib": max(
                (item["peak_container_memory_mib"] for item in resource_values),
                default=0.0,
            ),
            "peak_df_process_cpu_percent": max(
                (item["peak_df_process_cpu_percent"] for item in resource_values),
                default=0.0,
            ),
            "peak_df_process_rss_mib": max(
                (item["peak_df_process_rss_mib"] for item in resource_values),
                default=0.0,
            ),
            "peak_harness_process_cpu_percent": max(
                (item["peak_harness_process_cpu_percent"] for item in resource_values),
                default=0.0,
            ),
            "peak_harness_process_rss_mib": max(
                (item["peak_harness_process_rss_mib"] for item in resource_values),
                default=0.0,
            ),
            "peak_container_writable_layer_bytes": max(
                (
                    item["peak_container_writable_layer_bytes"]
                    for item in resource_values
                ),
                default=0,
            ),
        },
        "cohort_resources": cohort_resources,
        "interpretation_limit": (
            "E0 is a same-seed, same-script, same-image, same-host conditional "
            "replay feasibility cohort. It does not estimate general world, "
            "seed, model, or provider variance."
        ),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
