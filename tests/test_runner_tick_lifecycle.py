from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import pytest

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.mock_env import MockEnvironment
from fort_gym.bench.eval.scoring import GOVERNED_SCORE_PROGRESS_PROVENANCE
from fort_gym.bench.eval.summary import summarize
from fort_gym.bench.run.runner import (
    INTERACT_ALLOWED_VIEWSCREEN_TYPES,
    MAX_INTERACT_OPERATIONS_PER_MODAL,
    MAX_UNCHANGED_INTERACT_SCREENS,
    MIN_GOVERNED_ACTION_HISTORY,
    _effective_action_history_limit,
    _interact_context_reason,
    _interaction_terminal_reason,
    _measurement_calibration_step_limit_reached,
    _owned_excavation_snapshot_rects,
    _tick_terminal_reason,
    run_once,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.tick_receipt import TICKS_PER_YEAR


class CountingWaitAgent(Agent):
    def __init__(self, requested_ticks: int) -> None:
        self.calls = 0
        self.requested_ticks = requested_ticks
        self.observations: list[Dict[str, Any]] = []
        self.observation_texts: list[str] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.observations.append(dict(obs_json))
        self.observation_texts.append(obs_text)
        return {
            "type": "WAIT",
            "params": {},
            "intent": "exercise tick lifecycle",
            "advance_ticks": self.requested_ticks,
        }


class CountingInteractAgent(Agent):
    def __init__(self, operation: str = "confirm") -> None:
        self.calls = 0
        self.operation = operation
        self.observation_texts: list[str] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.observation_texts.append(obs_text)
        return {
            "type": "INTERACT",
            "params": {"operation": self.operation},
            "intent": "advance the visible dialog by one bounded input",
            "advance_ticks": 0,
        }


class WaitThenInteractAgent(Agent):
    def __init__(self, operation: str = "confirm") -> None:
        self.calls = 0
        self.operation = operation
        self.actions: list[Dict[str, Any]] = []
        self.observations: list[Dict[str, Any]] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.observations.append(dict(obs_json))
        if self.calls == 1:
            action = {
                "type": "WAIT",
                "params": {},
                "intent": "allow bounded governed tick polling",
                "advance_ticks": 15,
            }
        else:
            action = {
                "type": "INTERACT",
                "params": {"operation": self.operation},
                "intent": "handle the freshly observed dialog",
                "advance_ticks": 0,
            }
        self.actions.append(action)
        return action


class RepeatingRawActionAgent(Agent):
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


class OneOrderAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "ORDER",
            "params": {"job": "bed", "quantity": 1},
            "intent": "queue one bed",
            "advance_ticks": 10,
        }


class OneDigAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "DIG",
            "params": {"kind": "dig", "area": [10, 20, 5], "size": [1, 1, 1]},
            "intent": "prove one native completed excavation",
            "advance_ticks": 10,
        }


class OneLaborAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "LABOR",
            "params": {"unit_id": 1, "labor": "farming", "enable": True},
            "intent": "toggle one legal labor",
            "advance_ticks": 10,
        }


class OneWorkshopAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "BUILD",
            "params": {
                "kind": "CarpenterWorkshop",
                "x": 10,
                "y": 20,
                "z": 5,
            },
            "intent": "build one exactly tracked workshop",
            "advance_ticks": 10,
        }


class WorkshopThenWaitAgent(Agent):
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return OneWorkshopAgent().decide(obs_text, obs_json)
        return {
            "type": "WAIT",
            "params": {},
            "intent": "let the exactly owned workshop finish natively",
            "advance_ticks": 10,
        }


class DigThenWaitAgent(Agent):
    def __init__(self) -> None:
        self.calls = 0
        self.observation_texts: list[str] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.observation_texts.append(obs_text)
        if self.calls == 1:
            return {
                "type": "DIG",
                "params": {"kind": "dig", "area": [10, 20, 5], "size": [1, 1, 1]},
                "intent": "designate one native excavation",
                "advance_ticks": 10,
            }
        return {
            "type": "WAIT",
            "params": {},
            "intent": "let the owned native job finish",
            "advance_ticks": 10,
        }


class RaisingDecisionAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("review contract exhausted")


class ClassifiedDecisionError(RuntimeError):
    terminal_code = "provider_content_filter"
    terminal_details = {
        "finish_reasons": ["content_filter"],
        "attempts": 3,
        "code": "must_not_override",
    }


class RaisingClassifiedDecisionAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        raise ClassifiedDecisionError("provider blocked the governed action response")


def _advance_state_calendar(state: Dict[str, Any], ticks: int) -> None:
    year = int(state.get("year") or 0)
    year_tick = int(state.get("year_tick", state.get("time", 0)) or 0)
    absolute = year * TICKS_PER_YEAR + year_tick + max(0, ticks)
    state["year"] = absolute // TICKS_PER_YEAR
    state["year_tick"] = absolute % TICKS_PER_YEAR
    state["time"] = state["year_tick"]


def _run_dfhack_tick_fixture(
    tmp_path: Path,
    monkeypatch,
    tick_infos: Iterable[Dict[str, Any]],
    *,
    max_steps: int,
    requested_ticks: int = 10,
) -> tuple[CountingWaitAgent, RunRegistry, str]:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    state = MockEnvironment().observe()
    tick_info_sequence = iter(tick_infos)

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            self.last_tick_info: Dict[str, Any] = {}

        def connect(self) -> None:
            return None

        def pause(self) -> None:
            return None

        def advance(self, ticks: int) -> Dict[str, Any]:
            self.last_tick_info = dict(next(tick_info_sequence))
            _advance_state_calendar(
                state, int(self.last_tick_info.get("ticks_advanced") or 0)
            )
            return dict(state)

        def close(self) -> None:
            return None

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.StateReader.from_dfhack",
        lambda _: dict(state),
    )

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="fake",
        max_steps=max_steps,
        ticks_per_step=requested_ticks,
    )
    agent = CountingWaitAgent(requested_ticks)
    run_id = run_once(
        agent,
        backend="dfhack",
        model="fake",
        max_steps=max_steps,
        ticks_per_step=requested_ticks,
        run_id=created.run_id,
        registry=registry,
        preserve_save=True,
    )
    return agent, registry, run_id


def _trace_rows(tmp_path: Path, run_id: str) -> list[Dict[str, Any]]:
    trace_path = tmp_path / run_id / "trace.jsonl"
    return [json.loads(line) for line in trace_path.read_text().splitlines()]


def test_measurement_calibration_step_limit_stops_after_final_durable_row() -> None:
    assert _measurement_calibration_step_limit_reached(step=0, limit=1) is True
    assert _measurement_calibration_step_limit_reached(step=0, limit=2) is False
    assert _measurement_calibration_step_limit_reached(step=199, limit=200) is True
    assert _measurement_calibration_step_limit_reached(step=199, limit=None) is False


