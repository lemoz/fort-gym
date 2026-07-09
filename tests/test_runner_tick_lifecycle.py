from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import pytest

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.mock_env import MockEnvironment
from fort_gym.bench.run.runner import (
    INTERACT_ALLOWED_VIEWSCREEN_TYPES,
    MAX_INTERACT_OPERATIONS_PER_MODAL,
    MAX_UNCHANGED_INTERACT_SCREENS,
    _interact_context_reason,
    _interaction_terminal_reason,
    run_once,
)
from fort_gym.bench.run.storage import RunRegistry


class CountingWaitAgent(Agent):
    def __init__(self, requested_ticks: int) -> None:
        self.calls = 0
        self.requested_ticks = requested_ticks
        self.observations: list[Dict[str, Any]] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.observations.append(dict(obs_json))
        return {
            "type": "WAIT",
            "params": {},
            "intent": "exercise tick lifecycle",
            "advance_ticks": self.requested_ticks,
        }


class CountingInteractAgent(Agent):
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        return {
            "type": "INTERACT",
            "params": {"operation": "confirm"},
            "intent": "advance the visible dialog by one bounded input",
            "advance_ticks": 0,
        }


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
            state["time"] += int(self.last_tick_info.get("ticks_advanced") or 0)
            return dict(state)

        def close(self) -> None:
            return None

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
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


def test_duplicate_worker_cannot_touch_an_already_claimed_trace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(backend="mock", model="fake", max_steps=1, ticks_per_step=0)
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


def _run_governed_interact_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    screen_changes: bool,
    max_steps: int = 20,
    agent_override: Agent | None = None,
    stale_evidence: bool = False,
) -> tuple[Agent, RunRegistry, str]:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    raw_state = MockEnvironment().observe()
    raw_state.update(
        {
            "pause_state": True,
            "viewscreen_type": "viewscreen_textviewerst",
        }
    )
    screen_version = [0]

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            self.last_tick_info: Dict[str, Any] = {}

        def connect(self) -> None:
            return None

        def pause(self) -> None:
            raw_state["pause_state"] = True

        def get_state(self) -> Dict[str, Any]:
            return dict(raw_state)

        def advance(self, ticks: int) -> Dict[str, Any]:
            self.last_tick_info = {"ok": True, "ticks_advanced": ticks}
            raw_state["time"] = int(raw_state.get("time") or 0) + ticks
            return dict(raw_state)

        def get_screen_text(self, *, include_visual_hints: bool = False) -> str:
            assert include_visual_hints is True
            return f"dialog screen {screen_version[0]}"

        def close(self) -> None:
            return None

    def fake_execute(keys: list[str]) -> Dict[str, Any]:
        assert keys == ["SELECT"]
        if screen_changes:
            screen_version[0] += 1
        return {"ok": True, "keys_sent": 1}

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_view_state",
        lambda: {"window": [0, 0, 0]},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.prepare_keystroke_target",
        lambda *args, **kwargs: {"ok": False},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.restore_view_state",
        lambda state: {"ok": True},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_job_metrics",
        lambda rect: {"ok": False},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_fort_metrics",
        lambda: {"ok": False},
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
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.stop_g7_evidence",
        lambda: {"ok": True, "active": False},
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
    agent = agent_override or CountingInteractAgent()
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


def test_partial_timeout_is_degraded_and_allows_next_agent_decide(tmp_path, monkeypatch) -> None:
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
    created = registry.create(backend="mock", model="fake", max_steps=2, ticks_per_step=10)
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
    assert all(row["tick_advance"]["ticks_advanced"] == 0 for row in _trace_rows(tmp_path, run_id))

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_interact_context_is_governed_paused_and_viewscreen_allowlisted() -> None:
    allowed = next(iter(INTERACT_ALLOWED_VIEWSCREEN_TYPES))
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
    assert loaded.metadata["terminal_reason"]["code"] == "interaction_unchanged_screen_loop"

    rows = _trace_rows(tmp_path, run_id)
    assert len(rows) == MAX_UNCHANGED_INTERACT_SCREENS
    assert all(row["action"]["type"] == "INTERACT" for row in rows)
    assert all(row["execute"]["provenance"] == "dfhack_governed" for row in rows)
    assert all(row["execute"]["gameplay_progress_eligible"] is False for row in rows)
    assert all(row["gameplay_proof"]["ok"] is False for row in rows)
    assert rows[-1]["interaction"]["screen_changed"] is False
    assert "screen_text_after_interaction" in rows[-1]

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


def test_governed_positive_advance_captures_final_survival_evidence(tmp_path, monkeypatch) -> None:
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
