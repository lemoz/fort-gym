-- view_state.lua: read the live DF viewport/cursor without moving it.

local json = require('json')

local cursor = df.global.cursor or {}

print(json.encode({
  ok = true,
  window_x = df.global.window_x or 0,
  window_y = df.global.window_y or 0,
  window_z = df.global.window_z or 0,
  cursor_x = cursor.x or -30000,
  cursor_y = cursor.y or -30000,
  cursor_z = cursor.z or -30000,
}))
