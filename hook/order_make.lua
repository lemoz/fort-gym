-- order_make.lua: enqueue a safe manager order.

local json = require('json')
local args = {...}
local item = tostring(args[1] or '')
local qty = tonumber(args[2]) or 1

local whitelist = {
  bed = 'Make Bed',
  door = 'Make Door',
  table = 'Make Table',
  chair = 'Make Throne',
  barrel = 'Make Barrel',
  bin = 'Make Bin',
}

local jobname = whitelist[item]
if not jobname then
  print(json.encode({ ok = false, error = 'invalid_item' }))
  return
end

if qty < 1 or qty > 5 then qty = 1 end

local wo = df.workorder.WorkOrder:new()
wo.job_type = df.job_type[jobname:gsub(' ', '')]
wo.amount_total = qty
df.global.world.manager_workorders:insert('#', wo)

dfhack.run_script('orders', 'process-new')

print(json.encode({ ok = true, item = item, qty = qty }))