def test_duplicate_worker_cannot_touch_an_already_claimed_trace(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="mock", model="fake", max_steps=1, ticks_per_step=0
    )
    assert registry.claim_pending_run(created.run_id, started_at=datetime.utcnow())
    trace_path = tmp_path / created.run_id / "trace.jsonl"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text("original trace\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="cannot be claimed"):
        run_once(
            CountingWaitAgent(0),
            backend="mock",
            model="fake",
            max_steps=1,
            ticks_per_step=0,
            run_id=created.run_id,
            registry=registry,
        )

    assert trace_path.read_text(encoding="utf-8") == "original trace\n"
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_positive_ticks_with_unverified_repause_are_terminal(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [
            {
                "ok": False,
                "error": "repause_unverified",
                "ticks_advanced": 10,
                "repause_requested": True,
                "repause_effective": False,
            }
        ],
        max_steps=2,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert agent.calls == 1
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "tick_repause_unverified"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["terminal_reason"]["ticks_advanced"] == 10

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_work_metrics_setup_failure_cleans_runtime_before_failed_status(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    lifecycle_events: list[str] = []

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            return None

        def connect(self) -> None:
            lifecycle_events.append("client_connected")

        def set_work_metrics_global_only(self, enabled: bool) -> None:
            assert enabled is True
            raise RuntimeError("work metrics setup failed")

        def pause(self) -> None:
            lifecycle_events.append("client_paused")

        def close(self) -> None:
            lifecycle_events.append("client_closed")

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.start_g7_evidence",
        lambda run_id: (
            lifecycle_events.append("evidence_started")
            or {"ok": True, "active": True, "run_id": run_id}
        ),
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.stop_g7_evidence",
        lambda: (
            lifecycle_events.append("evidence_stopped") or {"ok": True, "active": False}
        ),
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=1,
        ticks_per_step=10,
    )
    original_set_status = registry.set_status

    def tracked_set_status(run_id, **kwargs):
        if kwargs.get("status") in {"stopped", "failed", "completed"}:
            lifecycle_events.append(f"status_{kwargs['status']}")
        return original_set_status(run_id, **kwargs)

    monkeypatch.setattr(registry, "set_status", tracked_set_status)

    with pytest.raises(RuntimeError, match="work metrics setup failed"):
        run_once(
            CountingWaitAgent(10),
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=1,
            ticks_per_step=10,
            run_id=created.run_id,
            registry=registry,
            preserve_save=True,
        )

    loaded = registry.get(created.run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert lifecycle_events == [
        "client_connected",
        "client_paused",
        "client_closed",
        "status_failed",
    ]
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_disabled_dfhack_setup_does_not_leave_claimed_run_running(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=1,
        ticks_per_step=10,
    )

    with pytest.raises(RuntimeError, match="DFHack backend disabled"):
        run_once(
            CountingWaitAgent(10),
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=1,
            ticks_per_step=10,
            run_id=created.run_id,
            registry=registry,
            preserve_save=True,
        )

    loaded = registry.get(created.run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert "cleanup_completed_at" in loaded.metadata
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_run_rejects_assisted_dig_before_connecting(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    monkeypatch.setenv("FORT_GYM_DFHACK_COMPLETE_DIG", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    connected = False

    class UnexpectedDFHackClient:
        def __init__(self, **_: Any) -> None:
            nonlocal connected
            connected = True

    monkeypatch.setattr(
        "fort_gym.bench.run.runner.DFHackClient", UnexpectedDFHackClient
    )

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=1,
        ticks_per_step=10,
    )

    with pytest.raises(RuntimeError, match="forbid.*FORT_GYM_DFHACK_COMPLETE_DIG"):
        run_once(
            CountingWaitAgent(10),
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=1,
            ticks_per_step=10,
            run_id=created.run_id,
            registry=registry,
            preserve_save=True,
        )

    loaded = registry.get(created.run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert connected is False
    assert "cleanup_completed_at" in loaded.metadata
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _run_governed_interact_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    screen_changes: bool,
    max_steps: int = 20,
    agent_override: Agent | None = None,
    stale_evidence: bool = False,
    lifecycle_events: list[str] | None = None,
    stop_after_execute: bool = False,
    stop_after_advance: bool = False,
    stop_during_cleanup: bool = False,
    observe_error: bool = False,
    cleanup_error: bool = False,
    operation: str = "confirm",
    viewscreen_type: str = "viewscreen_textviewerst",
    screen_text: str = "dialog screen",
    screen_capture_fails_after: bool = False,
    prepare_target_callback: Any | None = None,
    job_metrics_callback: Any | None = None,
    fort_metrics_callback: Any | None = None,
    map_snapshot_callback: Any | None = None,
    advance_callback: Any | None = None,
    advance_tick_info: Dict[str, Any] | None = None,
    advance_options: list[Dict[str, Any]] | None = None,
) -> tuple[Agent, RunRegistry, str]:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    raw_state = MockEnvironment().observe()
    raw_state.update(
        {
            "pause_state": True,
            "viewscreen_type": viewscreen_type,
            "year": 0,
            "year_tick": int(raw_state.get("time") or 0),
        }
    )
    screen_version = [0]
    interaction_sent = [False]

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            self.last_tick_info: Dict[str, Any] = {}

        def connect(self) -> None:
            return None

        def set_work_metrics_global_only(self, enabled: bool) -> None:
            assert enabled is True

        def pause(self) -> None:
            raw_state["pause_state"] = True

        def get_state(self) -> Dict[str, Any]:
            if observe_error:
                raise RuntimeError("unexpected observation failure")
            return dict(raw_state)

        def advance(self, ticks: int, **kwargs: Any) -> Dict[str, Any]:
            if advance_options is not None:
                advance_options.append(dict(kwargs))
            self.last_tick_info = dict(
                advance_tick_info or {"ok": True, "ticks_advanced": ticks}
            )
            _advance_state_calendar(
                raw_state, int(self.last_tick_info.get("ticks_advanced") or 0)
            )
            if advance_callback is not None:
                advance_callback(ticks, raw_state)
            if stop_after_advance:
                assert registry.request_stop(created.run_id) is True
            return dict(raw_state)

        def get_screen_text(self, *, include_visual_hints: bool = False) -> str:
            assert include_visual_hints is True
            if screen_capture_fails_after and interaction_sent[0]:
                raise RuntimeError("screen unavailable")
            return f"{screen_text} {screen_version[0]}"

        def close(self) -> None:
            if lifecycle_events is not None:
                lifecycle_events.append("client_closed")
            if stop_during_cleanup:
                assert registry.request_stop(created.run_id) is True
            return None

    def fake_execute(keys: list[str]) -> Dict[str, Any]:
        if operation == "finish_topic_meeting":
            expected_key = "OPTION1"
        elif operation == "cancel":
            expected_key = "LEAVESCREEN"
        elif operation.startswith("topic_option_"):
            expected_key = f"OPTION{'abcdefgh'.index(operation[-1]) + 1}"
        else:
            expected_key = "SELECT"
        assert keys == [expected_key]
        interaction_sent[0] = True
        if screen_changes:
            screen_version[0] += 1
            if operation in {"cancel", "finish_topic_meeting"}:
                raw_state["viewscreen_type"] = "viewscreen_dwarfmodest"
        return {"ok": True, "keys_sent": 1}

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.prepare_keystroke_target",
        prepare_target_callback or (lambda *args, **kwargs: {"ok": False}),
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_job_metrics",
        job_metrics_callback or (lambda: {"ok": False}),
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_fort_metrics",
        fort_metrics_callback or (lambda _focus=None: {"ok": False}),
    )
    if map_snapshot_callback is not None:
        monkeypatch.setattr(
            "fort_gym.bench.run.runner.read_map_snapshot",
            map_snapshot_callback,
        )
    evidence_run_id: list[str | None] = [None]

    def fake_start_g7(run_id: str) -> Dict[str, Any]:
        evidence_run_id[0] = run_id
        return {"ok": True, "active": True, "run_id": run_id}

    monkeypatch.setattr(
        "fort_gym.bench.run.runner.start_g7_evidence",
        fake_start_g7,
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_g7_evidence",
        lambda: {
            "ok": True,
            "active": True,
            "run_id": "stale-run" if stale_evidence else evidence_run_id[0],
        },
    )

    def fake_stop_g7() -> Dict[str, Any]:
        if lifecycle_events is not None:
            lifecycle_events.append("evidence_stopped")
        if cleanup_error:
            return {"ok": False, "active": True, "error": "callback detach failed"}
        return {"ok": True, "active": False}

    monkeypatch.setattr(
        "fort_gym.bench.run.runner.stop_g7_evidence",
        fake_stop_g7,
    )
    monkeypatch.setattr(
        "fort_gym.bench.env.executor.execute_keystroke_action",
        fake_execute,
    )

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=max_steps,
        ticks_per_step=10,
    )
    if stop_after_execute:

        def stop_from_labor(*_args) -> Dict[str, Any]:
            assert registry.request_stop(created.run_id) is True
            return {"ok": True, "labor_changed": True}

        monkeypatch.setattr(
            "fort_gym.bench.env.executor.safe_set_labor",
            stop_from_labor,
        )
    agent = agent_override or CountingInteractAgent(operation)
    run_id = run_once(
        agent,
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=max_steps,
        ticks_per_step=10,
        run_id=created.run_id,
        registry=registry,
        preserve_save=True,
    )
    return agent, registry, run_id


def test_governed_runner_scores_only_completed_owned_excavation(
    tmp_path, monkeypatch
) -> None:
    tile_state = {"value": "wall"}

    def fake_designate(*_args):
        tile_state["value"] = "designated"
        return {"ok": True, "newly_designated": 1, "already_designated": 0}

    def complete_after_advance(_ticks: int, _state: Dict[str, Any]) -> None:
        tile_state["value"] = "floor"

    def fort_metrics(_focus=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "map_origin": [10, 20, 5],
            "map_rows": ["#"],
            "enclosed_spaces": 0,
            "functional_rooms": 0,
            "constructions": 0,
        }

    def map_snapshot(rect) -> Dict[str, Any]:
        x1, y1, z1, x2, y2, z2 = rect
        tiles = []
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                tile = {
                    "x": x,
                    "y": y,
                    "z": z1,
                    "category": "floor",
                    "shape": "FLOOR",
                    "material": "SOIL",
                    "dig": "No",
                    "hidden": False,
                }
                if (x, y, z1) == (10, 20, 5):
                    if tile_state["value"] == "wall":
                        tile.update(category="wall", shape="WALL")
                    elif tile_state["value"] == "designated":
                        tile.update(category="dig", shape="WALL", dig="Default")
                tiles.append(tile)
        return {"ok": True, "rect": list(rect), "tiles": tiles}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_designate_rect", fake_designate
    )
    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneDigAgent(),
        fort_metrics_callback=fort_metrics,
        map_snapshot_callback=map_snapshot,
        advance_callback=complete_after_advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["metrics"]["observed_global_work_progress"] == 0
    assert row["metrics"]["governed_owned_excavation_tiles"] == 1
    assert row["metrics"]["governed_owned_work_progress"] == 1
    assert row["metrics"]["work_progress"] == 1
    assert row["metrics"]["completion_progress"] == 1
    assert row["gameplay_proof"]["ok"] is True
    assert row["gameplay_proof"]["owned_completion_observation"]["completed_tiles"] == [
        {"coordinate": [10, 20, 5], "kind": "dig"}
    ]
    assert (
        row["metrics"]["score_progress_provenance"]
        == GOVERNED_SCORE_PROGRESS_PROVENANCE
    )
    assert (
        row["gameplay_proof"]["action_footprint"]["owned_delta"][
            "governed_step_completion_progress"
        ]
        == 1
    )


def test_governed_runner_does_not_reuse_stale_fort_metrics_after_failed_read(
    tmp_path, monkeypatch
) -> None:
    reads = {"count": 0}

    def fort_metrics(_focus=None) -> Dict[str, Any]:
        reads["count"] += 1
        if reads["count"] == 1:
            return {
                "ok": True,
                "enclosed_spaces": 3,
                "functional_rooms": 3,
                "constructions": 12,
            }
        return {"ok": False, "error": "read_failed"}

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=CountingWaitAgent(10),
        fort_metrics_callback=fort_metrics,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["observation"]["fort"]["functional_rooms"] == 3
    assert row["state_after_advance"]["fort"] == {
        "ok": False,
        "error": "read_failed",
    }
    assert row["metrics"]["fort_metrics_observed"] is False
    assert row["metrics"]["fort_enclosed_spaces"] == 0
    assert row["metrics"]["fort_functional_rooms"] == 0
    assert row["metrics"]["fort_constructions"] == 0

    summary = json.loads((tmp_path / run_id / "summary.json").read_text())
    assert summary["fort_enclosed_spaces"] == 0
    assert summary["fort_functional_rooms"] == 0
    assert "no_fort_structure" in summary["rubric"]["blockers"]


def test_governed_stop_after_advance_keeps_current_fort_attestation(
    tmp_path, monkeypatch
) -> None:
    def fort_metrics(_focus=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "enclosed_spaces": 2,
            "functional_rooms": 2,
            "constructions": 8,
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=2,
        agent_override=CountingWaitAgent(10),
        fort_metrics_callback=fort_metrics,
        stop_after_advance=True,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["stopped"]["reason"] == "stop_requested_after_advance"
    assert row["state_after_advance"]["fort"]["ok"] is True
    assert row["metrics"]["fort_metrics_observed"] is True
    assert row["metrics"]["fort_enclosed_spaces"] == 2
    assert row["metrics"]["fort_functional_rooms"] == 2
    assert row["metrics"]["fort_constructions"] == 8


def test_governed_stop_after_execute_marks_missing_post_action_fort_observation(
    tmp_path, monkeypatch
) -> None:
    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=True,
        max_steps=2,
        agent_override=OneLaborAgent(),
        stop_after_execute=True,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["stopped"]["reason"] == "stop_requested_after_execute"
    assert row["metrics"]["fort_metrics_observed"] is False
    assert row["metrics"]["fort_enclosed_spaces"] == 0
    assert row["metrics"]["fort_functional_rooms"] == 0
    assert row["metrics"]["fort_constructions"] == 0


def test_governed_runner_keeps_unowned_global_progress_audit_only(
    tmp_path, monkeypatch
) -> None:
    advanced = {"value": False}

    def advance(_ticks: int, state: Dict[str, Any]) -> None:
        advanced["value"] = True
        state["work"] = {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 1,
        }

    def job_metrics(_rect=None) -> Dict[str, Any]:
        if not advanced["value"]:
            return {
                "ok": True,
                "jobs": {"total": 0, "active_ids": [], "active_ids_truncated": False},
                "goods": {"bed": 0},
                "workshops": [],
                "farm_plot_details": [],
            }
        return {
            "ok": True,
            "jobs": {"total": 0, "active_ids": [], "active_ids_truncated": False},
            "goods": {"bed": 1},
            "workshops": [
                {
                    "id": 999,
                    "subtype": "Carpenters",
                    "stage_read_ok": True,
                    "stage": 3,
                    "max_stage": 3,
                    "built": True,
                }
            ],
            "farm_plot_details": [],
        }

    def fort_metrics(_focus=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "map_origin": [10, 20, 5],
            "map_rows": ["#"],
            "enclosed_spaces": 1 if advanced["value"] else 0,
            "functional_rooms": 1 if advanced["value"] else 0,
            "constructions": 1 if advanced["value"] else 0,
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=CountingWaitAgent(10),
        job_metrics_callback=job_metrics,
        fort_metrics_callback=fort_metrics,
        advance_callback=advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["metrics"]["observed_global_utility_progress"] > 0
    assert row["metrics"]["observed_global_production_progress"] > 0
    assert row["metrics"]["observed_global_complexity_progress"] > 0
    assert row["metrics"]["utility_progress"] == 0
    assert row["metrics"]["production_progress"] == 0
    assert row["metrics"]["complexity_progress"] == 0
    assert row["metrics"]["governed_owned_buildings"] == 0
    assert row["metrics"]["score_duration_blocked"] is True
    assert row["metrics"]["run_elapsed_ticks"] == 0

    summary = json.loads((tmp_path / run_id / "summary.json").read_text())
    assert summary["utility_progress"] == 0
    assert summary["production_progress"] == 0
    assert summary["complexity_progress"] == 0
    assert summary["rubric"]["progress_provenance"] == (
        GOVERNED_SCORE_PROGRESS_PROVENANCE
    )
    assert "no_fort_structure" in summary["rubric"]["blockers"]
    assert "no_production_surface" in summary["rubric"]["blockers"]
    assert "no_broader_fort_layout" in summary["rubric"]["blockers"]


def test_governed_runner_credits_exact_owned_completed_workshop(
    tmp_path, monkeypatch
) -> None:
    advanced = {"value": False}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_workshop",
        lambda *_args: {
            "ok": True,
            "building_id": 42,
            "before_carpenter_workshops": 0,
            "after_carpenter_workshops": 1,
        },
    )

    def advance(_ticks: int, state: Dict[str, Any]) -> None:
        advanced["value"] = True
        state["work"] = {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 1,
        }

    def job_metrics(_rect=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "jobs": {"total": 0, "active_ids": [], "active_ids_truncated": False},
            "goods": {"bed": 0},
            "workshops": (
                [
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 3,
                        "max_stage": 3,
                        "built": True,
                    }
                ]
                if advanced["value"]
                else []
            ),
            "farm_plot_details": [],
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneWorkshopAgent(),
        job_metrics_callback=job_metrics,
        advance_callback=advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["metrics"]["governed_owned_buildings"] == 1
    assert row["metrics"]["governed_owned_completed_building_ids"] == [42]
    assert row["metrics"]["governed_owned_utility_progress"] == 0
    assert row["metrics"]["governed_owned_production_progress"] == 1
    assert row["metrics"]["utility_progress"] == 0
    assert row["metrics"]["production_progress"] == 1
    assert row["metrics"]["score_duration_blocked"] is False
    assert row["gameplay_proof"]["owned_building_completion_observation"] == {
        "source": "job_metrics_exact_building_id_and_native_stage",
        "completed_buildings": [{"building_id": 42, "kind": "CarpenterWorkshop"}],
    }


def test_governed_runner_rejects_fail_open_zero_stage_workshop_read(
    tmp_path, monkeypatch
) -> None:
    advanced = {"value": False}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_workshop",
        lambda *_args: {
            "ok": True,
            "building_id": 42,
            "before_carpenter_workshops": 0,
            "after_carpenter_workshops": 1,
        },
    )

    def advance(_ticks: int, state: Dict[str, Any]) -> None:
        advanced["value"] = True
        state["work"] = {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 1,
        }

    def job_metrics(_rect=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "jobs": {"total": 0, "active_ids": [], "active_ids_truncated": False},
            "goods": {"bed": 0},
            "workshops": (
                [
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": False,
                        "stage": 0,
                        "max_stage": 0,
                        "built": True,
                    }
                ]
                if advanced["value"]
                else []
            ),
            "farm_plot_details": [],
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneWorkshopAgent(),
        job_metrics_callback=job_metrics,
        advance_callback=advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["metrics"]["observed_global_utility_progress"] > 0
    assert row["metrics"]["governed_owned_buildings"] == 1
    assert row["metrics"]["governed_owned_completed_buildings"] == 0
    assert row["metrics"]["utility_progress"] == 0
    assert row["metrics"]["production_progress"] == 0
    assert row["metrics"]["score_duration_blocked"] is True


def test_governed_runner_persists_owned_building_until_later_native_completion(
    tmp_path, monkeypatch
) -> None:
    advances = {"value": 0}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_workshop",
        lambda *_args: {
            "ok": True,
            "building_id": 42,
            "before_carpenter_workshops": 0,
            "after_carpenter_workshops": 1,
        },
    )

    def advance(_ticks: int, state: Dict[str, Any]) -> None:
        advances["value"] += 1
        state["work"] = {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": int(advances["value"] >= 2),
        }

    def job_metrics(_rect=None) -> Dict[str, Any]:
        return {
            "ok": True,
            "jobs": {"total": 0, "active_ids": [], "active_ids_truncated": False},
            "goods": {"bed": 0},
            "workshops": (
                [
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 3 if advances["value"] >= 2 else 2,
                        "max_stage": 3,
                        "built": advances["value"] >= 2,
                    }
                ]
                if advances["value"] >= 1
                else []
            ),
            "farm_plot_details": [],
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=2,
        agent_override=WorkshopThenWaitAgent(),
        job_metrics_callback=job_metrics,
        advance_callback=advance,
    )

    first, second = _trace_rows(tmp_path, run_id)
    assert first["metrics"]["governed_owned_buildings"] == 1
    assert first["metrics"]["governed_owned_completed_buildings"] == 0
    assert first["metrics"]["utility_progress"] == 0
    assert first["metrics"]["score_duration_blocked"] is True
    assert second["action"]["type"] == "WAIT"
    assert second["metrics"]["governed_owned_completed_building_ids"] == [42]
    assert second["metrics"]["utility_progress"] == 0
    assert second["metrics"]["production_progress"] == 1
    assert second["metrics"]["score_duration_blocked"] is False
    assert second["gameplay_proof"]["owned_prior_action_effect_observed"] is True


