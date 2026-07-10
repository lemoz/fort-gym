-- set_farm_crop.lua: set (or clear) the seasonal crop selection on an existing
-- farm plot. Mirrors the player's q-menu crop picker: writing a plant raw
-- index into df.building_farmplotst.plant_id[season] is exactly what the UI
-- does; a dwarf with the PLANT labor then plants a matching seed over real
-- time. This hook only writes the selection — it never plants, hauls a seed,
-- or advances any job itself. Never mutates tiles, jobs, or any other building.
--
-- plant_id is a 4-slot array indexed 0..3 = spring,summer,autumn,winter
-- (live-verified on 0.47.05). "clear" writes -1 (no crop) into the requested
-- seasons.
--
-- Crop gating follows DFHack 0.47.05's native farm-plot/autofarm rules for the
-- underground slice: usable seed stock, SEED/non-TREE raw flags, season flag,
-- underground depth, and SUBTERRANEAN_WATER biome. Surface biome filtering is
-- deliberately unsupported until it has equivalent native proof, so surface
-- crop selection fails closed. All requested seasons are preflighted before a
-- plant_id slot is changed.

local json = require('json')
local args = {...}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local function sanitize(text)
  local cleaned = tostring(text or ''):gsub('[^%w %p]', '?')
  return cleaned
end

local SEASON_NAMES = { 'spring', 'summer', 'autumn', 'winter' }
local SEASON_INDEX = { spring = 0, summer = 1, autumn = 2, winter = 3 }

local building_id = to_int(args[1])
local crop_token = tostring(args[2] or '')
local seasons_csv = tostring(args[3] or '')

if not building_id then
  print(json.encode({ ok = false, error = 'invalid_building_id' }))
  return
end
if crop_token == '' then
  print(json.encode({ ok = false, error = 'invalid_crop' }))
  return
end

-- Requested seasons: an empty CSV means all four (the omitted-seasons default
-- the caller applies). Unknown tokens are rejected so a typo cannot silently
-- become "no seasons".
local requested = {}
if seasons_csv == '' then
  requested = { 0, 1, 2, 3 }
else
  local seen = {}
  for name in string.gmatch(seasons_csv, '[^,]+') do
    local idx = SEASON_INDEX[name]
    if idx == nil then
      print(json.encode({ ok = false, error = 'invalid_season', season = sanitize(name) }))
      return
    end
    if not seen[idx] then
      seen[idx] = true
      table.insert(requested, idx)
    end
  end
  table.sort(requested)
  if #requested == 0 then
    print(json.encode({ ok = false, error = 'invalid_season' }))
    return
  end
end

-- Locate the farm plot by id and confirm it is a farm plot building.
local plot = nil
local ok_find = pcall(function()
  for _, bld in ipairs(df.global.world.buildings.all) do
    if bld.id == building_id then
      plot = bld
      return
    end
  end
end)
if not ok_find then
  print(json.encode({ ok = false, error = 'buildings_unavailable' }))
  return
end
if not plot then
  print(json.encode({ ok = false, error = 'building_not_found' }))
  return
end

local is_farm = false
pcall(function()
  is_farm = df.building_farmplotst:is_instance(plot) and true or false
end)
if not is_farm then
  print(json.encode({ ok = false, error = 'not_a_farm_plot' }))
  return
end

-- DF resets seasonal plant selections while an unfinished farm plot advances
-- through construction stages. The native crop picker is only durable after
-- the plot is complete, so fail closed instead of reporting a transient write
-- as successful gameplay.
local build_stage = nil
local max_build_stage = nil
local ok_stage = pcall(function()
  build_stage = plot:getBuildStage()
  max_build_stage = plot:getMaxBuildStage()
end)
if not ok_stage or build_stage == nil or max_build_stage == nil then
  print(json.encode({ ok = false, error = 'farm_plot_stage_unreadable' }))
  return
end
if build_stage < max_build_stage then
  print(json.encode({
    ok = false,
    error = 'farm_plot_not_built',
    build_stage = build_stage,
    max_build_stage = max_build_stage,
  }))
  return
