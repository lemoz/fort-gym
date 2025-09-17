local ok, remote = pcall(require, 'plugins.remote')
if not ok then
  qerror('[dfhack-headless] failed to load plugins.remote: ' .. tostring(remote))
end
if not remote.isEnabled() then
  dfhack.println('[dfhack-headless] enabling remote plugin')
  remote.enable()
else
  dfhack.println('[dfhack-headless] remote plugin already enabled')
end
local port = tonumber(os.getenv('DFHACK_PORT') or '5000')
dfhack.println(string.format('[dfhack-headless] configuring remote host=0.0.0.0 port=%d', port))
remote.config{ host = '0.0.0.0', port = port }
