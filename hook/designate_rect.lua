-- designate_rect.lua: safely designate dig/channel rectangles or trigger
-- chop/gather.

local json = require('json')
local args = {...}

local kind = tostring(args[1] or '')
local valid = { dig = true, channel = true, chop = true, gather = true }
if not valid[kind] then
  print(json.encode({ ok = false, error = 'invalid_kind' }))
  return
end

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[2])
local y1 = to_int(args[3])
local z1 = to_int(args[4])
local x2 = to_int(args[5])
local y2 = to_int(args[6])
local z2 = to_int(args[7])

if not (x1 and y1 and z1 and x2 and y2 and z2) or z1 ~= z2 then
  print(json.encode({ ok = false, error = 'bad_rect' }))
  return
end

local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)

if (rx2 - rx1 + 1) > 30 or (ry2 - ry1 + 1) > 30 then
  print(json.encode({ ok = false, error = 'rect_too_large' }))
  return
end

local block_w, block_h = 16, 16

local attrs = df.tiletype.attrs
local wall_shape = df.tiletype_shape.WALL
local floor_shape = df.tiletype_shape.FLOOR
local tree_material = df.tiletype_material.TREE
local frozen_liquid_material = df.tiletype_material.FROZEN_LIQUID
local construction_material = df.tiletype_material.CONSTRUCTION
local disallowed_native_dig_materials = {
  [df.tiletype_material.POOL] = true,
  [df.tiletype_material.RIVER] = true,
  [df.tiletype_material.TREE] = true,
  [df.tiletype_material.ROOT] = true,
  [df.tiletype_material.LAVA_STONE] = true,
  [df.tiletype_material.MAGMA] = true,
  [df.tiletype_material.HFS] = true,
  [df.tiletype_material.UNDERWORLD_GATE] = true,
  -- DFHack's native helper allows only deep-special-tube FEATURE tiles. The
  -- 0.47 Lua surface cannot verify that feature type without inspecting
  -- hidden geology, so the governed action conservatively rejects all FEATURE.
  [df.tiletype_material.FEATURE] = true,
}

local shrub_shape = df.tiletype_shape.SHRUB

