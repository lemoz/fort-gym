from __future__ import annotations

import os
import pytest


LIVE = os.environ.get("DFHACK_LIVE") == "1"


@pytest.fixture(autouse=True)
def _block_external_dfhack_mutation(monkeypatch, request):
    """Focused controller tests must replace every mutating DFHack call."""

    if LIVE and request.node.name == "test_advance_ticks_progress":
        return

    from fort_gym.bench import tick_controller

    def blocked(*_args, **_kwargs):
        pytest.fail("test attempted a real DFHack mutation without an explicit stub")

    monkeypatch.setattr(tick_controller, "_set_nopause", blocked)
    monkeypatch.setattr(tick_controller, "set_paused", blocked)
    monkeypatch.setattr(tick_controller, "execute_keystroke_action", blocked)


@pytest.mark.skipif(not LIVE, reason="requires live DFHack")
def test_advance_ticks_progress():
    from fort_gym.bench.tick_controller import advance_ticks_exact_external

    result = advance_ticks_exact_external(10, True)
    assert result.get("ok") is True
    assert result.get("ticks_advanced", 0) >= 1
    assert result.get("calendar_safety_error") is not True


def test_advance_ticks_timeout_path(monkeypatch):
    from fort_gym.bench import tick_controller

    tick_value = {"value": 100}
    clock = {"now": 0.0}

    def fake_probe(timeout: float = 1.0):
        return {
            "cur_year": 0,
            "cur_year_tick": tick_value["value"],
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        }

    def fake_read_pause_state(timeout: float = 1.0) -> bool:
        return True

    def fake_set_paused(_paused: bool, timeout: float = 1.0) -> None:
        return None

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(duration: float) -> None:
        clock["now"] += duration

    monkeypatch.setattr(tick_controller, "read_tick_pause_viewscreen", fake_probe)
    monkeypatch.setattr(tick_controller, "read_pause_state", fake_read_pause_state)
    monkeypatch.setattr(tick_controller, "set_paused", fake_set_paused)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller, "execute_keystroke_action", lambda _keys: {"ok": True}
    )
    monkeypatch.setattr(tick_controller.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(tick_controller.time, "sleep", fake_sleep)

    result = tick_controller.advance_ticks_exact_external(100, True)
    assert result["ok"] is False
    assert result.get("ticks_advanced", 0) >= 0
    assert result.get("timeout") is True
    assert result.get("error") == "timeout_waiting_for_ticks"


def test_backend_reexports_tick_controller_public_api() -> None:
    from fort_gym.bench import dfhack_backend, tick_controller

    assert (
        dfhack_backend.advance_ticks_exact_external
        is tick_controller.advance_ticks_exact_external
    )
    assert dfhack_backend.advance_ticks_exact is tick_controller.advance_ticks_exact
    assert (
        dfhack_backend.ensure_paused_external is tick_controller.ensure_paused_external
    )
    assert dfhack_backend.MAX_ADVANCE_TICKS == tick_controller.MAX_ADVANCE_TICKS


def test_advance_ticks_interrupts_on_paused_viewscreen_transition(monkeypatch):
    from fort_gym.bench import tick_controller

    set_paused_calls: list[bool] = []
    keystroke_calls: list[list[str]] = []
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda paused, timeout=1.0: set_paused_calls.append(paused),
    )
    monkeypatch.setattr(
        tick_controller,
        "execute_keystroke_action",
        lambda keys: keystroke_calls.append(keys) or {"ok": True},
    )
    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 377,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 377,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
        ]
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(
        1500,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["interrupted"] is True
    assert result["error"] == "blocking_viewscreen_transition"
    assert result["ticks_advanced"] == 277
    assert result["start_tick"] == 100
    assert result["end_tick"] == 377
    assert result["viewscreen_before"] == "viewscreen_dwarfmodest"
    assert result["viewscreen_after"] == "viewscreen_textviewerst"
    assert result["pause_state_at_interrupt"] is True
    assert result.get("timeout") is not True
    assert result["repause_effective"] is True
    assert result["final_pause_state"] is True
    assert result["final_viewscreen_type"] == "viewscreen_textviewerst"
    assert set_paused_calls == []
    assert keystroke_calls == []


def test_advance_ticks_repauses_unpaused_allowlisted_transition(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    set_paused_calls: list[bool] = []
    keystroke_calls: list[list[str]] = []
    probes = iter(
        [
            {
                "cur_year": 30,
                "cur_year_tick": 223702,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 223702,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 223716,
                "pause_state": False,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 223716,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
        ]
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda paused, **_kwargs: set_paused_calls.append(paused),
    )
    monkeypatch.setattr(
        tick_controller,
        "execute_keystroke_action",
        lambda keys: keystroke_calls.append(keys) or {"ok": True},
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_kwargs: next(probes)
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(
        10,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "blocking_viewscreen_transition"
    assert result["interrupted"] is True
    assert result["pause_state_at_interrupt"] is False
    assert result["ticks_advanced"] == 14
    assert result["paused_after"] is True
    assert result["final_pause_state"] is True
    assert result["final_viewscreen_type"] == "viewscreen_topicmeetingst"
    assert result["interrupt_safety_error"] is False
    assert set_paused_calls == [False]
    assert keystroke_calls == []


def test_advance_ticks_accepts_allowlisted_meeting_cascade_during_repause(
    monkeypatch,
) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 30,
                "cur_year_tick": 217867,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 217867,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 217878,
                "pause_state": False,
                "viewscreen_type": "viewscreen_meetingst",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 217878,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
        ]
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda _paused, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_kwargs: next(probes)
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(
        1200,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "blocking_viewscreen_transition"
    assert result["interrupted"] is True
    assert result["ticks_advanced"] == 11
    assert result["viewscreen_at_interrupt"] == "viewscreen_meetingst"
    assert result["viewscreen_after"] == "viewscreen_topicmeetingst"
    assert result["final_viewscreen_type"] == "viewscreen_topicmeetingst"
    assert result["final_pause_state"] is True
    assert result["interrupt_safety_error"] is False


def test_advance_ticks_interrupts_before_any_tick_progress(monkeypatch):
    from fort_gym.bench import tick_controller

    set_paused_calls: list[bool] = []
    fallback_calls: list[list[str]] = []
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda paused, timeout=1.0: set_paused_calls.append(paused),
    )
    monkeypatch.setattr(
        tick_controller,
        "execute_keystroke_action",
        lambda keys: fallback_calls.append(keys) or {"ok": True},
    )
    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
        ]
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["interrupted"] is True
    assert result["ticks_advanced"] == 0
    assert result["start_tick"] == 100
    assert result["end_tick"] == 100
    assert result.get("timeout") is not True
    assert result["repause_effective"] is True
    assert result["viewscreen_after"] == "viewscreen_topicmeetingst"
    assert set_paused_calls == [False]
    assert fallback_calls == []


def test_advance_ticks_keeps_timeout_when_no_viewscreen_transition(monkeypatch):
    from fort_gym.bench import tick_controller

    clock = {"now": 0.0}
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: False)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": 100,
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        tick_controller.time,
        "sleep",
        lambda duration: clock.__setitem__("now", clock["now"] + duration),
    )

    result = tick_controller.advance_ticks_exact_external(
        10,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "timeout_waiting_for_ticks"
    assert result["timeout"] is True
    assert result.get("interrupted") is not True


def test_advance_ticks_fails_closed_on_unknown_viewscreen(monkeypatch):
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "unknown",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    result = tick_controller.advance_ticks_exact_external(
        10,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "interrupt_viewscreen_unknown"
    assert result["interrupt_safety_error"] is True
    assert result.get("interrupted") is not True


def test_advance_ticks_fails_closed_on_unexpected_viewscreen_transition(monkeypatch):
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_optionsst",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)

    result = tick_controller.advance_ticks_exact_external(
        10,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "interrupt_viewscreen_unexpected"
    assert result["interrupt_safety_error"] is True
    assert result.get("interrupted") is not True


@pytest.mark.parametrize(
    ("viewscreen_before", "actual_viewscreen", "pause_state", "error"),
    [
        (
            "viewscreen_textviewerst",
            "viewscreen_textviewerst",
            True,
            "interrupt_baseline_invalid",
        ),
        (
            "viewscreen_dwarfmodest",
            "viewscreen_textviewerst",
            True,
            "interrupt_baseline_mismatch",
        ),
        (
            "viewscreen_dwarfmodest",
            "viewscreen_dwarfmodest",
            False,
            "interrupt_baseline_unpaused",
        ),
    ],
)
def test_advance_ticks_rejects_unsafe_initial_baseline_before_resume(
    monkeypatch, viewscreen_before, actual_viewscreen, pause_state, error
):
    from fort_gym.bench import tick_controller

    mutations: list[object] = []
    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": pause_state,
                "viewscreen_type": actual_viewscreen,
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": viewscreen_before,
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "_set_nopause",
        lambda enabled: mutations.append(("nopause", enabled)),
    )
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda paused, timeout=1.0: mutations.append(("pause", paused)),
    )
    monkeypatch.setattr(
        tick_controller,
        "execute_keystroke_action",
        lambda keys: mutations.append(("keys", keys)) or {"ok": True},
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before=viewscreen_before,
    )

    assert result["ok"] is False
    assert result["error"] == error
    assert result["interrupt_safety_error"] is True
    assert mutations == []


def test_unsafe_initial_baseline_preserves_elapsed_ticks_after_repause(monkeypatch):
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": False,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 150,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "interrupt_baseline_unpaused"
    assert result["start_tick"] == 100
    assert result["end_tick"] == 150
    assert result["ticks_advanced"] == 50
    assert result["paused_before"] is False
    assert result["paused_after"] is True
    assert result["interrupt_safety_error"] is True


def test_advance_ticks_fails_closed_when_atomic_probe_read_fails(monkeypatch):
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    probes = iter(
        [
            DFHackError("probe unavailable"),
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )

    def read_probe(timeout=1.0):
        value = next(probes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(tick_controller, "read_tick_pause_viewscreen", read_probe)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        10,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["ok"] is False
    assert result["error"] == "calendar_sample_read_failed"
    assert result["interrupt_safety_error"] is True


def test_final_attestation_recovers_modal_transition_after_probe_failure(
    monkeypatch,
) -> None:
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError
    from fort_gym.bench.tick_receipt import validate_clean_interruption_receipt

    probes = iter(
        [
            {
                "cur_year": 30,
                "cur_year_tick": 348551,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 348551,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            DFHackError("probe blocked by notification"),
            {
                "cur_year": 30,
                "cur_year_tick": 350840,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
        ]
    )

    def read_probe(**_kwargs):
        value = next(probes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(tick_controller, "read_tick_pause_viewscreen", read_probe)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": True,
            "paused": True,
            "attempts": 1,
            "attempt_records": [
                {"attempt": 1, "nopause_disabled": True, "paused": True}
            ],
        },
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(
        2500,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
        max_advance_ticks=2500,
    )

    assert result["ok"] is False
    assert result["error"] == "blocking_viewscreen_transition"
    assert result["interrupted"] is True
    assert result["ticks_advanced"] == 2289
    assert result["viewscreen_after"] == "viewscreen_textviewerst"
    assert result["final_pause_state"] is True
    assert result["interrupt_safety_error"] is False
    assert result["calendar_safety_error"] is False
    assert result["intermediate_probe_error"] == "calendar_sample_read_failed"
    assert result["intermediate_probe_phase"] == "post_resume"
    assert result["intermediate_probe_failure_kind"] == "dfhack_error"
    assert result["interruption_detection"] == "final_attestation"
    assert "viewscreen_at_interrupt" not in result
    assert "pause_state_at_interrupt" not in result
    assert (
        validate_clean_interruption_receipt(
            result,
            requested_ticks=2500,
            state_after_apply={
                "year": 30,
                "year_tick": 348551,
                "time": 348551,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            state_after_advance={
                "year": 30,
                "year_tick": 350840,
                "time": 350840,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
        )
        is None
    )


def test_final_attestation_recovery_fails_closed_gate(monkeypatch) -> None:
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    cases = (
        {"final_viewscreen": "viewscreen_dwarfmodest"},
        {"final_pause": False},
        {"final_tick": 351102},
        {"final_tick": 348550},
        {"final_year": 32, "final_tick": 100},
        {"final_tick": 403200},
        {"final_viewscreen": "unknown"},
        {"final_viewscreen": "viewscreen_layer_noblelistst"},
        {"nopause_error": "nopause command failed"},
        {"resume_error": True},
        {"repause_ok": False},
    )
    for case in cases:
        final_year = case.get("final_year", 30)
        final_tick = case.get("final_tick", 350840)
        final_pause = case.get("final_pause", True)
        final_viewscreen = case.get("final_viewscreen", "viewscreen_textviewerst")
        repause_ok = case.get("repause_ok", True)
        probes: list[object] = [
            {
                "cur_year": 30,
                "cur_year_tick": 348551,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 30,
                "cur_year_tick": 348551,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            DFHackError("probe unavailable"),
        ]
        if repause_ok:
            probes.append(
                {
                    "cur_year": final_year,
                    "cur_year_tick": final_tick,
                    "pause_state": final_pause,
                    "viewscreen_type": final_viewscreen,
                }
            )
        probe_iterator = iter(probes)

        def read_probe(**_kwargs):
            value = next(probe_iterator)
            if isinstance(value, Exception):
                raise value
            return value

        def set_paused(*_args, **_kwargs):
            if case.get("resume_error"):
                raise DFHackError("resume failed")

        repause = (
            {
                "ok": True,
                "paused": True,
                "attempts": 1,
                "attempt_records": [
                    {"attempt": 1, "nopause_disabled": True, "paused": True}
                ],
            }
            if repause_ok
            else {
                "ok": False,
                "paused": False,
                "attempts": 2,
                "attempt_records": [],
                "error": "pause_state_unverified",
            }
        )
        with monkeypatch.context() as case_patch:
            case_patch.setattr(
                tick_controller, "read_tick_pause_viewscreen", read_probe
            )
            case_patch.setattr(
                tick_controller,
                "_set_nopause",
                lambda _enabled: case.get("nopause_error"),
            )
            case_patch.setattr(tick_controller, "set_paused", set_paused)
            case_patch.setattr(
                tick_controller,
                "ensure_paused_external",
                lambda **_kwargs: repause,
            )
            case_patch.setattr(tick_controller.time, "sleep", lambda _duration: None)

            result = tick_controller.advance_ticks_exact_external(
                2500,
                interrupt_on_viewscreen_transition=True,
                viewscreen_before="viewscreen_dwarfmodest",
                max_advance_ticks=2500,
            )

        assert result["ok"] is False
        assert result["error"] != "blocking_viewscreen_transition"
        assert result["interrupt_safety_error"] is True
        assert result.get("interruption_detection") is None


def test_interrupt_final_attestation_failure_dominates_interruption(monkeypatch):
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 377,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
            DFHackError("final probe unavailable"),
        ]
    )

    def read_probe(timeout=1.0):
        value = next(probes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(tick_controller, "read_tick_pause_viewscreen", read_probe)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["interrupted"] is True
    assert result["ok"] is False
    assert result["error"] == "calendar_final_read_failed"
    assert result["interrupt_safety_error"] is True


def test_interrupt_final_attestation_inconsistency_dominates_interruption(monkeypatch):
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": False,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["interrupted"] is True
    assert result["error"] == "repause_unverified"
    assert result["paused_after"] is False
    assert result["repause_effective"] is False
    assert result["interrupt_safety_error"] is True


def test_repause_error_dominates_interruption(monkeypatch):
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 0,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_topicmeetingst",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: next(probes),
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": False,
            "paused": False,
            "error": "pause_state_unverified",
        },
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["interrupted"] is True
    assert result["error"] == "repause_unverified"
    assert result["repause_error"] == "pause_state_unverified"


def test_legacy_repause_failure_preserves_prior_error(monkeypatch):
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    reads = iter([100, DFHackError("transient timeout")])

    def read_tick(timeout=1.0):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": read_tick(timeout),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": False,
            "paused": False,
            "error": "pause_state_unverified",
        },
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is False
    assert result["error"] == "tick_read_failed:transient timeout"
    assert result["repause_error"] == "pause_state_unverified"


def test_advance_ticks_uses_space_fallback_when_pause_flag_sticks(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 100, 100, 112, 112, 112])
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

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": fake_tick_read(timeout),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", fake_read_pause_state)
    monkeypatch.setattr(tick_controller, "set_paused", fake_set_paused)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(
        tick_controller, "execute_keystroke_action", fake_execute_keystroke_action
    )
    monkeypatch.setattr(tick_controller.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(tick_controller.time, "sleep", fake_sleep)

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is True
    assert result["ticks_advanced"] == 12
    assert result["resume_fallback"] == "STRING_A032"
    assert keys == ["STRING_A032"]


def test_advance_ticks_honors_agent_request_above_legacy_cap(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 1600, 1600, 1600])

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda duration: None)

    result = tick_controller.advance_ticks_exact_external(1500, True)

    assert result["ok"] is True
    assert result["requested"] == 1500
    assert result["ticks_advanced"] == 1500


def test_advance_ticks_caps_direct_calls_at_action_schema_limit(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 2100, 2100, 2100])

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda duration: None)

    result = tick_controller.advance_ticks_exact_external(5000, True)

    assert result["ok"] is True
    assert result["requested"] == tick_controller.MAX_ADVANCE_TICKS
    assert result["ticks_advanced"] == tick_controller.MAX_ADVANCE_TICKS


def test_advance_ticks_allows_explicit_p1_limit(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 2600, 2600, 2600])

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda duration: None)

    result = tick_controller.advance_ticks_exact_external(
        2500, True, max_advance_ticks=2500
    )

    assert result["ok"] is True
    assert result["requested"] == 2500
    assert result["ticks_advanced"] == 2500


