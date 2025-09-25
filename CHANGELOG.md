## [Unreleased]
### Added
- DFHack core now autoboots the TCP RPC server during `Core::init()` so headless boots expose 127.0.0.1:5000 without console/init dependencies.
- Ansible `dfhack` role builds/installs the patched DFHack, deploys the headless systemd unit, and verifies TCP listener plus `dfhack-run` connectivity.
- Documentation for operating the headless RPC service (`docs/dfhack-headless-rpc.md`).
