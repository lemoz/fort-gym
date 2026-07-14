"""Rubric evaluation over recent fortress trace history."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List

from .scoring import GOVERNED_SCORE_PROGRESS_PROVENANCE

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


def _to_nonnegative_int_or_none(value: Any) -> int | None:
    """Parse sensor counts without truncating or normalizing invalid evidence."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


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
    if action_type == "INTERACT":
        return f"INTERACT:{params.get('operation')}"
    if action_type == "DIG":
        kind = params.get("kind") or "dig"
        return f"DIG:{kind}:{params.get('area')}:{params.get('size')}"
    if action_type == "BUILD":
        fingerprint = f"BUILD:{params.get('kind')}:{params.get('x')}:{params.get('y')}:{params.get('z')}"
        x2 = params.get("x2")
        y2 = params.get("y2")
        if x2 is not None or y2 is not None:
            fingerprint = f"{fingerprint}:{x2}:{y2}"
        return fingerprint
    if action_type == "ORDER":
        return f"ORDER:{params.get('job')}:{params.get('quantity')}"
    if action_type == "UNSUSPEND":
        return f"UNSUSPEND:{params.get('area')}:{params.get('size')}"
    if action_type == "LABOR":
        # enable direction is deliberately excluded from the identity: toggling
        # one dwarf's labor back and forth is the same repeated fiddling, so an
        # enable/disable oscillation on the same (unit, labor) must collapse into
        # one stale-fingerprint bucket rather than split ~50/50 across True/False
        # buckets and slip under the repetitive_policy threshold.
        return f"LABOR:{params.get('unit_id')}:{params.get('labor')}"
    if action_type == "FARM":
        seasons = params.get("seasons")
        seasons_key = sorted(seasons) if isinstance(seasons, list) else seasons
        return f"FARM:{params.get('building_id')}:{params.get('crop')}:{seasons_key}"
    return action_type


def _metric_max(records: Iterable[Dict[str, Any]], field: str) -> int:
    return max((_to_int(_metrics(record).get(field)) for record in records), default=0)


def _metric_latest(records: Iterable[Dict[str, Any]], field: str) -> int:
    for record in reversed(list(records)):
        metrics = _metrics(record)
        if metrics.get(field) is not None:
            return _to_int(metrics.get(field))
    return 0


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


_QUEUE_ONLY_EVIDENCE_KEYS = {
    "created_job_ids",
    "manager_recorded",
    "already_designated",
    "non_wall_tiles",
    # before/after counts are only meaningful via the explicit delta checks
    # below; their bare (non-changing) presence is not itself world change
    "before_carpenter_workshops",
    "after_carpenter_workshops",
    "before_workshops_of_kind",
    "after_workshops_of_kind",
    "before_farm_plots",
    "after_farm_plots",
    "non_shrub_tiles",
    # LABOR before/after enabled state: a no-op flip (labor_changed False) leaves
    # these two as the only truthy evidence, and it is NOT world change. A real
    # flip is caught explicitly by the labor_changed check below.
    "labor_before",
    "labor_after",
    # labor_changed itself is queue-only for the fallthrough test: a real flip is
    # credited explicitly (count_labor=True path), and the repetition tally reads
    # it with count_labor=False so a bare flip does not exempt a repeated toggle
    # of an already-credited (unit, labor) target from the stale-fingerprint tally.
    "labor_changed",
    # FARM crop-selection informational evidence: world change is signalled
    # only by seasons_changed (a plant_id slot actually flipped). These keys
    # are present on every FARM step including a no-op re-set, so their bare
    # presence must not by itself count as world change.
    "farm_building_id",
    "crop",
    "seasons_set",
    "seasons_skipped",
    "seeds_on_hand",
    # INTERACT audit evidence confirms a bounded paused-interface input only.
    # It must never be treated as a world-state change or progress exemption.
    "operation",
    "interface_key",
    "keys_sent",
}


