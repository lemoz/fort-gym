"""Execute the normal-job fixture with native doubles, not gameplay evidence."""

import copy
import subprocess
from pathlib import Path

import pytest

from fort_gym.bench import production_brew_fixture as brew
from fort_gym.bench.production_observer_probe import SLOT, ProductionObserverProbe
from tests.test_selected_workshop_lua import LUA, PRELUDE

OBSERVER = ProductionObserverProbe(Path("/isolated"), "a" * 32)
STATE = {"year": 30, "year_tick": 123, "pause_state": True}
FIXTURE = f"""
building.subtype=2
df.global.world.cur_savegame.save_dir='campaign-resume'
df.building={{find=function(id) assert(locked and id==7); return building end}}
dfhack.getDFVersion=function() return 'v0.47.05 linux64' end
dfhack.getDFHackVersion=function() return '0.47.05-r8' end
local active=true
local slot={{owner='{"a" * 32}', observer={{snapshot=function()
    return {{installed=active, collector_records_complete=true}}
end}}}}
rawset(_G, '{SLOT}', slot)
"""


def run(setup="", assertions="", repeat=False):
    if LUA is None:
        pytest.skip("Lua interpreter unavailable")
    expression = brew.brew_expression(OBSERVER, STATE, 7)
    script = PRELUDE + FIXTURE + setup + expression
    if repeat:
        script += expression
    script += "\nassert(not locked)\n" + assertions
    result = subprocess.run(
        [LUA, "-"], input=script, text=True, capture_output=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


def test_exact_still_gets_one_native_job_and_cloned_reagent_filters():
    run(
        assertions="""
assert(captured.ok and captured.command_mutation=='completed')
assert(captured.jobs_queued==1 and captured.created_job_ids[1]==100)
assert(captured.queue_before==0 and captured.queue_after==1)
assert(captured.workshop_id==7 and captured.quantity==1)
assert(#linked==1 and #building.jobs==1 and df.global.job_next_id==101)
assert(slot.brew_attempted and refreshes==0)
local job=linked[1]
assert(job.job_type==7 and job.reaction_name=='BREW_DRINK_FROM_PLANT')
assert(job.flags.special and job.completion_timer==-1)
assert(job.job_items[1].item_type==77 and job.job_items[1].reagent_index==0)
assert(job.job_items[1].new and defs[2].items[1].new==nil)
assert(job.general_refs[1].building_id==7 and job.pos.x==20 and job.pos.z==4)
assert(captured.before.year_tick==123 and captured.after.year_tick==123)
assert(df.global.pause_state and df.global.cur_year_tick==123)
"""
    )


@pytest.mark.parametrize(
    "setup",
    [
        "loaded=false",
        "dfhack.getDFPath=function() return '/active' end",
        "dfhack.getDFVersion=function() return 'different' end",
        "dfhack.getDFHackVersion=function() return 'different' end",
        "df.global.cur_year=31",
        "df.global.cur_year_tick=124",
        "df.global.pause_state=false",
        "df.global.world.cur_savegame.save_dir='active'",
        f"rawset(_G, '{SLOT}', nil)",
        "slot.owner='another'",
        "active=false",
        "slot.observer.snapshot=function() return {installed=true, collector_records_complete=false} end",
        "slot.brew_attempted=true",
        "df.building.find=function() return nil end",
        "building.id=8",
        "building.subtype=1",
        "removed=true",
        "complete=false",
        "building.jobs:insert('#', {id=90})",
        "defs={}",
        "defs[2].items={}",
        "table.insert(defs, defs[2])",
    ],
)
def test_preflight_failures_never_allocate_or_link_a_job(setup):
    run(
        setup,
        """
assert(not captured.ok and captured.error and captured.command_mutation=='not_attempted')
assert(captured.jobs_queued==0 and allocations==0 and #linked==0)
""",
    )


@pytest.mark.parametrize(
    "setup",
    [
        "fail_at=1",
        "dfhack.job.linkIntoWorld=function() return false end",
    ],
)
def test_mutation_failures_are_retained_and_attempt_consumed(setup):
    run(
        setup,
        """
assert(not captured.ok and captured.command_mutation=='attempted' and captured.error)
assert(slot.brew_attempted and captured.jobs_queued==0 and allocations==1)
""",
    )


def test_repeating_rpc_cannot_queue_a_second_job():
    run(
        assertions="""
assert(not captured.ok and captured.error:find('already attempted'))
assert(allocations==1 and #linked==1 and #building.jobs==1)
""",
        repeat=True,
    )


@pytest.mark.parametrize("workshop_id", [-1, True, 1.5, "7", 2147483648])
def test_invalid_workshop_ids_rejected_without_rpc(workshop_id):
    with pytest.raises(ValueError):
        brew.brew_expression(OBSERVER, STATE, workshop_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pause_state", False),
        ("year", True),
        ("year", -1),
        ("year", 1000001),
        ("year_tick", True),
        ("year_tick", 403200),
        ("year_tick", -1),
    ],
)
def test_invalid_clock_rejected_without_rpc(field, value):
    with pytest.raises(ValueError):
        brew.brew_expression(OBSERVER, {**STATE, field: value}, 7)


def receipt(observer=OBSERVER, state=None, workshop_id=7):
    state = STATE if state is None else state
    point = {
        "root": str(observer.runtime),
        "year": state["year"],
        "year_tick": state["year_tick"],
        "paused": True,
        "save_name": "campaign-resume",
    }
    return {
        "schema_version": brew.SCHEMA,
        "owner": observer.owner,
        "workshop_id": workshop_id,
        "reaction_code": brew.REACTION,
        "quantity": 1,
        "ok": True,
        "command_mutation": "completed",
        "jobs_queued": 1,
        "created_job_ids": [100],
        "queue_before": 0,
        "queue_after": 1,
        "before": point,
        "after": copy.deepcopy(point),
    }


def test_receipt_only_confirms_insertion():
    brew.validate_brew_receipt(receipt(), OBSERVER, STATE, 7)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "other"),
        ("owner", "another"),
        ("workshop_id", 8),
        ("reaction_code", "other"),
        ("quantity", True),
        ("ok", False),
        ("command_mutation", "attempted"),
        ("jobs_queued", True),
        ("queue_before", False),
        ("queue_after", True),
        ("before", {}),
        ("after", {}),
        ("created_job_ids", []),
        ("created_job_ids", [True]),
        ("created_job_ids", [-1]),
        ("created_job_ids", [100, 101]),
    ],
)
def test_changed_receipts_never_confirm_insertion(field, value):
    with pytest.raises(ValueError):
        brew.validate_brew_receipt({**receipt(), field: value}, OBSERVER, STATE, 7)


def test_rpc_retains_raw_response_without_retry(monkeypatch):
    calls = []

    def rpc(expression, timeout):
        calls.append((expression, timeout))
        return "raw response"

    monkeypatch.setattr(brew, "run_lua_expr", rpc)
    assert brew.queue_brew(OBSERVER, STATE, 7) == "raw response"
    assert len(calls) == 1 and calls[0][1] == 10
