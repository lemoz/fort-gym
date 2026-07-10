from __future__ import annotations

import json
from pathlib import Path

from fort_gym.bench.agent.governed import DFHackGovernedScriptedAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.mock_env import MockEnvironment
from fort_gym.bench.eval.scoring import SCORE_VERSION
from fort_gym.bench.eval.summary import summarize
from fort_gym.bench.run.runner import run_once


def test_governed_agent_starts_with_starter_room_dig() -> None:
    env = MockEnvironment()
    action = DFHackGovernedScriptedAgent().decide("", env.observe())

    assert action["type"] == "DIG"
    assert action["params"] == {"area": [50, 35, 0], "size": [5, 5, 1], "kind": "dig"}
    assert action["advance_ticks"] == 1000
    assert action["objective"]


def test_governed_agent_builds_at_observed_workshop_room() -> None:
    env = MockEnvironment()
    state = env.observe()
    work = state["work"]
    work.update(
        {
            "target_floor_tiles": 25,
            "target_dig_designations": 0,
            "active_dig_jobs": 0,
            "fortress_connector_floor_tiles": 3,
            "fortress_workshop_room_floor_tiles": 25,
            "fortress_workshop_room_rect": [106, 97, 177, 110, 101, 177],
            "carpenter_workshops": 0,
        }
    )

    action = DFHackGovernedScriptedAgent().decide("", state)

    assert action["type"] == "BUILD"
    assert action["params"]["kind"] == "CarpenterWorkshop"
    assert action["params"]["x"] == 106
    assert action["params"]["y"] == 97
    assert action["params"]["z"] == 177


def test_governed_agent_advances_when_live_starter_has_no_walls() -> None:
    env = MockEnvironment()
    state = env.observe()
    work = state["work"]
    work.update(
        {
            "target_rect": [94, 91, 177, 97, 92, 177],
            "target_tiles": 8,
            "target_floor_tiles": 7,
            "target_wall_tiles": 0,
            "target_hidden_tiles": 0,
            "target_missing_blocks": 0,
            "target_dig_designations": 0,
            "active_dig_jobs": 0,
            "fortress_connector_rect": [98, 93, 177, 100, 93, 177],
            "fortress_connector_tiles": 3,
            "fortress_connector_floor_tiles": 0,
            "fortress_connector_wall_tiles": 3,
            "fortress_connector_hidden_tiles": 0,
            "fortress_connector_missing_blocks": 0,
        }
    )

    action = DFHackGovernedScriptedAgent().decide("", state)

    assert action["type"] == "DIG"
    assert action["intent"] == "dig the east connector toward the workshop room"
    assert action["params"] == {"area": [98, 93, 177], "size": [3, 1, 1], "kind": "dig"}


def test_governed_agent_builds_on_observed_site_when_annex_is_imperfect() -> None:
    env = MockEnvironment()
    state = env.observe()
    work = state["work"]
    work.update(
        {
            "target_floor_tiles": 7,
            "target_wall_tiles": 0,
            "target_hidden_tiles": 0,
            "target_missing_blocks": 0,
            "fortress_connector_floor_tiles": 3,
            "fortress_connector_wall_tiles": 0,
            "fortress_connector_hidden_tiles": 0,
            "fortress_connector_missing_blocks": 0,
            "fortress_workshop_room_tiles": 25,
            "fortress_workshop_room_floor_tiles": 17,
            "fortress_workshop_room_wall_tiles": 3,
            "fortress_workshop_room_hidden_tiles": 0,
            "fortress_workshop_room_missing_blocks": 0,
            "carpenter_build_site": [88, 96, 177],
            "carpenter_workshops": 0,
            "active_dig_jobs": 0,
        }
    )

    action = DFHackGovernedScriptedAgent().decide("", state)

    assert action["type"] == "BUILD"
    assert action["params"]["kind"] == "CarpenterWorkshop"
    assert action["params"]["x"] == 88
    assert action["params"]["y"] == 96
    assert action["params"]["z"] == 177


def test_governed_agent_orders_after_workshop_exists_despite_rough_annex() -> None:
    env = MockEnvironment()
    state = env.observe()
    work = state["work"]
    work.update(
        {
            "target_floor_tiles": 7,
            "target_wall_tiles": 0,
            "target_hidden_tiles": 0,
            "target_missing_blocks": 0,
            "fortress_connector_floor_tiles": 3,
            "fortress_connector_wall_tiles": 0,
            "fortress_connector_hidden_tiles": 0,
            "fortress_connector_missing_blocks": 0,
            "fortress_workshop_room_tiles": 25,
            "fortress_workshop_room_floor_tiles": 17,
            "fortress_workshop_room_wall_tiles": 3,
            "fortress_workshop_room_hidden_tiles": 0,
            "fortress_workshop_room_missing_blocks": 0,
            "carpenter_workshops": 1,
            "carpenter_workshops_usable": 0,
            "manager_orders_count": 0,
            "active_jobs": 0,
        }
    )

    action = DFHackGovernedScriptedAgent().decide("", state)

    assert action["type"] == "ORDER"
    assert action["params"]["job"] == "bed"


def test_governed_agent_reaches_broader_mock_fort(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()

    run_id = run_once(
        DFHackGovernedScriptedAgent(),
        backend="mock",
        model="dfhack-governed-scripted",
        max_steps=20,
        ticks_per_step=1000,
    )
    summary_path = Path(tmp_path) / run_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["completion_progress"] > 0
    assert summary["complexity_progress"] > 0
    assert summary["production_progress"] > 0
    assert summary["utility_progress"] > 0
    assert summary["rubric"]["rubric_score"] > 50
    assert "no_broader_fort_layout" not in summary["rubric"]["blockers"]


def test_summary_rubric_flags_repetitive_score_only_run(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = []
    for step in range(8):
        records.append(
            {
                "run_id": "repetitive",
                "step": step,
                "score_version": SCORE_VERSION,
                "action": {
                    "type": "ORDER",
                    "params": {"job": "bed", "quantity": 1},
                    "intent": "repeat same order",
                },
                "execute": {
                    "accepted": True,
                    "provenance": "dfhack_assisted",
                    "result": {"ok": True},
                },
                "metrics": {
                    "score_version": SCORE_VERSION,
                    "time": step * 100,
                    "run_elapsed_ticks": step * 100,
                    "pop": 7,
                    "food": 45,
                    "drink": 60,
                    "wealth": 9 + step,
                    "dead": 0,
                    "hostiles": False,
                    "work_progress": 0,
                    "completion_progress": 0,
                    "utility_progress": 0,
                    "production_progress": 0,
                    "complexity_progress": 0,
                    "score_provenance": "gameplay_only_assisted_progress_zeroed",
                },
                "tick_advance": {"ticks_advanced": 100},
                "events": [],
            }
        )
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.rubric["rubric_score"] < 50
    assert "repetitive_policy" in summary.rubric["blockers"]
    assert "illegal_or_assisted_progress_seen" in summary.rubric["blockers"]