def _proof_shows_world_change(
    proof: Dict[str, Any], *, count_labor: bool = True
) -> bool:
    """Queueing jobs is real but is not world change for repetition purposes.

    A proof exempts a step from the repetition tally only when it shows the
    world actually changed: tile diffs, productive state deltas, new
    designations, or new buildings — not merely another queued job (the
    order-spam exploit registers proof.ok via created_job_ids alone).

    ``count_labor`` controls whether a bare labor flip (``labor_changed``) is on
    its own world change. It is True by default (a single real flip is a genuine
    state change); the repetition tally passes False so that per-target labor
    crediting is decided by ``_step_progress_flags`` instead — otherwise an
    enable/disable oscillation on one (unit, labor) would flip for real every
    step and permanently escape the stale-fingerprint tally.
    """

    if int(proof.get("changed_tile_count") or 0) > 0:
        return True
    state_deltas = proof.get("state_deltas")
    if isinstance(state_deltas, dict) and state_deltas:
        return True
    evidence = proof.get("helper_evidence")
    if not isinstance(evidence, dict):
        # keystroke-mode proofs have no helper_evidence; ok already implies
        # observed step progress there
        return True
    if int(evidence.get("newly_designated") or 0) > 0:
        return True
    if int(evidence.get("unsuspended") or 0) > 0:
        return True
    if int(evidence.get("shrubs_designated") or 0) > 0:
        return True
    # A real labor flip (before != after) is a genuine state change; a no-op
    # flip (labor_changed False) is not, and falls through to the queue-only
    # whitelist so it never exempts a step from the repetition tally. When
    # count_labor is False the tally suppresses this exemption entirely and lets
    # _step_progress_flags credit only the first flip per (unit, labor) target.
    if count_labor and evidence.get("labor_changed") is True:
        return True
    if int(evidence.get("seasons_changed") or 0) > 0:
        return True
    before_ws = int(evidence.get("before_carpenter_workshops") or 0)
    after_ws = int(evidence.get("after_carpenter_workshops") or 0)
    before_ws_kind = int(evidence.get("before_workshops_of_kind") or 0)
    after_ws_kind = int(evidence.get("after_workshops_of_kind") or 0)
    before_fp = int(evidence.get("before_farm_plots") or 0)
    after_fp = int(evidence.get("after_farm_plots") or 0)
    if (
        after_ws > before_ws
        or after_ws_kind > before_ws_kind
        or after_fp > before_fp
        or evidence.get("building_id") is not None
    ):
        return True
    meaningful = {k for k, v in evidence.items() if v not in (None, 0, False, [], "")}
    return not meaningful <= _QUEUE_ONLY_EVIDENCE_KEYS


def _labor_flip_credits_progress(
    record: Dict[str, Any],
    proof: Any,
    credited_targets: set,
) -> bool:
    """First real flip of a (unit_id, labor) target is progress; repeats are not.

    Both enabling and disabling a labor genuinely flip real state, so an agent
    could alternate enable/disable on one dwarf's labor to emit a real flip every
    step. Crediting every flip would let that churn farm anti_repetition and dodge
    the repetitive_policy blocker forever. Only the first flip of a given target
    within the window earns credit; later toggles of the same pair fall through to
    the stale-fingerprint tally like any other non-progressing repeat.
    """

    if not isinstance(proof, dict) or not bool(proof.get("ok")):
        return False
    action = _record_action(record)
    if str(action.get("type") or "") != "LABOR":
        return False
    evidence = proof.get("helper_evidence")
    if not isinstance(evidence, dict) or evidence.get("labor_changed") is not True:
        return False
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    target = (params.get("unit_id"), params.get("labor"))
    if target in credited_targets:
        return False
    credited_targets.add(target)
    return True


