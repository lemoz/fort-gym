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

* **v2** — for utility/complexity, calls the *same*
  ``fort_gym.bench.eval.metrics`` functions this branch ships, but with the
  v3 kwargs omitted (``population=None``, no
  ``current_fort``/``baseline_fort``); those functions are built to fall
  back to the exact legacy (v2) computation in that case — see
  ``tests/test_score_v3.py`` for the tests that pin that contract. For
  production, the 2026-07-07 amendment changed the live function itself
  (usable-only payment, bounded scoring), so the TRUE v2 formulas are
  frozen inline (``_production_progress_v2`` / ``_production_score_v2``)
  and used for the validation column.
* **v3** — calls the live functions with ``population`` and the fort dicts
  supplied, exercising the demand-capped-production / plan-agnostic-
  complexity formulas, plus the amended usable-only bounded production.

Design note on "other summary aggregates": ``RunSummary`` (see
``fort_gym/bench/eval/summary.py``) does NOT persist ``drink_availability``,
``casualty_spike``, or ``hostiles_present`` — those are internal-only
variables inside ``summarize()`` used to build the ephemeral scoring
payload, never written to ``summary.json``. That makes it impossible to
recompute ``availability_score`` (or the casualty/hostiles penalty) from
scratch from a recorded summary alone. Instead of guessing those inputs,
this script reuses the *already-recorded, already-correct* component scores
for everything v3 does not touch (survival, population, availability,
wealth, work, completion) straight from summary.json, and recomputes
``utility_score``/``complexity_score``/``production_score`` fresh per
version. The casualty/hostiles penalty
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

# Components neither score-v3 change (nor the 2026-07-07 production
# amendment) touches: reused straight from the recorded summary for BOTH
# columns. utility/complexity/production are recomputed per version.
RECORDED_COMPONENT_KEYS = (
    "survival_score",
    "population_score",
    "availability_score",
    "wealth_score",
    "work_score",
    "completion_score",
)

# All recorded score components, used only to recover the casualty/hostiles
# penalty as the remainder vs the recorded total.
ALL_RECORDED_COMPONENT_KEYS = RECORDED_COMPONENT_KEYS + (
    "utility_score",
    "production_score",
    "complexity_score",
)

PRODUCTION_WORKSHOP_PROGRESS_V2 = 5


def _production_progress_v2(
    current_work: Dict[str, Any], baseline_work: Dict[str, Any]
) -> int:
    """TRUE score-v2 production formula, reimplemented inline.

    The v3 amendment (2026-07-07, operator-ratified) changed
    ``metrics.production_progress_delta`` to pay usable-workshop deltas
    only, so the live function no longer computes the v2 quantity. The
    validation column of this rescorer must reproduce recorded v2 scores
    with TRUE v2 formulas, so v2 production is frozen here exactly as it
    stood on origin/main before the amendment:
    ``max(usable_delta, task_jobs_delta) * 5`` — the very
    task-jobs-as-capacity payment the amendment removed (forcing evidence:
    ad70df06 production_score 320.0, 7f268bcc 420.0).
    """

    def _count(work: Dict[str, Any], key: str, fallback: str | None = None) -> int:
        value = work.get(key, work.get(fallback) if fallback else None)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    usable_delta = max(
        0,
        _count(current_work, "carpenter_workshops_usable", "carpenter_workshops")
        - _count(baseline_work, "carpenter_workshops_usable", "carpenter_workshops"),
    )
    task_jobs_delta = max(
        0,
        _count(current_work, "carpenter_workshop_task_jobs")
        - _count(baseline_work, "carpenter_workshop_task_jobs"),
    )
    return max(usable_delta, task_jobs_delta) * PRODUCTION_WORKSHOP_PROGRESS_V2


