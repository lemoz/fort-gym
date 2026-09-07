"""Factual campaign observations, independent of benchmark strategy/review text.

Keep native completeness/error markers and the model's recent commands. Do not
invent a plan, infer food production from stocks, or replace missing facts by zero.
This is a private model observation, not a publication or secret-redaction API.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

PROFILE = "campaign_state/v1"
STATE_FIELDS = (
    "year",
    "year_tick",
    "time",
    "pause_state",
    "viewscreen_type",
    "population",
    "stocks",
    "stock_observations",
    "recent_events",
    "campaign_observation_quality",
    "workshop_placement",
)
WORK_FIELDS = (
    "ok",
    "error",
    "observation_scope",
    "active_jobs",
    "active_dig_jobs",
    "active_construct_building_jobs",
    "active_carpenter_jobs",
    "active_job_type_names",
    "manager_orders_count",
    "manager_orders_amount_left",
    "manager_orders_amount_total",
    "workshop_count",
    "carpenter_workshops",
    "carpenter_workshops_planned",
    "carpenter_workshops_usable",
    "carpenter_workshops_unproven",
    "carpenter_workshop_task_jobs",
    "carpenter_workshop_construction_jobs",
    "carpenter_workshop_task_job_type_names",
    "carpenter_workshop_construction_job_type_names",
    "carpenter_workshop_x1",
    "carpenter_workshop_y1",
    "carpenter_workshop_x2",
    "carpenter_workshop_y2",
    "carpenter_workshop_z",
    "citizens_total",
    "miners_total",
    "carpenter_labors_enabled",
    "labor_state_complete",
)
FORT_FIELDS = (
    "ok",
    "error",
    "enclosed_spaces",
    "functional_rooms",
    "spaces",
    "spaces_limit",
    "spaces_truncated",
    "component_scan_truncated",
    "building_scan_complete",
    "raw_construction_records",
    "constructions",
    "construction_tiles",
    "construction_details",
    "construction_tiles_complete",
    "pending_constructions",
    "nearby_trees",
    "player_buildings",
    "frozen_liquid_tiles",
    "vertical_access_focus",
    "access_level_maps",
    "map_origin",
    "map_rows",
)
CREW_FIELDS = (
    "ok",
    "error",
    "citizens",
    "jobs",
    "workshops",
    "workshops_truncated",
    "production_inputs",
    "goods",
    "placed_furniture",
    "placed_furniture_completed",
    "placed_furniture_positions",
    "placed_furniture_details",
    "placed_furniture_details_truncated",
    "farm_plots",
    "farm_plot_positions",
    "farm_plot_details",
    "farm_plot_details_truncated",
    "building_evidence_complete",
    "dead_citizen_count",
    "dead_citizen_records",
    "death_evidence_complete",
    "death_causes_known",
    "seeds",
    "current_season",
    "rect_tiles",
)
HISTORY_FIELDS = (
    "step",
    "action_type",
    "params",
    "intent",
    "objective",
    "plan_step",
    "advance_ticks",
    "requested_ticks",
    "actual_ticks",
    "accepted",
    "validation_rejected",
    "error",
    "failed_targets",
    "placed_targets",
    "result_details",
)
MAP_LEGEND = (
    "Map rows start at map_origin [x,y,z]; x increases rightward and y downward. "
    "Blank=hidden/unreadable, W=built wall, x=queued wall/floor, #=natural wall, "
    "T=tree trunk, b=bed, t=table, c=chair, d=door, w=workshop, o=other building, "
    ".=floor, <=up stair, >=down stair, X=up/down stair, ^=ramp, i=frozen liquid, "
    ",=shrub, s=sapling, p=boulder/pebbles, @=dwarf, ~=impassable. "
    "Glyphs are summaries; native command feedback can supply more precise tile facts."
)


def _select(value: Any, fields: tuple[str, ...]) -> dict:
    return (
        {key: deepcopy(value[key]) for key in fields if key in value}
        if isinstance(value, dict)
        else {}
    )


def encode_campaign_observation(
    state: dict,
    *,
    screen_text: str,
    action_history: list[dict],
    last_action_result: dict | None,
    model_requested_time: bool = False,
) -> tuple[str, dict]:
    observation = _select(state, STATE_FIELDS)
    observation["observation_profile"] = PROFILE
    for key, fields in (("work", WORK_FIELDS), ("fort", FORT_FIELDS), ("crew", CREW_FIELDS)):
        if key in state:
            observation[key] = _select(state[key], fields)
    observation["action_history"] = [_select(row, HISTORY_FIELDS) for row in action_history[-12:]]
    observation["last_action_result"] = deepcopy(last_action_result)
    observation["screen_text"] = screen_text
    if model_requested_time:
        observation["time_control"] = {
            "policy": "model_requested/v1",
            "semantics": (
                "Your advance_ticks requests native game time after an accepted command or a "
                "preflight rejection that made no game changes. Zero means remain paused. "
                "Partial/uncertain execution errors stop the segment without further time. "
                "Native dialogs may interrupt advancement. While a known dialog is open, "
                "non-INTERACT commands are rejected with zero advancement; choose an allowed "
                "INTERACT operation with advance_ticks=0. No fallback action is chosen for you."
            ),
        }
    return render_campaign_observation(observation), observation


def render_campaign_observation(observation: dict, *, compact: bool = False) -> str:
    """Render an already selected observation; legacy spacing remains the default."""
    last_action_result = observation.get("last_action_result")
    accepted = last_action_result.get("accepted") if isinstance(last_action_result, dict) else None
    result_label = (
        "ACCEPTED" if accepted is True else "REJECTED" if accepted is False else "UNKNOWN"
    )
    reason = last_action_result.get("why") if isinstance(last_action_result, dict) else None
    # The first three lines and the Last Action line feed checkpointable memory.
    # JSON null remains visibly unknown, never an invented zero/death/empty stock.
    lines = [
        f"Native calendar: year={observation.get('year')} tick={observation.get('year_tick')}",
        f"Population: {observation.get('population', 'unknown')}",
        "Stocks: " + json.dumps(observation.get("stocks"), sort_keys=True),
        f"Last Action: {result_label}" + ("; " + json.dumps(reason) if reason else ""),
        MAP_LEGEND,
        "Observations are bounded snapshots. Missing values, ok=false and incomplete/truncated "
        "scans are not evidence of absence. Stock changes do not measure production/consumption. "
        "Command acceptance does not establish completed work. No planning review is required.",
        "Native facts and recent commands:\n"
        + json.dumps(
            observation,
            sort_keys=True,
            separators=(",", ":") if compact else None,
            allow_nan=not compact,
        ),
    ]
    return "\n".join(lines)
