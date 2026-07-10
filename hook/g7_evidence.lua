-- g7_evidence.lua: run-scoped factual survival evidence for governed play.
-- Commands: start <run_id>, read, stop. State and event callbacks persist in
-- the DFHack Lua interpreter between bounded dfhack-run invocations.

local json = require('json')
local args = {...}
local command = tostring(args[1] or 'read')
local run_id = tostring(args[2] or '')
local GLOBAL_KEY = 'FORT_GYM_G7_EVIDENCE'
local CALLBACK_KEY = 'fort_gym_g7'

local function sanitize(value)
  return tostring(value or ''):gsub('[^%w %p]', '?')
end

local function add_error(ledger, code)
  ledger.evidence_errors[code] = true
end

local function civ_dwarf(unit)
  local ok, result = pcall(function()
    return unit.civ_id == df.global.ui.civ_id and dfhack.units.isDwarf(unit)
  end)
  return ok and result or false
end

local function unit_is_dead(unit)
  local ok, dead = pcall(function() return dfhack.units.isDead(unit) end)
  return ok and dead or false
end

local function history_signatures(unit, kind)
  local counts = {}
  local eat_history = unit.status and unit.status.eat_history
  if not eat_history then return counts end
  local history = eat_history[kind]
  if not history then return counts end
  local size = #history.item_type
  for idx = 0, size - 1 do
    local signature = table.concat({
      tostring(history.year[idx] or -1),
      tostring(history.year_time[idx] or -1),
      tostring(history.item_type[idx] or -1),
      tostring(history.item_subtype[idx] or -1),
      tostring(history.material.mat_type[idx] or -1),
      tostring(history.material.mat_index[idx] or -1),
    }, ':')
    counts[signature] = (counts[signature] or 0) + 1
  end
  return counts
end

local function update_unit_consumption(ledger, unit, baseline_only)
  local unit_key = tostring(unit.id)
  local seen = ledger.history_seen[unit_key]
  local first_observation = seen == nil
  if first_observation then
    seen = { food = {}, drink = {} }
    ledger.history_seen[unit_key] = seen
  end

  for _, kind in ipairs({ 'food', 'drink' }) do
    local ok, current = pcall(history_signatures, unit, kind)
    if not ok then
      ledger.flow_evidence_complete = false
      add_error(
        ledger,
        'eat_history_' .. kind .. '_unreadable:' .. sanitize(current)
      )
    else
      for signature, count in pairs(current) do
        local previous = seen[kind][signature] or 0
        if not baseline_only and not first_observation and count > previous then
          local delta = count - previous
          if kind == 'food' then
            ledger.food_consumed = ledger.food_consumed + delta
          else
            ledger.drink_consumed = ledger.drink_consumed + delta
          end
        end
        if count > previous then seen[kind][signature] = count end
      end
    end
  end
end

local function scan_consumption(ledger, baseline_only)
  local ok = pcall(function()
    for _, unit in ipairs(df.global.world.units.all) do
      if civ_dwarf(unit) and not unit_is_dead(unit) then
        update_unit_consumption(ledger, unit, baseline_only)
      end
    end
  end)
  if not ok then
    ledger.flow_evidence_complete = false
    add_error(ledger, 'citizen_eat_history_scan_failed')
  end
end

local function raw_value(unit, field_table, field)
  local ok, value = pcall(function()
    local values = unit[field_table]
    return values and values[field] or nil
  end)
  if ok and value ~= nil then return value end
  return false
end

local function raw_flag(unit, field_table, field)
  local ok, value = pcall(function()
    local values = unit[field_table]
    return values and values[field] and true or false
  end)
  return ok and value or false
end

local function death_record(unit)
  local cause_enum = raw_value(unit, 'counters', 'death_cause')
  local cause_name = false
  local cause_known = false
  local cause_source = false
  if tonumber(cause_enum) and tonumber(cause_enum) >= 0 then
    local ok, name = pcall(function() return df.death_type[tonumber(cause_enum)] end)
    if ok and name and tostring(name) ~= 'NONE' then
      cause_name = sanitize(name)
      cause_known = true
      cause_source = 'counters.death_cause'
    end
  end
  return {
    unit_id = unit.id,
    cause_enum = cause_enum,
    cause_name = cause_name,
    cause_known = cause_known,
    cause_source = cause_source,
    incident_id = raw_value(unit, 'counters', 'death_id'),
    hunger_timer = raw_value(unit, 'counters2', 'hunger_timer'),
    thirst_timer = raw_value(unit, 'counters2', 'thirst_timer'),
    stored_fat = raw_value(unit, 'counters2', 'stored_fat'),
    stomach_food = raw_value(unit, 'counters2', 'stomach_food'),
    -- A current-condition flag, not authoritative historical cause evidence.
    drowning = raw_flag(unit, 'flags1', 'drowning'),
    suffocation = raw_value(unit, 'counters', 'suffocation'),
    emotionally_overloaded = raw_flag(unit, 'flags3', 'emotionally_overloaded'),
    observed_year = df.global.cur_year,
    observed_tick = df.global.cur_year_tick,
  }
