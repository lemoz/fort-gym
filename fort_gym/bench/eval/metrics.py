"""Evaluation metric helpers."""

from __future__ import annotations

from typing import Any, Dict

UTILITY_WORKSHOP_PROGRESS = 5
PRODUCTION_WORKSHOP_PROGRESS = 5
COMPLEXITY_SPACE_PROGRESS = 5

# Completed-workshop utility currently uses the carpenter-labeled fields from
# work_metrics.lua. Still capacity is evaluated through drink production and
# the G7 survival ledger; no BUILD kind receives instant action credit.


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _work_value(work: Dict[str, Any], key: str, *, fallback_key: str | None = None) -> int:
    if key in work:
        return _to_int(work.get(key))
    if fallback_key is not None:
        return _to_int(work.get(fallback_key))
    return 0


def _workshop_counts(work: Dict[str, Any]) -> Dict[str, int]:
    planned = _work_value(
        work,
        "carpenter_workshops_planned",
        fallback_key="carpenter_workshops",
    )
    usable = _work_value(
        work,
        "carpenter_workshops_usable",
        fallback_key="carpenter_workshops",
    )
    task_jobs = _to_int(work.get("carpenter_workshop_task_jobs"))
    construction_jobs = _to_int(work.get("carpenter_workshop_construction_jobs"))
    return {
        "planned": planned,
        "usable": usable,
        "task_jobs": task_jobs,
        "construction_jobs": construction_jobs,
    }


def work_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute bounded target-region work deltas from live work snapshots."""

    current = current_work or {}
    baseline = baseline_work or {}
    designations_delta = max(
        0,
        _to_int(current.get("target_dig_designations"))
        - _to_int(baseline.get("target_dig_designations")),
    )
    floor_delta = max(
        0,
        _to_int(current.get("target_floor_tiles"))
        - _to_int(baseline.get("target_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("target_wall_tiles"))
        - _to_int(current.get("target_wall_tiles")),
    )
    active_dig_jobs_delta = max(
        0,
        _to_int(current.get("active_dig_jobs")) - _to_int(baseline.get("active_dig_jobs")),
    )
    designation_progress = designations_delta + active_dig_jobs_delta
    completion_progress = max(floor_delta, wall_delta)
    return {
        "target_dig_designations_delta": designations_delta,
        "target_floor_tiles_delta": floor_delta,
        "target_wall_tiles_delta": wall_delta,
        "active_dig_jobs_delta": active_dig_jobs_delta,
        "designation_progress": designation_progress,
        "completion_progress": completion_progress,
        "work_progress": max(designation_progress, completion_progress),
    }


def _snapshot_tile_index(snapshot: Dict[str, Any] | None) -> Dict[tuple[int, int, int], Dict[str, Any]]:
    if not isinstance(snapshot, dict) or snapshot.get("ok") is not True:
        return {}
    indexed: Dict[tuple[int, int, int], Dict[str, Any]] = {}
    for tile in snapshot.get("tiles", []):
        if not isinstance(tile, dict):
            continue
        try:
            key = (int(tile["x"]), int(tile["y"]), int(tile["z"]))
        except (KeyError, TypeError, ValueError):
            continue
        indexed[key] = tile
    return indexed


def _has_dig_designation(tile: Dict[str, Any] | None) -> bool:
    if not isinstance(tile, dict):
        return False
    value = str(tile.get("dig") or "No").strip().lower()
    return value not in {"", "0", "no", "none"}


def _owned_excavation_complete(tile: Dict[str, Any] | None, kind: str) -> bool:
    if not isinstance(tile, dict) or tile.get("hidden") is True:
        return False
    if _has_dig_designation(tile):
        return False
    if kind == "dig":
        return (
            str(tile.get("category") or "").lower() == "floor"
            and str(tile.get("material") or "").upper() != "FROZEN_LIQUID"
        )
    if kind == "channel":
        return str(tile.get("shape") or "").upper() == "RAMP_TOP"
    return False


def governed_action_footprint_progress_delta(
    action: Dict[str, Any],
    before_snapshot: Dict[str, Any] | None,
    after_snapshot: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Attribute only observed excavation effects inside a model DIG footprint.

    A newly written designation establishes ownership but earns no scalar
    progress. A tile becomes scoreable only after its native map state reaches
    a stable completed dig floor or a completed channel ramp top.
    """

    empty: Dict[str, Any] = {
        "governed_step_designation_progress": 0,
        "governed_step_completion_progress": 0,
        "governed_owned_tiles_added": [],
        "governed_designated_tiles": [],
        "governed_completed_tiles": [],
    }
    if str(action.get("type") or "").upper() != "DIG":
        return empty
    params = action.get("params")
    if not isinstance(params, dict):
        return empty
    kind = str(params.get("kind") or "dig").lower()
    if kind not in {"dig", "channel"}:
        return empty
    if not (
        isinstance(before_snapshot, dict)
        and isinstance(after_snapshot, dict)
        and before_snapshot.get("ok") is True
        and after_snapshot.get("ok") is True
        and before_snapshot.get("rect") == after_snapshot.get("rect")
    ):
        return empty

    before_tiles = _snapshot_tile_index(before_snapshot)
    after_tiles = _snapshot_tile_index(after_snapshot)
    designated: list[list[int]] = []
    completed: list[list[int]] = []
    owned: list[list[int]] = []
    for coord in sorted(set(before_tiles) & set(after_tiles)):
        before = before_tiles[coord]
        after = after_tiles[coord]
        newly_designated = not _has_dig_designation(before) and _has_dig_designation(after)
        immediate_completion = (
            not _has_dig_designation(before)
            and str(before.get("category") or "").lower() in {"wall", "floor"}
            and _owned_excavation_complete(after, kind)
        )
        rendered = [coord[0], coord[1], coord[2]]
        if newly_designated:
            designated.append(rendered)
        if immediate_completion:
            completed.append(rendered)
        if newly_designated or immediate_completion:
            owned.append(rendered)

    return {
        "governed_step_designation_progress": len(designated),
        "governed_step_completion_progress": len(completed),
        "governed_owned_tiles_added": owned,
        "governed_designated_tiles": designated,
        "governed_completed_tiles": completed,
    }