def _step_progress_flags(records: List[Dict[str, Any]]) -> List[bool]:
    """Per record: did this step show real progress?

    Current governed traces use their explicit action-effect attribution.
    Older traces fall back to observed proof, metric deltas, and UI work.
    """

    flags: List[bool] = []
    previous_metrics: Dict[str, Any] = {}
    credited_labor_targets: set = set()
    for record in records:
        metrics = _metrics(record)
        proof = record.get("gameplay_proof")
        action = _record_action(record)
        if str(action.get("type") or "") == "INTERACT":
            flags.append(False)
            previous_metrics = metrics
            continue
        explicit_action_effect = (
            isinstance(proof, dict)
            and type(proof.get("action_effect_observed")) is bool
        )
        if explicit_action_effect:
            # Current governed traces already separated action-specific effect
            # from concurrent world changes. Do not re-credit a command from a
            # cumulative metric that happened to move in the same tick window.
            proof_ok = bool(proof.get("ok") and proof.get("action_effect_observed"))
            if str(action.get("type") or "") == "LABOR":
                proof_ok = False
            productive = False
            ui_progress = False
        else:
            # Legacy traces predate explicit action attribution.
            proof_ok = (
                isinstance(proof, dict)
                and bool(proof.get("ok"))
                and _proof_shows_world_change(proof, count_labor=False)
            )
            productive = any(
                _to_int(metrics.get(field)) > _to_int(previous_metrics.get(field))
                for field in _PROGRESS_FIELDS
            )
            ui_progress = _to_int(metrics.get("ui_step_work_progress")) > 0
        labor_progress = _labor_flip_credits_progress(
            record, proof, credited_labor_targets
        )
        flags.append(bool(proof_ok or labor_progress or productive or ui_progress))
        previous_metrics = metrics
    return flags


def _dimension(score: float, evidence: List[str], critique: str) -> Dict[str, Any]:
    return {
        "score": round(max(0.0, min(10.0, score)), 2),
        "evidence": evidence,
        "critique": critique,
    }


