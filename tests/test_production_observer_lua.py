"""Execute the collector with fake native objects, not a simulated-game claim."""

import shutil
import subprocess

import pytest

from fort_gym.bench.production_observer_lua import PRODUCTION_OBSERVER_LUA

LUA = shutil.which("lua")
PRELUDE = r"""
local callbacks = {JOB_COMPLETED=1, ITEM_CREATED=2, UNLOAD=3}
local eventful = {onJobCompleted={}, onItemCreated={}, onUnload={},
    eventType=callbacks, enabled={}}
eventful.enableEvent = function(kind, frequency) eventful.enabled[kind] = frequency end
local loaded = true
local df = {global = {pause_state=true, cur_year=30, cur_year_tick=100,
    world={frame_counter=500, cur_savegame={save_dir='region1'}}},
    item_type={DRINK=6}, job_type={[10]='BrewDrink'}, item={}}
local dfhack = {getDFVersion=function() return 'v0.47.05 linux64' end,
    getDFHackVersion=function() return '0.47.05-r8' end,
    getDFPath=function() return '/game' end,
    isMapLoaded=function() return loaded end}
local items = {}
df.item.find = function(id) return items[id] end
local config = {campaign_id='test-campaign', segment_id=0, max_events=10, expected_root='/game'}
local key = 'fortgym_production_observer_v1'
local function item(id, units, kind, edible)
    local flags = {}
    for _, name in ipairs({'removed', 'garbage_collect', 'foreign', 'trader',
        'owned', 'spider_web', 'rotten', 'forbid', 'in_job', 'hidden'}) do
        flags[name] = false
    end
    items[id] = {id=id, flags=flags, getType=function() return kind end,
        getStackSize=function() return units end,
        isEdibleRaw=function(_, arg) assert(arg==0); return edible end}
    return items[id]
end
local function job()
    return {id=12, job_type=10, flags={['repeat']=false}, completion_timer=0}
end
"""


@pytest.mark.skipif(LUA is None, reason="Lua interpreter unavailable")
@pytest.mark.parametrize(
    "scenario",
    [
        """
local observer = new_production_observer(df, dfhack, eventful, config)
config.max_events = 0
config.campaign_id = 'changed'
observer.start()
eventful.onJobCompleted[key](job())
assert(observer.snapshot().campaign_id == 'test-campaign')
assert(observer.snapshot().retained_events == 1)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
eventful.enableEvent = function(kind)
    if kind == 2 then error('unavailable') end
end
assert(not pcall(observer.start))
assert(eventful.onJobCompleted[key] == nil and eventful.onItemCreated[key] == nil)
local r = observer.snapshot()
assert(r.stop_reason == 'installation_failed' and not r.collector_records_complete)
assert(not pcall(observer.start))
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
df.global.pause_state = false
assert(observer.snapshot().endpoint == false)
assert(not observer.snapshot().collector_records_complete)
df.global.pause_state = true
local j = job()
j.completion_timer = -1
eventful.onJobCompleted[key](j)
assert(observer.snapshot().read_failures == 1)
assert(not observer.snapshot().collector_records_complete)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
assert(eventful.enabled[1] == 0 and eventful.enabled[2] == 0)
local j = job()
eventful.onJobCompleted[key](j)
item(17, 5, 6)
eventful.onItemCreated[key](17)
local r = observer.snapshot()
assert(r.collector_records_complete and #r.events == 2)
assert(r.events[1].kind == 'job_completion_notification')
assert(r.events[1].product_quantity_status == 'not_measured')
assert(r.events[2].kind == 'item_creation_observation')
assert(r.events[2].resource == 'drink' and r.events[2].units_at_observation == 5)
assert(r.flow_measurement.production == 'not_measured')
assert(r.flow_measurement.consumption == 'not_measured')
assert(r.events[2].attribution == 'unattributed')
assert(r.native_coverage_validated == false and r.agent_observation == false)
assert(j.completion_timer == 0 and items[17].flags.removed == false)
r.events[2].units_at_observation = 99
assert(observer.snapshot().events[2].units_at_observation == 5)
observer.stop()
assert(eventful.onJobCompleted[key] == nil and eventful.onItemCreated[key] == nil)
assert(eventful.onUnload[key] == nil)
assert(observer.snapshot().stop_reason == 'explicit_stop')
assert(not pcall(observer.start))
""",
        """
config.max_events = 1
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
eventful.onJobCompleted[key](job())
eventful.onJobCompleted[key](job())
local r = observer.snapshot()
assert(#r.events == 1 and r.observed_events == 2 and r.dropped_events == 1)
assert(not r.collector_records_complete and r.flow_measurement.production == 'not_measured')
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
item(17, 3, 7, true)
item(18, 3, 7, false)
eventful.onItemCreated[key](17)
eventful.onItemCreated[key](18)
assert(observer.snapshot().events[1].resource == 'food')
assert(#observer.snapshot().events == 1 and observer.snapshot().callbacks_seen.item == 2)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local j = job()
j.flags['repeat'] = true
eventful.onJobCompleted[key](j)
df.global.cur_year_tick = 101
eventful.onJobCompleted[key](j)
assert(#observer.snapshot().events == 2)
assert(observer.snapshot().events[2].sequence == 2)
assert(observer.snapshot().events[1].repeated)
""",
        """
local other = function() end
eventful.onJobCompleted.other = other
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
eventful.onJobCompleted[key] = other
observer.stop()
assert(eventful.onJobCompleted[key] == other and eventful.onJobCompleted.other == other)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local callback = eventful.onItemCreated[key]
loaded = false
eventful.onUnload[key]()
assert(eventful.onJobCompleted[key] == nil and eventful.onItemCreated[key] == nil)
callback(17)
local r = observer.snapshot()
assert(r.endpoint == false and r.stop_reason == 'map_unloaded')
assert(not r.installed and not r.collector_records_complete and r.callbacks_seen.item == 0)
""",
        *[
            f"""
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
item(17, 3, 6)
{change}
eventful.onItemCreated[key](17)
local r = observer.snapshot()
assert(r.read_failures == 1 and not r.collector_records_complete and #r.events == 0)
"""
            for change in (
                "items[17] = nil",
                "items[17].flags.trader = nil",
                "items[17].flags.removed = true",
                "items[17].getStackSize = function() return -1 end",
                "items[17].getStackSize = function() return 0/0 end",
                "items[17].getStackSize = function() return '3' end",
                "items[17].getType = function() return nil end",
                "df.global.world.cur_savegame.save_dir = 'region2'",
                "df.global.cur_year_tick = 99",
                "df.global.world.frame_counter = 499",
            )
        ],
        *[
            f"""
{change}
assert(not pcall(function()
    local observer = new_production_observer(df, dfhack, eventful, config)
    observer.start()
end))
assert(eventful.onItemCreated[key] == nil)
"""
            for change in (
                "config.max_events = 0",
                "config.max_events = 8193",
                "config.max_events = true",
                "config.segment_id = -1",
                "config.campaign_id = '../elsewhere'",
                "config.expected_root = '/wrong'",
                "df.global.pause_state = false",
                "dfhack.getDFHackVersion = function() return 'other' end",
                "eventful.onJobCompleted[key] = function() end",
            )
        ],
    ],
)
def test_candidate_collector_executes_without_game_or_complete_flow_claims(scenario):
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + PRODUCTION_OBSERVER_LUA + scenario,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
