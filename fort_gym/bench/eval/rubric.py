"""Rubric evaluation over recent fortress trace history."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List


RUBRIC_WINDOW = 100
DIMENSION_NAMES = (
    "survival_management",
    "shelter_layout",
    "production_economy",
    "fortress_breadth",
    "responsiveness",
    "plan_coherence",
    "anti_repetition",
    "legal_evidence",
)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _record_action(record: Dict[str, Any]) -> Dict[str, Any]:
    action = record.get("action")
    if isinstance(action, dict):
        return action
    raw_action = record.get("raw_action")
    return raw_action if isinstance(raw_action, dict) else {}


def _metrics(record: Dict[str, Any]) -> Dict[str, Any]:
    value = record.get("metrics")
    return value if isinstance(value, dict) else {}


def _execute(record: Dict[str, Any]) -> Dict[str, Any]:
    value = record.get("execute")
    return value if isinstance(value, dict) else {}


def _tick_advance(record: Dict[str, Any]) -> Dict[str, Any]:
    value = record.get("tick_advance")
    return value if isinstance(value, dict) else {}


def _action_fingerprint(action: Dict[str, Any]) -> str:
    action_type = str(action.get("type") or "unknown")
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if action_type == "KEYSTROKE":
        keys = params.get("keys") if isinstance(params, dict) else []
        if isinstance(keys, list):
            return f"{action_type}:{','.join(str(key) for key in keys[:8])}"
    if action_type == "DIG":
        return f"DIG:{params.get('area')}:{params.get('size')}"
    if action_type == "BUILD":
        return f"BUILD:{params.get('kind')}:{params.get('x')}:{params.get('y')}:{params.get('z')}"
    if action_type == "ORDER":
        return f"ORDER:{params.get('job')}:{params.get('quantity')}"
    return action_type


def _metric_max(records: Iterable[Dict[str, Any]], field: str) -> int:
    return max((_to_int(_metrics(record).get(field)) for record in records), default=0)


def _nested_work_max(records: Iterable[Dict[str, Any]], field: str) -> int:
    value = 0
    for record in records:
        metrics = _metrics(record)
        work = metrics.get("work")
        if isinstance(work, dict):
            value = max(value, _to_int(work.get(field)))
        for state_key in ("observation", "state_after_apply", "state_after_advance"):
            state = record.get(state_key)
            if isinstance(state, dict) and isinstance(state.get("work"), dict):
                value = max(value, _to_int(state["work"].get(field)))
    return value


_PROGRESS_FIELDS = (
    "work_progress",
    "completion_progress",
    "utility_progress",
    "production_progress",
    "complexity_progress",
    "ui_work_progress",
)


def _step_progress_flags(records: List[Dict[str, Any]]) -> List[bool]:
    """Per record: did this step show real progress?

    A step counts as progress-backed when its recorded ``gameplay_proof``
    shows real state change, when a tracked progress metric advanced versus
    the previous step, or when per-step UI work progress was observed.
    """

    flags: List[bool] = []
    previous_metrics: Dict[str, Any] = {}
    for record in records:
        metrics = _metrics(record)
        proof = record.get("gameplay_proof")
        proof_ok = isinstance(proof, dict) and bool(proof.get("ok"))
        productive = any(
            _to_int(metrics.get(field)) > _to_int(previous_metrics.get(field))
            for field in _PROGRESS_FIELDS
        )
        flags.append(
            bool(
                proof_ok
                or productive
                or _to_int(metrics.get("ui_step_work_progress")) > 0
            )
        )
        previous_metrics = metrics
    return flags


def _dimension(score: float, evidence: List[str], critique: str) -> Dict[str, Any]:
    return {
        "score": round(max(0.0, min(10.0, score)), 2),
        "evidence": evidence,
        "critique": critique,
    }


def evaluate_trace_records(records: List[Dict[str, Any]], *, window: int = RUBRIC_WINDOW) -> Dict[str, Any]:
    """Return a deterministic 0-100 rubric over the recent fortress history."""

    recent = records[-window:] if window > 0 else list(records)
    total_steps = len(recent)
    actions = [_record_action(record) for record in recent]
    action_types = [str(action.get("type") or "unknown") for action in actions]
    action_counts = Counter(action_types)
    fingerprints = Counter(_action_fingerprint(action) for action in actions)
    accepted_steps = sum(1 for record in recent if _execute(record).get("accepted") is True)
    tick_steps = sum(1 for record in recent if _to_int(_tick_advance(record).get("ticks_advanced")) > 0)
    ticks_advanced = sum(_to_int(_tick_advance(record).get("ticks_advanced")) for record in recent)
    unique_action_types = len({item for item in action_types if item != "unknown"})
    # Repetition is a failure only when the repeated steps produced no real
    # state change (the dimension's own critique text). Steps whose recorded
    # gameplay_proof shows real change, or whose metrics advanced, do not
    # count toward the repetition tally.
    progress_flags = _step_progress_flags(recent)
    stale_fingerprints = Counter(
        _action_fingerprint(action)
        for action, progressed in zip(actions, progress_flags)
        if not progressed
    )
    most_common_count = (
        stale_fingerprints.most_common(1)[0][1] if stale_fingerprints else 0
    )
    repetition_ratio = most_common_count / total_steps if total_steps else 0.0

    completion_progress = _metric_max(recent, "completion_progress")
    utility_progress = _metric_max(recent, "utility_progress")
    production_progress = _metric_max(recent, "production_progress")
    complexity_progress = _metric_max(recent, "complexity_progress")
    work_progress = _metric_max(recent, "work_progress")
    designation_progress = _metric_max(recent, "designation_progress")
    ui_work_progress = _metric_max(recent, "ui_work_progress")
    manager_orders = max(
        _metric_max(recent, "manager_orders_count"),
        _metric_max(recent, "manager_orders_delta"),
        _nested_work_max(recent, "manager_orders_count"),
    )
    carpenter_workshops = max(
        _metric_max(recent, "carpenter_workshops"),
        _metric_max(recent, "carpenter_workshops_delta"),
        _nested_work_max(recent, "carpenter_workshops"),
    )
    completed_spaces = max(
        _metric_max(recent, "fortress_complexity_spaces_completed"),
        _nested_work_max(recent, "fortress_complexity_spaces_completed"),
    )
    # plan-agnostic fort structure (from fort_metrics.lua via the runner)
    fort_enclosed_spaces = _metric_max(recent, "fort_enclosed_spaces")
    fort_functional_rooms = _metric_max(recent, "fort_functional_rooms")
    fort_constructions = _metric_max(recent, "fort_constructions")
    final_pop = 0
    final_food = 0
    final_drink = 0
    for record in reversed(recent):
        metrics = _metrics(record)
        final_pop = _to_int(metrics.get("pop") or metrics.get("population"), final_pop)
        final_food = _to_int(metrics.get("food"), final_food)
        final_drink = _to_int(metrics.get("drink"), final_drink)
        if final_pop or final_food or final_drink:
            break

    no_progress_steps = sum(1 for progressed in progress_flags if not progressed)

    illegal_markers: List[str] = []
    for record in recent:
        action = _record_action(record)
        execute = _execute(record)
        metrics = _metrics(record)
        result = execute.get("result") if isinstance(execute.get("result"), dict) else {}
        if action.get("type") == "DIG" and "completion" in result:
            illegal_markers.append("debug_complete_dig")
        provenance = str(execute.get("provenance") or metrics.get("score_provenance") or "")
        if "assisted" in provenance and "governed" not in provenance:
            illegal_markers.append(provenance)

    dimensions = {
        "survival_management": _dimension(
            min(10.0, (2.0 if final_pop > 0 else 0.0) + min(4.0, final_food / 25.0) + min(4.0, final_drink / 20.0)),
            [f"pop={final_pop}", f"food={final_food}", f"drink={final_drink}", f"ticks={ticks_advanced}"],
            "Fort health is good when population survives and basic stocks remain available.",
        ),
        "shelter_layout": _dimension(
            min(
                10.0,
                fort_functional_rooms * 3.0
                + fort_enclosed_spaces * 1.5
                + min(2.0, fort_constructions / 10.0)
                + completion_progress / 5.0
                + completed_spaces * 1.0,
            ),
            [
                f"fort_functional_rooms={fort_functional_rooms}",
                f"fort_enclosed_spaces={fort_enclosed_spaces}",
                f"fort_constructions={fort_constructions}",
                f"completion_progress={completion_progress}",
            ],
            "Shelter credit requires real enclosed structure the player built — "
            "functional rooms bounded by walls/buildings/doors — not elapsed time.",
        ),
        "production_economy": _dimension(
            min(10.0, production_progress + utility_progress / 2.0 + carpenter_workshops * 2.0 + manager_orders),
            [
                f"production_progress={production_progress}",
                f"utility_progress={utility_progress}",
                f"carpenter_workshops={carpenter_workshops}",
                f"manager_orders={manager_orders}",
            ],
            "Production credit requires buildings, orders, jobs, or produced goods.",
        ),
        "fortress_breadth": _dimension(
            min(10.0, unique_action_types * 1.5 + bool(work_progress) * 2.0 + bool(complexity_progress) * 3.0),
            [
                f"unique_action_types={unique_action_types}",
                f"work_progress={work_progress}",
                f"complexity_progress={complexity_progress}",
            ],
            "Breadth rewards a fort that moves through layout, production, and expansion stages.",
        ),
        "responsiveness": _dimension(
            min(10.0, accepted_steps / max(1, total_steps) * 5.0 + tick_steps / max(1, total_steps) * 5.0),
            [f"accepted_steps={accepted_steps}/{total_steps}", f"tick_steps={tick_steps}/{total_steps}"],
            "The agent should issue valid commands and advance simulation when work is pending.",
        ),
        "plan_coherence": _dimension(
            min(10.0, sum(1 for action in actions if action.get("objective")) / max(1, total_steps) * 4.0 + min(6.0, completed_spaces * 2.0 + carpenter_workshops * 2.0 + manager_orders)),
            [f"objective_steps={sum(1 for action in actions if action.get('objective'))}", f"chain={completed_spaces}/{carpenter_workshops}/{manager_orders}"],
            "Plan coherence means actions state a goal and the trace advances along that goal.",
        ),
        "anti_repetition": _dimension(
            max(0.0, 10.0 - repetition_ratio * 10.0 - max(0, no_progress_steps - 3) * 0.25),
            [f"stale_fingerprint_ratio={repetition_ratio:.2f}", f"no_progress_steps={no_progress_steps}"],
            "Repeated identical actions without state change are a failure even if the scalar score rises.",
        ),
        "legal_evidence": _dimension(
            10.0 if not illegal_markers else max(0.0, 10.0 - len(set(illegal_markers)) * 4.0),
            [f"illegal_markers={sorted(set(illegal_markers))}", f"designation_progress={designation_progress}", f"ui_work_progress={ui_work_progress}"],
            "Legal evidence excludes debug completion and non-governed assisted progress from rubric credit.",
        ),
    }

    rubric_score = round(
        sum(value["score"] for value in dimensions.values()) / len(dimensions) * 10.0,
        2,
    )
    blockers: List[str] = []
    if (
        fort_enclosed_spaces <= 0
        and fort_constructions <= 0
        and completion_progress <= 0
        and work_progress <= 0
    ):
        blockers.append("no_fort_structure")
    if carpenter_workshops <= 0 and production_progress <= 0:
        blockers.append("no_production_surface")
    if complexity_progress <= 0 and completed_spaces <= 0:
        blockers.append("no_broader_fort_layout")
    if repetition_ratio >= 0.6 and total_steps >= 5:
        blockers.append("repetitive_policy")
    if illegal_markers:
        blockers.append("illegal_or_assisted_progress_seen")

    return {
        "rubric_score": rubric_score,
        "window": min(window, total_steps) if window > 0 else total_steps,
        "total_steps": total_steps,
        "dimensions": dimensions,
        "action_counts": dict(sorted(action_counts.items())),
        "top_action_fingerprints": [
            {"fingerprint": key, "count": count}
            for key, count in fingerprints.most_common(5)
        ],
        "blockers": blockers,
        "critique": _critique(rubric_score, blockers, dimensions),
    }


def _critique(
    rubric_score: float,
    blockers: List[str],
    dimensions: Dict[str, Dict[str, Any]],
) -> str:
    if blockers:
        return (
            "The run still fails the fortress-quality rubric because "
            + ", ".join(blockers)
            + "."
        )
    weak = [
        name
        for name, payload in dimensions.items()
        if float(payload.get("score") or 0.0) < 5.0
    ]
    if weak:
        return "The run is playable but weak on " + ", ".join(weak) + "."
    if rubric_score >= 75:
        return "The run shows broad, legal fortress progress across layout, production, and survival."
    return "The run shows partial legal fortress progress but needs broader long-horizon development."


__all__ = ["DIMENSION_NAMES", "RUBRIC_WINDOW", "evaluate_trace_records"]