def evaluate_trace_records(
    records: List[Dict[str, Any]], *, window: int = RUBRIC_WINDOW
) -> Dict[str, Any]:
    """Return a deterministic 0-100 rubric over the recent fortress history."""

    recent = records[-window:] if window > 0 else list(records)
    total_steps = len(recent)
    actions = [_record_action(record) for record in recent]
    action_types = [str(action.get("type") or "unknown") for action in actions]
    action_counts = Counter(action_types)
    fingerprints = Counter(_action_fingerprint(action) for action in actions)
    accepted_steps = sum(
        1 for record in recent if _execute(record).get("accepted") is True
    )
    tick_steps = sum(
        1
        for record in recent
        if _to_int(_tick_advance(record).get("ticks_advanced")) > 0
    )
    ticks_advanced = sum(
        _to_int(_tick_advance(record).get("ticks_advanced")) for record in recent
    )
    unique_action_types = len({item for item in action_types if item != "unknown"})
    # Current governed proofs carry action-specific attribution. Legacy traces
    # fall back to their older proof/metric semantics.
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

    governed_action_truth = any(
        _metrics(record).get("score_progress_provenance")
        == GOVERNED_SCORE_PROGRESS_PROVENANCE
        for record in recent
    )
    if governed_action_truth:
        completion_progress = _metric_max(recent, "governed_owned_completion_progress")
        utility_progress = _metric_max(recent, "governed_owned_utility_progress")
        production_progress = _metric_max(recent, "governed_owned_production_progress")
        complexity_progress = _metric_max(recent, "governed_owned_complexity_progress")
        work_progress = _metric_max(recent, "governed_owned_work_progress")
        designation_progress = _metric_max(
            recent, "governed_owned_designation_progress"
        )
        ui_work_progress = 0
    else:
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
    if governed_action_truth:
        carpenter_workshops = _metric_max(
            recent, "governed_owned_completed_carpenter_workshops"
        )
        carpenter_workshops_usable = carpenter_workshops
        # Global room/construction totals are retained in trace telemetry, but
        # they cannot clear governed rubric blockers without owned evidence.
        completed_spaces = 0
        fort_enclosed_spaces = 0
        fort_functional_rooms = 0
        fort_constructions = 0
    else:
        carpenter_workshops = max(
            _metric_max(recent, "carpenter_workshops"),
            _metric_max(recent, "carpenter_workshops_delta"),
            _nested_work_max(recent, "carpenter_workshops"),
        )
        carpenter_workshops_usable = max(
            _metric_max(recent, "carpenter_workshops_usable"),
            _metric_max(recent, "carpenter_workshops_usable_delta"),
            _nested_work_max(recent, "carpenter_workshops_usable"),
        )
        completed_spaces = max(
            _metric_max(recent, "fortress_complexity_spaces_completed"),
            _nested_work_max(recent, "fortress_complexity_spaces_completed"),
        )
        # plan-agnostic fort structure (from fort_metrics.lua via the runner)
        fort_enclosed_spaces = _metric_latest(recent, "fort_enclosed_spaces")
        fort_functional_rooms = _metric_latest(recent, "fort_functional_rooms")
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
        result = (
            execute.get("result") if isinstance(execute.get("result"), dict) else {}
        )
        if action.get("type") == "DIG" and "completion" in result:
            illegal_markers.append("debug_complete_dig")
        provenance = str(
            execute.get("provenance") or metrics.get("score_provenance") or ""
        )
        if "assisted" in provenance and "governed" not in provenance:
            illegal_markers.append(provenance)

    dimensions = {
        "survival_management": _dimension(
            min(
                10.0,
                (2.0 if final_pop > 0 else 0.0)
                + min(4.0, final_food / 25.0)
                + min(4.0, final_drink / 20.0),
            ),
            [
                f"pop={final_pop}",
                f"food={final_food}",
                f"drink={final_drink}",
                f"ticks={ticks_advanced}",
            ],
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
            min(
                10.0,
                production_progress
                + utility_progress / 2.0
                + carpenter_workshops_usable * 2.0,
            ),
            [
                f"production_progress={production_progress}",
                f"utility_progress={utility_progress}",
                f"carpenter_workshops={carpenter_workshops}",
                f"carpenter_workshops_usable={carpenter_workshops_usable}",
                f"manager_orders_uncredited={manager_orders}",
            ],
            "Production credit requires completed workshop capacity or observed produced goods; "
            "orders and queued jobs are evidence only.",
        ),
        "fortress_breadth": _dimension(
            min(
                10.0,
                unique_action_types * 1.5
                + bool(work_progress) * 2.0
                + bool(fort_constructions > 0 or fort_enclosed_spaces > 0) * 3.0,
            ),
            [
                f"unique_action_types={unique_action_types}",
                f"work_progress={work_progress}",
                f"fort_constructions={fort_constructions}",
                f"fort_enclosed_spaces={fort_enclosed_spaces}",
            ],
            "Breadth rewards a fort that moves through layout, production, and expansion stages — "
            "the expansion signal is plan-agnostic structure (any enclosed space or construction), "
            "not progress against the retired fixed two_room_workshop plan.",
        ),
        "responsiveness": _dimension(
            sum(progress_flags) / max(1, total_steps) * 10.0,
            [
                f"action_effect_steps={sum(progress_flags)}/{total_steps}",
                f"accepted_steps_uncredited={accepted_steps}/{total_steps}",
                f"tick_steps_uncredited={tick_steps}/{total_steps}",
            ],
            "Responsiveness requires an observed action-specific effect; command acceptance and "
            "elapsed ticks are evidence only.",
        ),
        "plan_coherence": _dimension(
            min(
                10.0,
                sum(1 for action in actions if action.get("objective"))
                / max(1, total_steps)
                * 4.0
                + min(
                    6.0,
                    min(fort_functional_rooms, 2) * 2.0
                    + carpenter_workshops_usable * 2.0
                    + bool(production_progress or utility_progress) * 2.0,
                ),
            ),
            [
                f"objective_steps={sum(1 for action in actions if action.get('objective'))}",
                f"chain={fort_functional_rooms}/{carpenter_workshops_usable}/"
                f"{bool(production_progress or utility_progress)}",
            ],
            "Plan coherence means actions state a goal and the trace advances along that goal — "
            "room completion credit comes from plan-agnostic flood-fill functional rooms, not the "
            "retired fixed two_room_workshop plan's space-completion count.",
        ),
        "anti_repetition": _dimension(
            max(
                0.0,
                10.0 - repetition_ratio * 10.0 - max(0, no_progress_steps - 3) * 0.25,
            ),
            [
                f"stale_fingerprint_ratio={repetition_ratio:.2f}",
                f"no_progress_steps={no_progress_steps}",
            ],
            "Repeated identical actions without state change are a failure even if the scalar score rises.",
        ),
        "legal_evidence": _dimension(
            10.0
            if not illegal_markers
            else max(0.0, 10.0 - len(set(illegal_markers)) * 4.0),
            [
                f"illegal_markers={sorted(set(illegal_markers))}",
                f"designation_progress={designation_progress}",
                f"ui_work_progress={ui_work_progress}",
            ],
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
    if (
        carpenter_workshops_usable <= 0
        and production_progress <= 0
        and utility_progress <= 0
    ):
        blockers.append("no_production_surface")
    if complexity_progress <= 0 and completed_spaces <= 0:
        blockers.append("no_broader_fort_layout")
    if repetition_ratio >= 0.6 and total_steps >= 5:
        blockers.append("repetitive_policy")
    if illegal_markers:
        blockers.append("illegal_or_assisted_progress_seen")

    return {
        "rubric_score": rubric_score,
        "progress_provenance": (
            GOVERNED_SCORE_PROGRESS_PROVENANCE
            if governed_action_truth
            else "legacy_or_ungoverned"
        ),
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


def evaluate_trace_records_v2(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a full-trace, non-scalar behavior outcome vector.

    Version 2 deliberately does not award points for action vocabulary,
    objective-field presence, elapsed time, or stochastic population. It
    reports achieved capabilities and normalized behavior rates so one
    primitive cannot silently pay multiple quality dimensions.
    """

    total_steps = len(records)
    actions = [_record_action(record) for record in records]
    action_types = [str(action.get("type") or "unknown") for action in actions]
    progress_flags = _step_progress_flags(records)
    semantic_interactions = 0
    productive_waits = 0
    for index, record in enumerate(records):
        action = actions[index]
        proof = record.get("gameplay_proof")
        execute = _execute(record)
        result = (
            execute.get("result") if isinstance(execute.get("result"), dict) else {}
        )
        if (
            action.get("type") == "INTERACT"
            and result.get("semantic_effect_observed") is True
        ):
            progress_flags[index] = True
            semantic_interactions += 1
        if (
            action.get("type") == "WAIT"
            and isinstance(proof, dict)
            and proof.get("owned_prior_action_effect_observed") is True
        ):
            progress_flags[index] = True
            productive_waits += 1

    stale_counts = Counter(
        _action_fingerprint(action)
        for action, progressed in zip(actions, progress_flags)
        if not progressed
    )
    repeated_noops = sum(max(0, count - 1) for count in stale_counts.values())
    final_metrics = _metrics(records[-1]) if records else {}
    final_state: Dict[str, Any] = {}
    if records:
        for key in ("observation", "state_after_apply", "state_after_advance"):
            value = records[-1].get(key)
            if isinstance(value, dict):
                final_state.update(value)
    survival = (
        final_state.get("survival")
        if isinstance(final_state.get("survival"), dict)
        else {}
    )

    def _optional_fact(name: str) -> int | None:
        raw = survival.get(name, final_metrics.get(name))
        return _to_nonnegative_int_or_none(raw)

    food_produced = _optional_fact("food_produced_in_run")
    food_consumed = _optional_fact("food_consumed_in_run")
    drink_produced = _optional_fact("drink_produced_in_run")
    drink_consumed = _optional_fact("drink_consumed_in_run")
    room_evidence_complete = (
        final_metrics.get("governed_owned_room_evidence_complete") is True
    )
    room_lower_bound_proven = (
        final_metrics.get("governed_owned_layout_room_lower_bound_proven") is True
    )
    building_evidence_complete = (
        final_metrics.get("governed_owned_building_evidence_complete") is True
    )
    output_evidence_complete = (
        final_metrics.get("governed_owned_output_evidence_complete") is True
    )
    output_lower_bound_proven = (
        final_metrics.get("governed_owned_output_lower_bound_proven") is True
    )
    flow_fields = (
        "food_produced_in_run",
        "food_consumed_in_run",
        "drink_produced_in_run",
        "drink_consumed_in_run",
    )
    trace_run_ids = {
        record.get("run_id")
        for record in records
        if isinstance(record.get("run_id"), str) and record.get("run_id")
    }
    trace_run_binding_complete = bool(
        records
        and all(
            isinstance(record.get("run_id"), str) and record.get("run_id")
            for record in records
        )
        and len(trace_run_ids) == 1
    )
    flow_evidence_complete = bool(
        survival.get("flow_evidence_complete") is True
        and all(field in survival for field in flow_fields)
        and all(
            value is not None
            for value in (
                food_produced,
                food_consumed,
                drink_produced,
                drink_consumed,
            )
        )
        and trace_run_binding_complete
        and survival.get("run_id") in trace_run_ids
    )

    def _domain(value: Any, *, complete: bool) -> bool | None:
        parsed = _to_nonnegative_int_or_none(value)
        return parsed > 0 if complete and parsed is not None else None

    domains: Dict[str, bool | None] = {
        "layout": _domain(
            final_metrics.get("governed_owned_accessible_layout_rooms"),
            complete=room_evidence_complete or room_lower_bound_proven,
        ),
        "furnishing": _domain(
            final_metrics.get("governed_owned_completed_beds"),
            complete=building_evidence_complete,
        ),
        "industry": _domain(
            final_metrics.get("governed_owned_production_capacity"),
            complete=building_evidence_complete,
        ),
        "realized_owned_output": _domain(
            final_metrics.get("governed_owned_output_units"),
            complete=output_evidence_complete or output_lower_bound_proven,
        ),
        "food_loop": (
            food_produced > food_consumed if flow_evidence_complete else None
        ),
        "drink_loop": (
            drink_produced > drink_consumed if flow_evidence_complete else None
        ),
    }

    illegal_markers: List[str] = []
    legal_evidence_complete = bool(records)
    for record in records:
        action = _record_action(record)
        execute = _execute(record)
        metrics = _metrics(record)
        result = (
            execute.get("result") if isinstance(execute.get("result"), dict) else {}
        )
        if action.get("type") == "DIG" and "completion" in result:
            illegal_markers.append("debug_complete_dig")
        provenance = str(
            execute.get("provenance") or metrics.get("score_provenance") or ""
        )
        if not provenance:
            legal_evidence_complete = False
        if "assisted" in provenance and "governed" not in provenance:
            illegal_markers.append(provenance)

    evidence_complete = bool(
        records
        and (room_evidence_complete or room_lower_bound_proven)
        and building_evidence_complete
        and (output_evidence_complete or output_lower_bound_proven)
        and flow_evidence_complete
        and all(value is not None for value in domains.values())
        and legal_evidence_complete
    )
    return {
        "measurement_version": 2,
        "score": None,
        "score_status": "retired_for_g7_v5",
        "window": "full_trace",
        "total_steps": total_steps,
        "achieved_domains": domains,
        "unknown_domain_count": sum(value is None for value in domains.values()),
        "action_effect_steps": sum(progress_flags),
        "action_effect_rate": round(sum(progress_flags) / max(1, total_steps), 6),
        "repeated_failed_noop_steps": repeated_noops,
        "repeated_failed_noop_rate": round(repeated_noops / max(1, total_steps), 6),
        "productive_wait_steps": productive_waits,
        "semantic_interaction_steps": semantic_interactions,
        "action_counts": dict(sorted(Counter(action_types).items())),
        "legal_execution": (
            not illegal_markers if legal_evidence_complete else None
        ),
        "legal_evidence_complete": legal_evidence_complete,
        "illegal_markers": sorted(set(illegal_markers)),
        "evidence_complete": evidence_complete,
        "notes": [
            "Objective text and action-type variety receive no credit.",
            "Population and elapsed ticks are exposure diagnostics only.",
            "Final owned accessible capabilities replace peak/global proxies.",
        ],
    }


__all__ = [
    "DIMENSION_NAMES",
    "RUBRIC_WINDOW",
    "evaluate_trace_records",
    "evaluate_trace_records_v2",
]