def test_owned_excavation_snapshot_rects_are_bounded_and_camera_independent() -> None:
    owned = {
        (1, 2, 5): "dig",
        (63, 60, 5): "dig",
        (64, 2, 5): "channel",
        (130, 130, 4): "dig",
    }

    rects = _owned_excavation_snapshot_rects(owned)

    assert rects == [
        (130, 130, 4, 130, 130, 4),
        (1, 2, 5, 63, 60, 5),
        (64, 2, 5, 64, 2, 5),
    ]
    assert all(
        x2 - x1 + 1 <= 64 and y2 - y1 + 1 <= 64 for x1, y1, _, x2, y2, _ in rects
    )


def test_governed_runner_retains_owned_dig_through_job_assignment_and_off_camera_completion(
    tmp_path, monkeypatch
) -> None:
    tile_state = {"value": "wall"}
    advance_count = {"value": 0}

    def fake_designate(*_args):
        tile_state["value"] = "designated"
        return {"ok": True, "newly_designated": 1, "already_designated": 0}

    def advance(_ticks: int, _state: Dict[str, Any]) -> None:
        advance_count["value"] += 1
        tile_state["value"] = "assigned" if advance_count["value"] == 1 else "floor"

    def fort_metrics(_focus=None) -> Dict[str, Any]:
        # The replay/camera window never contains the owned coordinate.
        return {
            "ok": True,
            "map_origin": [50, 50, 5],
            "map_rows": ["#"],
            "enclosed_spaces": 0,
            "functional_rooms": 0,
            "constructions": 0,
        }

    def map_snapshot(rect) -> Dict[str, Any]:
        x1, y1, z1, x2, y2, _ = rect
        tiles = []
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                tile = {
                    "x": x,
                    "y": y,
                    "z": z1,
                    "category": "floor",
                    "shape": "FLOOR",
                    "material": "SOIL",
                    "dig": "No",
                    "hidden": False,
                }
                if (x, y, z1) == (10, 20, 5):
                    if tile_state["value"] in {"wall", "assigned"}:
                        tile.update(category="wall", shape="WALL")
                    elif tile_state["value"] == "designated":
                        tile.update(category="dig", shape="WALL", dig="Default")
                tiles.append(tile)
        return {"ok": True, "rect": list(rect), "tiles": tiles}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_designate_rect", fake_designate
    )
    dig_agent = DigThenWaitAgent()
    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=3,
        agent_override=dig_agent,
        fort_metrics_callback=fort_metrics,
        map_snapshot_callback=map_snapshot,
        advance_callback=advance,
    )

    first, second, _third = _trace_rows(tmp_path, run_id)
    assert first["metrics"]["governed_owned_excavation_tiles"] == 1
    assert first["metrics"]["governed_owned_completion_progress"] == 0
    assert first["metrics"]["score_duration_blocked"] is True
    assert first["gameplay_proof"]["ok"] is False
    assert second["action"]["type"] == "WAIT"
    assert second["metrics"]["governed_owned_completion_progress"] == 1
    assert second["metrics"]["work_progress"] == 1
    assert second["metrics"]["score_duration_blocked"] is False
    assert second["gameplay_proof"]["ok"] is True
    assert second["gameplay_proof"]["owned_prior_action_effect_observed"] is True
    assert second["execute"]["governed_wait_effect_observed"] is True
    assert second["gameplay_proof"]["owned_completion_observation"][
        "completed_tiles"
    ] == [{"coordinate": [10, 20, 5], "kind": "dig"}]
    assert (
        "step=0 outcome=action_pending expected_review_verdict=partial"
        in dig_agent.observation_texts[1]
    )
    assert (
        "step=1 outcome=gameplay_state_changed expected_review_verdict=progressed"
        in dig_agent.observation_texts[2]
    )


