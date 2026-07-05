-- unsuspend_jobs.lua: clear the suspended flag on construction/build jobs
-- inside a bounded rect. This mirrors a player's q-menu unsuspend action —
-- it does NOT complete any work itself. A suspended job (job.flags.suspend)
-- means a dwarf cannot currently path to or reach the job site, so the game
-- auto-suspends it; unsuspending only re-arms the job so a dwarf will
-- reattempt it as the simulation continues to run. Never mutates tiles,
-- designations, or buildings — only the suspend flag on matching jobs.

local json = require('json')
local args = {...}

local function to_int(v)
  local n = tonumber(v)
  if not n then return nil end
  return math.floor(n)
end

local x1 = to_int(args[1])
local y1 = to_int(args[2])
local z1 = to_int(args[3])
local x2 = to_int(args[4])
local y2 = to_int(args[5])
local z2 = to_int(args[6])

if not (x1 and y1 and z1 and x2 and y2 and z2) or z1 ~= z2 then
  print(json.encode({ ok = false, error = 'bad_rect' }))
  return
end

local rx1, ry1, rz = math.min(x1, x2), math.min(y1, y2), z1
local rx2, ry2 = math.max(x1, x2), math.max(y1, y2)

if (rx2 - rx1 + 1) > 10 or (ry2 - ry1 + 1) > 10 then
  print(json.encode({ ok = false, error = 'rect_too_large' }))
  return
end

local function pos_in_rect(pos)
  local ok, x, y, z = pcall(function() return pos.x, pos.y, pos.z end)
  if not ok then return false end
  return z == rz and x >= rx1 and x <= rx2 and y >= ry1 and y <= ry2
end

local unsuspended = 0
local suspended_found = 0

-- Walk the live jobs linked list (same pattern as job_metrics.lua) and clear
-- the suspend flag on any job whose position falls inside the bounded rect.
local ok_walk = pcall(function()
  local link = df.global.world.jobs.list.next
  while link do
    local job = link.item
    if job then
      local ok_flags, suspended = pcall(function() return job.flags.suspend and true or false end)
      if ok_flags and suspended and pos_in_rect(job.pos) then
        suspended_found = suspended_found + 1
        job.flags.suspend = false
        unsuspended = unsuspended + 1
      end
    end
    link = link.next
  end
end)

if not ok_walk then
  print(json.encode({ ok = false, error = 'job_list_unavailable' }))
  return
end

-- ok=true even when unsuspended==0: an empty rect or a rect with no
-- suspended jobs is a legitimate, honestly-reported outcome, not an error.
print(json.encode({
  ok = true,
  rect = { rx1, ry1, rz, rx2, ry2, rz },
  unsuspended = unsuspended,
  suspended_found = suspended_found,
}))