-- Bounded chop/gather designation. Preflight the entire selection, then commit
-- and read back every eligible tile as one transaction. A failed write is
-- rolled back and verified before returning, matching the dig/channel contract.
if kind == 'chop' or kind == 'gather' then
  local target = df.tile_dig_designation.Default
  local writes = {}
  local newly_designated = 0
  local already_designated = 0
  local non_target_tiles = 0
  local non_target_samples = {}
  local MAX_NON_TARGET_SAMPLES = 12
  local preflight_error = nil

  local function add_non_target_sample(tx, ty, error_name, tile_shape, tiletype)
    if #non_target_samples >= MAX_NON_TARGET_SAMPLES then return end
    local sample = { x = tx, y = ty, z = rz, error = error_name }
    if tile_shape then sample.tile_shape = tile_shape end
    if tiletype then sample.tiletype = tiletype end
    table.insert(non_target_samples, sample)
  end

  local function attach_non_target_evidence(payload)
    if non_target_tiles <= 0 then return end
    payload.failed_count = non_target_tiles
    payload.failed = non_target_samples
    payload.failed_truncated = non_target_tiles > #non_target_samples
  end

  for tx = rx1, rx2 do
    for ty = ry1, ry2 do
      local block = dfhack.maps.getTileBlock(tx, ty, rz)
      if block then
        local dx, dy = tx % block_w, ty % block_h
        local designation = block.designation[dx][dy]
        local is_target = false
        local non_target_error = nil
        local tile_shape_name = nil
        local tiletype_name = nil
        if not designation then
          preflight_error = preflight_error or 'designation_unreadable'
          non_target_error = 'designation_unreadable'
        elseif designation.hidden then
          non_target_error = 'hidden_unexplored'
        elseif not designation.hidden then
          local tiletype = block.tiletype[dx][dy]
          local ok_attr, attr = pcall(function()
            return attrs[tiletype]
          end)
          if not ok_attr or not attr then
            preflight_error = preflight_error or 'tiletype_unreadable'
            non_target_error = 'tiletype_unreadable'
          else
            tile_shape_name = tostring(df.tiletype_shape[attr.shape] or attr.shape)
            tiletype_name = tostring(df.tiletype[tiletype] or tiletype)
            if kind == 'chop' then
              is_target = attr.material == tree_material and attr.shape == wall_shape
            else
              is_target = attr.shape == shrub_shape
            end
            if not is_target then
              non_target_error = kind == 'chop' and 'not_tree' or 'not_shrub'
            end
          end
        end
        if is_target then
          local already = designation.dig == target
          table.insert(writes, {
            block = block,
            designation = designation,
            original = designation.dig,
            original_block_designated = block.flags.designated,
            already = already,
          })
          if already then
            already_designated = already_designated + 1
          else
            newly_designated = newly_designated + 1
          end
        else
          non_target_tiles = non_target_tiles + 1
          add_non_target_sample(
            tx,
            ty,
            non_target_error or (kind == 'chop' and 'not_tree' or 'not_shrub'),
            tile_shape_name,
            tiletype_name
          )
        end
      else
        preflight_error = preflight_error or 'missing_block'
        non_target_tiles = non_target_tiles + 1
        add_non_target_sample(tx, ty, 'missing_block', nil, nil)
      end
    end
  end

  if preflight_error then
    local failure = {
      ok = false,
      error = 'designation_preflight_failed',
      detail = preflight_error,
      kind = kind,
      rect = { rx1, ry1, rz, rx2, ry2, rz },
      already_designated = 0,
    }
    if kind == 'chop' then
      failure.trees_designated = 0
      failure.non_tree_tiles = non_target_tiles
    else
      failure.shrubs_designated = 0
      failure.non_shrub_tiles = non_target_tiles
    end
    attach_non_target_evidence(failure)
    print(json.encode(failure))
    return
  end

  local function rollback_writes()
    for _, record in ipairs(writes) do
      record.designation.dig = record.original
      record.block.flags.designated = record.original_block_designated
    end
  end

  local committed, commit_error = pcall(function()
    for _, record in ipairs(writes) do
      if not record.already then record.designation.dig = target end
      record.block.flags.designated = true
    end
  end)
  if committed then
    for _, record in ipairs(writes) do
      if record.designation.dig ~= target or not record.block.flags.designated then
        committed = false
        commit_error = 'designation_readback_mismatch'
        break
      end
    end
  end

  if not committed then
    local rollback_ok = pcall(rollback_writes)
    local rollback_verified = false
    if rollback_ok then
      rollback_verified = pcall(function()
        for _, record in ipairs(writes) do
          if record.designation.dig ~= record.original
              or record.block.flags.designated ~= record.original_block_designated then
            error('designation_rollback_readback_mismatch')
          end
        end
      end)
    end
    local failure = {
      ok = false,
      error = 'designation_write_failed',
      detail = tostring(commit_error),
      kind = kind,
      rect = { rx1, ry1, rz, rx2, ry2, rz },
      already_designated = 0,
      rollback_verified = rollback_verified,
    }
    if kind == 'chop' then
      failure.trees_designated = 0
      failure.non_tree_tiles = non_target_tiles
    else
      failure.shrubs_designated = 0
      failure.non_shrub_tiles = non_target_tiles
    end
    attach_non_target_evidence(failure)
    print(json.encode(failure))
    return
  end

  local success = {
    ok = true,
    kind = kind,
    rect = { rx1, ry1, rz, rx2, ry2, rz },
    already_designated = already_designated,
  }
  if kind == 'chop' then
    success.trees_designated = newly_designated
    success.non_tree_tiles = non_target_tiles
  else
    success.shrubs_designated = newly_designated
    success.non_shrub_tiles = non_target_tiles
  end
  attach_non_target_evidence(success)
  print(json.encode(success))
  return
end

local function target_designation(mode)
  if mode == 'dig' then
    return df.tile_dig_designation.Default
  elseif mode == 'channel' then
    return df.tile_dig_designation.Channel
  end
  return nil
end

local function is_map_edge(x, y)
  local region = df.global.world.map
  if not region then return true end
  local max_x = (region.x_count_block or 0) * block_w - 1
  local max_y = (region.y_count_block or 0) * block_h - 1
  return x <= 0 or y <= 0 or x >= max_x or y >= max_y
end

local function scan_building_at_tile(x, y, z)
  return pcall(function()
    local all = df.global.world.buildings and df.global.world.buildings.all
    if not all then error('building_list_unavailable') end
    for _, building in ipairs(all) do
      if building.z == z
          and x >= building.x1 and x <= building.x2
          and y >= building.y1 and y <= building.y2 then
        -- Conservatively treat every tile in a building's native footprint as
        -- occupied. This scan is independent of the potentially stale map
        -- occupancy bit used internally by findAtTile in DFHack 0.47.05.
        return building
      end
    end
    return nil
  end)
end