def test_governed_runner_quarantines_unverified_rollback_before_advancing(
    tmp_path, monkeypatch
) -> None:
    advances = {"value": 0}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_designate_rect",
        lambda *_args: {
            "ok": False,
            "error": "designation_write_failed",
            "rollback_verified": False,
        },
    )

    def advance(_ticks: int, _state: Dict[str, Any]) -> None:
        advances["value"] += 1

    def map_snapshot(rect) -> Dict[str, Any]:
        x, y, z, *_ = rect
        return {
            "ok": True,
            "rect": list(rect),
            "tiles": [
                {
                    "x": x,
                    "y": y,
                    "z": z,
                    "category": "wall",
                    "shape": "WALL",
                    "material": "SOIL",
                    "dig": "No",
                    "hidden": False,
                }
            ],
        }

    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneDigAgent(),
        map_snapshot_callback=map_snapshot,
        advance_callback=advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    loaded = registry.get(run_id)
    assert advances["value"] == 0
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert row["terminal_reason"]["code"] == "governed_rollback_unverified"
    assert row["state_after_advance"]["fort"] == {
        "ok": False,
        "error": "post_action_fort_observation_skipped",
        "reason": "governed_rollback_unverified",
    }
    assert row["metrics"]["fort_metrics_observed"] is False
    assert loaded is not None and loaded.status == "failed"


def test_governed_runner_quarantines_explicit_rollback_failure_without_flag(
    tmp_path, monkeypatch
) -> None:
    advances = {"value": 0}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_workshop",
        lambda *_args: {
            "ok": False,
            "error": "rollback_failed",
            "building_id": 42,
        },
    )

    def advance(_ticks: int, _state: Dict[str, Any]) -> None:
        advances["value"] += 1

    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneWorkshopAgent(),
        advance_callback=advance,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    loaded = registry.get(run_id)
    assert advances["value"] == 0
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert row["terminal_reason"]["code"] == "governed_rollback_unverified"
    assert row["terminal_reason"]["helper_error"] == "rollback_failed"
    assert row["metrics"]["fort_metrics_observed"] is False
    assert loaded is not None and loaded.status == "failed"


def test_vanished_order_jobs_remain_ineligible_in_complete_trace(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_queue_manager_order",
        lambda job, qty: {
            "ok": True,
            "created_job_ids": [501],
            "item": job,
            "qty": qty,
        },
    )

    def empty_jobs(_rect=None):
        return {
            "ok": True,
            "jobs": {
                "total": 0,
                "active_ids": [],
                "active_ids_truncated": False,
                "order_jobs": [],
                "order_jobs_truncated": False,
            },
            "goods": {"bed": 0},
            "workshops": [],
        }

    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=OneOrderAgent(),
        job_metrics_callback=empty_jobs,
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["score_version"] == 5
    assert row["score"]["version"] == 5
    assert row["metrics"]["score_version"] == 5
    score_event = next(event for event in row["events"] if event["type"] == "score")
    assert score_event["data"]["version"] == 5
    assert row["execute"]["accepted"] is True
    assert row["execute"]["gameplay_progress_eligible"] is False
    assert row["metrics"]["gameplay_progress_eligible"] is False
    assert row["metrics"]["governed_dfhack_progress"] is False
    assert row["gameplay_proof"]["ok"] is False
    assert row["gameplay_proof"]["action_effect"]["status"] == "no_progress"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_runner_never_requests_workshop_candidate(
    tmp_path,
    monkeypatch,
) -> None:
    target_calls = 0

    def prepare_target(mode: str, **_: Any) -> Dict[str, Any]:
        nonlocal target_calls
        target_calls += 1
        raise AssertionError(f"governed runner requested external {mode} target")

    agent = CountingWaitAgent(10)
    _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=2,
        agent_override=agent,
        prepare_target_callback=prepare_target,
    )

    assert len(agent.observations) == 2
    assert target_calls == 0
    assert all(
        "carpenter_build_site" not in observation.get("work", {})
        for observation in agent.observations
    )


