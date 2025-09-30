#!/usr/bin/env bash
set -euo pipefail
cd /opt/dwarf-fortress
export TERM=xterm-256color
export DFHACK_HEADLESS=1
export DFHACK_DISABLE_CONSOLE=1
: "${DFHACK_PORT:=5000}"
export LD_LIBRARY_PATH="$PWD/libs:$PWD/hack"
export LD_PRELOAD="$PWD/hack/libdfhack.so"
exec ./dwarfort
