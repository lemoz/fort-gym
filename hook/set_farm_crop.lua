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
--   * a subterranean crop cannot be selected on an outside (surface) plot,
--     and a surface crop cannot be selected on an underground plot ->
--     crop_not_growable_here (the flag values are reported).
--   * a crop is only offered in the seasons whose grow-flag is set; a
--     requested season the crop lacks is skipped with season_not_growable.
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

-- Read the plot's surface-ness from the "outside" designation bit at its
-- center tile. NEEDS-LIVE-VALIDATION: the outside bit as a farmability
-- surface indicator has not been probed against a live save.
local plot_outside = nil
pcall(function()
  local block = dfhack.maps.getTileBlock(plot.centerx, plot.centery, plot.z)
  if block then
    local dx, dy = plot.centerx % 16, plot.centery % 16
    plot_outside = block.designation[dx][dy].outside and true or false
  end
end)

-- Crop/plot surface gating mirrors the q-menu: a subterranean crop is not
-- offered on an outside plot, and a surface crop is not offered on an
-- underground plot. Only enforced when we could read the plot's outside bit
-- and the crop is a real plant (clearing is always legal).
local crop_subterranean = nil
if not CLEAR then
  crop_subterranean = crop_flags.BIOME_SUBTERRANEAN_WATER and true or false
  if plot_outside ~= nil then
    if crop_subterranean and plot_outside then
      print(json.encode({
        ok = false,
        error = 'crop_not_growable_here',
        crop = sanitize(crop_token),
        crop_subterranean = true,
        plot_outside = true,
      }))
      return
    end
    if (not crop_subterranean) and (not plot_outside) then
      print(json.encode({
        ok = false,
        error = 'crop_not_growable_here',
        crop = sanitize(crop_token),
        crop_subterranean = false,
        plot_outside = false,
      }))
      return
    end
  end
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
  crop = CLEAR and 'clear' or sanitize(crop_token),
  crop_raw_index = crop_index,
  crop_subterranean = crop_subterranean,
  plot_outside = plot_outside,
  before_plant_id = before_plant_id,
  after_plant_id = after_plant_id,
  seasons_set = seasons_set,
  seasons_skipped = seasons_skipped,
  seasons_changed = seasons_changed,
  seeds_on_hand = seeds_on_hand,
}))
