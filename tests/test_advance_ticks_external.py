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
    assert result["ok"] is True
    assert result.get("ticks_advanced", 0) >= 0
    assert result.get("timeout") is True
