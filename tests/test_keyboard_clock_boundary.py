"""Synthetic replay of a keyboard screen transition before a native interruption."""

from copy import deepcopy
import json

import pytest

from tests.test_campaign_codex_keyboard import Environment, decision, start


class BoundaryEnvironment(Environment):
    def __init__(self, *, partial_ticks=3, corruption=None):
        super().__init__()
        self.view = "viewscreen"
        self.partial_ticks = partial_ticks
        self.corruption = corruption
        self.clock_states = []
        self.paused = True

    def observe(self):
        return {**super().observe(), "time": self.tick, "pause_state": self.paused,
                "viewscreen_type": self.view}

    def apply(self, action, state):
        result = super().apply(action, state)
        self.view = "viewscreen_dwarfmodest"
        if self.corruption == "tick":
            self.tick += 1
        elif self.corruption == "pause":
            self.paused = False
        return result

    def advance(self, ticks, state):
        self.clock_states.append(deepcopy(state))
        if ticks == 0:
            return self.observe(), {"ok": True, "ticks_advanced": 0, "skipped": True}
        before = self.tick
        self.tick += self.partial_ticks
        self.view = "viewscreen_textviewerst"
        receipt = {
            "ok": False, "requested": ticks, "ticks_advanced": self.partial_ticks,
            "start_year": 30, "start_tick": before, "end_year": 30, "end_tick": self.tick,
            "paused_before": True, "paused_after": True,
            "repause_requested": True, "repause_effective": True,
            "repause": {"ok": True, "paused": True, "attempts": 1,
                        "attempt_records": [{"attempt": 1, "nopause_disabled": True, "paused": True}]},
            "error": "blocking_viewscreen_transition", "interrupted": True,
            "viewscreen_before": "viewscreen_dwarfmodest", "viewscreen_after": self.view,
            "viewscreen_at_interrupt": self.view, "pause_state_at_interrupt": False,
            "interrupt_safety_error": False, "calendar_safety_error": False,
            "final_pause_state": True, "final_viewscreen_type": self.view,
        }
        if isinstance(self.corruption, tuple):
            key, value = self.corruption
            receipt[key] = value
        return self.observe(), receipt


def transition_loop(tmp_path, **kwargs):
    feedbacks = []

    def callback(screen, memory, feedback):
        feedbacks.append(deepcopy(feedback))
        value = decision(screen, memory, feedback)
        value["action"]["params"]["keys"] = ["LEAVESCREEN", "D_PAUSE"] if not memory else ["LEAVESCREEN"]
        value["action"]["advance_ticks"] = 10 if not memory else 0
        return value

    loop = start(tmp_path, callback)
    loop.environment = BoundaryEnvironment(**kwargs)
    return loop, feedbacks


@pytest.mark.parametrize("partial_ticks", [0, 3, 10])
def test_partial_dialogue_interruption_uses_post_keyboard_boundary(tmp_path, partial_ticks):
    loop, feedbacks = transition_loop(tmp_path, partial_ticks=partial_ticks)
    first = loop.step()
    assert loop.at_boundary and not loop.failed and loop.next_step == 1
    assert first["tick_advance"]["ticks_advanced"] == partial_ticks
    assert first["tick_advance"]["ok"] is False
    assert first["tick_advance"]["native_after_apply"] == {
        "year": 30, "year_tick": 123, "time": 123, "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }
    assert loop.environment.clock_states[0]["viewscreen_type"] == "viewscreen_dwarfmodest"
    assert loop.environment.view == "viewscreen_textviewerst"
    assert [action["params"]["keys"] for action in loop.environment.actions] == [["LEAVESCREEN", "D_PAUSE"]]
    loop.step()
    assert [action["params"]["keys"] for action in loop.environment.actions] == [
        ["LEAVESCREEN", "D_PAUSE"], ["LEAVESCREEN"],
    ]
    assert feedbacks[-1]["simulation"]["ticks_advanced"] == partial_ticks
    assert feedbacks[-1]["simulation"]["reason"] == "blocking_viewscreen_transition"
    assert "hidden" not in json.dumps(feedbacks)
    assert loop.agent.usage["accounted_responses"] == 2
    assert loop.committed_elapsed_ticks == partial_ticks


@pytest.mark.parametrize("corruption", ["tick", "pause"])
def test_post_input_calendar_or_pause_drift_does_not_start_another_clock(tmp_path, corruption):
    loop, _ = transition_loop(tmp_path, corruption=corruption)
    with pytest.raises(ValueError, match="Keyboard input changed the paused calendar boundary"):
        loop.step()
    assert loop.failed and not loop.at_boundary and loop.next_step == 0
    assert len(loop.environment.actions) == 1 and loop.environment.clock_states == []
    assert loop.agent.usage["accounted_responses"] == 1


@pytest.mark.parametrize("field,value", [
    ("paused_before", False), ("paused_after", False), ("interrupted", False),
    ("interrupt_safety_error", True), ("calendar_safety_error", True),
    ("viewscreen_before", "viewscreen"), ("final_pause_state", False),
    ("final_viewscreen_type", "viewscreen_dwarfmodest"),
    ("requested", 11), ("ticks_advanced", 4), ("start_tick", 124),
])
def test_fresh_post_input_observation_does_not_accept_bad_interruption_receipts(tmp_path, field, value):
    loop, _ = transition_loop(tmp_path, corruption=(field, value))
    with pytest.raises(ValueError, match="Native time disagrees|did not finish or interrupt cleanly"):
        loop.step()
    assert loop.failed and not loop.at_boundary and loop.next_step == 0
    assert len(loop.environment.actions) == 1 and len(loop.environment.clock_states) == 1
    assert loop.agent.usage["accounted_responses"] == 1