end

-- Snapshot the plant_id array before mutating so world-change can be diffed.
local before_plant_id = {}
local ok_before = pcall(function()
  for s = 0, 3 do
    before_plant_id[s + 1] = plot.plant_id[s]
  end
end)
if not ok_before then
  print(json.encode({ ok = false, error = 'plant_id_unreadable' }))
  return
end

local SEASON_FLAG = { [0] = 'SPRING', [1] = 'SUMMER', [2] = 'AUTUMN', [3] = 'WINTER' }
local function raw_flag(flags, name)
  local ok, value = pcall(function() return flags[name] and true or false end)
  return ok and value or false
end

local function usable_seed(item)
  local flags = item and item.flags
  if not flags then return false end
  local rejected = false
  pcall(function()
    rejected = flags.dump
      or flags.forbid
      or flags.garbage_collect
      or flags.hostile
      or flags.on_fire
      or flags.rotten
      or flags.trader
      or flags.in_building
      or flags.construction
      or flags.artifact
  end)
  return not rejected
end

local seeds_by_plant = {}
local ok_seeds = pcall(function()
  for _, item in ipairs(df.global.world.items.other.SEEDS or {}) do
    if usable_seed(item) then
      seeds_by_plant[item.mat_index] =
        (seeds_by_plant[item.mat_index] or 0) + (tonumber(item.stack_size) or 1)
    end
  end
end)
if not ok_seeds then
  print(json.encode({ ok = false, error = 'seed_inventory_unreadable' }))
  return
end

local plot_subterranean = nil
local ok_context = pcall(function()
  local block = dfhack.maps.getTileBlock(plot.centerx, plot.centery, plot.z)
  if not block then return end
  local designation = block.designation[plot.centerx % 16][plot.centery % 16]
  if designation and not designation.hidden then
    plot_subterranean = designation.subterranean and true or false
  end
end)
if not ok_context or plot_subterranean == nil then
  print(json.encode({ ok = false, error = 'farm_plot_context_unreadable' }))
  return
end

local offered_lookup = { [0] = {}, [1] = {}, [2] = {}, [3] = {} }
local offered_crops_by_season = {
  spring = {}, summer = {}, autumn = {}, winter = {},
}
if plot_subterranean then
  local ok_offers = pcall(function()
    for index, plant in ipairs(df.global.world.raws.plants.all) do
      local flags = plant.flags
      local has_seed_stock = (seeds_by_plant[index] or 0) > 0
      local surface_crop = plant.underground_depth_min == 0
        or plant.underground_depth_max == 0
      local depth_ok = surface_crop ~= plot_subterranean
      local biome_ok = raw_flag(flags, 'BIOME_SUBTERRANEAN_WATER')
      if has_seed_stock
          and raw_flag(flags, 'SEED')
          and not raw_flag(flags, 'TREE')
          and depth_ok
          and biome_ok then
        for season = 0, 3 do
          if raw_flag(flags, SEASON_FLAG[season]) then
            offered_lookup[season][index] = true
            table.insert(
              offered_crops_by_season[SEASON_NAMES[season + 1]],
              sanitize(plant.id)
            )
          end
        end
      end
    end
  end)
  if not ok_offers then
    print(json.encode({ ok = false, error = 'crop_options_unreadable' }))
    return
  end
  for _, name in ipairs(SEASON_NAMES) do
    table.sort(offered_crops_by_season[name])
  end
end

local CLEAR = crop_token == 'clear'
local crop_index = -1
if not CLEAR then
  local ok_scan = pcall(function()
    for index, plant in ipairs(df.global.world.raws.plants.all) do
      if plant.id == crop_token then
        crop_index = index
        return
      end
    end
  end)
  if not ok_scan then
    print(json.encode({ ok = false, error = 'raws_unavailable' }))
    return
  end
  if crop_index < 0 then
    print(json.encode({ ok = false, error = 'crop_not_found', crop = sanitize(crop_token) }))
    return
  end
  if not plot_subterranean then
    print(json.encode({
      ok = false,
      error = 'surface_crop_options_unverified',
      farm_building_id = building_id,
      plot_subterranean = false,
      before_plant_id = before_plant_id,
      offered_crops_by_season = offered_crops_by_season,
    }))
    return
  end