end

local function record_death(ledger, unit)
  if not unit or not civ_dwarf(unit) then return end
  update_unit_consumption(ledger, unit, false)
  local key = tostring(unit.id)
  local record = death_record(unit)
  local previous = ledger.deaths[key]
  if not previous or record.cause_known or not previous.cause_known then
    ledger.deaths[key] = record
  end
end

local function scan_deaths(ledger)
  local ok = pcall(function()
    for _, unit in ipairs(df.global.world.units.all) do
      if unit_is_dead(unit)
        and civ_dwarf(unit)
        and not ledger.baseline_dead_ids[tostring(unit.id)] then
        record_death(ledger, unit)
      end
    end
  end)
  if not ok then
    ledger.death_evidence_complete = false
    add_error(ledger, 'dead_citizen_scan_failed')
  end
end

local function item_on_completed_farm_plot(item)
  local ok, result = pcall(function()
    if not item.pos or item.pos.x < 0 then return false end
    for _, bld in ipairs(df.global.world.buildings.all) do
      if bld:getType() == df.building_type.FarmPlot
        and bld:getBuildStage() >= bld:getMaxBuildStage()
        and item.pos.z == bld.z
        and item.pos.x >= bld.x1 and item.pos.x <= bld.x2
        and item.pos.y >= bld.y1 and item.pos.y <= bld.y2 then
        return true
      end
    end
    return false
  end)
  return ok, ok and result or false
end

local function record_created_item(ledger, item_id)
  if tonumber(item_id) and tonumber(item_id) < ledger.start_item_next_id then return end
  local ok, err = pcall(function()
    local item = df.item.find(item_id)
    if not item then return end
    local item_type = item:getType()
    local farm_check_ok, on_completed_farm = true, false
    if item_type == df.item_type.PLANT then
      farm_check_ok, on_completed_farm = item_on_completed_farm_plot(item)
      if not farm_check_ok then
        ledger.flow_evidence_complete = false
        add_error(ledger, 'farm_output_classification_failed')
        return
      end
    end
    if item_type == df.item_type.DRINK
      or (item_type == df.item_type.PLANT and on_completed_farm) then
      local amount = tonumber(item.stack_size) or 1
      if amount < 1 then amount = 1 end
      if item_type == df.item_type.DRINK then
        ledger.drink_produced = ledger.drink_produced + amount
      else
        ledger.food_produced = ledger.food_produced + amount
      end
    elseif item_type == df.item_type.PLANT then
      ledger.nonfarm_plants_created = ledger.nonfarm_plants_created
        + (tonumber(item.stack_size) or 1)
    end
  end)
  if not ok then
    ledger.flow_evidence_complete = false
    add_error(ledger, 'item_created_callback_failed:' .. sanitize(err))
  end
end

local function detach_callbacks()
  local ok, eventful = pcall(require, 'plugins.eventful')
  if not ok then return end
  pcall(function() eventful.onItemCreated[CALLBACK_KEY] = nil end)
  pcall(function() eventful.onUnitDeath[CALLBACK_KEY] = nil end)
end

