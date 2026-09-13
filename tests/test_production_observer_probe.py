"""Offline adapter/ownership checks; these do not establish native event coverage."""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fort_gym.bench import production_observer_probe as adapter

OWNER = "a" * 32


def boundary(runtime=Path("/game"), owner=OWNER, tick=100):
    point = {
        "root": str(runtime),
        "save_name": "campaign-resume",
        "year": 30,
        "year_tick": tick,
        "frame_counter": tick + 400,
    }
    shared = {
        "campaign_id": owner,
        "segment_id": 0,
        "native_coverage_validated": False,
        "agent_observation": False,
    }
    return {
        "schema_version": adapter.SCHEMA,
        "owner": owner,
        "operation": "capture",
        "inventory": {
            **shared,
            "schema_version": "fortgym.private-production-inventory/v1",
            "complete": True,
            "start": point,
            "endpoint": copy.deepcopy(point),
            "observer_start": point,
            "event_sequence": 0,
        },
        "events": {
            **shared,
            "schema_version": "fortgym.private-production-events/v1",
            "collector_records_complete": True,
            "installed": True,
            "endpoint": copy.deepcopy(point),
            "start": point,
            "observed_events": 0,
        },
    }


def test_complete_boundary_is_not_native_coverage_acceptance():
    value = boundary()
    adapter.validate_boundary(
        value, {"year": 30, "year_tick": 100, "pause_state": True}, Path("/game"), OWNER
    )
    assert not value["events"]["native_coverage_validated"]


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("inventory", "complete", False),
        ("events", "collector_records_complete", False),
        ("events", "installed", False),
        ("events", "schema_version", "wrong"),
        ("events", "campaign_id", "wrong"),
        ("inventory", "segment_id", 1),
        ("events", "native_coverage_validated", True),
        ("inventory", "agent_observation", True),
        ("inventory", "event_sequence", 2),
        ("inventory", "observer_start", {}),
        ("events", "endpoint", {}),
        ("inventory", "endpoint", {}),
    ],
)
def test_boundary_rejects_incomplete_mismatched_and_overclaimed_evidence(
    section, field, value
):
    payload = boundary()
    payload[section][field] = value
    with pytest.raises(ValueError):
        adapter.validate_boundary(
            payload,
            {"year": 30, "year_tick": 100, "pause_state": True},
            Path("/game"),
            OWNER,
        )


@pytest.mark.parametrize(
    "state",
    [
        {"year": 30, "year_tick": 101, "pause_state": True},
        {"year": 30, "year_tick": 100, "pause_state": False},
    ],
)
def test_boundary_rejects_wrong_native_state(state):
    with pytest.raises(ValueError):
        adapter.validate_boundary(boundary(), state, Path("/game"), OWNER)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"schema_version": adapter.SCHEMA, "owner": "b" * 32, "operation": "start"},
    ],
)
def test_rpc_response_identity_is_checked(monkeypatch, value):
    monkeypatch.setattr(adapter, "run_lua_expr", lambda *a, **k: json.dumps(value))
    with pytest.raises(ValueError):
        adapter.ProductionObserverProbe(Path("/game"), OWNER).command("start")


def test_rpc_is_bounded_and_import_is_passive(monkeypatch):
    calls = []

    def execute(expression, **kwargs):
        calls.append((expression, kwargs))
        return json.dumps(
            {
                "schema_version": adapter.SCHEMA,
                "owner": OWNER,
                "operation": "start",
                "installed": True,
            }
        )

    monkeypatch.setattr(adapter, "run_lua_expr", execute)
    probe = adapter.ProductionObserverProbe(Path("/game"), OWNER)
    assert calls == []
    assert probe.command("start")["installed"] is True
    assert calls[0][1] == {"timeout": 10}
    with pytest.raises(ValueError):
        probe.expression("queue")
    with pytest.raises(ValueError):
        adapter.ProductionObserverProbe(Path("/game"), "unsafe'owner")


@pytest.mark.skipif(shutil.which("lua") is None, reason="Lua interpreter unavailable")
@pytest.mark.parametrize(
    "scenario", ["normal", "collision", "wrong_root", "installation_failure"]
)
def test_real_lua_adapter_owns_only_its_slot(scenario):
    # Reuse the collector's fake native-object fixture, not a second game model.
    from tests.test_production_observer_lua import PRELUDE

    probe = adapter.ProductionObserverProbe(Path("/game"), OWNER)
    script = (
        PRELUDE
        + """
df.global.world.cur_savegame.save_dir = 'campaign-resume'
df.global.world.items = {other={IN_PLAY={}}}
local printed = {}
local print = function(value) printed[#printed+1] = value end
local require = function(name)
    if name == 'plugins.eventful' then return eventful end
    assert(name == 'json')
    return {encode=function(value) return value end}
end
"""
    )
    script += "\nlocal function start()\n" + probe.expression("start") + "\nend\n"
    script += "\nlocal function capture()\n" + probe.expression("capture") + "\nend\n"
    script += "\nlocal function stop()\n" + probe.expression("stop") + "\nend\n"
    if scenario == "normal":
        script += f"""
start()
assert(printed[#printed].installed)
assert(not pcall(start))
capture()
assert(printed[#printed].inventory.complete)
assert(not printed[#printed].events.native_coverage_validated)
local other = function() end
eventful.onItemCreated.other = other
stop()
assert(printed[#printed].installed == false)
assert(rawget(_G, '{adapter.SLOT}') == nil)
assert(eventful.onItemCreated.other == other)
assert(eventful.onItemCreated[key] == nil)
stop()
assert(printed[#printed].owner_slot_absent)
"""
    elif scenario == "collision":
        script += f"""
local other = {{owner='different'}}
rawset(_G, '{adapter.SLOT}', other)
assert(not pcall(start) and not pcall(capture) and not pcall(stop))
assert(rawget(_G, '{adapter.SLOT}') == other)
"""
    elif scenario == "wrong_root":
        script += "dfhack.getDFPath = function() return '/not-owned' end\nassert(not pcall(start))\nassert(not pcall(stop))"
    else:
        script += "eventful.enableEvent = function() error('fixture unavailable') end\nassert(not pcall(start))\nstop()\nassert(printed[#printed].owner_slot_absent)"
    completed = subprocess.run(
        [shutil.which("lua"), "-"],
        input=script,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
