#!/usr/bin/env python3
"""Offline v2-vs-v3 rescorer for recorded fort-gym runs.

Given an artifacts directory of recorded runs (each ``<run_id>/trace.jsonl``
+ ``<run_id>/summary.json``), this script reconstructs the baseline
(first-row) work/crew.goods/fort snapshot, replays every step's
``observation`` (``work``, ``crew.goods``, ``fort``, ``population``)
against that fixed baseline, and takes the running max across the whole
run -- exactly mirroring how ``summary.py`` aggregates the live per-step
metrics (``utility_progress = max(utility_progress, ...)`` each step). It
then recomputes the scalar composite score two ways:

* **v2** — calls the *same* ``fort_gym.bench.eval.metrics`` functions this
  branch ships, but with the v3 kwargs omitted (``population=None``, no
  ``current_fort``/``baseline_fort``). Those functions are built to fall
  back to the exact legacy (v2) computation in that case — see
  ``tests/test_score_v3.py`` for the tests that pin that contract — so this
  reuses one code path instead of hand-duplicating the v2 formulas.
* **v3** — calls the same functions with ``population`` and the fort dicts
  supplied, exercising the demand-capped-production / plan-agnostic-
  complexity formulas.

Design note on "other summary aggregates": ``RunSummary`` (see
``fort_gym/bench/eval/summary.py``) does NOT persist ``drink_availability``,
``casualty_spike``, or ``hostiles_present`` — those are internal-only
variables inside ``summarize()`` used to build the ephemeral scoring
payload, never written to ``summary.json``. That makes it impossible to
recompute ``availability_score`` (or the casualty/hostiles penalty) from
scratch from a recorded summary alone. Instead of guessing those inputs,
this script reuses the *already-recorded, already-correct* component scores
for everything utility/complexity do not touch (survival, population,
availability, wealth, work, completion, production) straight from
summary.json, and only recomputes ``utility_score``/``complexity_score``
fresh via ``scoring.score_components``. The casualty/hostiles penalty
amount is recovered exactly as the remainder:
``penalties = sum(recorded components) - recorded total_score`` (composite_score's
own definition), so no raw penalty inputs need to be reconstructed either.
This is more robust than trying to recompute every component from raw
aggregates -- it isolates exactly the two components v3 changes and holds
everything else fixed at its originally-recorded value.

Validation gate (mandatory): for every run recorded under score_version >= 2,
the v2-recomputed total must match the recorded total_score within +/-1.0.
If any run misses that tolerance the script prints a clear failure banner
and exits non-zero -- the v3 numbers should not be trusted until the
reconstruction gap is understood. v1-era runs (score_version == 1, or the
field missing entirely on old summaries) are reported but marked
non-validatable, per the ratified proposal.

Usage (see docs/score_v3_calibration.md for the exact VM invocation):

    python scripts/rescore_traces.py \\
        --artifacts-dir /opt/fort-gym/fort_gym/artifacts \\
        --output docs/score_v3_calibration.md \\
        24042365de5649acb1403f9e84fa6823 \\
        ad70df06f9c643169273c9384f90c623:chair_factory \\
        e57ff8e2:deepseek_exploit

Each RUN_ID may be a full id or an unambiguous prefix (resolved against the
artifacts directory's subdirectory names, e.g. the short ids called out in
the score-v3 proposal). An optional ``:label`` suffix sets the label shown
in the output table. Runs whose artifacts are missing (or whose prefix
does not resolve to exactly one directory) are skipped with a clear note
rather than failing the whole run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fort_gym.bench.eval import metrics, scoring  # noqa: E402

VALIDATION_TOLERANCE = 1.0
# score_version at/above which a recorded run is expected to be exactly
# reproducible by the v2 recomputation path (see scoring.py's SCORE_VERSION
# history comment for the 2026-07-03 v2 cutover).
MIN_VALIDATABLE_SCORE_VERSION = 2

RECORDED_COMPONENT_KEYS = (
    "survival_score",
    "population_score",
    "availability_score",
    "wealth_score",
    "work_score",
    "completion_score",
    "production_score",
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def resolve_run_dir(artifacts_dir: Path, run_id: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a run id (full or unambiguous prefix) to its artifacts dir.

    Returns (path, error). path is None if unresolved; error explains why.
    """

    exact = artifacts_dir / run_id
    if exact.is_dir():
        return exact, None
    if not artifacts_dir.is_dir():
        return None, f"artifacts dir not found: {artifacts_dir}"
    matches = [
        entry
        for entry in artifacts_dir.iterdir()
        if entry.is_dir() and entry.name.startswith(run_id)
    ]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, "no artifacts directory matches this id/prefix"
    return None, f"prefix ambiguous, {len(matches)} matches: " + ", ".join(
        m.name for m in matches
    )


