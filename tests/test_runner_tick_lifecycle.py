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


def test_governed_setup_failure_cleans_runtime_before_failed_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    lifecycle_events: list[str] = []

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            return None

        def connect(self) -> None:
            lifecycle_events.append("client_connected")

        def pause(self) -> None:
            lifecycle_events.append("client_paused")

        def close(self) -> None:
            lifecycle_events.append("client_closed")

    monkeypatch.setattr("fort_gym.bench.run.runner.DFHackClient", FakeDFHackClient)
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.start_g7_evidence",
        lambda run_id: lifecycle_events.append("evidence_started")
        or {"ok": True, "active": True, "run_id": run_id},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.stop_g7_evidence",
        lambda: lifecycle_events.append("evidence_stopped") or {"ok": True, "active": False},
    )
    monkeypatch.setattr(
        "fort_gym.bench.run.runner.read_view_state",
        lambda: {"window": [0, 0, 0]},
    )

    def fail_target_setup(*args, **kwargs):
        raise RuntimeError("target setup failed")

    monkeypatch.setattr(
        "fort_gym.bench.run.runner.prepare_keystroke_target",
        fail_target_setup,
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

    with pytest.raises(RuntimeError, match="target setup failed"):
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
        "evidence_started",
        "client_paused",
        "evidence_stopped",
        "client_closed",
        "status_failed",
    ]
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_disabled_dfhack_setup_does_not_leave_claimed_run_running(tmp_path, monkeypatch) -> None:
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


def _run_governed_interact_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    screen_changes: bool,
    max_steps: int = 20,
    agent_override: Agent | None = None,
    stale_evidence: bool = False,
    lifecycle_events: list[str] | None = None,
    stop_during_cleanup: bool = False,
    observe_error: bool = False,
    cleanup_error: bool = False,
    operation: str = "confirm",
    viewscreen_type: str = "viewscreen_textviewerst",
    screen_text: str = "dialog screen",
    screen_capture_fails_after: bool = False,
) -> tuple[Agent, RunRegistry, str]:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("DFHACK_ENABLED", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    raw_state = MockEnvironment().observe()
    raw_state.update(
        {
            "pause_state": True,
            "viewscreen_type": viewscreen_type,
        }
    )
    screen_version = [0]
    interaction_sent = [False]

    class FakeDFHackClient:
        def __init__(self, **_: Any) -> None:
            self.last_tick_info: Dict[str, Any] = {}

        def connect(self) -> None:
            return None

        def pause(self) -> None:
            raw_state["pause_state"] = True

        def get_state(self) -> Dict[str, Any]:
            if observe_error:
                raise RuntimeError("unexpected observation failure")
            return dict(raw_state)

        def advance(self, ticks: int) -> Dict[str, Any]:
            self.last_tick_info = {"ok": True, "ticks_advanced": ticks}
            raw_state["time"] = int(raw_state.get("time") or 0) + ticks
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
        expected_key = "OPTION1" if operation == "finish_topic_meeting" else "SELECT"
        assert keys == [expected_key]
        interaction_sent[0] = True
        if screen_changes:
            screen_version[0] += 1
            if operation == "finish_topic_meeting":
                raw_state["viewscreen_type"] = "viewscreen_dwarfmodest"
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


def test_parsed_validation_failure_keeps_command_identity(tmp_path, monkeypatch) -> None:
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


def test_finish_topic_meeting_no_effect_is_recorded_as_rejected(tmp_path, monkeypatch) -> None:
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


def test_finish_topic_meeting_capture_failure_is_not_success(tmp_path, monkeypatch) -> None:
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
    assert lifecycle_events.index("evidence_stopped") < lifecycle_events.index("client_closed")
    assert lifecycle_events.index("client_closed") < lifecycle_events.index("summary_persisted")
    assert lifecycle_events.index("summary_persisted") < lifecycle_events.index("status:completed")
    assert lifecycle_events.index("status:completed") < lifecycle_events.index("analysis_started")

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unverified_cleanup_cannot_publish_success_or_start_analysis(tmp_path, monkeypatch) -> None:
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
    assert lifecycle_events.index("client_closed") < lifecycle_events.index("status:stopped")

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
    assert recovered[0].metadata["terminal_reason"]["code"] == "tick_timeout_zero_progress"
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unexpected_exception_cleans_df_before_failed_status(tmp_path, monkeypatch) -> None:
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
    assert lifecycle_events.index("client_closed") < lifecycle_events.index("status:failed")

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
