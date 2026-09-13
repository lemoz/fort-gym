"""Candidate private event collector; importing this module never touches a game.

Not part of any active observation profile. Job notifications and item sightings
are deliberately separate: neither proves a complete production/consumption flow.
"""

PRODUCTION_OBSERVER_LUA = r"""
local function new_production_observer(df, dfhack, eventful, config)
    local function integer(value)
        return type(value) == 'number' and value >= 0
            and value <= 9007199254740991 and value == math.floor(value)
    end
    assert(type(config) == 'table')
    assert(type(config.campaign_id) == 'string' and #config.campaign_id <= 96
        and config.campaign_id:match('^[a-zA-Z0-9_-]+$'))
    assert(integer(config.segment_id))
    assert(integer(config.max_events) and config.max_events >= 1
        and config.max_events <= 8192)
    assert(type(config.expected_root) == 'string'
        and config.expected_root:sub(1, 1) == '/')
    config = {campaign_id=config.campaign_id, segment_id=config.segment_id,
        max_events=config.max_events, expected_root=config.expected_root}
    assert(dfhack.getDFVersion() == 'v0.47.05 linux64')
    assert(dfhack.getDFHackVersion() == '0.47.05-r8')
    local key = 'fortgym_production_observer_v1'
    local events, sequence, dropped, read_failures = {}, 0, 0, 0
    local installed, started, stop_reason = false, false, nil
    local origin, last_clock
    local callbacks_seen = {job = 0, item = 0}
    local function copy(value)
        if type(value) ~= 'table' then return value end
        local result = {}
        for k, v in pairs(value) do result[k] = copy(v) end
        return result
    end
    local function boundary(paused)
        assert(dfhack.isMapLoaded(), 'map unavailable')
        local value = {
            root = dfhack.getDFPath(),
            save_name = df.global.world.cur_savegame.save_dir,
            year = df.global.cur_year,
            year_tick = df.global.cur_year_tick,
            frame_counter = df.global.world.frame_counter,
        }
        assert(value.root == config.expected_root and type(value.save_name) == 'string'
            and #value.save_name > 0, 'wrong native identity')
        assert(integer(value.year) and integer(value.year_tick)
            and value.year_tick < 403200 and integer(value.frame_counter), 'invalid clock')
        assert(value.year <= 1000000, 'calendar overflow')
        if paused then assert(df.global.pause_state == true, 'not paused') end
        if origin then
            assert(value.save_name == origin.save_name, 'save changed')
            assert(value.year * 403200 + value.year_tick >= last_clock, 'clock regressed')
            assert(value.frame_counter >= origin.frame_counter, 'native frames regressed')
        end
        return value
    end
    local function append(event)
        sequence = sequence + 1
        event.sequence = sequence
        if #events < config.max_events then
            events[#events + 1] = event
        else
            dropped = dropped + 1
        end
    end
    local function capture(kind, read)
        if not installed then return end
        callbacks_seen[kind] = callbacks_seen[kind] + 1
        local ok, event = pcall(function()
            local clock = boundary(false)
            local value = read()
            last_clock = clock.year * 403200 + clock.year_tick
            if value then value.clock = clock end
            return value
        end)
        if not ok then
            read_failures = read_failures + 1
        elseif event then
            append(event)
        end
    end
    local function on_job(job)
        capture('job', function()
            assert(integer(job.id) and integer(job.job_type), 'invalid job')
            local name = df.job_type[job.job_type]
            assert(type(name) == 'string' and #name <= 128, 'invalid job type')
            assert(type(job.flags['repeat']) == 'boolean', 'missing repeat flag')
            assert(job.completion_timer == 0, 'unexpected completion notification')
            return {kind = 'job_completion_notification', job_id = job.id,
                job_type = name, repeated = job.flags['repeat'],
                product_quantity_status = 'not_measured'}
        end)
    end
    local function on_item(id)
        capture('item', function()
            assert(integer(id), 'invalid item id')
            local item = assert(df.item.find(id), 'created item disappeared')
            assert(item.id == id, 'item identity differs')
            local kind = item:getType()
            assert(integer(kind), 'invalid item type')
            local resource
            if kind == df.item_type.DRINK then
                resource = 'drink'
            else
                local edible = item:isEdibleRaw(0)
                assert(type(edible) == 'boolean', 'invalid food predicate')
                if not edible then return nil end
                resource = 'food'
            end
            local units = item:getStackSize()
            assert(integer(units), 'invalid stack size')
            local flags = {}
            for _, name in ipairs({'removed', 'garbage_collect', 'foreign',
                'trader', 'owned', 'spider_web', 'rotten', 'forbid', 'in_job', 'hidden'}) do
                assert(type(item.flags[name]) == 'boolean', 'missing item flag')
                flags[name] = item.flags[name]
            end
            assert(not flags.removed and not flags.garbage_collect, 'item unavailable')
            return {kind = 'item_creation_observation', item_id = id, resource = resource,
                units_at_observation = units, flags = flags, attribution = 'unattributed'}
        end)
    end
    local function stop(reason)
        if installed then
            -- Never remove a listener installed by someone else after our start.
            if eventful.onJobCompleted[key] == on_job then
                eventful.onJobCompleted[key] = nil
            end
            if eventful.onItemCreated[key] == on_item then
                eventful.onItemCreated[key] = nil
            end
            installed = false
        end
        stop_reason = stop_reason or reason
    end
    local function on_unload()
        stop('map_unloaded')
        if eventful.onUnload[key] == on_unload then eventful.onUnload[key] = nil end
    end
    local api = {}
    function api.start()
        assert(not started, 'collector identity already consumed')
        assert(eventful.onJobCompleted[key] == nil
            and eventful.onItemCreated[key] == nil
            and eventful.onUnload[key] == nil, 'observer listener collision')
        origin = boundary(true)
        last_clock = origin.year * 403200 + origin.year_tick
        started = true
        -- This global polling registration cannot be restored through eventful's
        -- Lua API. Only use in a separately declared disposable native process.
        local ok, err = pcall(function()
            eventful.enableEvent(eventful.eventType.JOB_COMPLETED, 0)
            eventful.enableEvent(eventful.eventType.ITEM_CREATED, 0)
            eventful.enableEvent(eventful.eventType.UNLOAD, 1)
        end)
        if not ok then
            stop_reason = 'installation_failed'
            error(err)
        end
        eventful.onJobCompleted[key] = on_job
        eventful.onItemCreated[key] = on_item
        eventful.onUnload[key] = on_unload
        installed = true
    end
    function api.stop()
        stop('explicit_stop')
        if eventful.onUnload[key] == on_unload then eventful.onUnload[key] = nil end
    end
    function api.snapshot()
        assert(started, 'collector not started')
        local ok, endpoint = pcall(function() return boundary(true) end)
        return {
            schema_version = 'fortgym.private-production-events/v1',
            campaign_id = config.campaign_id, segment_id = config.segment_id,
            df_version = 'v0.47.05 linux64', dfhack_version = '0.47.05-r8',
            start = copy(origin), endpoint = ok and endpoint or false,
            installed = installed, stop_reason = stop_reason or false,
            max_events = config.max_events, observed_events = sequence,
            retained_events = #events, dropped_events = dropped, read_failures = read_failures,
            callbacks_seen = copy(callbacks_seen), events = copy(events),
            collector_records_complete = ok and read_failures == 0 and dropped == 0
                and (installed or stop_reason == 'explicit_stop'),
            native_coverage_validated = false,
            flow_measurement = {production='not_measured', consumption='not_measured',
                trade='not_measured', losses='not_measured'},
            agent_observation = false,
        }
    end
    return api
end
"""