def test_tick_read_failure_after_nopause_fails_closed_and_recovers_end_tick(
    monkeypatch,
):
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    reads = iter([100, DFHackError("transient timeout"), 123])
    toggles: list[bool] = []
    pause_state = {"value": True}

    def fake_tick_read(timeout: float = 1.0) -> int:
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    def fake_set_nopause(enabled: bool) -> None:
        toggles.append(enabled)
        if enabled:
            pause_state["value"] = False
        return None

    def fake_set_paused(paused: bool, timeout: float = 1.0) -> None:
        pause_state["value"] = paused

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": fake_tick_read(timeout),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", fake_set_nopause)
    monkeypatch.setattr(tick_controller, "set_paused", fake_set_paused)
    monkeypatch.setattr(
        tick_controller,
        "read_pause_state",
        lambda timeout=1.0: pause_state["value"],
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is False
    assert result["error"] == "tick_read_failed:transient timeout"
    assert result["ticks_advanced"] == 23
    assert result["paused_after"] is True
    assert result["repause_effective"] is True
    assert toggles == [True, False]


def test_successful_repause_records_the_stable_post_pause_tick(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 110, 110, 115])
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is True
    assert result["end_tick"] == 115
    assert result["ticks_advanced"] == 15
    assert result["paused_after"] is True