def _production_score_v2(production_progress: float) -> float:
    """TRUE score-v2 production scoring: open-ended _scaled_component.

    scoring.py now bounds production_score at its weight (the amendment),
    so the v2 scaling is frozen inline for the validation column.
    """

    if scoring.TARGET_PRODUCTION_PROGRESS <= 0:
        return 0.0
    return (
        max(0.0, production_progress)
        / scoring.TARGET_PRODUCTION_PROGRESS
        * scoring.PRODUCTION_WEIGHT
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
    full per-step sequence of work/crew.goods/fort/population snapshots.

    NOTE 1 -- running max, not an endpoint diff: this replays every step and
    takes the running max, exactly mirroring how summary.py aggregates the
    live per-step metrics (`utility_progress = max(utility_progress,
    metrics_snapshot["utility_progress"])`, ditto complexity_progress). Those
    per-step deltas are not always monotonic (e.g. legacy
    `fortress_complexity_wall_tiles` can rise and fall as walls get dug
    through/replaced across a long run), so a first-vs-last diff can land
    below a peak reached mid-run and understate the recorded metric --
    empirically, on real dfhack-governed runs, endpoint-only reconstruction
    missed the recorded complexity_progress on 6 of 9 v2-era calibration
    runs. Replaying every step closes that gap.

    NOTE 2 -- work vs. observation timing: the live runner
    (fort_gym/bench/run/runner.py) does NOT feed metrics.py a single
    consistent per-step snapshot. It calls
    ``metrics.utility_progress_delta(current_work, baseline_work,
    current_goods=current_goods, ..., population=advance_state.get(...))``
    where ``current_work``/``population`` come from ``advance_state`` (the
    state *after* that step's action + tick advance), while
    ``current_goods`` comes from ``state_before.get("crew")`` (captured at
    the *start* of that same step, before the action ran) -- crew/fort are
    only refreshed once per step via the (expensive) observe() call, not
    re-read after advancing. ``complexity_progress_delta``'s current_fort
    also reads from state_before (this branch's own fix -- advance_state
    never carries a "fort" key at all, see the comment at that call site in
    runner.py). Trace records store both: ``record["observation"]`` is
    exactly that step's ``state_before`` (``encode_observation`` passes the
    raw state through unfiltered -- see ``redact_noise`` in
    fort_gym/bench/env/encoder.py), and ``record["state_after_advance"]`` is
    that step's ``advance_state``. Reproducing the recorded utility_progress
    exactly requires pairing ``state_after_advance["work"]``/["population"]
    with ``observation["crew"]["goods"]``/["fort"] from the *same* record --
    mixing both from ``observation`` alone reproduced complexity_progress
    exactly but silently undercounted utility_progress by up to a few raw
    units on some runs (confirmed empirically against 4 of 9 v2-era
    calibration runs before this fix).
    """

    baseline_obs = records[0].get("observation") or {}
    baseline_work = baseline_obs.get("work") if isinstance(baseline_obs.get("work"), dict) else {}
    baseline_goods = _goods(baseline_obs)
    baseline_fort = baseline_obs.get("fort")
    steps = []
    for record in records:
        obs = record.get("observation") or {}
        after_advance = record.get("state_after_advance") or {}
        steps.append(
            {
                "work": (
                    after_advance.get("work")
                    if isinstance(after_advance.get("work"), dict)
                    else {}
                ),
                "goods": _goods(obs),
                "fort": obs.get("fort") if isinstance(obs.get("fort"), dict) else None,
                "population": after_advance.get("population", obs.get("population")),
            }
        )
    return {
        "baseline_work": baseline_work,
        "baseline_goods": baseline_goods,
        "baseline_fort": baseline_fort if isinstance(baseline_fort, dict) else None,
        "steps": steps,
    }


def recompute_progress(inputs: Dict[str, Any]) -> Dict[str, float]:
    """Recompute utility/complexity/production progress under v2 and v3
    semantics, by replaying every trace step against the fixed run baseline
    and taking the running max -- exactly mirroring how summary.py
    aggregates the live per-step metrics.

    Version paths: utility/complexity v2 reuse the same metrics.py
    functions this branch ships, called without the new kwargs (the
    documented backward-compatible fallback, see tests/test_score_v3.py).
    Production v2 CANNOT reuse the live function -- the 2026-07-07
    amendment changed it to usable-only payment -- so the TRUE v2 formula
    is frozen inline in `_production_progress_v2` above; production v3 uses
    the amended `metrics.production_progress_delta`.
    """

    utility_progress_v2 = 0.0
    utility_progress_v3 = 0.0
    complexity_progress_v2 = 0.0
    complexity_progress_v3 = 0.0
    production_progress_v2 = 0.0
    production_progress_v3 = 0.0
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
        production_v2 = _production_progress_v2(step["work"], baseline_work)
        production_v3 = metrics.production_progress_delta(step["work"], baseline_work)

        utility_progress_v2 = max(utility_progress_v2, _to_float(utility_v2["utility_progress"]))
        utility_progress_v3 = max(utility_progress_v3, _to_float(utility_v3["utility_progress"]))
        complexity_progress_v2 = max(
            complexity_progress_v2, _to_float(complexity_v2["complexity_progress"])
        )
        complexity_progress_v3 = max(
            complexity_progress_v3, _to_float(complexity_v3["complexity_progress"])
        )
        production_progress_v2 = max(production_progress_v2, float(production_v2))
        production_progress_v3 = max(
            production_progress_v3, _to_float(production_v3["production_progress"])
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
        "production_progress_v2": production_progress_v2,
        "production_progress_v3": production_progress_v3,
        "produced_goods_delta": produced_goods_delta,
        "demand_capped_production_v3": demand_capped_production_v3,
        "fort_available": fort_available,
    }


def recompute_total(
    recorded_summary: Dict[str, Any],
    utility_progress: float,
    complexity_progress: float,
    production_progress: float,
    penalties: float,
    *,
    version: int,
) -> Tuple[float, float, float, float]:
    """Recompute the composite total: recorded (unaffected) components plus
    freshly computed utility/complexity/production scores. Returns
    (total, utility_score, complexity_score, production_score).

    version=2 scores production with the TRUE v2 open-ended scaling
    (`_production_score_v2`); version=3 uses the live amended scoring
    (bounded at the weight) via scoring.score_components.
    """

    fresh = scoring.score_components(
        {
            "utility_progress": utility_progress,
            "complexity_progress": complexity_progress,
            "production_progress": production_progress,
        }
    )
    utility_score = fresh["utility_score"]
    complexity_score = fresh["complexity_score"]
    if version == 2:
        production_score = _production_score_v2(production_progress)
    else:
        production_score = fresh["production_score"]
    total = (
        sum(_to_float(recorded_summary.get(key)) for key in RECORDED_COMPONENT_KEYS)
        + utility_score
        + complexity_score
        + production_score
        - penalties
    )
    return (
        round(total, 2),
        round(utility_score, 2),
        round(complexity_score, 2),
        round(production_score, 2),
    )


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
        _to_float(summary.get(key)) for key in ALL_RECORDED_COMPONENT_KEYS
    )
    penalties = recorded_components_sum - recorded_total

    inputs = reconstruct_inputs(records)
    progress = recompute_progress(inputs)

    total_v2, utility_score_v2, complexity_score_v2, production_score_v2 = recompute_total(
        summary,
        progress["utility_progress_v2"],
        progress["complexity_progress_v2"],
        progress["production_progress_v2"],
        penalties,
        version=2,
    )
    total_v3, utility_score_v3, complexity_score_v3, production_score_v3 = recompute_total(
        summary,
        progress["utility_progress_v3"],
        progress["complexity_progress_v3"],
        progress["production_progress_v3"],
        penalties,
        version=3,
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
            "production_progress_v2": progress["production_progress_v2"],
            "production_progress_v3": progress["production_progress_v3"],
            "produced_goods_delta": progress["produced_goods_delta"],
            "demand_capped_production_v3": progress["demand_capped_production_v3"],
            "fort_available": progress["fort_available"],
            "utility_score_v2": utility_score_v2,
            "complexity_score_v2": complexity_score_v2,
            "production_score_v2": production_score_v2,
            "utility_score_v3": utility_score_v3,
            "complexity_score_v3": complexity_score_v3,
            "production_score_v3": production_score_v3,
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
            f"- production_progress: v2={row['production_progress_v2']}, "
            f"v3={row['production_progress_v3']} (amendment: usable-only, bounded)"
        )
        lines.append(
            f"- utility_score: v2={row['utility_score_v2']}, v3={row['utility_score_v3']}; "
            f"complexity_score: v2={row['complexity_score_v2']}, v3={row['complexity_score_v3']}; "
            f"production_score: v2={row['production_score_v2']}, v3={row['production_score_v3']}"
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
