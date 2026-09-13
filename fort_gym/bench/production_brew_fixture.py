"""One normal brewing job in an explicit copied-save Still, never an agent control."""

from __future__ import annotations

import json

from .dfhack_exec import run_lua_expr
from .production_observer_probe import SLOT, ProductionObserverProbe

SCHEMA = "fortgym.private-production-brew-fixture/v1"
REACTION = "BREW_DRINK_FROM_PLANT"

BREW_FIXTURE_LUA = r"""
local function queue_fixture(config)
    local result = {schema_version='fortgym.private-production-brew-fixture/v1',
        owner=config.owner, workshop_id=config.workshop_id,
        reaction_code='BREW_DRINK_FROM_PLANT', quantity=1, ok=false,
        command_mutation='not_attempted', jobs_queued=0, created_job_ids={}}
    local function boundary()
        return {root=dfhack.getDFPath(), year=df.global.cur_year,
            year_tick=df.global.cur_year_tick, paused=df.global.pause_state,
            save_name=df.global.world.cur_savegame.save_dir}
    end
    local function matches(point)
        return point.root==config.root and point.year==config.year
            and point.year_tick==config.year_tick and point.paused==true
            and point.save_name=='campaign-resume'
    end
    local locked, failure = pcall(dfhack.with_suspend, function()
        assert(dfhack.getDFVersion()=='v0.47.05 linux64', 'unsupported DF')
        assert(dfhack.getDFHackVersion()=='0.47.05-r8', 'unsupported DFHack')
        assert(dfhack.isMapLoaded() and dfhack.world.isFortressMode(), 'fortress not loaded')
        result.before=boundary()
        assert(matches(result.before), 'fixture boundary differs')
        local slot=rawget(_G, config.slot)
        assert(slot and slot.owner==config.owner, 'fixture observer owner differs')
        local snapshot=slot.observer.snapshot()
        assert(snapshot.installed==true and snapshot.collector_records_complete==true,
            'fixture observer unavailable')
        assert(not slot.brew_attempted, 'fixture job already attempted')
        -- Exact caller-selected identity, not a search or UI-selection assumption.
        local building=df.building.find(config.workshop_id)
        assert(df.building_workshopst:is_instance(building), 'fixture workshop absent')
        assert(building.id==config.workshop_id and building:getSubtype()==df.workshop_type.Still,
            'fixture workshop is not the declared Still')
        assert(not dfhack.buildings.markedForRemoval(building)
            and building:getBuildStage()==building:getMaxBuildStage(), 'fixture Still unavailable')
        result.queue_before=#building.jobs
        assert(result.queue_before==0, 'fixture Still queue must be empty')
        local entry=nil
        for _, candidate in pairs(require('dfhack.workshops').getJobs(
                building:getType(), building:getSubtype(), building:getCustomType()) or {}) do
            if candidate.job_fields and candidate.job_fields.job_type==df.job_type.CustomReaction
                    and candidate.job_fields.reaction_name==result.reaction_code then
                assert(entry==nil, 'ambiguous native brewing definition')
                entry=candidate
            end
        end
        assert(entry and entry.items and #entry.items>0, 'native brewing definition absent')
        slot.brew_attempted=true
        result.command_mutation='attempted'
        -- Same native job construction as the selected-workshop shorthand. No
        -- material injection, instant completion, labour edits or manual job id.
        local job=df.job:new()
        job.flags.special=true
        job.completion_timer=-1
        job.pos.x, job.pos.y, job.pos.z=building.x1, building.y1, building.z
        job:assign(entry.job_fields)
        for _, filter in ipairs(entry.items) do
            local copy=require('utils').clone(filter, true)
            copy.new=true
            job.job_items:insert('#', copy)
        end
        job.general_refs:insert('#', {new=df.general_ref_building_holderst, building_id=building.id})
        building.jobs:insert('#', job)
        assert(dfhack.job.linkIntoWorld(job, true)==true, 'native job link failed')
        result.created_job_ids[1]=job.id
        result.jobs_queued=1
        result.queue_after=#building.jobs
        result.after=boundary()
        assert(matches(result.after), 'fixture boundary changed')
        assert(result.queue_after==1, 'fixture queue count differs')
        result.command_mutation='completed'
        result.ok=true
    end)
    if not locked then result.error=tostring(failure) end
    return result
end
"""


def validate_workshop_id(workshop_id: int | None) -> None:
    if workshop_id is not None and (
        type(workshop_id) is not int or not 0 <= workshop_id <= 2147483647
    ):
        raise ValueError("Brew fixture requires an explicit nonnegative workshop ID")


def brew_expression(
    observer: ProductionObserverProbe, state: dict, workshop_id: int
) -> str:
    """Build a single-use, owner/calendar-bound command, without running it."""
    validate_workshop_id(workshop_id)
    if workshop_id is None or state.get("pause_state") is not True:
        raise ValueError("Brew fixture requires a paused declared boundary")
    year, tick = state.get("year"), state.get("year_tick")
    if (
        type(year) is not int
        or not 0 <= year <= 1000000
        or type(tick) is not int
        or not 0 <= tick < 403200
    ):
        raise ValueError("Brew fixture requires a valid native calendar")
    return (
        BREW_FIXTURE_LUA
        + f"""
print(require('json').encode(queue_fixture({{
    root={json.dumps(str(observer.runtime))}, owner={json.dumps(observer.owner)},
    slot='{SLOT}', year={year}, year_tick={tick}, workshop_id={workshop_id},
}})))
"""
    )


def queue_brew(observer: ProductionObserverProbe, state: dict, workshop_id: int) -> str:
    """Return the raw RPC reply so a caller retains it before validation; no retry."""
    return run_lua_expr(brew_expression(observer, state, workshop_id), timeout=10)


def validate_brew_receipt(
    value: dict, observer: ProductionObserverProbe, state: dict, workshop_id: int
) -> None:
    """Validate job insertion only, never job completion or drink production."""
    point = {
        "root": str(observer.runtime),
        "year": state["year"],
        "year_tick": state["year_tick"],
        "paused": True,
        "save_name": "campaign-resume",
    }
    ids = value.get("created_job_ids")
    if (
        value.get("schema_version") != SCHEMA
        or value.get("owner") != observer.owner
        or type(value.get("workshop_id")) is not int
        or value.get("workshop_id") != workshop_id
        or value.get("reaction_code") != REACTION
        or type(value.get("quantity")) is not int
        or value.get("quantity") != 1
        or value.get("ok") is not True
        or value.get("command_mutation") != "completed"
        or type(value.get("jobs_queued")) is not int
        or value.get("jobs_queued") != 1
        or type(value.get("queue_before")) is not int
        or value.get("queue_before") != 0
        or type(value.get("queue_after")) is not int
        or value.get("queue_after") != 1
        or value.get("before") != point
        or value.get("after") != point
        or not isinstance(ids, list)
        or len(ids) != 1
        or type(ids[0]) is not int
        or not 0 <= ids[0] <= 2147483647
    ):
        raise ValueError("Native brewing job insertion was not confirmed")