def test_post_pause_tick_read_failure_is_not_reported_as_success(monkeypatch):
    from fort_gym.bench import tick_controller
    from fort_gym.bench.dfhack_exec import DFHackError

    ticks = iter([100, 110, 110, DFHackError("final read timeout")])

    def fake_tick_read(timeout: float = 1.0) -> int:
        value = next(ticks)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": fake_tick_read(timeout),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is False
    assert result["error"] == "final_tick_read_failed:final read timeout"
    assert result["repause_effective"] is True


def test_successful_tick_advance_fails_when_repause_is_unverified(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 110, 110])
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_kwargs: {
            "ok": False,
            "paused": False,
            "error": "pause_state_unverified",
        },
    )

    result = tick_controller.advance_ticks_exact_external(10, True)

    assert result["ok"] is False
    assert result["error"] == "repause_unverified"
    assert result["repause_effective"] is False
    assert result["repause_error"] == "pause_state_unverified"


def test_ensure_paused_requires_nopause_disable_and_pause_readback(monkeypatch):
    from fort_gym.bench import tick_controller

    monkeypatch.setattr(
        tick_controller,
        "_set_nopause",
        lambda enabled: "disable failed" if enabled is False else None,
    )
    monkeypatch.setattr(tick_controller, "set_paused", lambda paused, timeout=1.0: None)
    monkeypatch.setattr(tick_controller, "read_pause_state", lambda timeout=1.0: True)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.ensure_paused_external(attempts=2)

    assert result["ok"] is False
    assert result["paused"] is True
    assert result["attempts"] == 2
    assert all(
        record["nopause_disabled"] is False for record in result["attempt_records"]
    )


