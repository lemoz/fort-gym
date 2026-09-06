from __future__ import annotations

import shutil
import subprocess

import pytest

from fort_gym.bench import tick_controller


def test_nopause_uses_selected_dfhack_command_transport(monkeypatch) -> None:
    calls: list[tuple[str, list[str], float]] = []
    monkeypatch.setattr(
        tick_controller,
        "run_command",
        lambda command, arguments, *, timeout: (
            calls.append((command, arguments, timeout)) or ""
        ),
    )

    assert tick_controller._set_nopause(False) is None
    assert tick_controller._set_nopause(True) is None
    assert calls == [
        ("nopause", ["0"], 2.0),
        ("nopause", ["1"], 2.0),
    ]


def test_nopause_transport_failure_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        tick_controller,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rpc down")),
    )

    assert tick_controller._set_nopause(False) == "rpc down"


def _deadline_scripts(monkeypatch):
    scripts = []
    def capture(command, arguments, *, timeout):
        assert command == "lua"
        assert timeout == 2.5
        scripts.append(arguments[0])
        return "a" * 32
    monkeypatch.setattr(tick_controller.uuid, "uuid4", lambda: type("ID", (), {"hex": "a" * 32})())
    monkeypatch.setattr(tick_controller, "run_command", capture)
    token = tick_controller._arm_tick_deadline(200, {"cur_year": 1, "cur_year_tick": 100})
    tick_controller._cancel_tick_deadline(token)
    return scripts


@pytest.mark.parametrize("interrupt_at", [None, 53])
def test_runtime_deadline_stops_without_host_polling_and_cancels(monkeypatch, interrupt_at):
    lua = shutil.which("lua")
    if lua is None:
        pytest.skip("Lua interpreter required for runtime timer simulation")
    arm, cancel = _deadline_scripts(monkeypatch)
    prefix = """
df = {global={cur_year=1, cur_year_tick=100, pause_state=true}}
local callback, due
local nopause = false
dfhack = {
    timeout=function(ticks, unit, cb)
        assert(unit == 'ticks'); due=100+ticks; callback=cb; return 0
    end,
    timeout_active=function(id, cb) assert(id == 0); callback=cb end,
    run_command=function(command, value)
        assert(command == 'nopause' and value == '0'); nopause=false
    end,
}
local function advance(frames)
    for frame=1,frames do
        if nopause then df.global.pause_state=false end
        if not df.global.pause_state then
            df.global.cur_year_tick=df.global.cur_year_tick+1
        end
        if callback and df.global.cur_year_tick >= due then
            local cb=callback; callback=nil; cb()
        end
    end
end
"""
    if interrupt_at is None:
        scenario = """
nopause=true; df.global.pause_state=false
advance(10000) -- host cannot poll or repause during this interval
assert(df.global.cur_year_tick == 300)
assert(df.global.pause_state == true and nopause == false)
"""
    else:
        scenario = f"""
nopause=true; df.global.pause_state=false
advance({interrupt_at})
nopause=false; df.global.pause_state=true
assert(df.global.cur_year_tick == {100 + interrupt_at})
"""
    suffix = """
assert(_G._fortgym_tick_deadline == nil)
local before=df.global.cur_year_tick
df.global.pause_state=false
advance(400)
assert(df.global.cur_year_tick == before+400) -- no stale callback interrupts next action
"""
    result = subprocess.run([lua, "-"], input=prefix + arm + scenario + cancel + suffix,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_deadline_rejects_wrong_acknowledgement(monkeypatch):
    monkeypatch.setattr(tick_controller, "run_command", lambda *_a, **_kw: "unexpected")
    with pytest.raises(tick_controller.DFHackError, match="acknowledgement"):
        tick_controller._arm_tick_deadline(200, {"cur_year": 1, "cur_year_tick": 100})


def test_deadline_cancel_rejects_untrusted_identity_before_rpc(monkeypatch):
    monkeypatch.setattr(tick_controller, "run_command", lambda *_a, **_kw: pytest.fail("unexpected RPC"))
    with pytest.raises(tick_controller.DFHackError, match="identity"):
        tick_controller._cancel_tick_deadline("'injected'")


@pytest.mark.parametrize("colored", [False, True])
def test_deadline_acknowledgements_accept_cli_display_codes_only(monkeypatch, colored):
    token = "a" * 32
    output = f"\x1b[0m{token}\n\x1b[0m" if colored else token
    monkeypatch.setattr(tick_controller.uuid, "uuid4", lambda: type("ID", (), {"hex": token})())
    monkeypatch.setattr(tick_controller, "run_command", lambda *_args, **_kwargs: output)
    assert tick_controller._arm_tick_deadline(10, {"cur_year": 30, "cur_year_tick": 19309}) == token
    tick_controller._cancel_tick_deadline(token)


def test_colored_wrong_acknowledgement_is_still_rejected(monkeypatch):
    monkeypatch.setattr(tick_controller, "run_command", lambda *_args, **_kwargs: "\x1b[0munexpected\n\x1b[0m")
    with pytest.raises(tick_controller.DFHackError, match="acknowledgement"):
        tick_controller._arm_tick_deadline(10, {"cur_year": 30, "cur_year_tick": 19309})
