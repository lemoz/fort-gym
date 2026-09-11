"""Experimental key projection and dispatch tests, not physical keyboard proof."""

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

BASE = Path(__file__).resolve().parents[1] / "experiments/keyboard_binding_adapter_20260911"
SPEC = importlib.util.spec_from_file_location("experimental_bindings", BASE / "bindings.py")
bindings = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bindings
SPEC.loader.exec_module(bindings)


def parse(text):
    return bindings.parse_bindings(text.encode("utf-8"))


def test_complete_binding_set_is_case_sensitive_deduplicated_and_source_bound():
    raw = (
        "\ufeff[BIND:CUSTOM_B:REPEAT_NOT]\r\n[KEY:b]\r\n[KEY:b]\r\n"
        "[BIND:HOTKEY_CARPENTER_BED:REPEAT_NOT]\r\n[KEY:b]\r\n"
        "[BIND:STRING_A098:REPEAT_SLOW]\r\n[KEY:b]\r\n"
        "[BIND:CUSTOM_SHIFT_B:REPEAT_NOT]\r\n[KEY:B]\r\n"
    ).encode("utf-8")
    index = bindings.parse_bindings(raw)
    assert index.sha256 == hashlib.sha256(raw).hexdigest()
    assert index.resolve({"type": "character", "value": "b"}) == (
        "CUSTOM_B",
        "HOTKEY_CARPENTER_BED",
        "STRING_A098",
    )
    assert index.resolve({"type": "character", "value": "B"}) == ("CUSTOM_SHIFT_B",)
    assert index.repeat_policy["STRING_A098"] == "REPEAT_SLOW"


def test_legacy_nel_and_delimiter_characters_do_not_split_or_strip_records():
    for char in ("\x85", " ", ":", "[", "]", "é"):
        index = parse(f"[BIND:STRING_A133:REPEAT_SLOW]\n[KEY:{char}]\n")
        assert index.resolve({"type": "character", "value": char}) == ("STRING_A133",)


def test_symbols_modifier_masks_mouse_and_repeated_declarations():
    index = parse(
        "# comment\n[BIND:SELECT:REPEAT_NOT]\n[SYM:0:Enter]\n"
        "[SYM:0:Numpad Enter]\n[BUTTON:0:1]\n"
        "[BIND:SEC_SELECT:REPEAT_NOT]\n[SYM:1:Enter]\n"
        "[BIND:SELECT:REPEAT_NOT]\n[SYM:0:Enter]\n"
    )
    for symbol in ("Enter", "Numpad Enter"):
        assert index.resolve({"type": "symbol", "value": symbol, "modifiers": 0}) == ("SELECT",)
    assert index.resolve({"type": "symbol", "value": "Enter", "modifiers": 1}) == ("SEC_SELECT",)
    assert index.mouse_bindings == 1
    with pytest.raises(ValueError):
        index.resolve({"type": "symbol", "value": "Enter", "modifiers": 2})


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "b",
        {},
        {"type": "character", "value": ""},
        {"type": "character", "value": "bb"},
        {"type": "character", "value": "\n"},
        {"type": "character", "value": "b", "modifiers": 0},
        {"type": "character", "value": "unknown"},
        {"type": "symbol", "value": "Enter", "modifiers": True},
        {"type": "symbol", "value": "Enter", "modifiers": -1},
        {"type": "symbol", "value": "Enter", "modifiers": 8},
        {"type": "symbol", "value": "Enter"},
        {"type": "symbol", "value": "Enter", "modifiers": 0, "extra": 1},
        {"type": "button", "value": 1, "modifiers": 0},
    ],
)
def test_bad_requests_fail_without_fallback(event):
    index = parse("[BIND:CUSTOM_B:REPEAT_NOT]\n[KEY:b]\n")
    with pytest.raises(ValueError):
        index.resolve(event)