def load_trace(run_dir: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    trace_path = run_dir / "trace.jsonl"
    if not trace_path.exists():
        return None, f"missing {trace_path.name}"
    records: List[Dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        return None, "trace.jsonl has no parseable records"
    return records, None


def load_summary(run_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return None, f"missing {summary_path.name}"
    try:
        return json.loads(summary_path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"summary.json is not valid JSON: {exc}"


def _goods(observation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    crew = observation.get("crew")
    if isinstance(crew, dict) and isinstance(crew.get("goods"), dict):
        return crew["goods"]
    return None


def reconstruct_inputs(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pull the baseline (first row) work/crew.goods/fort snapshot, plus the
    full per-step sequence of work/crew.goods/fort/population snapshots,
    straight from each trace record's ``observation`` -- ``encode_observation``
    passes the raw state through unfiltered (see ``redact_noise`` in
    fort_gym/bench/env/encoder.py), so ``record["observation"]`` is exactly
    the ``state_before`` the live runner fed to ``metrics.py`` at that step.

    NOTE: this recomputes a *running max* across every step, not just a
    first-vs-last endpoint diff. That matters because the runner's own
    ``summary.py`` aggregation is itself a running max of each step's
    delta-from-baseline (`utility_progress = max(utility_progress,
    metrics_snapshot["utility_progress"])`, ditto complexity_progress) --
    and those per-step deltas are not always monotonic (e.g. legacy
    `fortress_complexity_wall_tiles` can rise and fall as walls get dug
    through/replaced across a long run). A first-vs-last diff can land
    below a peak reached mid-run and understate the recorded metric --
    empirically, on real dfhack-governed runs, endpoint-only reconstruction
    missed the recorded complexity_progress on 6 of 9 v2-era runs checked
    during this rescorer's own validation. Replaying every step and taking
    the running max, exactly mirroring summary.py's own aggregation, closes
    that gap.
    """

    baseline_obs = records[0].get("observation") or {}
    baseline_work = baseline_obs.get("work") if isinstance(baseline_obs.get("work"), dict) else {}
    baseline_goods = _goods(baseline_obs)
    baseline_fort = baseline_obs.get("fort")
    steps = []
    for record in records:
        obs = record.get("observation") or {}
        steps.append(
            {
                "work": obs.get("work") if isinstance(obs.get("work"), dict) else {},
                "goods": _goods(obs),
                "fort": obs.get("fort") if isinstance(obs.get("fort"), dict) else None,
                "population": obs.get("population"),
            }
        )
    return {
        "baseline_work": baseline_work,
        "baseline_goods": baseline_goods,
        "baseline_fort": baseline_fort if isinstance(baseline_fort, dict) else None,
        "steps": steps,
    }


def recompute_progress(inputs: Dict[str, Any]) -> Dict[str, float]:
    """Recompute utility_progress/complexity_progress under v2 (legacy,
    population/fort kwargs omitted) and v3 (kwargs supplied) semantics, by
    replaying every trace step against the fixed run baseline and taking
    the running max -- exactly mirroring how summary.py aggregates the live
    per-step metrics. Reuses the same metrics.py functions this branch
    ships for both versions; v2 is simply v3's functions called without the
    new kwargs, which is the documented backward-compatible fallback (see
    tests/test_score_v3.py)."""

    utility_progress_v2 = 0.0
    utility_progress_v3 = 0.0
    complexity_progress_v2 = 0.0
    complexity_progress_v3 = 0.0
    produced_goods_delta = 0
    demand_capped_production_v3 = 0.0
    fort_available = False

    baseline_work = inputs["baseline_work"]
    baseline_goods = inputs["baseline_goods"]
    baseline_fort = inputs["baseline_fort"]

    for step in inputs["steps"]:
        utility_v2 = metrics.utility_progress_delta(
            step["work"],
            baseline_work,
            current_goods=step["goods"],
            baseline_goods=baseline_goods,
        )
        utility_v3 = metrics.utility_progress_delta(
            step["work"],
            baseline_work,
            current_goods=step["goods"],
            baseline_goods=baseline_goods,
            population=step["population"],
        )
        complexity_v2 = metrics.complexity_progress_delta(step["work"], baseline_work)
        complexity_v3 = metrics.complexity_progress_delta(
            step["work"],
            baseline_work,
            current_fort=step["fort"],
            baseline_fort=baseline_fort,
        )

        utility_progress_v2 = max(utility_progress_v2, _to_float(utility_v2["utility_progress"]))
        utility_progress_v3 = max(utility_progress_v3, _to_float(utility_v3["utility_progress"]))
        complexity_progress_v2 = max(
            complexity_progress_v2, _to_float(complexity_v2["complexity_progress"])
        )
        complexity_progress_v3 = max(
            complexity_progress_v3, _to_float(complexity_v3["complexity_progress"])
        )
        produced_goods_delta = max(produced_goods_delta, utility_v2["produced_goods_delta"])
        demand_capped_production_v3 = max(
            demand_capped_production_v3, _to_float(utility_v3.get("demand_capped_production"))
        )
        fort_available = fort_available or "complexity_rooms_delta" in complexity_v3

    return {
        "utility_progress_v2": utility_progress_v2,
        "utility_progress_v3": utility_progress_v3,
        "complexity_progress_v2": complexity_progress_v2,
        "complexity_progress_v3": complexity_progress_v3,
        "produced_goods_delta": produced_goods_delta,
        "demand_capped_production_v3": demand_capped_production_v3,
        "fort_available": fort_available,
    }


def recompute_total(
    recorded_summary: Dict[str, Any],
    utility_progress: float,
    complexity_progress: float,
    penalties: float,
) -> Tuple[float, float, float]:
    """Recompute the composite total using recorded (unaffected) components
    plus freshly computed utility_score/complexity_score. Returns
    (total, utility_score, complexity_score)."""

    fresh = scoring.score_components(
        {"utility_progress": utility_progress, "complexity_progress": complexity_progress}
    )
    utility_score = fresh["utility_score"]
    complexity_score = fresh["complexity_score"]
    total = (
        sum(_to_float(recorded_summary.get(key)) for key in RECORDED_COMPONENT_KEYS)
        + utility_score
        + complexity_score
        - penalties
    )
    return round(total, 2), round(utility_score, 2), round(complexity_score, 2)


def score_run(run_id: str, label: str, run_dir: Path) -> Dict[str, Any]:
    row: Dict[str, Any] = {"run_id": run_id, "label": label, "dir": str(run_dir)}

    records, err = load_trace(run_dir)
    if err:
        row["status"] = f"SKIPPED ({err})"
        return row
    summary, err = load_summary(run_dir)
    if err:
        row["status"] = f"SKIPPED ({err})"
        return row

    recorded_total = _to_float(summary.get("total_score"))
    recorded_components_sum = sum(
        _to_float(summary.get(key)) for key in RECORDED_COMPONENT_KEYS
    ) + _to_float(summary.get("utility_score")) + _to_float(summary.get("complexity_score"))
    penalties = recorded_components_sum - recorded_total

    inputs = reconstruct_inputs(records)
    progress = recompute_progress(inputs)

    total_v2, utility_score_v2, complexity_score_v2 = recompute_total(
        summary, progress["utility_progress_v2"], progress["complexity_progress_v2"], penalties
    )
    total_v3, utility_score_v3, complexity_score_v3 = recompute_total(
        summary, progress["utility_progress_v3"], progress["complexity_progress_v3"], penalties
    )

    score_version = summary.get("score_version")
    validatable = isinstance(score_version, int) and score_version >= MIN_VALIDATABLE_SCORE_VERSION
    delta_v2 = round(total_v2 - recorded_total, 2)

    row.update(
        {
            "status": "ok",
            "steps": summary.get("steps"),
            "score_version": score_version,
            "recorded_total": round(recorded_total, 2),
            "total_v2": total_v2,
            "delta_v2": delta_v2,
            "total_v3": total_v3,
            "validatable": validatable,
            "validation_ok": (abs(delta_v2) <= VALIDATION_TOLERANCE) if validatable else None,
            "utility_progress_v2": progress["utility_progress_v2"],
            "utility_progress_v3": progress["utility_progress_v3"],
            "complexity_progress_v2": progress["complexity_progress_v2"],
            "complexity_progress_v3": progress["complexity_progress_v3"],
            "produced_goods_delta": progress["produced_goods_delta"],
            "demand_capped_production_v3": progress["demand_capped_production_v3"],
            "fort_available": progress["fort_available"],
            "utility_score_v2": utility_score_v2,
            "complexity_score_v2": complexity_score_v2,
            "utility_score_v3": utility_score_v3,
            "complexity_score_v3": complexity_score_v3,
        }
    )
    return row


def _rank(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    scored = [r for r in rows if r.get("status") == "ok"]
    ordered = sorted(scored, key=lambda r: r[key], reverse=True)
    return {r["run_id"]: idx + 1 for idx, r in enumerate(ordered)}


def render_markdown(rows: List[Dict[str, Any]]) -> str:
    rank_recorded = _rank(rows, "recorded_total")
    rank_v3 = _rank(rows, "total_v3")

    lines = [
        "# score-v3 calibration table",
        "",
        "Generated by `scripts/rescore_traces.py`. See docs/score_v3_proposal.md",
        "for the ratified proposal and the two forcing findings (legacy-rect",
        "complexity payments; chair-factory monoculture, run ad70df06).",
        "",
        "| Run ID | Label | Steps | Score ver | Recorded | v2-recomputed | "
        "|Δv2| | v3 | Rank shift (recorded→v3) | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        run_id = row["run_id"]
        label = row.get("label") or ""
        if row.get("status") != "ok":
            lines.append(
                f"| `{run_id}` | {label} | - | - | - | - | - | - | - | {row['status']} |"
            )
            continue
        r_recorded = rank_recorded.get(run_id)
        r_v3 = rank_v3.get(run_id)
        shift = "-" if r_recorded is None or r_v3 is None else str(r_recorded - r_v3)
        if not row["validatable"]:
            note = "v1/pre-v2-era (score_version=%r), non-validatable" % (row["score_version"],)
        elif row["validation_ok"]:
            note = "validation OK"
        else:
            note = "VALIDATION FAILED (|Δv2| > 1.0)"
        if not row["fort_available"]:
            note += "; fort data absent, complexity fell back to legacy"
        lines.append(
            f"| `{run_id}` | {label} | {row['steps']} | {row['score_version']} | "
            f"{row['recorded_total']} | {row['total_v2']} | {row['delta_v2']} | "
            f"{row['total_v3']} | {shift} | {note} |"
        )

    lines.append("")
    lines.append("## Per-run detail")
    lines.append("")
    for row in rows:
        if row.get("status") != "ok":
            continue
        lines.append(f"### `{row['run_id']}`" + (f" ({row['label']})" if row.get("label") else ""))
        lines.append("")
        lines.append(
            f"- utility_progress: v2={row['utility_progress_v2']}, "
            f"v3={row['utility_progress_v3']} "
            f"(produced_goods_delta={row['produced_goods_delta']}, "
            f"demand_capped_production_v3={row['demand_capped_production_v3']})"
        )
        lines.append(
            f"- complexity_progress: v2={row['complexity_progress_v2']}, "
            f"v3={row['complexity_progress_v3']} (fort data available: {row['fort_available']})"
        )
        lines.append(
            f"- utility_score: v2={row['utility_score_v2']}, v3={row['utility_score_v3']}; "
            f"complexity_score: v2={row['complexity_score_v2']}, v3={row['complexity_score_v3']}"
        )
        lines.append("")

    return "\n".join(lines)


def parse_run_arg(raw: str) -> Tuple[str, Optional[str]]:
    if ":" in raw:
        run_id, label = raw.split(":", 1)
        return run_id, label
    return raw, None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None, help="write markdown table here")
    parser.add_argument(
        "run_ids",
        nargs="+",
        help="run id (full or unambiguous prefix), optionally 'run_id:label'",
    )
    args = parser.parse_args(argv)

    rows: List[Dict[str, Any]] = []
    for raw in args.run_ids:
        run_id, label = parse_run_arg(raw)
        run_dir, err = resolve_run_dir(args.artifacts_dir, run_id)
        if err:
            rows.append({"run_id": run_id, "label": label or "", "status": f"SKIPPED ({err})"})
            continue
        resolved_id = run_dir.name
        rows.append(score_run(resolved_id, label or "", run_dir))

    markdown = render_markdown(rows)
    print(markdown)
    if args.output:
        args.output.write_text(markdown + "\n", encoding="utf-8")

    failures = [
        row
        for row in rows
        if row.get("status") == "ok" and row.get("validatable") and not row.get("validation_ok")
    ]
    if failures:
        print(
            "\nVALIDATION GATE FAILED for "
            f"{len(failures)} run(s): "
            + ", ".join(row["run_id"] for row in failures),
            file=sys.stderr,
        )
        print(
            "Reconstruction did not reproduce the recorded v2 score within "
            f"+/-{VALIDATION_TOLERANCE}. Do not trust the v3 numbers above "
            "until this gap is understood.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