def test_success_with_repause_false_still_disables_nopause(monkeypatch):
    from fort_gym.bench import tick_controller

    ticks = iter([100, 110, 110])
    pauses = iter([True, False])
    toggles: list[bool] = []
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda timeout=1.0: {
            "cur_year": 0,
            "cur_year_tick": next(ticks),
            "pause_state": True,
            "viewscreen_type": "viewscreen_dwarfmodest",
        },
    )
    monkeypatch.setattr(
        tick_controller,
        "read_pause_state",
        lambda timeout=1.0: next(pauses),
    )
    monkeypatch.setattr(
        tick_controller,
        "_set_nopause",
        lambda enabled: toggles.append(enabled) or None,
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.advance_ticks_exact_external(10, repause=False)

    assert result["ok"] is True
    assert result["paused_after"] is True
    assert result["repause_effective"] is None
    assert toggles == [True, False]


def test_governed_repause_false_is_rejected_before_mutation(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    mutations: list[str] = []
    monkeypatch.setattr(
        tick_controller,
        "read_tick_pause_viewscreen",
        lambda **_: mutations.append("read") or {},
    )
    monkeypatch.setattr(
        tick_controller,
        "_set_nopause",
        lambda _enabled: mutations.append("nopause") or None,
    )
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda *_args, **_kwargs: mutations.append("pause"),
    )

    result = tick_controller.advance_ticks_exact_external(
        10,
        repause=False,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result == {
        "ok": False,
        "error": "governed_repause_required",
        "requested": 10,
        "ticks_advanced": 0,
        "repause_requested": False,
        "repause_effective": None,
    }
    assert mutations == []


def test_external_ticks_measure_a_same_year_calendar_span(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 125,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 125,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 125,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(25)

    assert (result["start_year"], result["start_tick"]) == (7, 100)
    assert (result["end_year"], result["end_tick"]) == (7, 125)
    assert result["ticks_advanced"] == 25


def test_external_ticks_measure_one_rollover(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 403199,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(2)

    assert result["ok"] is True
    assert (result["start_year"], result["start_tick"]) == (7, 403199)
    assert (result["end_year"], result["end_tick"]) == (8, 1)
    assert result["ticks_advanced"] == 2


def test_governed_interruption_preserves_rollover_ticks(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 403199,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_textviewerst",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["error"] == "blocking_viewscreen_transition"
    assert result["ticks_advanced"] == 2
    assert (result["start_year"], result["end_year"]) == (7, 8)


@pytest.mark.parametrize(
    ("second", "expected_error"),
    [
        ((7, 99), "calendar_tick_reversed"),
        ((6, 100), "calendar_year_decreased"),
        ((9, 100), "calendar_year_jump_invalid"),
    ],
)
def test_calendar_regressions_fail_closed(monkeypatch, second, expected_error) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": second[0],
                "cur_year_tick": second[1],
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(15)

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["calendar_safety_error"] is True


def test_unsafe_governed_baseline_contains_rollover_elapsed_ticks(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 403199,
                "pause_state": False,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 8,
                "cur_year_tick": 1,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["error"] == "interrupt_baseline_unpaused"
    assert result["ticks_advanced"] == 2
    assert result["interrupt_safety_error"] is True


def test_invalid_initial_calendar_sample_never_enables_nopause(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    mutations: list[object] = []
    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 403200,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 403200,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(
        tick_controller,
        "_set_nopause",
        lambda enabled: mutations.append(("nopause", enabled)),
    )
    monkeypatch.setattr(
        tick_controller,
        "set_paused",
        lambda paused, **_: mutations.append(("pause", paused)),
    )
    monkeypatch.setattr(
        tick_controller,
        "execute_keystroke_action",
        lambda keys: mutations.append(("keys", keys)) or {"ok": True},
    )
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )

    result = tick_controller.advance_ticks_exact_external(
        15,
        interrupt_on_viewscreen_transition=True,
        viewscreen_before="viewscreen_dwarfmodest",
    )

    assert result["error"] == "calendar_tick_out_of_range"
    assert result["interrupt_safety_error"] is True
    assert mutations == []


def test_repause_cap_plus_one_preserves_elapsed_ticks(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2101,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(2000)

    assert result["ok"] is True
    assert "error" not in result
    assert result["ticks_advanced"] == 2001
    assert result["end_tick"] == 2101


def test_repause_overshoot_beyond_allowance_fails_with_exact_ticks(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 2151,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(2000)

    assert result["ok"] is False
    assert result["error"] == "tick_overshoot_exceeds_allowance"
    assert result["ticks_advanced"] == 2051
    assert result["end_tick"] == 2151


def test_non_governed_final_unpaused_attestation_fails_repause(monkeypatch) -> None:
    from fort_gym.bench import tick_controller

    probes = iter(
        [
            {
                "cur_year": 7,
                "cur_year_tick": 100,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 110,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 110,
                "pause_state": True,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
            {
                "cur_year": 7,
                "cur_year_tick": 110,
                "pause_state": False,
                "viewscreen_type": "viewscreen_dwarfmodest",
            },
        ]
    )
    monkeypatch.setattr(
        tick_controller, "read_tick_pause_viewscreen", lambda **_: next(probes)
    )
    monkeypatch.setattr(tick_controller, "_set_nopause", lambda _enabled: None)
    monkeypatch.setattr(tick_controller, "set_paused", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tick_controller,
        "ensure_paused_external",
        lambda **_: {"ok": True, "paused": True},
    )
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _: None)

    result = tick_controller.advance_ticks_exact_external(10, repause=True)

    assert result["ok"] is False
    assert result["error"] == "repause_unverified"
    assert result["paused_after"] is False
    assert result["repause_effective"] is False
    assert result["repause_error"] == "pause_state_unverified"


def test_ensure_paused_converts_process_spawn_errors_to_failed_attempts(monkeypatch):
    from fort_gym.bench import tick_controller

    monkeypatch.setattr(tick_controller, "_set_nopause", lambda enabled: None)

    def fail_spawn(*_args, **_kwargs):
        raise FileNotFoundError("dfhack-run missing")

    monkeypatch.setattr(tick_controller, "set_paused", fail_spawn)
    monkeypatch.setattr(tick_controller, "read_pause_state", fail_spawn)
    monkeypatch.setattr(tick_controller.time, "sleep", lambda _duration: None)

    result = tick_controller.ensure_paused_external(attempts=2)

    assert result["ok"] is False
    assert result["paused"] is None
    assert result["attempts"] == 2
    assert all(
        "dfhack-run missing" in record["pause_error"]
        for record in result["attempt_records"]
    )
