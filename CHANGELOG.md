## [Unreleased]
_Nothing yet._

## [0.4.0] - 2025-12-11
### Added
- LLM-based trace analyzer using Gemini, with optional auto-analysis after runs (`GOOGLE_API_KEY`) and a new `fort-gym analyze <run_id>` CLI command.
- Pause-state + last-action-result feedback in observations to improve agent situational awareness.
- DFHack fork-storm recovery tooling: direct + GCP scripts, hardened systemd readiness helper, and an Ansible `dfhack_build` role for reproducible rebuilds.
- Drift-free VM workflow helpers: `make vm-test` / `make vm-deploy` targets and deployment best-practices docs.

### Fixed
- `FakeLLMAgent` now emits a valid `DIG` action for deterministic tests.

### Changed
- Ignore local run artifacts and scratch scripts via `.gitignore`.

## [0.3.0] - 2025-10-13
### Added
- DFHack core autoboots the TCP RPC server during `Core::init()` so headless boots expose 127.0.0.1:5000 without console/init dependencies.
- Ansible `dfhack` role builds/installs the patched DFHack, deploys the headless systemd unit, and verifies TCP listener plus `dfhack-run` connectivity.
- Documentation for operating the headless RPC service (`docs/dfhack-headless-rpc.md`).
