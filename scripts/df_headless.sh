#!/usr/bin/env bash
set -euo pipefail
: "${DF_DIR:?Set DF_DIR to your Dwarf Fortress folder}"
: "${DFHACK_PORT:=5000}"
if ! command -v Xvfb >/dev/null; then
  echo "Xvfb not found; install xvfb." >&2
  exit 1
fi
XVFB_DISPLAY=${XVFB_DISPLAY:-:99}
echo "Starting DF under Xvfb ${XVFB_DISPLAY}, DFHack RPC port ${DFHACK_PORT}"
Xvfb ${XVFB_DISPLAY} -screen 0 1280x800x24 &
XVFB_PID=$!
trap "kill ${XVFB_PID} >/dev/null 2>&1 || true" EXIT
export DISPLAY=${XVFB_DISPLAY}
pushd "$DF_DIR" >/dev/null
# TODO: ensure DFHack remote plugin is configured and matches DFHACK_PORT
./dfhack
popd >/dev/null
