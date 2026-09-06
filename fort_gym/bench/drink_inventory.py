"""Read-only native drink-unit measurement, shared by both DFHack transports.

This Lua runs inside the same snapshot as the rest of read_game_state.
It does not refresh UI counters, alter items, or infer production/consumption.
"""

DRINK_INVENTORY_LUA = """
local function read_drink_inventory(in_play, drink_type)
    local result = {
        source = 'world.items.other.IN_PLAY DRINK stack_size',
        scope = 'existing units, not accessibility, ownership or production/consumption',
        complete = false,
        scanned_units = 0,
        item_records = 0,
        excluded_records = 0,
        type_read_failures = 0,
        item_read_failures = 0,
        list_read_failures = 0,
        forbidden_units = 0,
        rotten_units = 0,
        in_job_units = 0,
    }
    if in_play == nil or drink_type == nil then
        result.list_read_failures = 1
        return result
    end
    local scan_ok = pcall(function()
        for _, item in ipairs(in_play) do
            local type_ok, kind = pcall(function() return item:getType() end)
            if not type_ok or kind == nil then
                -- An unreadable type might itself be a drink. Never report a
                -- successful zero or partial total when the scan is incomplete.
                result.type_read_failures = result.type_read_failures + 1
            elseif kind == drink_type then
                result.item_records = result.item_records + 1
                local item_ok, entry = pcall(function()
                    local flags = assert(item.flags, 'missing item flags')
                    if flags.removed or flags.garbage_collect then
                        return {excluded = true}
                    end
                    local units = item.stack_size
                    assert(type(units) == 'number' and units >= 0
                        and units < math.huge and units == math.floor(units),
                        'invalid drink stack size')
                    return {units = units, forbidden = flags.forbid,
                        rotten = flags.rotten, in_job = flags.in_job}
                end)
                if not item_ok then
                    result.item_read_failures = result.item_read_failures + 1
                elseif entry.excluded then
                    result.excluded_records = result.excluded_records + 1
                else
                    result.scanned_units = result.scanned_units + entry.units
                    for _, flag in ipairs({'forbidden', 'rotten', 'in_job'}) do
                        if entry[flag] then
                            result[flag .. '_units'] = result[flag .. '_units'] + entry.units
                        end
                    end
                end
            end
        end
    end)
    if not scan_ok then result.list_read_failures = result.list_read_failures + 1 end
    result.complete = result.type_read_failures == 0
        and result.item_read_failures == 0 and result.list_read_failures == 0
    if result.complete then result.units = result.scanned_units end
    return result
end
"""
