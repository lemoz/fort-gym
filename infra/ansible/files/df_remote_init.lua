local remote = require('plugins.remote')
if not remote.isEnabled() then
  remote.enable()
end
remote.config{ host = '0.0.0.0', port = tonumber(os.getenv('DFHACK_PORT') or '5000') }