def governed_owned_excavation_completion_tiles(
    owned_tiles: Dict[tuple[int, int, int], str],
    *snapshots: Dict[str, Any] | None,
) -> list[list[int]]:
    """Return owned coordinates whose latest observed native state is complete."""

    observed: Dict[tuple[int, int, int], Dict[str, Any]] = {}
    for snapshot in snapshots:
        observed.update(_snapshot_tile_index(snapshot))
    completed = [
        [x, y, z]
        for (x, y, z), kind in sorted(owned_tiles.items())
        if _owned_excavation_complete(observed.get((x, y, z)), kind)
    ]
    return completed


def ui_work_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute progress inside a fixed live UI rectangle.

    The caller is responsible for passing snapshots from the same rectangle. If
    the rectangle changes, return zero progress to avoid scoring camera motion.
    """

    current = current_work or {}
    baseline = baseline_work or {}
    target_rect = current.get("target_rect")
    if target_rect is None or target_rect != baseline.get("target_rect"):
        return {
            "ui_target_dig_designations_delta": 0,
            "ui_target_floor_tiles_delta": 0,
            "ui_target_floor_removed_delta": 0,
            "ui_target_wall_tiles_delta": 0,
            "ui_designation_progress": 0,
            "ui_completion_progress": 0,
            "ui_excavation_progress": 0,
            "ui_work_progress": 0,
        }

    designations_delta = max(
        0,
        _to_int(current.get("target_dig_designations"))
        - _to_int(baseline.get("target_dig_designations")),
    )
    floor_delta = max(
        0,
        _to_int(current.get("target_floor_tiles"))
        - _to_int(baseline.get("target_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("target_wall_tiles"))
        - _to_int(current.get("target_wall_tiles")),
    )
    floor_removed_delta = max(
        0,
        _to_int(baseline.get("target_floor_tiles"))
        - _to_int(current.get("target_floor_tiles")),
    )
    excavation_progress = max(wall_delta, floor_removed_delta)
    completion_progress = max(floor_delta, excavation_progress)
    return {
        "ui_target_dig_designations_delta": designations_delta,
        "ui_target_floor_tiles_delta": floor_delta,
        "ui_target_floor_removed_delta": floor_removed_delta,
        "ui_target_wall_tiles_delta": wall_delta,
        "ui_designation_progress": designations_delta,
        "ui_completion_progress": completion_progress,
        "ui_excavation_progress": excavation_progress,
        "ui_work_progress": max(designations_delta, completion_progress),
    }


# drink added 2026-07-08 (operator call): brew output pays like other goods,
# demand-capped; DF counts drink as stacks, so one brew job = one item delta
ORDERABLE_GOODS = ("bed", "door", "table", "chair", "barrel", "bin", "drink")


def utility_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
    current_goods: Dict[str, Any] | None = None,
    baseline_goods: Dict[str, Any] | None = None,
    population: int | None = None,
) -> Dict[str, Any]:
    """Compute bounded useful-work deltas from live work snapshots.

    Score-v2 (2026-07-03): utility pays only for COMPLETED production —
    in-play item-count deltas of orderable goods — plus workshops that became
    usable. Order/queue depth deltas remain in the output for observability
    but earn nothing: queueing 91 orders is a menu action, not utility.

    Score-v3 (2026-07-07): linear per-item payment let the optimal
    long-horizon policy degenerate into mass-producing the cheapest item
    instead of building a fortress — endurance probe ad70df06 finished one
    room at step 98 then produced 26 chairs for 13 dwarves over ~150 steps
    and scored 5.35x its step-100 mark even though every chair was real,
    proof-backed production (v2's fake-progress defenses held; the exploit
    was Goodhart-by-monoculture, not fabricated state). v3 caps payment at
    fort demand (current population): each orderable good type pays full
    rate up to `population` items produced this run, and 20% surplus rate
    beyond that, so mass production of one item stops dominating the score.
    `produced_goods_delta` keeps paying the full raw count for legacy
    callers/observability; `demand_capped_production` is the new paid
    quantity that feeds `utility_progress`. Passing `population=None`
    preserves the exact v2 behavior (paid == raw) for legacy callers.
    """

    current = current_work or {}
    baseline = baseline_work or {}
    manager_orders_delta = max(
        0,
        _to_int(current.get("manager_orders_count"))
        - _to_int(baseline.get("manager_orders_count")),
    )
    manager_order_quantity_delta = max(
        0,
        _to_int(current.get("manager_orders_amount_left"))
        - _to_int(baseline.get("manager_orders_amount_left")),
    )
    current_workshops = _workshop_counts(current)
    baseline_workshops = _workshop_counts(baseline)
    carpenter_workshops_planned_delta = max(
        0,
        current_workshops["planned"] - baseline_workshops["planned"],
    )
    carpenter_workshops_usable_delta = max(
        0,
        current_workshops["usable"] - baseline_workshops["usable"],
    )
    carpenter_workshop_task_jobs_delta = max(
        0,
        current_workshops["task_jobs"] - baseline_workshops["task_jobs"],
    )
    carpenter_workshops_delta = max(
        carpenter_workshops_usable_delta,
        carpenter_workshop_task_jobs_delta,
    )
    produced_goods_delta = 0
    demand_capped_production = 0.0
    demand = max(int(population), 0) if population is not None else None
    if isinstance(current_goods, dict) and isinstance(baseline_goods, dict):
        for good in ORDERABLE_GOODS:
            raw_t = max(
                0, _to_int(current_goods.get(good)) - _to_int(baseline_goods.get(good))
            )
            produced_goods_delta += raw_t
            if demand is None:
                paid_t: float = raw_t
            else:
                paid_t = min(raw_t, demand) + 0.2 * max(0, raw_t - demand)
            demand_capped_production += paid_t
    demand_capped_production = round(demand_capped_production, 2)
    workshop_progress = carpenter_workshops_usable_delta * UTILITY_WORKSHOP_PROGRESS
    return {
        "manager_orders_delta": manager_orders_delta,
        "manager_order_quantity_delta": manager_order_quantity_delta,
        "carpenter_workshops_planned_delta": carpenter_workshops_planned_delta,
        "carpenter_workshops_usable_delta": carpenter_workshops_usable_delta,
        "carpenter_workshop_task_jobs_delta": carpenter_workshop_task_jobs_delta,
        "carpenter_workshops_delta": carpenter_workshops_delta,
        "produced_goods_delta": produced_goods_delta,
        "demand_capped_production": demand_capped_production,
        "utility_progress": demand_capped_production + workshop_progress,
    }


def production_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute bounded production/build deltas from live work snapshots.

    Score-v3 amendment (2026-07-07, operator-ratified): production pays
    USABLE-workshop deltas only. Through v2, `production_workshops_delta`
    was `max(usable_delta, task_jobs_delta)` — queued workshop task jobs
    counted as production capacity, and since task-job depth rises with
    every ORDER an agent stacks, the open-ended production_score became a
    queue-depth meter. The first score-v3 calibration round exposed it as
    the dominant unreformed Goodhart vector: run ad70df06 (chair factory)
    recorded production_score 320.0 and run 7f268bcc recorded 420.0 — an
    order of magnitude above every honest component — from task-jobs churn,
    while both G4-passing runs sat at 30-50. Queueing is a menu action, not
    production (the same doctrine score-v2 applied to utility's
    order-queue deltas). `production_task_jobs_delta` stays in the output
    for observability but earns nothing.
    """

    current = current_work or {}
    baseline = baseline_work or {}
    current_workshops = _workshop_counts(current)
    baseline_workshops = _workshop_counts(baseline)
    carpenter_workshops_planned_delta = max(
        0,
        current_workshops["planned"] - baseline_workshops["planned"],
    )
    carpenter_workshops_usable_delta = max(
        0,
        current_workshops["usable"] - baseline_workshops["usable"],
    )
    carpenter_workshop_task_jobs_delta = max(
        0,
        current_workshops["task_jobs"] - baseline_workshops["task_jobs"],
    )
    production_workshops_delta = carpenter_workshops_usable_delta
    return {
        "production_workshops_planned_delta": carpenter_workshops_planned_delta,
        "production_workshops_delta": production_workshops_delta,
        "production_task_jobs_delta": carpenter_workshop_task_jobs_delta,
        "production_progress": production_workshops_delta * PRODUCTION_WORKSHOP_PROGRESS,
    }


