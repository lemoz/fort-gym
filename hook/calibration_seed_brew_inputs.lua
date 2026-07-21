-- calibration_seed_brew_inputs.lua: deterministically place exactly
-- BREW_INPUT_LIMIT brewable MUSHROOM_HELMET_PLUMP PLANT items on a walkable,
-- OFF-FARM floor tile adjacent to the completed Still, for the provider-free
-- owned-layout-and-provisioning calibration scenario only.
--
-- Like calibration_kill_one.lua this hook is deliberately narrow and bounded:
-- it takes NO args and creates a fixed literal quantity in a single bounded
-- loop (it cannot be asked to create more).
-- It does not write any measurement or output evidence itself. The ordinary
-- G7 ledger credits only the DRINK the
-- plan's already-committed brew ORDER jobs later produce from these inputs; the
-- raw plant stock this hook seeds is never counted as an output (a PLANT placed
-- OFF a completed FarmPlot classifies as g7_evidence's nonfarm_plants_created,
-- never food_produced, never drink_produced).
--
-- LIVE VALIDATION ITEMS (confirm on the pinned DFHack 0.47.05 build during a
-- paused dry-run, mirroring order_make.lua:11-16's BrewDrink note):
--   (i) the exact dfhack.items.createItem argument order and whether it returns
--       an item id or an item object -- this hook resolves df.item.find and
--       validates getType() == df.item_type.PLANT regardless, and fails closed
--       if created_count ~= BREW_INPUT_LIMIT.
--   (ii) the correct submaterial token for the harvested brewable plant item
--       (STRUCTURAL vs the plant's growth material) -- fail-closed
--       'brewable_material_unresolved' guards a wrong token.

local json = require('json')

local FIXTURE = 'dfhack_bounded_brewable_input_seed'
local TARGET = 'brewable_plant_stock'
local ITEM_TOKEN = 'MUSHROOM_HELMET_PLUMP'
local METHOD = 'still_adjacent_item_create'
local MATERIAL = ITEM_TOKEN .. ':STRUCTURAL'
local BREW_INPUT_LIMIT = 8

local function result(payload)
  print(json.encode(payload))
end

local function fail(error_code, extra)
  local payload = {
    ok = false,
    fixture = FIXTURE,
    target = TARGET,
    item = ITEM_TOKEN,
    limit = BREW_INPUT_LIMIT,
    method = METHOD,
    error = error_code,
  }
  if extra then
    for k, v in pairs(extra) do
      payload[k] = v
    end
  end
  result(payload)
end

if not dfhack.isMapLoaded() then
  fail('map_not_loaded')
  return
end

-- Resolve the brewable plant raw index (precedent: set_farm_crop.lua:235-240).
local plant_raw_index = -1
local ok_plant_scan = pcall(function()
  for index, plant in ipairs(df.global.world.raws.plants.all) do
    if plant.id == ITEM_TOKEN then
      plant_raw_index = index
      return
    end
  end
end)
if not ok_plant_scan or plant_raw_index < 0 then
  fail('brewable_plant_raw_missing')
  return
end

-- Resolve the material ref (precedent: dfhack.matinfo in job_metrics.lua:578).
local mat = nil
pcall(function()
  mat = dfhack.matinfo.find(MATERIAL)
end)
if not mat or mat.type == nil or mat.index == nil then
  fail('brewable_material_unresolved')
  return
end
local mat_type = mat.type
local mat_index = mat.index

-- Locate the completed Still (precedent: order_make.lua:45-88).
local function is_workshop_of_subtype(building, subtype_name)
  if not building then return false end
  local is_workshop = false
  local ok_type, building_type = pcall(function() return building:getType() end)
  if ok_type and building_type == df.building_type.Workshop then
    is_workshop = true
  end
  local ok_instance, is_instance = pcall(function()
    return df.building_workshopst and df.building_workshopst:is_instance(building)
  end)
  if ok_instance and is_instance then
    is_workshop = true
  end
  if not is_workshop then return false end

  local ok_removal, marked_for_removal = pcall(function()
    return dfhack.buildings.markedForRemoval(building)
  end)
  if not ok_removal or marked_for_removal then return false end

  local ok_stage, is_complete = pcall(function()
    return building:getBuildStage() >= building:getMaxBuildStage()
  end)
  if not ok_stage or not is_complete then return false end

  local target_type = df.workshop_type and df.workshop_type[subtype_name] or nil
  local ok_workshop_type, workshop_type = pcall(function() return building.type end)
  local workshop_type_name = ok_workshop_type and tostring(workshop_type) or ''
  return (ok_workshop_type and target_type ~= nil and workshop_type == target_type)
      or workshop_type_name == subtype_name
end

local still = nil
local ok_still_scan = pcall(function()
  local buildings = df.global.world.buildings and df.global.world.buildings.all
  if not buildings then return end
  for _, building in ipairs(buildings) do
    if is_workshop_of_subtype(building, 'Still') then
      still = building
      return
    end
  end
end)
if not ok_still_scan or not still then
  fail('still_not_found')
  return
end

local still_building_id = -1
pcall(function() still_building_id = tonumber(still.id) or -1 end)

-- Reject any tile inside a completed FarmPlot rectangle (inverted precedent:
-- g7_evidence.lua:206-221 item_on_completed_farm_plot).
local function pos_on_completed_farm_plot(x, y, z)
  local ok, on_farm = pcall(function()
    for _, bld in ipairs(df.global.world.buildings.all) do
      if bld:getType() == df.building_type.FarmPlot
        and bld:getBuildStage() >= bld:getMaxBuildStage()
        and z == bld.z
        and x >= bld.x1 and x <= bld.x2
        and y >= bld.y1 and y <= bld.y2 then
        return true
      end
    end
    return false
  end)
  return ok, ok and on_farm or false
end

local function is_walkable_non_building_floor(x, y, z)
  local ok, walkable = pcall(function()
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return false end
    local shape = df.tiletype.attrs[tt].shape
    local shape_attrs = df.tiletype_shape.attrs[shape]
    if not (shape_attrs and shape_attrs.walkable and shape_attrs.walkable > 0) then
      return false
    end
    local bld = dfhack.buildings.findAtTile(x, y, z)
    if bld then return false end
    return true
  end)
  return ok and walkable or false
end

-- Choose placement: Still anchor then its Moore neighborhood; first walkable,
-- non-building floor tile that is NOT inside any completed FarmPlot rectangle.
local px, py, pz = nil, nil, nil
local placement_saw_farm_tile = false
do
  local sx1, sy1, sx2, sy2, sz = nil, nil, nil, nil, nil
  pcall(function()
    sx1 = tonumber(still.x1)
    sy1 = tonumber(still.y1)
    sx2 = tonumber(still.x2) or sx1
    sy2 = tonumber(still.y2) or sy1
    sz = tonumber(still.z)
  end)
  if sx1 and sy1 and sz then
    local rx2 = sx2 or sx1
    local ry2 = sy2 or sy1
    -- Expand one tile beyond the still footprint (Moore neighborhood).
    for y = sy1 - 1, ry2 + 1 do
      for x = sx1 - 1, rx2 + 1 do
        -- skip tiles inside the still footprint itself
        local inside_still = (x >= sx1 and x <= rx2 and y >= sy1 and y <= ry2)
        if not inside_still and px == nil then
          local farm_ok, on_farm = pos_on_completed_farm_plot(x, y, sz)
          if farm_ok and on_farm then
            placement_saw_farm_tile = true
          elseif farm_ok and is_walkable_non_building_floor(x, y, sz) then
            px, py, pz = x, y, sz
          end
        end
      end
    end
  end
end

if px == nil then
  if placement_saw_farm_tile then
    fail('placement_on_farm_tile')
  else
    fail('placement_unavailable')
  end
  return
end

-- Reference (maker) unit: lowest-id living citizen (precedent:
-- calibration_kill_one.lua:29-44). This unit is NOT harmed.
local ref_unit = nil
local ok_unit_walk = pcall(function()
  for _, unit in ipairs(df.global.world.units.active) do
    local eligible = unit
      and not unit.flags1.inactive
      and not unit.flags1.caged
      and not unit.flags1.chained
      and dfhack.units.isCitizen(unit, true)
      and not dfhack.units.isDead(unit)
    if eligible and (ref_unit == nil or unit.id < ref_unit.id) then
      ref_unit = unit
    end
  end
end)
if not ok_unit_walk or ref_unit == nil then
  fail('placement_unavailable', { reason = 'no_reference_unit' })
  return
end

-- Bounded, single-invocation create loop. Fixed literal quantity; fails closed
-- on any miss so a partial spawn terminates the calibration run.
local created_item_ids = {}
local created_all_plant = true
for i = 1, BREW_INPUT_LIMIT do
  local item = nil
  local ok_create = pcall(function()
    local created = dfhack.items.createItem(
      df.item_type.PLANT, plant_raw_index, mat_type, mat_index, ref_unit
    )
    if type(created) == 'number' then
      item = df.item.find(created)
    else
      item = created
    end
  end)
  if not ok_create or not item then
    fail('item_create_failed:' .. tostring(#created_item_ids))
    return
  end
  local ok_type = pcall(function()
    if item:getType() ~= df.item_type.PLANT then
      created_all_plant = false
    end
    item.stack_size = 1
    dfhack.items.moveToGround(item, { x = px, y = py, z = pz })
  end)
  if not ok_type or not created_all_plant then
    fail('item_validation_failed', { created_count = #created_item_ids })
    return
  end
  table.insert(created_item_ids, tonumber(item.id))
end

if #created_item_ids ~= BREW_INPUT_LIMIT then
  fail('item_create_failed:' .. tostring(#created_item_ids))
  return
end

result({
  ok = true,
  fixture = FIXTURE,
  target = TARGET,
  item = ITEM_TOKEN,
  method = METHOD,
  limit = BREW_INPUT_LIMIT,
  created_count = #created_item_ids,
  created_item_ids = created_item_ids,
  created_all_plant = created_all_plant,
  plant_raw_index = plant_raw_index,
  material = MATERIAL,
  mat_type = mat_type,
  mat_index = mat_index,
  still_found = true,
  still_building_id = still_building_id,
  placement = { x = px, y = py, z = pz },
  placement_off_farm = true,
})