def test_zero_progress_timeout_is_terminal_before_another_agent_decide(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [{"ok": False, "timeout": True, "ticks_advanced": 0}],
        max_steps=3,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "tick_timeout_zero_progress"
    reopened = RunRegistry(db_path=tmp_path / "runs.sqlite3").get(run_id)
    assert reopened is not None
    assert reopened.metadata["terminal_reason"] == loaded.metadata["terminal_reason"]

    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == 1
    assert rows[0]["action"]["type"] == "WAIT"
    assert rows[0]["tick_advance"]["ticks_advanced"] == 0
    assert rows[0]["terminal_reason"] == loaded.metadata["terminal_reason"]
    assert any(event["type"] == "terminal" for event in rows[0]["events"])
    assert (tmp_path / run_id / "summary.json").is_file()

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_partial_timeout_is_degraded_and_allows_next_agent_decide(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [
            {"ok": False, "timeout": True, "ticks_advanced": 915},
            {"ok": True, "ticks_advanced": 1},
        ],
        max_steps=2,
    )

    assert agent.calls == 2
    assert agent.observations[1]["time"] == 915
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert "terminal_reason" not in loaded.metadata

    rows = _trace_rows(tmp_path, run_id)
    assert rows[0]["tick_degraded"]["code"] == "partial_tick_timeout"
    assert rows[0]["tick_degraded"]["ticks_advanced"] == 915
    assert not any(event["type"] == "terminal" for event in rows[0]["events"])

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_viewscreen_interruption_is_degraded_and_reobserved(
    tmp_path, monkeypatch
) -> None:
    agent = WaitThenInteractAgent(operation="cancel")
    advance_options: list[Dict[str, Any]] = []

    def interrupt_with_modal(_ticks: int, state: Dict[str, Any]) -> None:
        state["pause_state"] = True
        state["viewscreen_type"] = "viewscreen_textviewerst"

    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=2,
        agent_override=agent,
        viewscreen_type="viewscreen_dwarfmodest",
        advance_callback=interrupt_with_modal,
        advance_tick_info={
            "ok": False,
            "error": "blocking_viewscreen_transition",
            "interrupted": True,
            "requested": 15,
            "ticks_advanced": 0,
            "start_year": 0,
            "start_tick": 0,
            "end_year": 0,
            "end_tick": 0,
            "paused_before": True,
            "paused_after": True,
            "viewscreen_before": "viewscreen_dwarfmodest",
            "viewscreen_after": "viewscreen_textviewerst",
            "repause_requested": True,
            "repause_effective": True,
            "repause": {
                "ok": True,
                "paused": True,
                "attempts": 1,
                "attempt_records": [
                    {"attempt": 1, "nopause_disabled": True, "paused": True}
                ],
            },
            "interrupt_safety_error": False,
            "calendar_safety_error": False,
            "final_pause_state": True,
            "final_viewscreen_type": "viewscreen_textviewerst",
            "intermediate_probe_error": "calendar_sample_read_failed",
            "intermediate_probe_phase": "poll",
            "intermediate_probe_failure_kind": "dfhack_error",
            "interruption_detection": "final_attestation",
        },
        advance_options=advance_options,
        operation="cancel",
    )

    assert agent.calls == 2
    assert agent.actions[1]["type"] == "INTERACT"
    assert agent.actions[1]["params"]["operation"] == "cancel"
    assert agent.actions[1]["advance_ticks"] == 0
    assert agent.observations[1]["time"] == 0
    assert agent.observations[1]["viewscreen_type"] == "viewscreen_textviewerst"
    assert advance_options[0] == {
        "interrupt_on_viewscreen_transition": True,
        "viewscreen_before": "viewscreen_dwarfmodest",
    }
    assert len(advance_options) == 1

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    rows = _trace_rows(tmp_path, run_id)
    assert rows[0]["tick_degraded"]["code"] == "blocking_viewscreen_transition"
    assert rows[0]["tick_advance"]["ticks_advanced"] == 0
    assert (
        rows[0]["tick_advance"]["intermediate_probe_error"]
        == "calendar_sample_read_failed"
    )
    assert rows[0]["tick_advance"]["intermediate_probe_phase"] == "poll"
    assert rows[0]["tick_advance"]["intermediate_probe_failure_kind"] == "dfhack_error"
    assert rows[0]["tick_advance"]["interruption_detection"] == "final_attestation"
    assert not any(event["type"] == "terminal" for event in rows[0]["events"])

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_viewscreen_interruption_does_not_mask_repause_failure(
    tmp_path, monkeypatch
) -> None:
    def interrupt_with_modal(_ticks: int, state: Dict[str, Any]) -> None:
        state["pause_state"] = True
        state["viewscreen_type"] = "viewscreen_topicmeetingst"

    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        agent_override=CountingWaitAgent(15),
        viewscreen_type="viewscreen_dwarfmodest",
        advance_callback=interrupt_with_modal,
        advance_tick_info={
            "ok": False,
            "error": "blocking_viewscreen_transition",
            "interrupted": True,
            "ticks_advanced": 0,
            "start_tick": 0,
            "end_tick": 0,
            "viewscreen_before": "viewscreen_dwarfmodest",
            "viewscreen_after": "viewscreen_topicmeetingst",
            "pause_state_at_interrupt": True,
            "repause_requested": True,
            "repause_effective": False,
            "repause_error": "pause_state_unverified",
        },
        max_steps=2,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "tick_repause_unverified"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_incomplete_viewscreen_interruption_receipt_is_terminal(
    tmp_path, monkeypatch
) -> None:
    def interrupt_with_modal(_ticks: int, state: Dict[str, Any]) -> None:
        state["pause_state"] = True
        state["viewscreen_type"] = "viewscreen_topicmeetingst"

    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        agent_override=CountingWaitAgent(15),
        viewscreen_type="viewscreen_dwarfmodest",
        advance_callback=interrupt_with_modal,
        advance_tick_info={
            "ok": False,
            "error": "blocking_viewscreen_transition",
            "interrupted": True,
            "requested": 15,
            "ticks_advanced": 277,
            "start_year": 0,
            "start_tick": 0,
            "end_year": 0,
            "end_tick": 277,
            "paused_before": True,
            "paused_after": True,
            "viewscreen_before": "viewscreen_dwarfmodest",
            "viewscreen_after": "viewscreen_topicmeetingst",
            "pause_state_at_interrupt": True,
            "repause_requested": True,
            "repause_effective": True,
            "repause": {
                "ok": True,
                "paused": True,
                "attempts": 1,
                "attempt_records": [
                    {"attempt": 1, "nopause_disabled": True, "paused": True}
                ],
            },
            "interrupt_safety_error": False,
        },
        max_steps=2,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert (
        loaded.metadata["terminal_reason"]["code"] == "interruption_attestation_failed"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_start_tick", "interrupt_calendar_sample_invalid"),
        ("boolean_end_tick", "interrupt_calendar_sample_invalid"),
        ("contradictory_ticks", "interrupt_tick_evidence_mismatch"),
        ("post_time_mismatch", "interrupt_end_tick_state_mismatch"),
        ("requested_mismatch", "interrupt_requested_ticks_mismatch"),
        ("paused_before_false", "interrupt_paused_before_unattested"),
        ("paused_after_false", "interrupt_paused_after_unattested"),
        ("missing_repause", "interrupt_repause_missing"),
        ("nested_repause_disagreement", "interrupt_repause_nested_unattested"),
        ("nested_repause_error", "interrupt_repause_nested_error_present"),
        ("missing_repause_records", "interrupt_repause_records_invalid"),
        ("repause_record_count", "interrupt_repause_records_invalid"),
        ("repause_final_disable", "interrupt_repause_final_record_invalid"),
        ("negative_year", "interrupt_calendar_sample_invalid"),
        ("negative_tick", "interrupt_calendar_sample_invalid"),
        ("negative_state_calendar", "interrupt_calendar_state_invalid"),
        ("timeout_string", "interrupt_timeout_invalid"),
        ("boolean_state_time", "interrupt_start_tick_state_invalid"),
        ("boolean_attempt", "interrupt_repause_records_invalid"),
        ("boolean_attempt_count", "interrupt_repause_attempts_invalid"),
        ("invalid_interrupt_pause", "interrupt_pause_state_invalid"),
        ("resume_error", "interrupt_resume_error_present"),
    ],
)
def test_interruption_receipt_contradictions_are_terminal(
    mutation, expected_error
) -> None:
    tick_info: Dict[str, Any] = {
        "ok": False,
        "error": "blocking_viewscreen_transition",
        "interrupted": True,
        "requested": 1500,
        "ticks_advanced": 277,
        "start_year": 0,
        "start_tick": 100,
        "end_year": 0,
        "end_tick": 377,
        "paused_before": True,
        "paused_after": True,
        "viewscreen_before": "viewscreen_dwarfmodest",
        "viewscreen_after": "viewscreen_textviewerst",
        "pause_state_at_interrupt": True,
        "repause_requested": True,
        "repause_effective": True,
        "repause": {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
        "interrupt_safety_error": False,
        "calendar_safety_error": False,
        "final_pause_state": True,
        "final_viewscreen_type": "viewscreen_textviewerst",
    }
    state_after_apply = {
        "year": 0,
        "year_tick": 100,
        "time": 100,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }
    state_after_advance = {
        "year": 0,
        "year_tick": 377,
        "time": 377,
        "pause_state": True,
        "viewscreen_type": "viewscreen_textviewerst",
    }
    if mutation == "missing_start_tick":
        del tick_info["start_tick"]
    elif mutation == "boolean_end_tick":
        tick_info["end_tick"] = True
    elif mutation == "contradictory_ticks":
        tick_info["ticks_advanced"] = 276
    elif mutation == "post_time_mismatch":
        state_after_advance["time"] = 376
    elif mutation == "requested_mismatch":
        tick_info["requested"] = 15
    elif mutation == "paused_before_false":
        tick_info["paused_before"] = False
    elif mutation == "paused_after_false":
        tick_info["paused_after"] = False
    elif mutation == "missing_repause":
        del tick_info["repause"]
    elif mutation == "nested_repause_disagreement":
        tick_info["repause"] = {"ok": True, "paused": False}
    elif mutation == "nested_repause_error":
        tick_info["repause"] = {
            "ok": True,
            "paused": True,
            "error": "pause_state_unverified",
        }
    elif mutation == "missing_repause_records":
        del tick_info["repause"]["attempt_records"]
    elif mutation == "repause_record_count":
        tick_info["repause"]["attempts"] = 2
    elif mutation == "repause_final_disable":
        tick_info["repause"]["attempt_records"][-1]["nopause_disabled"] = False
    elif mutation == "negative_year":
        tick_info["start_year"] = -1
    elif mutation == "negative_tick":
        tick_info["end_tick"] = -1
    elif mutation == "negative_state_calendar":
        state_after_advance["year_tick"] = -1
    elif mutation == "timeout_string":
        tick_info["timeout"] = "false"
    elif mutation == "boolean_state_time":
        state_after_apply["time"] = True
    elif mutation == "boolean_attempt":
        tick_info["repause"]["attempt_records"][0]["attempt"] = True
    elif mutation == "boolean_attempt_count":
        tick_info["repause"]["attempts"] = True
    elif mutation == "invalid_interrupt_pause":
        tick_info["pause_state_at_interrupt"] = "false"
    else:
        tick_info["resume_error"] = "resume RPC failed"

    terminal, degraded, _ = _tick_terminal_reason(
        1500,
        tick_info,
        0,
        state_after_apply=state_after_apply,
        state_after_advance=state_after_advance,
    )

    assert degraded is None
    assert terminal is not None
    assert terminal["code"] == "interruption_attestation_failed"
    assert terminal["attestation_error"] == expected_error


FINAL_ATTESTATION_PROVENANCE_CONTRADICTIONS = (
    ("missing_detection", "interrupt_fallback_provenance_unexpected"),
    ("unknown_detection", "interrupt_detection_invalid"),
    ("missing_probe_error", "interrupt_final_attestation_probe_error_invalid"),
    ("changed_probe_error", "interrupt_final_attestation_probe_error_invalid"),
    ("missing_probe_phase", "interrupt_final_attestation_probe_phase_invalid"),
    ("initial_probe_phase", "interrupt_final_attestation_probe_phase_invalid"),
    ("missing_probe_kind", "interrupt_final_attestation_probe_kind_invalid"),
    ("unknown_probe_kind", "interrupt_final_attestation_probe_kind_invalid"),
    (
        "synthetic_interrupt_viewscreen",
        "interrupt_final_attestation_temporal_evidence_invalid",
    ),
    (
        "synthetic_interrupt_pause",
        "interrupt_final_attestation_temporal_evidence_invalid",
    ),
)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    FINAL_ATTESTATION_PROVENANCE_CONTRADICTIONS,
)
def test_final_attestation_provenance_contradictions_are_terminal(
    mutation, expected_error
) -> None:
    tick_info: Dict[str, Any] = {
        "ok": False,
        "error": "blocking_viewscreen_transition",
        "interrupted": True,
        "requested": 2500,
        "ticks_advanced": 2289,
        "start_year": 30,
        "start_tick": 348551,
        "end_year": 30,
        "end_tick": 350840,
        "paused_before": True,
        "paused_after": True,
        "viewscreen_before": "viewscreen_dwarfmodest",
        "viewscreen_after": "viewscreen_textviewerst",
        "repause_requested": True,
        "repause_effective": True,
        "repause": {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
        "interrupt_safety_error": False,
        "calendar_safety_error": False,
        "final_pause_state": True,
        "final_viewscreen_type": "viewscreen_textviewerst",
        "intermediate_probe_error": "calendar_sample_read_failed",
        "intermediate_probe_phase": "poll",
        "intermediate_probe_failure_kind": "dfhack_error",
        "interruption_detection": "final_attestation",
    }
    state_after_apply = {
        "year": 30,
        "year_tick": 348551,
        "time": 348551,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }
    state_after_advance = {
        "year": 30,
        "year_tick": 350840,
        "time": 350840,
        "pause_state": True,
        "viewscreen_type": "viewscreen_textviewerst",
    }

    if mutation == "missing_detection":
        del tick_info["interruption_detection"]
    elif mutation == "unknown_detection":
        tick_info["interruption_detection"] = "inferred"
    elif mutation == "missing_probe_error":
        del tick_info["intermediate_probe_error"]
    elif mutation == "changed_probe_error":
        tick_info["intermediate_probe_error"] = "timeout"
    elif mutation == "missing_probe_phase":
        del tick_info["intermediate_probe_phase"]
    elif mutation == "initial_probe_phase":
        tick_info["intermediate_probe_phase"] = "initial"
    elif mutation == "missing_probe_kind":
        del tick_info["intermediate_probe_failure_kind"]
    elif mutation == "unknown_probe_kind":
        tick_info["intermediate_probe_failure_kind"] = "unknown"
    elif mutation == "synthetic_interrupt_viewscreen":
        tick_info["viewscreen_at_interrupt"] = "viewscreen_textviewerst"
    else:
        tick_info["pause_state_at_interrupt"] = True

    terminal, degraded, _ = _tick_terminal_reason(
        2500,
        tick_info,
        0,
        state_after_apply=state_after_apply,
        state_after_advance=state_after_advance,
    )

    assert degraded is None
    assert terminal is not None
    assert terminal["code"] == "interruption_attestation_failed"
    assert terminal["attestation_error"] == expected_error


def test_final_attestation_provenance_fails_closed_gate() -> None:
    for mutation, expected_error in FINAL_ATTESTATION_PROVENANCE_CONTRADICTIONS:
        test_final_attestation_provenance_contradictions_are_terminal(
            mutation, expected_error
        )


def test_rollover_interruption_receipt_has_exact_duration() -> None:
    tick_info: Dict[str, Any] = {
        "ok": False,
        "error": "blocking_viewscreen_transition",
        "interrupted": True,
        "requested": 15,
        "ticks_advanced": 2,
        "start_year": 7,
        "start_tick": 403199,
        "end_year": 8,
        "end_tick": 1,
        "paused_before": True,
        "paused_after": True,
        "viewscreen_before": "viewscreen_dwarfmodest",
        "viewscreen_after": "viewscreen_textviewerst",
        "pause_state_at_interrupt": False,
        "repause_requested": True,
        "repause_effective": True,
        "repause": {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
        "interrupt_safety_error": False,
        "calendar_safety_error": False,
        "final_pause_state": True,
        "final_viewscreen_type": "viewscreen_textviewerst",
    }
    start_state = {
        "year": 7,
        "year_tick": 403199,
        "time": 403199,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }
    end_state = {
        "year": 8,
        "year_tick": 1,
        "time": 1,
        "pause_state": True,
        "viewscreen_type": "viewscreen_textviewerst",
    }

    terminal, degraded, _ = _tick_terminal_reason(
        15, tick_info, 0, state_after_apply=start_state, state_after_advance=end_state
    )

    assert terminal is None
    assert degraded is not None
    assert degraded["ticks_advanced"] == 2


@pytest.mark.parametrize(
    ("end_tick", "ticks_advanced", "terminal_error"),
    [
        (2101, 2001, None),
        (2151, 2051, "interrupt_tick_overshoot_exceeds_allowance"),
    ],
)
def test_clean_interruption_receipt_uses_request_overshoot_allowance(
    end_tick, ticks_advanced, terminal_error
) -> None:
    tick_info: Dict[str, Any] = {
        "ok": False,
        "error": "blocking_viewscreen_transition",
        "interrupted": True,
        "requested": 2000,
        "ticks_advanced": ticks_advanced,
        "start_year": 7,
        "start_tick": 100,
        "end_year": 7,
        "end_tick": end_tick,
        "paused_before": True,
        "paused_after": True,
        "viewscreen_before": "viewscreen_dwarfmodest",
        "viewscreen_after": "viewscreen_textviewerst",
        "pause_state_at_interrupt": True,
        "repause_requested": True,
        "repause_effective": True,
        "repause": {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
        "interrupt_safety_error": False,
        "calendar_safety_error": False,
        "final_pause_state": True,
        "final_viewscreen_type": "viewscreen_textviewerst",
    }
    state_after_apply = {
        "year": 7,
        "year_tick": 100,
        "time": 100,
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }
    state_after_advance = {
        "year": 7,
        "year_tick": end_tick,
        "time": end_tick,
        "pause_state": True,
        "viewscreen_type": "viewscreen_textviewerst",
    }

    terminal, degraded, _ = _tick_terminal_reason(
        2000,
        tick_info,
        0,
        state_after_apply=state_after_apply,
        state_after_advance=state_after_advance,
    )

    if terminal_error is None:
        assert terminal is None
        assert degraded is not None
        assert degraded["ticks_advanced"] == 2001
    else:
        assert degraded is None
        assert terminal is not None
        assert terminal["attestation_error"] == terminal_error


def test_tick_request_rewrite_fails_attestation() -> None:
    tick_info: Dict[str, Any] = {
        "ok": True,
        "requested": 2000,
        "ticks_advanced": 2000,
    }

    terminal, degraded, streak = _tick_terminal_reason(2500, tick_info, 0)

    assert terminal is not None
    assert terminal["code"] == "tick_request_attestation_failed"
    assert terminal["requested_ticks"] == 2500
    assert terminal["controller_requested_ticks"] == 2000
    assert degraded is None
    assert streak == 0


def test_summary_calendar_fallback_uses_exact_g7_rollover_duration(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {
                    "run_id": "g7-rollover",
                    "step": 0,
                    "score_version": 5,
                    "metrics": {
                        "score_version": 5,
                        "time": 403199,
                        "year": 7,
                        "year_tick": 403199,
                        "pop": 7,
                        "food": 1,
                        "drink": 1,
                    },
                    "events": [],
                },
                {
                    "run_id": "g7-rollover",
                    "step": 1,
                    "score_version": 5,
                    "metrics": {
                        "score_version": 5,
                        "time": 1,
                        "year": 8,
                        "year_tick": 1,
                        "pop": 7,
                        "food": 1,
                        "drink": 1,
                    },
                    "events": [],
                },
            )
        ),
        encoding="utf-8",
    )

    assert summarize(trace_path).duration_ticks == 2


def test_interrupt_safety_error_is_terminal_with_partial_ticks(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [
            {
                "ok": False,
                "error": "interrupt_viewscreen_unexpected",
                "interrupt_safety_error": True,
                "ticks_advanced": 277,
                "repause_requested": True,
                "repause_effective": True,
            }
        ],
        max_steps=2,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"] == {
        "code": "interruption_attestation_failed",
        "attestation_error": "interrupt_viewscreen_unexpected",
        "requested_ticks": 10,
        "ticks_advanced": 277,
        "tick_info": {
            "ok": False,
            "error": "interrupt_viewscreen_unexpected",
            "interrupt_safety_error": True,
            "ticks_advanced": 277,
            "repause_requested": True,
            "repause_effective": True,
        },
    }

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_runner_passes_recent_action_outcomes_to_next_decision(
    tmp_path, monkeypatch
) -> None:
    wait_agent = CountingWaitAgent(10)
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=3,
        agent_override=wait_agent,
    )

    assert agent is wait_agent
    assert wait_agent.calls == 3
    assert "== RECENT ACTION OUTCOMES ==" not in wait_agent.observation_texts[0]
    assert "== RECENT ACTION OUTCOMES ==" not in wait_agent.observation_texts[1]
    assert "Last Action command: step=0 WAIT" in wait_agent.observation_texts[1]
    assert "Last Action: ACCEPTED" in wait_agent.observation_texts[1]
    assert "== RECENT ACTION OUTCOMES ==" in wait_agent.observation_texts[2]
    assert "WAIT" in wait_agent.observation_texts[2]
    assert "actual=10t" in wait_agent.observation_texts[2]
    assert "recent_progress_summary" not in wait_agent.observations[2]
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_action_history_limit_prefers_generic_env_and_keeps_legacy_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FORT_GYM_KEYSTROKE_ACTION_HISTORY_LIMIT", "17")
    monkeypatch.delenv("FORT_GYM_ACTION_HISTORY_LIMIT", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert get_settings().ACTION_HISTORY_LIMIT == 17

    monkeypatch.setenv("FORT_GYM_ACTION_HISTORY_LIMIT", "23")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert get_settings().ACTION_HISTORY_LIMIT == 23

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_history_limit_cannot_erase_review_continuity() -> None:
    assert _effective_action_history_limit(0, governed=False) == 0
    for configured in (0, 1, 5):
        assert (
            _effective_action_history_limit(configured, governed=True)
            == MIN_GOVERNED_ACTION_HISTORY
        )
    assert _effective_action_history_limit(30, governed=True) == 30


def test_parsed_validation_failure_keeps_command_identity(
    tmp_path, monkeypatch
) -> None:
    interact_agent = CountingInteractAgent("finish_topic_meeting")
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=2,
        agent_override=interact_agent,
        viewscreen_type="viewscreen_topicmeetingst",
        screen_text="unrelated topic text",
    )

    assert agent is interact_agent
    assert interact_agent.calls == 2
    assert (
        "Last Action command: step=0 INTERACT(operation=finish_topic_meeting)"
        in interact_agent.observation_texts[1]
    )
    assert "requires the visible option" in interact_agent.observation_texts[1]
    assert "== RECENT ACTION OUTCOMES ==" not in interact_agent.observation_texts[1]
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_zero_tick_non_timeout_uses_fixed_streak(tmp_path, monkeypatch) -> None:
    agent, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [
            {"ok": True, "ticks_advanced": 0},
            {"ok": True, "ticks_advanced": 0},
            {"ok": True, "ticks_advanced": 0},
        ],
        max_steps=4,
    )

    assert agent.calls == 3
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "consecutive_zero_ticks"
    assert loaded.metadata["terminal_reason"]["consecutive_zero_tick_streak"] == 3
    assert loaded.metadata["terminal_reason"]["zero_tick_threshold"] == 3

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_requested_zero_ticks_are_legal_and_do_not_trigger_the_streak(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="mock", model="fake", max_steps=2, ticks_per_step=10
    )
    agent = CountingWaitAgent(0)
    run_id = run_once(
        agent,
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
        run_id=created.run_id,
        registry=registry,
    )

    assert agent.calls == 2
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert "terminal_reason" not in loaded.metadata
    assert all(
        row["tick_advance"]["ticks_advanced"] == 0
        for row in _trace_rows(tmp_path, run_id)
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_interact_context_is_governed_paused_and_viewscreen_allowlisted() -> None:
    allowed = "viewscreen_textviewerst"
    assert allowed in INTERACT_ALLOWED_VIEWSCREEN_TYPES
    assert (
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state={"pause_state": True, "viewscreen_type": allowed},
        )
        is None
    )
    assert "governed DFHack" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=False,
            state={"pause_state": True, "viewscreen_type": allowed},
        )
    )
    assert "paused" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state={"pause_state": False, "viewscreen_type": allowed},
        )
    )
    assert "not allowed" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state={"pause_state": True, "viewscreen_type": "viewscreen_dwarfmodest"},
        )
    )
    topic_action = {
        "type": "INTERACT",
        "params": {"operation": "finish_topic_meeting"},
        "advance_ticks": 0,
    }
    topic_state = {"pause_state": True, "viewscreen_type": "viewscreen_topicmeetingst"}
    assert (
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=topic_state,
            action=topic_action,
            screen_text="a - Finish peeking in on conversation",
        )
        is None
    )
    assert "requires the visible option" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=topic_state,
            action=topic_action,
            screen_text="unrelated topic text",
        )
    )
    visible_option_action = {
        "type": "INTERACT",
        "params": {"operation": "topic_option_a"},
        "advance_ticks": 0,
    }
    assert (
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=topic_state,
            action=visible_option_action,
            screen_text="# a - Begin discussion.",
        )
        is None
    )
    assert "requires a visible 'a - ...'" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=topic_state,
            action=visible_option_action,
            screen_text="# b - Discuss another matter.",
        )
    )

    stores_state = {"pause_state": True, "viewscreen_type": "viewscreen_storesst"}
    stores_cancel = {
        "type": "INTERACT",
        "params": {"operation": "cancel"},
        "advance_ticks": 0,
    }
    assert (
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=stores_state,
            action=stores_cancel,
        )
        is None
    )
    assert "blocks simulation" in str(
        _interact_context_reason(
            backend_name="dfhack",
            is_governed_dfhack_mode=True,
            state=stores_state,
            action={
                "type": "INTERACT",
                "params": {"operation": "confirm"},
                "advance_ticks": 0,
            },
        )
    )