-- Return a write record or a factual rejection reason. Hidden tiles are
-- rejected before tiletype inspection, so this helper cannot become a geology
-- oracle. Scan buildings.all directly because DFHack 0.47.05 findAtTile exits
-- early when the occupancy bit is stale-zero (the attempt-19 incident).
local function classify_tile(x, y, z, mode)
  if is_map_edge(x, y) then return nil, 'map_edge' end
  local block = dfhack.maps.getTileBlock(x, y, z)
  if not block then return nil, 'missing_block' end
  local dx, dy = x % block_w, y % block_h
  local designation = block.designation[dx][dy]
  if not designation then return nil, 'designation_unreadable' end
  if designation.hidden then return nil, 'hidden_unexplored' end

  local ok_building, building = scan_building_at_tile(x, y, z)
  if not ok_building then return nil, 'building_state_unreadable' end
  if building or block.occupancy[dx][dy].building ~= 0 then
    return nil, 'occupied_by_building'
  end
  if designation.flow_size > 0 then return nil, 'active_liquid' end

  local ok_attr, attr = pcall(function()
    return attrs[block.tiletype[dx][dy]]
  end)
  if not ok_attr or not attr then return nil, 'tiletype_unreadable' end
  if attr.material == construction_material then return nil, 'player_construction' end
  if attr.material == frozen_liquid_material then return nil, 'frozen_liquid' end
  if attr.material == tree_material then return nil, 'tree' end
  if disallowed_native_dig_materials[attr.material] then
    return nil, 'native_material_not_diggable'
  end

  local shape_ok = attr.shape == wall_shape
  if mode == 'channel' then
    shape_ok = shape_ok or attr.shape == floor_shape
  end
  if not shape_ok then return nil, 'ineligible_shape' end

  local target = target_designation(mode)
  return {
    block = block,
    designation = designation,
    target = target,
    original = designation.dig,
    original_block_designated = block.flags.designated,
    already = designation.dig == target,
  }, nil
end

-- Preflight the complete requested rectangle before writing anything. A
-- rejected multi-tile command is therefore a true no-op instead of a partial
-- designation whose actual footprint differs from the model's command.
local writes = {}
local failed = {}
local failed_count = 0
local reason_counts = {}
local MAX_FAILED_DETAILS = 32

for tx = rx1, rx2 do
  for ty = ry1, ry2 do
    local record, reason = classify_tile(tx, ty, rz, kind)
    if record then
      table.insert(writes, record)
    else
      failed_count = failed_count + 1
      reason_counts[reason] = (reason_counts[reason] or 0) + 1
      if #failed < MAX_FAILED_DETAILS then
        table.insert(failed, { x = tx, y = ty, z = rz, error = reason })
      end
    end
  end
end

if failed_count > 0 then
  print(json.encode({
    ok = false,
    error = 'tile_not_designatable',
    kind = kind,
    rect = { rx1, ry1, rz, rx2, ry2, rz },
    failed_count = failed_count,
    failed = failed,
    rejection_counts = reason_counts,
    newly_designated = 0,
    already_designated = 0,
    ineligible_tiles = failed_count,
    non_wall_tiles = reason_counts.ineligible_shape or 0,
    missing_tiles = reason_counts.missing_block or 0,
  }))
  return
end

local newly_designated = 0
local already_designated = 0
local function rollback_writes()
  for _, record in ipairs(writes) do
    record.designation.dig = record.original
    record.block.flags.designated = record.original_block_designated
  end
end

local committed, commit_error = pcall(function()
  for _, record in ipairs(writes) do
    if record.already then
      already_designated = already_designated + 1
    else
      record.designation.dig = record.target
      newly_designated = newly_designated + 1
    end
    record.block.flags.designated = true
  end
end)

if committed then
  for _, record in ipairs(writes) do
    if record.designation.dig ~= record.target
        or not record.block.flags.designated then
      committed = false
      commit_error = 'designation_readback_mismatch'
      break
    end
  end
end

if not committed then
  local rollback_ok = pcall(rollback_writes)
  local rollback_verified = false
  if rollback_ok then
    rollback_verified = pcall(function()
      for _, record in ipairs(writes) do
        if record.designation.dig ~= record.original
            or record.block.flags.designated ~= record.original_block_designated then
          error('designation_rollback_readback_mismatch')
        end
      end
    end)
  end
  print(json.encode({
    ok = false,
    error = 'designation_write_failed',
    detail = tostring(commit_error),
    kind = kind,
    rect = { rx1, ry1, rz, rx2, ry2, rz },
    newly_designated = 0,
    already_designated = 0,
    rollback_verified = rollback_verified,
  }))
  return
end

print(json.encode({
  ok = true,
  kind = kind,
  rect = { rx1, ry1, rz, rx2, ry2, rz },
  newly_designated = newly_designated,
  already_designated = already_designated,
  ineligible_tiles = 0,
  non_wall_tiles = 0,
  missing_tiles = 0,
}))
