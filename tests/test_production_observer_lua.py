"""Execute the collector with fake native objects, not a simulated-game claim."""

import shutil
import subprocess

import pytest

from fort_gym.bench.production_observer_lua import PRODUCTION_OBSERVER_LUA

LUA = shutil.which("lua")
PRELUDE = r"""
local callbacks = {JOB_COMPLETED=1, ITEM_CREATED=2, UNLOAD=3}
local eventful = {onJobCompleted={}, onItemCreated={}, onUnload={}, onReactionComplete={},
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
observer.start()
local reaction, worker, product = {code='BREW_TEST'}, {id=7}, {quantity=999}
local a, b = item(17, 5, 6), item(18, 1, 7, false)
local inputs = {item(19, 8, 7, true)}
eventful.onReactionComplete[key](reaction, product, worker, inputs, {}, {a})
eventful.onReactionComplete[key](reaction, product, worker, inputs, {}, {a, b})
local r = observer.snapshot()
assert(#r.events == 2 and r.callbacks_seen.reaction == 2)
assert(r.events[1].kind == 'reaction_output_observation')
assert(r.events[2].vector_scope == 'cumulative_outputs_at_callback')
assert(r.events[2].output_items[1].item_id == r.events[1].output_items[1].item_id)
assert(r.events[2].output_items[1].units_at_observation == 5)
assert(r.events[2].output_items[2].resource == 'other')
assert(r.events[2].worker_id == 7 and r.events[2].reaction_code == 'BREW_TEST')
assert(r.events[2].production_quantity_status == 'not_totalled')
assert(r.flow_measurement.production == 'not_measured')
assert(r.flow_measurement.consumption == 'not_measured')
assert(product.quantity == 999 and inputs[1]:getStackSize() == 8)
r.events[1].output_items[1].flags.rotten = true
assert(not observer.snapshot().events[1].output_items[1].flags.rotten)
assert(not a.flags.rotten and not r.native_coverage_validated)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local a = item(17, 3, 7, true)
eventful.onReactionComplete[key]({code='FOOD_TEST'}, {}, nil, {}, {}, {a, a})
local r = observer.snapshot()
assert(r.events[1].duplicate_output_id_records == 1)
assert(r.events[1].worker_id == false)
assert(r.events[1].output_items[1].resource == 'food')
assert(r.events[1].production_quantity_status == 'not_totalled')
assert(r.retained_item_records == 2)
""",
        """
config.max_events = 3
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local outputs = {item(17, 3, 6), item(18, 1, 7, false)}
eventful.onReactionComplete[key]({code='TEST'}, {}, nil, {}, {}, outputs)
eventful.onReactionComplete[key]({code='TEST'}, {}, nil, {}, {}, outputs)
eventful.onJobCompleted[key](job())
local r = observer.snapshot()
assert(r.max_item_records == 3 and r.retained_item_records == 2)
assert(#r.events == 2 and r.observed_events == 3 and r.dropped_events == 1)
assert(not r.collector_records_complete)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local other = function() end
eventful.onReactionComplete.other = other
local retained_callback = eventful.onReactionComplete[key]
observer.stop()
assert(eventful.onReactionComplete[key] == nil and eventful.onReactionComplete.other == other)
retained_callback({code='TEST'}, {}, nil, {}, {}, {item(17, 3, 6)})
assert(observer.snapshot().callbacks_seen.reaction == 0)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local other = function() end
eventful.onReactionComplete[key] = other
observer.stop()
assert(eventful.onReactionComplete[key] == other)
""",
        """
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
loaded = false
eventful.onUnload[key]()
assert(eventful.onReactionComplete[key] == nil)
""",
        """
eventful.onReactionComplete[key] = function() end
local observer = new_production_observer(df, dfhack, eventful, config)
assert(not pcall(observer.start))
assert(eventful.onJobCompleted[key] == nil)
""",
        """
local original = function() end
eventful.onReactionCompleting = {other=original}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
eventful.onReactionComplete[key]({code='TEST'}, {}, {id=1}, {}, {}, {item(17, 0, 6)})
assert(observer.snapshot().events[1].output_items[1].units_at_observation == 0)
assert(eventful.onReactionCompleting.other == original)
assert(eventful.onReactionCompleting[key] == nil)
""",
        *[
            f"""
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local reaction, worker, outputs = {{code='TEST'}}, {{id=7}}, {{item(17, 3, 6)}}
{change}
eventful.onReactionComplete[key](reaction, {{}}, worker, {{}}, {{}}, outputs)
local r = observer.snapshot()
assert(#r.events == 0 and r.read_failures == 1 and not r.collector_records_complete)
assert(r.flow_measurement.production == 'not_measured')
"""
            for change in (
                "reaction.code = ''",
                "reaction.code = string.rep('A', 129)",
                "reaction.code = 'BAD' .. string.char(10)",
                "worker.id = false",
                "outputs = {}",
                "outputs = nil",
                "for i=2,33 do outputs[i] = item(i+100, 3, 6) end",
                "outputs[1].flags.hidden = nil",
                "outputs[1].getStackSize = function() return math.huge end",
                "outputs[2] = {id=18}",
                "df.global.world.cur_savegame.save_dir = 'elsewhere'",
            )
        ],
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