def complexity_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
    current_fort: Dict[str, Any] | None = None,
    baseline_fort: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compute visible fortress-layout complexity.

    Score-v2 and earlier paid from `fortress_complexity_*` — floor/wall tile
    deltas and a "second space completed" flag lifted straight from the
    retired `two_room_workshop` fixed plan. An agent building real rooms
    anywhere else on the map earned zero here, which silently punished the
    plan-agnostic play the gates now require (confirmed by adversarial
    review 2026-07-05, forcing finding #1 behind score-v3).

    Score-v3 (2026-07-07): when plan-agnostic fort structure facts are
    available (`current_fort`/`baseline_fort`, from fort_metrics.lua via the
    runner, both `ok`), complexity instead pays from flood-fill facts:
    completed functional rooms, enclosed spaces, and constructions, anywhere
    on the map. The legacy tile/space fields are still computed and returned
    for observability but no longer feed `complexity_progress` once fort
    data is present. When fort data is absent (old traces, mock backend),
    this falls back to the exact legacy computation so historical replay is
    unaffected.
    """

    current = current_work or {}
    baseline = baseline_work or {}
    floor_delta = max(
        0,
        _to_int(current.get("fortress_complexity_floor_tiles"))
        - _to_int(baseline.get("fortress_complexity_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("fortress_complexity_wall_tiles"))
        - _to_int(current.get("fortress_complexity_wall_tiles")),
    )
    spaces_delta = max(
        0,
        _to_int(current.get("fortress_complexity_spaces_completed"))
        - _to_int(baseline.get("fortress_complexity_spaces_completed")),
    )
    complexity_tiles_delta = max(floor_delta, wall_delta)

    fort_available = (
        isinstance(current_fort, dict)
        and current_fort.get("ok")
        and isinstance(baseline_fort, dict)
        and baseline_fort.get("ok")
    )
    if not fort_available:
        # Legacy fallback: exact v2 computation, unchanged output shape.
        return {
            "complexity_floor_tiles_delta": floor_delta,
            "complexity_wall_tiles_delta": wall_delta,
            "complexity_spaces_delta": spaces_delta,
            "complexity_progress": complexity_tiles_delta
            + spaces_delta * COMPLEXITY_SPACE_PROGRESS,
        }

    rooms_delta = max(
        0,
        _to_int(current_fort.get("functional_rooms"))
        - _to_int(baseline_fort.get("functional_rooms")),
    )
    fort_spaces_delta = max(
        0,
        _to_int(current_fort.get("enclosed_spaces"))
        - _to_int(baseline_fort.get("enclosed_spaces")),
    )
    constructions_delta = max(
        0,
        _to_int(current_fort.get("constructions"))
        - _to_int(baseline_fort.get("constructions")),
    )
    complexity_progress = (
        rooms_delta * 15 + fort_spaces_delta * 5 + min(constructions_delta, 60) * 0.5
    )
    return {
        # Legacy keys: still computed from `work` as today, for observability
        # only — they no longer feed complexity_progress once fort data is
        # present.
        "complexity_floor_tiles_delta": floor_delta,
        "complexity_wall_tiles_delta": wall_delta,
        "complexity_spaces_delta": spaces_delta,
        # Plan-agnostic v3 keys, distinctly named so they never collide with
        # (or silently overwrite) the legacy observability fields above.
        "complexity_rooms_delta": rooms_delta,
        "complexity_fort_spaces_delta": fort_spaces_delta,
        "complexity_constructions_delta": constructions_delta,
        "complexity_progress": complexity_progress,
    }


def utility_action_progress(action: Dict[str, Any], execute_result: Dict[str, Any]) -> Dict[str, int]:
    """Accepted commands alone never prove useful work.

    Utility is derived from completed workshops and observed produced goods in
    ``utility_progress_delta``. Keeping this field at zero preserves trace
    compatibility without paying for queue or placement acceptance.
    """

    return {"utility_action_progress": 0}


def step_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized metrics from a raw environment state."""

    stocks = state.get("stocks") or {}
    hazards = state.get("hazards") or {}

    food = _to_int(stocks.get("food"))
    drink = _to_int(stocks.get("drink"))
    wealth = stocks.get("wealth")
    if wealth is None:
        wealth = state.get("wealth")
    wealth_value = _to_int(wealth, default=0) if wealth is not None else None

    hostiles_raw = state.get("hostiles")
    if hostiles_raw is None:
        risks = state.get("risks") or []
        hostiles_raw = any("hostile" in str(r).lower() for r in risks)
    if hostiles_raw is None:
        hostiles_raw = bool(hazards.get("hostiles"))

    snapshot = {
        "time": _to_int(state.get("time")),
        "pop": _to_int(state.get("population")),
        "food": food,
        "drink": drink,
        "wealth": wealth_value,
        "hostiles": bool(hostiles_raw),
        "dead": _to_int(state.get("dead"), default=0),
    }
    work = state.get("work")
    if isinstance(work, dict):
        snapshot["work"] = {
            "ok": bool(work.get("ok", False)),
            "target_rect": work.get("target_rect"),
            "target_tiles": _to_int(work.get("target_tiles")),
            "target_z": _to_int(work.get("target_z")),
            "window_x": _to_int(work.get("window_x")),
            "window_y": _to_int(work.get("window_y")),
            "window_z": _to_int(work.get("window_z")),
            "cursor_x": _to_int(work.get("cursor_x")),
            "cursor_y": _to_int(work.get("cursor_y")),
            "cursor_z": _to_int(work.get("cursor_z")),
            "target_dig_designations": _to_int(work.get("target_dig_designations")),
            "target_floor_tiles": _to_int(work.get("target_floor_tiles")),
            "target_wall_tiles": _to_int(work.get("target_wall_tiles")),
            "target_hidden_tiles": _to_int(work.get("target_hidden_tiles")),
            "target_visible_tiles": _to_int(work.get("target_visible_tiles")),
            "target_missing_blocks": _to_int(work.get("target_missing_blocks")),
            "active_jobs": _to_int(work.get("active_jobs")),
            "active_dig_jobs": _to_int(work.get("active_dig_jobs")),
            "active_construct_building_jobs": _to_int(
                work.get("active_construct_building_jobs")
            ),
            "active_carpenter_jobs": _to_int(work.get("active_carpenter_jobs")),
            "citizens_total": _to_int(work.get("citizens_total")),
            "miners_total": _to_int(work.get("miners_total")),
            "carpenter_labors_enabled": _to_int(work.get("carpenter_labors_enabled")),
            "citizens_on_target_z": _to_int(work.get("citizens_on_target_z")),
            "manager_orders_count": _to_int(work.get("manager_orders_count")),
            "manager_orders_amount_left": _to_int(work.get("manager_orders_amount_left")),
            "carpenter_workshops": _to_int(work.get("carpenter_workshops")),
            "carpenter_workshops_planned": _work_value(
                work,
                "carpenter_workshops_planned",
                fallback_key="carpenter_workshops",
            ),
            "carpenter_workshops_usable": _work_value(
                work,
                "carpenter_workshops_usable",
                fallback_key="carpenter_workshops",
            ),
            "carpenter_workshops_unproven": _to_int(
                work.get("carpenter_workshops_unproven")
            ),
            "carpenter_workshop_task_jobs": _to_int(
                work.get("carpenter_workshop_task_jobs")
            ),
            "carpenter_workshop_construction_jobs": _to_int(
                work.get("carpenter_workshop_construction_jobs")
            ),
            "carpenter_build_site": work.get("carpenter_build_site"),
            "carpenter_build_site_rect": work.get("carpenter_build_site_rect"),
            "carpenter_build_site_source": work.get("carpenter_build_site_source"),
            "fortress_plan_name": work.get("fortress_plan_name"),
            "fortress_connector_rect": work.get("fortress_connector_rect"),
            "fortress_connector_tiles": _to_int(work.get("fortress_connector_tiles")),
            "fortress_connector_floor_tiles": _to_int(
                work.get("fortress_connector_floor_tiles")
            ),
            "fortress_connector_wall_tiles": _to_int(
                work.get("fortress_connector_wall_tiles")
            ),
            "fortress_connector_hidden_tiles": _to_int(
                work.get("fortress_connector_hidden_tiles")
            ),
            "fortress_connector_missing_blocks": _to_int(
                work.get("fortress_connector_missing_blocks")
            ),
            "fortress_workshop_room_rect": work.get("fortress_workshop_room_rect"),
            "fortress_workshop_room_tiles": _to_int(
                work.get("fortress_workshop_room_tiles")
            ),
            "fortress_workshop_room_floor_tiles": _to_int(
                work.get("fortress_workshop_room_floor_tiles")
            ),
            "fortress_workshop_room_wall_tiles": _to_int(
                work.get("fortress_workshop_room_wall_tiles")
            ),
            "fortress_workshop_room_hidden_tiles": _to_int(
                work.get("fortress_workshop_room_hidden_tiles")
            ),
            "fortress_workshop_room_missing_blocks": _to_int(
                work.get("fortress_workshop_room_missing_blocks")
            ),
            "fortress_complexity_tiles": _to_int(work.get("fortress_complexity_tiles")),
            "fortress_complexity_floor_tiles": _to_int(
                work.get("fortress_complexity_floor_tiles")
            ),
            "fortress_complexity_wall_tiles": _to_int(
                work.get("fortress_complexity_wall_tiles")
            ),
            "fortress_complexity_spaces_completed": _to_int(
                work.get("fortress_complexity_spaces_completed")
            ),
        }
    ui_work = state.get("ui_work")
    if isinstance(ui_work, dict):
        snapshot["ui_work"] = {
            "ok": bool(ui_work.get("ok", False)),
            "target_rect": ui_work.get("target_rect"),
            "target_tiles": _to_int(ui_work.get("target_tiles")),
            "target_z": _to_int(ui_work.get("target_z")),
            "target_dig_designations": _to_int(ui_work.get("target_dig_designations")),
            "target_floor_tiles": _to_int(ui_work.get("target_floor_tiles")),
            "target_wall_tiles": _to_int(ui_work.get("target_wall_tiles")),
            "target_hidden_tiles": _to_int(ui_work.get("target_hidden_tiles")),
            "target_visible_tiles": _to_int(ui_work.get("target_visible_tiles")),
            "target_missing_blocks": _to_int(ui_work.get("target_missing_blocks")),
        }
    return snapshot


__all__ = [
    "step_snapshot",
    "complexity_progress_delta",
    "production_progress_delta",
    "ui_work_progress_delta",
    "utility_action_progress",
    "utility_progress_delta",
    "work_progress_delta",
]
