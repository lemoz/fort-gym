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
-- Engine-constraint gating mirrors what the q-menu itself offers (NOT a
-- gameplay heuristic — the UI simply does not present these choices):
--   * a crop is only offered in the seasons whose grow-flag is set; a
--     requested season the crop lacks is skipped with season_not_growable.
-- We do NOT gate on surface-vs-subterranean here. DF farm-plot crop
-- eligibility is governed by a plant's full biome/environment token set
-- against the plot, not a single biome flag; approximating that from one
-- unverified flag risked wrongly rejecting a legal crop selection with a
-- dishonest not-growable-here reason. Surface/subterranean eligibility
-- is therefore left to the engine, and no such rejection is emitted.
-- There is NO seed-availability gating (the player can select a crop with
-- zero seeds; planting simply waits) — seeds_on_hand is reported as evidence
-- only.

local json = require('json')
local args = {...}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local function sanitize(text)
  return tostring(text or ''):gsub('[^%w %p]', '?')
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

-- Resolve the crop token to a plant raw index (exact match on .id).
local CLEAR = crop_token == 'clear'
local crop_index = -1
local crop_flags = nil
if not CLEAR then
  local ok_scan = pcall(function()
    for i, plant in ipairs(df.global.world.raws.plants.all) do
      if plant.id == crop_token then
        crop_index = i
        crop_flags = plant.flags
        return
      end
    end
  end)
  if not ok_scan then
    print(json.encode({ ok = false, error = 'raws_unavailable' }))
    return
  end
  if crop_index < 0 or crop_flags == nil then
    print(json.encode({ ok = false, error = 'crop_not_found', crop = sanitize(crop_token) }))
    return
  end
end

-- Surface-vs-subterranean eligibility is intentionally NOT gated here. DF
-- decides a plot's offered crop list from the plant's full biome/environment
-- token set, not a single biome flag; approximating it from one unverified
-- flag would risk a dishonest not-growable-here rejection of a legal
-- crop. We leave that constraint to the engine and never reject on it.

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
local seasons_set = {}
local seasons_skipped = {}
local after_plant_id = { before_plant_id[1], before_plant_id[2], before_plant_id[3], before_plant_id[4] }

for _, idx in ipairs(requested) do
  if CLEAR then
    -- Clearing is offered in every season.
    plot.plant_id[idx] = -1
    after_plant_id[idx + 1] = -1
    table.insert(seasons_set, SEASON_NAMES[idx + 1])
  else
    local grows = false
    pcall(function()
      grows = crop_flags[SEASON_FLAG[idx]] and true or false
    end)
    if grows then
      plot.plant_id[idx] = crop_index
      after_plant_id[idx + 1] = crop_index
      table.insert(seasons_set, SEASON_NAMES[idx + 1])
    else
      table.insert(seasons_skipped, {
        season = SEASON_NAMES[idx + 1],
        reason = 'season_not_growable',
      })
    end
  end
end

local seasons_changed = 0
for s = 1, 4 do
  if after_plant_id[s] ~= before_plant_id[s] then
    seasons_changed = seasons_changed + 1
  end
end

-- Seeds on hand for the crop (informational only — never gates the action).
local seeds_on_hand = 0
if not CLEAR then
  pcall(function()
    local seeds = df.global.world.items.other.SEEDS
    if seeds then
      for _, item in ipairs(seeds) do
        if item.mat_index == crop_index then
          seeds_on_hand = seeds_on_hand + 1
        end
      end
    end
  end)
end

print(json.encode({
  ok = true,
  farm_building_id = building_id,
  build_stage = build_stage,
  max_build_stage = max_build_stage,
  crop = CLEAR and 'clear' or sanitize(crop_token),
  crop_raw_index = crop_index,
  before_plant_id = before_plant_id,
  after_plant_id = after_plant_id,
  seasons_set = seasons_set,
  seasons_skipped = seasons_skipped,
  seasons_changed = seasons_changed,
  seeds_on_hand = seeds_on_hand,
}))