@pytest.mark.skipif(LUA is None, reason="Lua interpreter unavailable")
@pytest.mark.parametrize(
    "scenario",
    [
        """
local food, drink = item(17, 3, 7, true), item(18, 5, 6)
local nonfood, removed = item(19, 9, 7, false), item(20, 50, 6)
food.flags.forbid = true
drink.flags.trader = true
drink.flags.rotten = true
removed.flags.removed = true
df.global.world.items = {other={IN_PLAY={food, drink, nonfood, removed}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
eventful.onItemCreated[key](17)
local r = observer.inventory_snapshot()
assert(r.complete and r.units.food == 3 and r.units.drink == 5)
assert(r.scanned_items == 4 and r.expected_items == 4 and r.omitted_items == 0)
assert(#r.items == 2 and r.excluded_items == 1 and r.nonfood_items == 1)
assert(r.items[1].item_id == 17 and r.items[2].item_id == 18)
assert(r.items[1].flags.forbid and r.items[2].flags.trader and r.items[2].flags.rotten)
assert(r.event_sequence == 1 and r.start.year_tick == r.endpoint.year_tick)
assert(r.accessibility == 'not_measured' and r.attribution == 'unattributed')
assert(not r.agent_observation and not r.native_coverage_validated)
r.items[1].units_at_observation = 99
r.items[2].flags.trader = false
assert(observer.inventory_snapshot().items[1].units_at_observation == 3)
assert(drink.flags.trader and food:getStackSize() == 3)
assert(observer.snapshot().retained_events == 1)
assert(observer.snapshot().flow_measurement.production == 'not_measured')
df.global.cur_year_tick = 101
drink.getStackSize = function() return 2 end
local later = observer.inventory_snapshot()
assert(later.complete and later.units.drink == 2 and later.event_sequence == 1)
assert(later.start.year_tick == 101 and later.observer_start.year_tick == 100)
df.global.cur_year_tick = 100
assert(not observer.inventory_snapshot().complete)
""",
        """
df.global.world.items = {other={IN_PLAY={}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local r = observer.inventory_snapshot()
assert(r.complete and r.units.food == 0 and r.units.drink == 0)
assert(r.scanned_items == 0 and #r.items == 0)
""",
        """
config.max_inventory_items = 1
df.global.world.items = {other={IN_PLAY={item(17, 3, 6), item(18, 5, 6)}}}
local observer = new_production_observer(df, dfhack, eventful, config)
config.max_inventory_items = 65536
observer.start()
local r = observer.inventory_snapshot()
assert(not r.complete and r.units == false and r.omitted_items == 1)
assert(r.scanned_items == 1 and #r.items == 1 and r.max_inventory_items == 1)
assert(observer.snapshot().collector_records_complete)
""",
        """
local a = item(17, 3, 6)
df.global.world.items = {other={IN_PLAY={a, a}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
local r = observer.inventory_snapshot()
assert(not r.complete and r.units == false and r.duplicate_items == 1)
assert(#r.items == 1 and r.scanned_items == 2)
""",
        *[
            f"""
local a, b = item(17, 3, 6), item(18, 5, 6)
df.global.world.items = {{other={{IN_PLAY={{a, b}}}}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
{change}
local r = observer.inventory_snapshot()
assert(not r.complete and r.units == false)
assert(r.item_read_failures == 1 and #r.items == 1)
assert(observer.snapshot().read_failures == 0)
"""
            for change in (
                "a.id = -1",
                "a.flags.removed = nil",
                "a.flags.hidden = nil",
                "a.getType = function() return false end",
                "a.getStackSize = function() return -1 end",
                "a.getStackSize = function() return math.huge end",
                "a.getStackSize = function() return 9007199254740991 end",
                "a.getType = function() return 7 end; a.isEdibleRaw = function() return nil end",
            )
        ],
        *[
            f"""
df.global.world.items = {{other={{IN_PLAY={{item(17, 3, 6)}}}}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
{change}
local r = observer.inventory_snapshot()
assert(not r.complete and r.units == false)
assert(r.boundary_read_failures == 1)
"""
            for change in (
                "df.global.pause_state = false",
                "loaded = false",
                "df.global.world.cur_savegame.save_dir = 'different'",
                "df.global.cur_year_tick = 99",
                "items[17].getStackSize = function() df.global.cur_year_tick = 101; return 3 end",
                "items[17].getStackSize = function() df.global.world.frame_counter = 501; return 3 end",
                "items[17].getStackSize = function() df.global.pause_state = false; return 3 end",
                "items[17].getStackSize = function() eventful.onJobCompleted[key](job()); return 3 end",
            )
        ],
        *[
            f"""
df.global.world.items = {{other={{IN_PLAY={{item(17, 3, 6)}}}}}}
local observer = new_production_observer(df, dfhack, eventful, config)
observer.start()
{change}
local r = observer.inventory_snapshot()
assert(not r.complete and r.units == false and r.list_read_failures == 1)
"""
            for change in (
                "df.global.world.items = nil",
                "df.global.world.items.other.IN_PLAY = nil",
                "setmetatable(df.global.world.items.other.IN_PLAY, {__len=function() return 2 end})",
                "items[17].getStackSize = function() df.global.world.items.other.IN_PLAY[2] = item(18, 1, 6); return 3 end",
            )
        ],
        *[
            f"""
config.max_inventory_items = {value}
assert(not pcall(function() new_production_observer(df, dfhack, eventful, config) end))
"""
            for value in ("0", "65537", "true", "1.5", "math.huge", "'10'")
        ],
        """
local observer = new_production_observer(df, dfhack, eventful, config)
assert(not pcall(observer.inventory_snapshot))
observer.start()
observer.stop()
assert(not pcall(observer.inventory_snapshot))
""",
    ],
)
def test_candidate_inventory_is_identity_level_bounded_and_not_a_flow_claim(scenario):
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + PRODUCTION_OBSERVER_LUA + scenario,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