end

local seasons_skipped = {}
if not CLEAR then
  for _, idx in ipairs(requested) do
    if not offered_lookup[idx][crop_index] then
      table.insert(seasons_skipped, {
        season = SEASON_NAMES[idx + 1],
        reason = 'crop_not_offered_for_plot_season',
      })
    end
  end
end
if #seasons_skipped > 0 then
  print(json.encode({
    ok = false,
    error = 'crop_not_offered',
    farm_building_id = building_id,
    crop = sanitize(crop_token),
    plot_subterranean = plot_subterranean,
    before_plant_id = before_plant_id,
    seasons_skipped = seasons_skipped,
    offered_crops_by_season = offered_crops_by_season,
    seeds_on_hand = seeds_by_plant[crop_index] or 0,
  }))
  return
end

local seasons_set = {}
local expected_plant_id = {
  before_plant_id[1], before_plant_id[2], before_plant_id[3], before_plant_id[4],
}
for _, idx in ipairs(requested) do
  local value = CLEAR and -1 or crop_index
  expected_plant_id[idx + 1] = value
  table.insert(seasons_set, SEASON_NAMES[idx + 1])
end

local function restore_before()
  for s = 0, 3 do
    plot.plant_id[s] = before_plant_id[s + 1]
  end
end

local write_ok, write_error = pcall(function()
  for _, idx in ipairs(requested) do
    plot.plant_id[idx] = expected_plant_id[idx + 1]
  end
end)

local after_plant_id = {}
local readback_ok = false
if write_ok then
  readback_ok = pcall(function()
    for s = 0, 3 do
      after_plant_id[s + 1] = plot.plant_id[s]
    end
  end)
end

local readback_matches = write_ok and readback_ok
if readback_matches then
  for s = 1, 4 do
    if after_plant_id[s] ~= expected_plant_id[s] then
      readback_matches = false
      break
    end
  end
end

if not readback_matches then
  local rollback_ok = pcall(restore_before)
  local rollback_verified = false
  if rollback_ok then
    rollback_verified = pcall(function()
      for s = 0, 3 do
        if plot.plant_id[s] ~= before_plant_id[s + 1] then
          error('rollback_readback_mismatch')
        end
      end
    end)
  end
  print(json.encode({
    ok = false,
    error = write_ok and 'crop_readback_mismatch' or 'crop_write_failed',
    detail = write_ok and nil or sanitize(write_error),
    farm_building_id = building_id,
    before_plant_id = before_plant_id,
    attempted_plant_id = expected_plant_id,
    observed_plant_id = after_plant_id,
    rollback_verified = rollback_verified,
  }))
  return
end

local seasons_changed = 0
for s = 1, 4 do
  if after_plant_id[s] ~= before_plant_id[s] then
    seasons_changed = seasons_changed + 1
  end
end

local seeds_on_hand = CLEAR and 0 or (seeds_by_plant[crop_index] or 0)

print(json.encode({
  ok = true,
  farm_building_id = building_id,
  build_stage = build_stage,
  max_build_stage = max_build_stage,
  plot_subterranean = plot_subterranean,
  eligibility_scope = plot_subterranean
    and 'native_seed_season_depth_subterranean_water'
    or 'surface_unverified',
  offered_crops_by_season = offered_crops_by_season,
  crop = CLEAR and 'clear' or sanitize(crop_token),
  crop_raw_index = crop_index,
  before_plant_id = before_plant_id,
  after_plant_id = after_plant_id,
  seasons_set = seasons_set,
  seasons_skipped = seasons_skipped,
  seasons_changed = seasons_changed,
  seeds_on_hand = seeds_on_hand,
}))
