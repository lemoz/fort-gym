"""Read a retained development probe without launching a game or provider call.

Worker return, model validity, native time, and teardown are independent facts.
Never copy legacy summary defaults into a campaign population or collapse claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from fort_gym.bench.eval.campaign import TICKS_PER_YEAR, campaign_progress


def native_clock(value: dict[str, Any]) -> int | None:
    year, tick = value.get("year"), value.get("year_tick")
    if type(year) is not int or year < 0 or type(tick) is not int:
        return None
    if not 0 <= tick < TICKS_PER_YEAR:
        return None
    return year * TICKS_PER_YEAR + tick


def assess_probe(
    experiment: dict[str, Any], runtime: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Describe evidence, not a model ranking or autonomous-success verdict."""
    run_id = experiment["run_id"]
    if any(row.get("run_id") != run_id for row in rows):
        raise ValueError("Trace identity does not match the experiment")
    terminals = [row["terminal_reason"] for row in rows if row.get("terminal_reason")]
    terminal = terminals[-1] if terminals else {}
    code = terminal.get("code")
    if code == "governed_review_contract_exhausted":
        outcome = "model_action_contract_failure"
    elif code == "budget_cap_exceeded":
        outcome = "budget_limited_pause"
    elif isinstance(code, str) and code.startswith("provider_"):
        outcome = "provider_failure"
    elif terminal or experiment.get("status") == "failed":
        outcome = "unclassified_failure"
    elif experiment.get("status") == "returned" and rows:
        outcome = "bounded_probe_returned"
    else:
        outcome = "incomplete"

    start = experiment.get("native_start") or {}
    end = experiment.get("native_final") or {}
    start_clock, end_clock = native_clock(start), native_clock(end)
    delta = None
    if (
        start_clock is not None
        and end_clock is not None
        and end_clock >= start_clock
        and start.get("save_name")
        and start.get("save_name") == end.get("save_name")
    ):
        delta = end_clock - start_clock
    populations = []
    for row in rows:
        observation = row.get("observation") or {}
        population = observation.get("population")
        if type(population) is int and population >= 0:
            populations.append(population)
    usage = experiment.get("usage") or {}
    dispatches, responses = experiment.get("dispatches"), usage.get("returned_responses")
    unreturned = None
    if type(dispatches) is int and type(responses) is int and 0 <= responses <= dispatches:
        unreturned = dispatches - responses
    return {
        "schema_version": "fortgym.development-probe-assessment/v1",
        "run_id": run_id,
        "model": experiment.get("model"),
        "phase": "development",
        "outcome": outcome,
        "terminal_code": code,
        "trace_rows": len(rows),
        "action_rows": sum(isinstance(row.get("action"), dict) for row in rows),
        "native_elapsed_ticks": delta,
        "trace_progress": campaign_progress(rows),
        "first_observed_population": populations[0] if populations else None,
        "last_observed_population": populations[-1] if populations else None,
        "fortress_collapse": "not_assessed",
        "functioning_fortress": "not_assessed",
        "autonomous_year_two": "not_assessed",
        "dispatches": dispatches,
        "returned_responses": responses,
        "dispatches_without_returned_usage": unreturned,
        "reported_model_cost_usd": usage.get("total_cost_usd"),
        "billing_reconciled": False,
        "cleanup_verified": runtime.get("cleanup_verified"),
        "campaign_recovery_verified": experiment.get("campaign_recovery_verified"),
        "limits": [
            "Native boundary time is distinct from complete per-action tick evidence.",
            "An action row does not prove command acceptance or a useful gameplay effect.",
            "Unreturned dispatches are not assumed free or billed; reconcile provider billing.",
            "Development probes do not support model rankings or year-two success claims.",
        ],
    }


def report_probe(root: Path) -> dict[str, Any]:
    experiment_path, runtime_path = root / "experiment.json", root / "result.json"
    experiment = json.loads(experiment_path.read_text())
    run_id = experiment["run_id"]
    if not isinstance(run_id, str) or run_id != root.name:
        raise ValueError("Experiment identity must match its artifact directory")
    trace_path = root / "segments" / run_id / "trace.jsonl"
    rows = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    result = assess_probe(experiment, json.loads(runtime_path.read_text()), rows)
    result["source_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (experiment_path, runtime_path, trace_path)
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(report_probe(args.artifact_directory), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
