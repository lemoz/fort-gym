from __future__ import annotations

import os
import pytest


LIVE = os.environ.get("DFHACK_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="requires live DFHack")
def test_advance_ticks_progress():
    from fort_gym.bench.dfhack_backend import advance_ticks_exact_external

    result = advance_ticks_exact_external(10, True)
    assert result.get("ok") is True
    assert result.get("ticks_advanced", 0) >= 1
    assert result["end_tick"] >= result["start_tick"]


def test_advance_ticks_timeout_path(monkeypatch):
    from fort_gym.bench import dfhack_backend

    tick_value = {"value": 100}
    clock = {"now": 0.0}

    def fake_tick_read(timeout: float = 1.0) -> int:
        return tick_value["value"]

    def fake_read_pause_state(timeout: float = 1.0) -> bool:
        return True

    def fake_set_paused(_paused: bool, timeout: float = 1.0) -> None:
        return None

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(duration: float) -> None:
        clock["now"] += duration

    monkeypatch.setattr(dfhack_backend, "tick_read", fake_tick_read)
    monkeypatch.setattr(dfhack_backend, "read_pause_state", fake_read_pause_state)
    monkeypatch.setattr(dfhack_backend, "set_paused", fake_set_paused)
    monkeypatch.setattr(dfhack_backend.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(dfhack_backend.time, "sleep", fake_sleep)

    result = dfhack_backend.advance_ticks_exact_external(100, True)
    assert result["ok"] is False
    assert result.get("ticks_advanced", 0) >= 0
    assert result.get("timeout") is True
    assert result.get("error") == "timeout_waiting_for_ticks"


def test_advance_ticks_uses_space_fallback_when_pause_flag_sticks(monkeypatch):
    from fort_gym.bench import dfhack_backend

    ticks = iter([100, 100, 100, 112, 112])
    clock = {"now": 0.0}
    keys = []

    def fake_tick_read(timeout: float = 1.0) -> int:
        return next(ticks)

    def fake_read_pause_state(timeout: float = 1.0) -> bool:
        return True

    def fake_set_paused(_paused: bool, timeout: float = 1.0) -> None:
        return None

    def fake_execute_keystroke_action(sent_keys):
        keys.extend(sent_keys)
        return {"ok": True, "keys_sent": len(sent_keys)}

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(duration: float) -> None:
        clock["now"] += duration

    monkeypatch.setattr(dfhack_backend, "tick_read", fake_tick_read)
    monkeypatch.setattr(dfhack_backend, "read_pause_state", fake_read_pause_state)
    monkeypatch.setattr(dfhack_backend, "set_paused", fake_set_paused)
    monkeypatch.setattr(dfhack_backend, "execute_keystroke_action", fake_execute_keystroke_action)
    monkeypatch.setattr(dfhack_backend.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(dfhack_backend.time, "sleep", fake_sleep)

    result = dfhack_backend.advance_ticks_exact_external(10, True)

    assert result["ok"] is True
    assert result["ticks_advanced"] == 12
    assert result["resume_fallback"] == "STRING_A032"
    assert keys == ["STRING_A032"]


def test_advance_ticks_honors_agent_request_above_legacy_cap(monkeypatch):
    from fort_gym.bench import dfhack_backend

    ticks = iter([100, 1600, 1600])

    monkeypatch.setattr(dfhack_backend, "tick_read", lambda timeout=1.0: next(ticks))
    monkeypatch.setattr(dfhack_backend, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(dfhack_backend, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(dfhack_backend, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(dfhack_backend.time, "sleep", lambda duration: None)

    result = dfhack_backend.advance_ticks_exact_external(1500, True)

    assert result["ok"] is True
    assert result["requested"] == 1500
    assert result["ticks_advanced"] == 1500


def test_advance_ticks_caps_direct_calls_at_action_schema_limit(monkeypatch):
    from fort_gym.bench import dfhack_backend

    ticks = iter([100, 2100, 2100])

    monkeypatch.setattr(dfhack_backend, "tick_read", lambda timeout=1.0: next(ticks))
    monkeypatch.setattr(dfhack_backend, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(dfhack_backend, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(dfhack_backend, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(dfhack_backend.time, "sleep", lambda duration: None)

    result = dfhack_backend.advance_ticks_exact_external(5000, True)

    assert result["ok"] is True
    assert result["requested"] == dfhack_backend.MAX_ADVANCE_TICKS
    assert result["ticks_advanced"] == dfhack_backend.MAX_ADVANCE_TICKS
