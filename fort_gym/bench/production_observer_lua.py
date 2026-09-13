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
    local max_inventory_items = config.max_inventory_items
    if max_inventory_items == nil then max_inventory_items = 8192 end
    assert(integer(max_inventory_items) and max_inventory_items >= 1
        and max_inventory_items <= 65536)
    assert(type(config.expected_root) == 'string'
        and config.expected_root:sub(1, 1) == '/')
    config = {campaign_id=config.campaign_id, segment_id=config.segment_id,
        max_events=config.max_events, expected_root=config.expected_root,
        max_inventory_items=max_inventory_items}
    assert(dfhack.getDFVersion() == 'v0.47.05 linux64')
    assert(dfhack.getDFHackVersion() == '0.47.05-r8')
    local key = 'fortgym_production_observer_v1'
    local events, sequence, dropped, read_failures = {}, 0, 0, 0
    local retained_item_records = 0
    local installed, started, stop_reason = false, false, nil
    local origin, last_clock
    local callbacks_seen = {job = 0, item = 0, reaction = 0}
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
        local item_count = event.output_items and #event.output_items
            or (event.item_id and 1 or 0)
        if #events < config.max_events
            and retained_item_records + item_count <= config.max_events then
            events[#events + 1] = event
            retained_item_records = retained_item_records + item_count
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
    local function read_item(item, include_nonfood)
        local id = item.id
        assert(integer(id), 'invalid item id')
        local kind = item:getType()
        assert(integer(kind), 'invalid item type')
        local resource
        if kind == df.item_type.DRINK then
            resource = 'drink'
        else
            local edible = item:isEdibleRaw(0)
            assert(type(edible) == 'boolean', 'invalid food predicate')
            if not edible and not include_nonfood then return nil end
            resource = edible and 'food' or 'other'
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
        return {item_id = id, resource = resource, item_type = kind,
            units_at_observation = units, flags = flags}
    end
    local function on_item(id)
        capture('item', function()
            assert(integer(id), 'invalid item id')
            local item = assert(df.item.find(id), 'created item disappeared')
            assert(item.id == id, 'item identity differs')
            local record = read_item(item, false)
            if record then
                record.kind = 'item_creation_observation'
                record.attribution = 'unattributed'
            end
            return record
        end)
    end
    local function on_reaction(reaction, _product, unit, _inputs, _reagents, outputs)
        capture('reaction', function()
            local code = reaction.code
            assert(type(code) == 'string' and #code > 0 and #code <= 128
                and not code:find('%c'), 'invalid reaction code')
            local worker_id = false
            if unit ~= nil then
                assert(integer(unit.id), 'invalid reaction worker')
                worker_id = unit.id
            end
            local count = #outputs
            assert(integer(count) and count >= 1 and count <= 32,
                'reaction output vector unavailable or over limit')
            local records, seen, duplicates = {}, {}, 0
            for _, item in ipairs(outputs) do
                assert(#records < count, 'reaction vector grew')
                local record = read_item(item, true)
                records[#records + 1] = record
                if seen[record.item_id] then duplicates = duplicates + 1 end
                seen[record.item_id] = true
            end
            assert(#records == count and #outputs == count, 'reaction vector changed')
            -- The plugin passes the whole output vector, not only this product's
            -- newly appended suffix. Preserve identities; never total this as yield.
            return {kind = 'reaction_output_observation', reaction_code = code,
                worker_id = worker_id, output_items = records,
                vector_scope = 'cumulative_outputs_at_callback',
                duplicate_output_id_records = duplicates,
                production_quantity_status = 'not_totalled'}
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
            if eventful.onReactionComplete[key] == on_reaction then
                eventful.onReactionComplete[key] = nil
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
            and eventful.onReactionComplete[key] == nil
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
        eventful.onReactionComplete[key] = on_reaction
        eventful.onUnload[key] = on_unload
        installed = true
    end
    function api.stop()
        stop('explicit_stop')
        if eventful.onUnload[key] == on_unload then eventful.onUnload[key] = nil end
    end
    function api.inventory_snapshot()
        assert(installed, 'inventory requires an installed collector')
        local result = {
            schema_version = 'fortgym.private-production-inventory/v1',
            campaign_id = config.campaign_id, segment_id = config.segment_id,
            df_version = 'v0.47.05 linux64', dfhack_version = '0.47.05-r8',
            source = 'world.items.other.IN_PLAY', predicate_argument = 0,
            scope = 'DRINK or isEdibleRaw(0); not ownership, accessibility or flow',
            observer_start = copy(origin), event_sequence = sequence,
            max_inventory_items = config.max_inventory_items,
            start = false, endpoint = false, expected_items = false,
            scanned_items = 0, omitted_items = false, excluded_items = 0,
            nonfood_items = 0, duplicate_items = 0, item_read_failures = 0,
            list_read_failures = 0, boundary_read_failures = 0,
            items = {}, complete = false, units = false,
            native_coverage_validated = false, agent_observation = false,
            accessibility = 'not_measured', attribution = 'unattributed',
        }
        local before_ok, before = pcall(function() return boundary(true) end)
        if not before_ok then
            result.boundary_read_failures = 1
            return result
        end
        result.start = before
        local seen, totals = {}, {food=0, drink=0}
        local list_ok = pcall(function()
            local list = df.global.world.items.other.IN_PLAY
            local count = #list
            assert(integer(count), 'invalid inventory length')
            result.expected_items = count
            for _, item in ipairs(list) do
                if result.scanned_items >= config.max_inventory_items then break end
                result.scanned_items = result.scanned_items + 1
                local ok, record, category = pcall(function()
                    assert(integer(item.id), 'invalid inventory identity')
                    if seen[item.id] then return nil, 'duplicate_items' end
                    seen[item.id] = true
                    assert(type(item.flags.removed) == 'boolean'
                        and type(item.flags.garbage_collect) == 'boolean',
                        'unreadable exclusion flags')
                    if item.flags.removed or item.flags.garbage_collect then
                        return nil, 'excluded_items'
                    end
                    local value = read_item(item, false)
                    if not value then return nil, 'nonfood_items' end
                    assert(integer(totals[value.resource] + value.units_at_observation),
                        'inventory total overflow')
                    return value
                end)
                if not ok then
                    result.item_read_failures = result.item_read_failures + 1
                elseif record then
                    result.items[#result.items + 1] = record
                    totals[record.resource] = totals[record.resource]
                        + record.units_at_observation
                else
                    result[category] = result[category] + 1
                end
            end
            result.omitted_items = math.max(0, count - result.scanned_items)
            assert(#list == count and result.scanned_items
                == math.min(count, config.max_inventory_items), 'inventory list changed')
        end)
        if not list_ok then result.list_read_failures = 1 end
        local after_ok, after = pcall(function() return boundary(true) end)
        if after_ok then
            result.endpoint = after
            for field, value in pairs(before) do
                if after[field] ~= value then after_ok = false end
            end
        end
        if not after_ok or sequence ~= result.event_sequence then
            result.boundary_read_failures = 1
        end
        result.complete = result.boundary_read_failures == 0
            and result.list_read_failures == 0 and result.item_read_failures == 0
            and result.duplicate_items == 0 and result.omitted_items == 0
        -- Partial item records remain inspectable, but never become a complete
        -- inventory total, an accessible supply or an attributed production flow.
        if result.complete then result.units = totals end
        if after_ok then last_clock = after.year * 403200 + after.year_tick end
        return result
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
            max_item_records = config.max_events, max_reaction_output_items = 32,
            retained_item_records = retained_item_records,
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