local function attach_callbacks(ledger)
  local ok, eventful = pcall(require, 'plugins.eventful')
  if not ok then
    ledger.flow_evidence_complete = false
    ledger.death_evidence_complete = false
    add_error(ledger, 'eventful_unavailable')
    return
  end
  local attached, err = pcall(function()
    eventful.onItemCreated[CALLBACK_KEY] = function(item_id)
      local active = _G[GLOBAL_KEY]
      if active and active.active then record_created_item(active, item_id) end
    end
    eventful.onUnitDeath[CALLBACK_KEY] = function(unit_id)
      local active = _G[GLOBAL_KEY]
      if not active or not active.active then return end
      local unit = df.unit.find(unit_id)
      if active.baseline_dead_ids[tostring(unit_id)] then
        return
      elseif unit then
        local death_ok, death_err = pcall(record_death, active, unit)
        if not death_ok then
          active.death_evidence_complete = false
          add_error(active, 'death_callback_failed:' .. sanitize(death_err))
        end
      else
        active.death_evidence_complete = false
        add_error(active, 'death_callback_unit_missing')
      end
    end
    eventful.enableEvent(eventful.eventType.ITEM_CREATED, 1)
    eventful.enableEvent(eventful.eventType.UNIT_DEATH, 1)
  end)
  if not attached then
    ledger.flow_evidence_complete = false
    ledger.death_evidence_complete = false
    add_error(ledger, 'eventful_registration_failed:' .. sanitize(err))
  end
end

local function new_ledger(id)
  return {
    active = true,
    run_id = id,
    start_year = df.global.cur_year,
    start_tick = df.global.cur_year_tick,
    start_item_next_id = tonumber(df.global.item_next_id) or 0,
    food_produced = 0,
    food_consumed = 0,
    drink_produced = 0,
    drink_consumed = 0,
    nonfarm_plants_created = 0,
    flow_evidence_complete = true,
    death_evidence_complete = true,
    history_seen = {},
    baseline_dead_ids = {},
    deaths = {},
    evidence_errors = {},
  }
end

local function snapshot(ledger)
  if not ledger then
    return { ok = false, active = false, error = 'g7_evidence_not_started' }
  end
  scan_consumption(ledger, false)
  scan_deaths(ledger)

  local deaths = {}
  local all_causes_known = ledger.death_evidence_complete
  local direct_neglect_deaths = 0
  for _, record in pairs(ledger.deaths) do
    table.insert(deaths, record)
    if not record.cause_known then all_causes_known = false end
    if record.cause_name == 'HUNGER' or record.cause_name == 'THIRST' then
      direct_neglect_deaths = direct_neglect_deaths + 1
    end
  end
  table.sort(deaths, function(a, b) return a.unit_id < b.unit_id end)

  local errors = {}
  for code, _ in pairs(ledger.evidence_errors) do table.insert(errors, code) end
  table.sort(errors)

  local out = {
    ok = true,
    active = ledger.active and true or false,
    run_id = ledger.run_id,
    start_year = ledger.start_year,
    start_tick = ledger.start_tick,
    start_item_next_id = ledger.start_item_next_id,
    observed_year = df.global.cur_year,
    observed_tick = df.global.cur_year_tick,
    food_produced_in_run = ledger.food_produced,
    food_consumed_in_run = ledger.food_consumed,
    drink_produced_in_run = ledger.drink_produced,
    drink_consumed_in_run = ledger.drink_consumed,
    nonfarm_plants_created_in_run = ledger.nonfarm_plants_created,
    flow_evidence_complete = ledger.flow_evidence_complete,
    death_records = deaths,
    deaths_in_run = #deaths,
    death_evidence_complete = ledger.death_evidence_complete,
    death_causes_known = all_causes_known,
    direct_neglect_deaths = direct_neglect_deaths,
    evidence_errors = errors,
  }
  if #deaths == 0 or direct_neglect_deaths > 0 then
    -- Zero deaths is unambiguous; hunger/thirst is an unambiguous failure.
    -- Other deaths need separate tantrum-chain evidence before being cleared.
    out.neglect_deaths = direct_neglect_deaths
  end
  return out
end

if command == 'start' then
  detach_callbacks()
  local ledger = new_ledger(run_id)
  _G[GLOBAL_KEY] = ledger
  for _, unit in ipairs(df.global.world.units.all) do
    if civ_dwarf(unit) and unit_is_dead(unit) then
      ledger.baseline_dead_ids[tostring(unit.id)] = true
    end
  end
  scan_consumption(ledger, true)
  attach_callbacks(ledger)
  print(json.encode(snapshot(ledger)))
elseif command == 'stop' then
  local ledger = _G[GLOBAL_KEY]
  if ledger then ledger.active = false end
  detach_callbacks()
  print(json.encode(snapshot(ledger)))
elseif command == 'read' then
  print(json.encode(snapshot(_G[GLOBAL_KEY])))
else
  print(json.encode({ ok = false, active = false, error = 'invalid_command' }))
end