@pytest.mark.parametrize(
    "suffix",
    [
        "[KEY:]",
        "[KEY:ab]",
        "[KEY:\t]",
        "[SYM:8:Enter]",
        "[SYM:0:]",
        "[SYM:0:[Enter]]",
        "[BUTTON:0:256]",
        "[BUTTON:0:x]",
        "[BUTTON:0:١]",
        "[OTHER:0:Enter]",
        "[BIND:CUSTOM_B:INVALID]",
        "[BIND:lower:REPEAT_NOT]",
        "[BIND:CUSTOM_B:REPEAT_FAST]",
        "not a record",
    ],
)
def test_unknown_or_ambiguous_file_records_fail(suffix):
    with pytest.raises(ValueError):
        parse("[BIND:CUSTOM_B:REPEAT_NOT]\n[KEY:b]\n" + suffix)


@pytest.mark.parametrize(
    "raw",
    [b"", b"\xff", b"[KEY:b]", b"# comments only", b"[BIND:CUSTOM_B:REPEAT_NOT]", "not bytes"],
)
def test_unusable_file_rejected(raw):
    with pytest.raises(ValueError):
        bindings.parse_bindings(raw)


def test_resource_bounds(monkeypatch):
    monkeypatch.setattr(bindings, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError):
        parse("[BIND:A:REPEAT_NOT]\n[KEY:b]\n")
    monkeypatch.setattr(bindings, "MAX_FILE_BYTES", 1000)
    monkeypatch.setattr(bindings, "MAX_EVENTS", 1)
    raw = "[BIND:A:REPEAT_NOT]\n[KEY:b]\n[BIND:B:REPEAT_NOT]\n[KEY:b]\n"
    with pytest.raises(ValueError):
        parse(raw)
    monkeypatch.setattr(bindings, "MAX_EVENTS", 2)
    monkeypatch.setattr(bindings, "MAX_EVENTS_PER_KEY", 1)
    with pytest.raises(ValueError):
        parse(raw).resolve({"type": "character", "value": "b"})


@pytest.mark.parametrize("mode", ["success", "invalid", "duplicate", "boundary", "throws"])
def test_lua_dispatch_is_one_simultaneous_set_or_no_call(mode):
    lua = shutil.which("lua")
    if not lua:
        pytest.skip("Lua runtime unavailable; native dispatch remains unproven")
    program = r"""
local mode, path = arg[1], arg[2]
local calls, encoded = 0, nil
local view={}
df={interface_key={CUSTOM_B=107,STRING_A098=1457,HOTKEY_CARPENTER_BED=772},
    global={cur_year=30,cur_year_tick=152201,pause_state=true,
            world={cur_savegame={save_dir='region'}}}}
dfhack={getDFPath=function() return '/runtime' end,
  isMapLoaded=function() return true end,world={isFortressMode=function() return true end},
  with_suspend=function(fn) fn() end,
  gui={getCurViewscreen=function() return view end,
       getFocusString=function() return 'menu' end}}
package.preload.json=function() return {encode=function(value) encoded=value; return '{}' end} end
package.preload.gui=function() return {simulateInput=function(screen, keys)
  calls=calls+1
  assert(screen==view and #keys==3)
  assert(keys[1]==107 and keys[2]==772 and keys[3]==1457)
  df.global.pause_state=false
  if mode=='throws' then error('input failed') end
end} end
local events={'CUSTOM_B','HOTKEY_CARPENTER_BED','STRING_A098'}
if mode=='invalid' then events[3]='NOT_A_KEY' end
if mode=='duplicate' then events[3]='CUSTOM_B' end
if mode=='boundary' then df.global.cur_year_tick=152202 end
assert(loadfile(path))('/runtime','30','152201','region',table.unpack(events))
local executed=mode=='success' or mode=='throws'
assert(calls==(executed and 1 or 0))
assert(encoded.input_calls==calls and encoded.ok==(mode=='success'))
assert(df.global.pause_state==true)
"""
    subprocess.run(
        [lua, "-", mode, str(BASE / "event_set.lua")],
        input=program,
        text=True,
        check=True,
        capture_output=True,
        timeout=10,
    )
