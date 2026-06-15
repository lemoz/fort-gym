-- order_make.lua: enqueue a safe manager order.

local json = require('json')
local args = {...}
local item = tostring(args[1] or '')
local qty = tonumber(args[2]) or 1

local whitelist = {
  bed = 'ConstructBed',
  door = 'ConstructDoor',
  table = 'ConstructTable',
  chair = 'ConstructThrone',
  barrel = 'MakeBarrel',
  bin = 'ConstructBin',
}

local jobname = whitelist[item]
if not jobname then
  print(json.encode({ ok = false, error = 'invalid_item' }))
  return
end

if qty < 1 or qty > 5 then qty = 1 end

local job_type = df.job_type[jobname]
if not job_type then
  print(json.encode({ ok = false, error = 'unsupported_job_type', job = jobname }))
  return
end

local manager_orders = df.global.world.manager_orders
if not manager_orders then
  print(json.encode({ ok = false, error = 'manager_orders_unavailable' }))
  return
end

local wo = df.manager_order:new()
wo.job_type = job_type
wo.amount_total = qty
wo.amount_left = qty
manager_orders:insert('#', wo)

local processed_ok, processed_error = pcall(function()
  dfhack.run_script('orders', 'process-new')
end)

print(json.encode({
  ok = true,
  item = item,
  qty = qty,
  processed = processed_ok,
  process_error = processed_ok and nil or tostring(processed_error),
}))
