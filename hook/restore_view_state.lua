-- restore_view_state.lua: restore the live DF viewport/cursor after helper probes.

local json = require('json')
local args = {...}

local function to_int(value, default)
  local parsed = tonumber(value)
  if not parsed then return default end
  return math.floor(parsed)
end

local window_x = to_int(args[1], df.global.window_x or 0)
local window_y = to_int(args[2], df.global.window_y or 0)
local window_z = to_int(args[3], df.global.window_z or 0)
local cursor_x = to_int(args[4], -30000)
local cursor_y = to_int(args[5], -30000)
local cursor_z = to_int(args[6], -30000)

df.global.window_x = window_x
df.global.window_y = window_y
df.global.window_z = window_z

if df.global.cursor then
  df.global.cursor.x = cursor_x
  df.global.cursor.y = cursor_y
  df.global.cursor.z = cursor_z
end

print(json.encode({
  ok = true,
  window_x = df.global.window_x or 0,
  window_y = df.global.window_y or 0,
  window_z = df.global.window_z or 0,
  cursor_x = df.global.cursor and df.global.cursor.x or -30000,
  cursor_y = df.global.cursor and df.global.cursor.y or -30000,
  cursor_z = df.global.cursor and df.global.cursor.z or -30000,
}))