def test_interact_modal_exit_resets_episode_without_terminal_failure() -> None:
    terminal, count, unchanged = _interaction_terminal_reason(
        action_type="INTERACT",
        interaction_audit={"screen_changed": True},
        state_after={"viewscreen_type": "viewscreen_dwarfmodest"},
        episode_count=7,
        unchanged_screen_streak=2,
    )

    assert terminal is None
    assert count == 0
    assert unchanged == 0


def test_governed_validation_rejection_keeps_complete_zero_change_evidence(
    tmp_path, monkeypatch
) -> None:
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        operation="finish_topic_meeting",
        viewscreen_type="viewscreen_topicmeetingst",
        screen_text="# a - Begin discussion.",
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["validation"]["valid"] is False
    assert "requires the visible option" in row["validation"]["reason"]
    assert row["execute"]["accepted"] is False
    assert row["execute"]["provenance"] == "dfhack_governed"
    assert row["execute"]["gameplay_progress_eligible"] is False
    assert row["gameplay_proof"]["ok"] is False
    assert row["gameplay_proof"]["source"] == "dfhack-map-and-state"
    assert row["gameplay_proof"]["provenance"] == "dfhack_governed"
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert "a - Begin discussion" in row["screen_text"]
    assert row["state_after_advance"]["fort"]["ok"] is False
    assert row["metrics"]["fort_metrics_observed"] is False

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_blocking_stores_view_rejects_positive_ticks_before_execution(
    tmp_path, monkeypatch
) -> None:
    advanced: list[int] = []
    agent = CountingWaitAgent(1200)
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=agent,
        viewscreen_type="viewscreen_storesst",
        screen_text=(
            "The Wealth of Kilrudvutok\n"
            "Beds                    None   3\n"
            "Tab: Mode                  z: Zoom"
        ),
        advance_callback=lambda ticks, _state: advanced.append(ticks),
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["validation"]["valid"] is False
    assert "blocks simulation" in row["validation"]["reason"]
    assert row["execute"]["validation_rejected"] is True
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert row["tick_advance"]["validation_rejected"] is True
    assert "timeout" not in row["tick_advance"]
    assert advanced == []
    assert "Blocking Wealth/Stocks screen" in agent.observation_texts[0]

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_repeated_stores_rejections_hit_modal_recovery_limit(
    tmp_path, monkeypatch
) -> None:
    agent = CountingWaitAgent(1200)
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=MAX_UNCHANGED_INTERACT_SCREENS + 2,
        agent_override=agent,
        viewscreen_type="viewscreen_storesst",
        screen_text=(
            "The Wealth of Kilrudvutok\n"
            "Beds                    None   3\n"
            "Tab: Mode                  z: Zoom"
        ),
    )

    assert agent.calls == MAX_UNCHANGED_INTERACT_SCREENS
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == (
        "interaction_unchanged_screen_loop"
    )
    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == MAX_UNCHANGED_INTERACT_SCREENS
    assert all(row["execute"]["validation_rejected"] is True for row in rows)
    assert all(row["tick_advance"]["ticks_advanced"] == 0 for row in rows)
    assert rows[-1]["terminal_reason"]["unchanged_screen_streak"] == (
        MAX_UNCHANGED_INTERACT_SCREENS
    )
    assert rows[-1]["interaction"]["blocking_viewscreen"] == "viewscreen_storesst"

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "type": "INTERACT",
            "params": {"operation": "escape"},
            "advance_ticks": 0,
        },
        {
            "actions": [
                {
                    "type": "WAIT",
                    "params": {},
                    "advance_ticks": 1200,
                }
            ]
        },
    ],
)
def test_stores_preparse_rejections_hit_modal_recovery_limit(
    tmp_path, monkeypatch, payload
) -> None:
    agent = RepeatingRawActionAgent(payload)
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=MAX_UNCHANGED_INTERACT_SCREENS + 2,
        agent_override=agent,
        viewscreen_type="viewscreen_storesst",
        screen_text="The Wealth of Kilrudvutok\nTab: Mode",
    )

    assert agent.calls == MAX_UNCHANGED_INTERACT_SCREENS
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == (
        "interaction_unchanged_screen_loop"
    )
    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == MAX_UNCHANGED_INTERACT_SCREENS
    assert all(row["validation"]["valid"] is False for row in rows)
    assert rows[-1]["terminal_reason"]["unchanged_screen_streak"] == (
        MAX_UNCHANGED_INTERACT_SCREENS
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_stores_cancel_exits_with_one_zero_tick_interaction(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=True,
        max_steps=1,
        operation="cancel",
        viewscreen_type="viewscreen_storesst",
        screen_text=(
            "The Wealth of Kilrudvutok\n"
            "Beds                    None   3\n"
            "Tab: Mode                  z: Zoom"
        ),
    )

    assert isinstance(agent, CountingInteractAgent)
    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["validation"] == {"valid": True, "reason": None}
    assert row["execute"]["accepted"] is True
    assert row["execute"]["result"]["interface_key"] == "LEAVESCREEN"
    assert row["tick_advance"]["ticks_advanced"] == 0
    assert row["gameplay_proof"]["helper_evidence"]["viewscreen_before"] == (
        "viewscreen_storesst"
    )
    assert row["gameplay_proof"]["helper_evidence"]["viewscreen_after"] == (
        "viewscreen_dwarfmodest"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unchanged_interact_loop_terminates_before_another_model_call(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
    )

    assert agent.calls == MAX_UNCHANGED_INTERACT_SCREENS
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert (
        loaded.metadata["terminal_reason"]["code"]
        == "interaction_unchanged_screen_loop"
    )

    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == MAX_UNCHANGED_INTERACT_SCREENS
    assert all(row["action"]["type"] == "INTERACT" for row in rows)
    assert all(row["execute"]["provenance"] == "dfhack_governed" for row in rows)
    assert all(row["execute"]["gameplay_progress_eligible"] is False for row in rows)
    assert all(row["gameplay_proof"]["ok"] is False for row in rows)
    assert rows[-1]["interaction"]["screen_changed"] is False
    assert "screen_text_after_interaction" in rows[-1]

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_finish_topic_meeting_no_effect_is_recorded_as_rejected(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        operation="finish_topic_meeting",
        viewscreen_type="viewscreen_topicmeetingst",
        screen_text="a - Finish peeking in on conversation",
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["execute"]["accepted"] is False
    assert row["execute"]["why"] == "interaction_no_effect"
    assert row["execute"]["result"]["ok"] is False
    assert row["execute"]["result"]["error"] == "interaction_no_effect"
    assert row["interaction"]["semantic_effect_observed"] is False

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_visible_topic_option_no_effect_is_recorded_as_rejected(
    tmp_path, monkeypatch
) -> None:
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        operation="topic_option_a",
        viewscreen_type="viewscreen_topicmeetingst",
        screen_text="# a - Begin discussion.",
    )

    row = _trace_rows(tmp_path, run_id)[0]
    assert row["execute"]["accepted"] is False
    assert row["execute"]["why"] == "interaction_no_effect"
    assert row["interaction"]["semantic_effect_observed"] is False

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_finish_topic_meeting_capture_failure_is_not_success(
    tmp_path, monkeypatch
) -> None:
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        screen_capture_fails_after=True,
        max_steps=1,
        operation="finish_topic_meeting",
        viewscreen_type="viewscreen_topicmeetingst",
        screen_text="a - Finish peeking in on conversation",
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["execute"]["accepted"] is False
    assert row["execute"]["why"] == "interaction_no_effect"
    assert row["interaction"]["post_screen_captured"] is False
    assert row["interaction"]["semantic_effect_observed"] is False
    assert row["screen_text_after_interaction"] == "(screen capture failed)"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_changing_interact_screens_still_hit_per_modal_operation_budget(
    tmp_path, monkeypatch
) -> None:
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=True,
    )

    assert agent.calls == MAX_INTERACT_OPERATIONS_PER_MODAL
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "interaction_budget_exhausted"

    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == MAX_INTERACT_OPERATIONS_PER_MODAL
    assert all(row["interaction"]["screen_changed"] is True for row in rows)
    assert rows[-1]["terminal_reason"]["interaction_episode_count"] == 8

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_positive_advance_captures_final_survival_evidence(
    tmp_path, monkeypatch
) -> None:
    wait_agent = CountingWaitAgent(10)
    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=wait_agent,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["tick_advance"]["ticks_advanced"] == 10
    assert row["state_after_advance"]["survival"] == {
        "ok": True,
        "active": True,
        "run_id": run_id,
    }

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_dfhack_cleanup_precedes_terminal_status_and_optional_analysis(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.eval.analyzer import AnalysisReport, TraceAnalyzer

    lifecycle_events: list[str] = []
    monkeypatch.setenv("GOOGLE_API_KEY", "configured-for-ordering-test")

    original_set_status = RunRegistry.set_status
    original_finalize = RunRegistry.finalize_success_after_cleanup
    original_set_summary = RunRegistry.set_summary

    def tracked_set_status(self, run_id, **kwargs):
        status = kwargs.get("status")
        if status in {"completed", "failed", "stopped"}:
            lifecycle_events.append(f"status:{status}")
        return original_set_status(self, run_id, **kwargs)

    def fake_analyze(self, trace_path):
        lifecycle_events.append("analysis_started")
        return AnalysisReport(run_id=trace_path.parent.name, total_steps=1)

    def tracked_finalize(self, run_id, **kwargs):
        status = original_finalize(self, run_id, **kwargs)
        lifecycle_events.append(f"status:{status}")
        return status

    def tracked_set_summary(self, run_id, summary):
        result = original_set_summary(self, run_id, summary)
        lifecycle_events.append("summary_persisted")
        return result

    monkeypatch.setattr(RunRegistry, "set_status", tracked_set_status)
    monkeypatch.setattr(RunRegistry, "finalize_success_after_cleanup", tracked_finalize)
    monkeypatch.setattr(RunRegistry, "set_summary", tracked_set_summary)
    monkeypatch.setattr(TraceAnalyzer, "analyze", fake_analyze)

    agent, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=CountingWaitAgent(10),
        lifecycle_events=lifecycle_events,
    )

    assert agent.calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert lifecycle_events.count("evidence_stopped") == 1
    assert lifecycle_events.count("client_closed") == 1
    assert lifecycle_events.index("evidence_stopped") < lifecycle_events.index(
        "client_closed"
    )
    assert lifecycle_events.index("client_closed") < lifecycle_events.index(
        "summary_persisted"
    )
    assert lifecycle_events.index("summary_persisted") < lifecycle_events.index(
        "status:completed"
    )
    assert lifecycle_events.index("status:completed") < lifecycle_events.index(
        "analysis_started"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_dfhack_cleanup_rejects_rpc_success_without_pause_attestation(
    monkeypatch,
) -> None:
    from fort_gym.bench.run import runner as runner_module

    lifecycle_events: list[str] = []

    class ApparentlyPausedClient:
        def pause(self) -> None:
            lifecycle_events.append("pause_rpc_returned")

        def close(self) -> None:
            lifecycle_events.append("client_closed")

    monkeypatch.setattr(
        runner_module,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": False,
            "paused": False,
            "error": "pause_state_unverified",
        },
    )

    outcome = runner_module._cleanup_dfhack_runtime(
        ApparentlyPausedClient(),
        evidence_attempted=False,
    )

    assert outcome["ok"] is False
    assert outcome["pause_rpc_completed"] is True
    assert outcome["pause_verified"] is False
    assert outcome["errors"] == [
        {"stage": "pause_attestation", "error": "pause_state_unverified"}
    ]
    assert lifecycle_events == ["pause_rpc_returned", "client_closed"]


def test_run_without_registry_raises_when_cleanup_cannot_attest_pause(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.run import runner as runner_module

    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    state = MockEnvironment().observe()

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            self.last_tick_info: Dict[str, Any] = {}

        def connect(self) -> None:
            return None

        def pause(self) -> None:
            return None

        def advance(self, ticks: int) -> Dict[str, Any]:
            self.last_tick_info = {"ok": True, "ticks_advanced": ticks}
            state["time"] = int(state.get("time") or 0) + ticks
            return dict(state)

        def close(self) -> None:
            return None

    pause_results = iter(
        [
            {"ok": True, "paused": True},
            {"ok": False, "paused": False, "error": "pause_state_unverified"},
            {"ok": False, "paused": False, "error": "pause_state_unverified"},
        ]
    )
    monkeypatch.setattr(runner_module, "DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        runner_module.StateReader,
        "from_dfhack",
        lambda _client: dict(state),
    )
    monkeypatch.setattr(
        runner_module,
        "ensure_paused_external",
        lambda **_kwargs: next(pause_results),
    )

    with pytest.raises(RuntimeError, match="cleanup remained unverified"):
        run_once(
            CountingWaitAgent(10),
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
            run_id="cleanup-without-registry",
            preserve_save=True,
        )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unverified_cleanup_cannot_publish_success_or_start_analysis(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.eval.analyzer import TraceAnalyzer

    lifecycle_events: list[str] = []
    monkeypatch.setenv("GOOGLE_API_KEY", "configured-for-ordering-test")
    monkeypatch.setattr(
        TraceAnalyzer,
        "analyze",
        lambda self, trace_path: lifecycle_events.append("analysis_started"),
    )

    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=CountingWaitAgent(10),
        lifecycle_events=lifecycle_events,
        cleanup_error=True,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "dfhack_cleanup_unverified"
    assert loaded.metadata["terminal_reason"]["cleanup"]["attempts"] == 2
    assert "cleanup_completed_at" not in loaded.metadata
    assert lifecycle_events.count("evidence_stopped") == 2
    assert "analysis_started" not in lifecycle_events
    assert loaded.latest_summary is not None

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_stop_requested_during_cleanup_finalizes_stopped(tmp_path, monkeypatch) -> None:
    lifecycle_events: list[str] = []
    original_set_status = RunRegistry.set_status
    original_finalize = RunRegistry.finalize_success_after_cleanup

    def tracked_set_status(self, run_id, **kwargs):
        status = kwargs.get("status")
        if status in {"completed", "failed", "stopped"}:
            lifecycle_events.append(f"status:{status}")
        return original_set_status(self, run_id, **kwargs)

    def tracked_finalize(self, run_id, **kwargs):
        status = original_finalize(self, run_id, **kwargs)
        lifecycle_events.append(f"status:{status}")
        return status

    monkeypatch.setattr(RunRegistry, "set_status", tracked_set_status)
    monkeypatch.setattr(RunRegistry, "finalize_success_after_cleanup", tracked_finalize)

    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=CountingWaitAgent(10),
        lifecycle_events=lifecycle_events,
        stop_during_cleanup=True,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "stopped"
    assert registry.stop_requested(run_id) is False
    assert "status:completed" not in lifecycle_events
    assert lifecycle_events.index("client_closed") < lifecycle_events.index(
        "status:stopped"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_terminal_reason_is_staged_before_cleanup_and_finalized_after(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.run import runner as runner_module

    lifecycle_events: list[str] = []
    original_pending = RunRegistry.record_pending_terminal_failure
    original_final = RunRegistry.record_terminal_failure
    original_cleanup = runner_module._cleanup_dfhack_runtime

    def tracked_pending(self, run_id, **kwargs):
        lifecycle_events.append("terminal_reason_staged")
        return original_pending(self, run_id, **kwargs)

    def tracked_cleanup(client, **kwargs):
        lifecycle_events.append("cleanup_started")
        return original_cleanup(client, **kwargs)

    def tracked_final(self, run_id, **kwargs):
        lifecycle_events.append("terminal_failure_finalized")
        return original_final(self, run_id, **kwargs)

    monkeypatch.setattr(RunRegistry, "record_pending_terminal_failure", tracked_pending)
    monkeypatch.setattr(RunRegistry, "record_terminal_failure", tracked_final)
    monkeypatch.setattr(runner_module, "_cleanup_dfhack_runtime", tracked_cleanup)

    _, registry, run_id = _run_dfhack_tick_fixture(
        tmp_path,
        monkeypatch,
        [{"ok": False, "timeout": True, "ticks_advanced": 0}],
        max_steps=2,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"]["code"] == "tick_timeout_zero_progress"
    assert lifecycle_events.index("terminal_reason_staged") < lifecycle_events.index(
        "cleanup_started"
    )
    assert lifecycle_events.index("cleanup_started") < lifecycle_events.index(
        "terminal_failure_finalized"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_terminal_reason_survives_sse_delivery_failure(tmp_path, monkeypatch) -> None:
    original_append = RunRegistry.append_event

    def fail_terminal_delivery(self, run_id, event):
        if event.get("t") == "terminal":
            raise RuntimeError("event loop closed")
        return original_append(self, run_id, event)

    monkeypatch.setattr(RunRegistry, "append_event", fail_terminal_delivery)

    with pytest.raises(RuntimeError, match="event loop closed"):
        _run_dfhack_tick_fixture(
            tmp_path,
            monkeypatch,
            [{"ok": False, "timeout": True, "ticks_advanced": 0}],
            max_steps=2,
        )

    recovered = RunRegistry(db_path=tmp_path / "runs.sqlite3").list()
    assert len(recovered) == 1
    assert recovered[0].status == "failed"
    assert (
        recovered[0].metadata["terminal_reason"]["code"] == "tick_timeout_zero_progress"
    )
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unexpected_exception_cleans_df_before_failed_status(
    tmp_path, monkeypatch
) -> None:
    lifecycle_events: list[str] = []
    original_set_status = RunRegistry.set_status

    def tracked_set_status(self, run_id, **kwargs):
        status = kwargs.get("status")
        if status in {"completed", "failed", "stopped"}:
            lifecycle_events.append(f"status:{status}")
        return original_set_status(self, run_id, **kwargs)

    monkeypatch.setattr(RunRegistry, "set_status", tracked_set_status)

    with pytest.raises(RuntimeError, match="unexpected observation failure"):
        _run_governed_interact_fixture(
            tmp_path,
            monkeypatch,
            screen_changes=False,
            max_steps=1,
            agent_override=CountingWaitAgent(10),
            lifecycle_events=lifecycle_events,
            observe_error=True,
        )

    assert lifecycle_events.count("evidence_stopped") == 1
    assert lifecycle_events.count("client_closed") == 1
    assert lifecycle_events.index("client_closed") < lifecycle_events.index(
        "status:failed"
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_agent_decide_failure_records_durable_terminal_reason(
    tmp_path, monkeypatch
) -> None:
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=RaisingDecisionAgent(),
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"] == {
        "code": "agent_decide_error",
        "stage": "agent_decide",
        "type": "RuntimeError",
        "message": "review contract exhausted",
    }
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["terminal_reason"] == loaded.metadata["terminal_reason"]
    assert row["events"][-1]["type"] == "terminal"

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_agent_decide_failure_preserves_safe_terminal_classification(
    tmp_path, monkeypatch
) -> None:
    _, registry, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=RaisingClassifiedDecisionAgent(),
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.metadata["terminal_reason"] == {
        "code": "provider_content_filter",
        "stage": "agent_decide",
        "type": "ClassifiedDecisionError",
        "message": "provider blocked the governed action response",
        "finish_reasons": ["content_filter"],
        "attempts": 3,
    }
    row = _trace_rows(tmp_path, run_id)[0]
    assert row["terminal_reason"] == loaded.metadata["terminal_reason"]

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_governed_run_rejects_stale_survival_ledger(tmp_path, monkeypatch) -> None:
    wait_agent = CountingWaitAgent(10)
    _, _, run_id = _run_governed_interact_fixture(
        tmp_path,
        monkeypatch,
        screen_changes=False,
        max_steps=1,
        agent_override=wait_agent,
        stale_evidence=True,
    )

    survival = _trace_rows(tmp_path, run_id)[0]["state_after_advance"]["survival"]
    assert survival["ok"] is False
    assert survival["flow_evidence_complete"] is False
    assert survival["death_evidence_complete"] is False
    assert survival["error"] == "g7_evidence_run_scope_invalid"
    assert survival["expected_run_id"] == run_id

    get_settings.cache_clear()  # type: ignore[attr-defined]
