#!/usr/bin/env bash
set -euo pipefail

provider_vars=(
  ANTHROPIC_API_KEY
  GEMINI_API_KEY
  GOOGLE_API_KEY
  OPENAI_API_KEY
  OPENROUTER_API_KEY
  OPENROUTER_MODEL
)
for provider_var in "${provider_vars[@]}"; do
  if [[ -n "${!provider_var:-}" ]]; then
    printf 'provider credential or route is forbidden in M1a: %s\n' "$provider_var" >&2
    exit 64
  fi
done

: "${DFHACK_PORT:?DFHACK_PORT is required}"
: "${FORTGYM_RUN_ID:?FORTGYM_RUN_ID is required}"
: "${FORTGYM_RUNTIME_SAVE:=region3}"

if [[ ! "$DFHACK_PORT" =~ ^[0-9]+$ ]] || (( DFHACK_PORT < 1024 || DFHACK_PORT > 65535 )); then
  printf 'invalid DFHACK_PORT: %s\n' "$DFHACK_PORT" >&2
  exit 64
fi
if [[ ! "$FORTGYM_RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  printf 'invalid FORTGYM_RUN_ID\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_RUNTIME_SAVE" =~ ^[A-Za-z0-9_-]+$ ]]; then
  printf 'invalid FORTGYM_RUNTIME_SAVE\n' >&2
  exit 64
fi

seed_root=/opt/seed_saves/seed_region3_fresh
runtime_root="/opt/dwarf-fortress/data/save/$FORTGYM_RUNTIME_SAVE"
test -f "$seed_root/world.sav"

rm -rf /opt/dwarf-fortress/data/save
mkdir -p /opt/dwarf-fortress/data/save /run/fortgym
cp -a "$seed_root" "$runtime_root"
chmod -R u+w "$runtime_root"
printf '%s\n' "$FORTGYM_RUN_ID" > /run/fortgym/run-id

cat > /opt/dwarf-fortress/dfhack-config/remote-server.json <<JSON
{
  "allow_remote": false,
  "port": ${DFHACK_PORT}
}
JSON

if [[ -d /artifacts ]]; then
  (
    cd "$seed_root"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum --zero
  ) > /artifacts/seed_tree.sha256z
  (
    cd "$runtime_root"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum --zero
  ) > /artifacts/runtime_tree.before.sha256z
  cmp /artifacts/seed_tree.sha256z /artifacts/runtime_tree.before.sha256z
  sha256sum /artifacts/seed_tree.sha256z > /artifacts/seed_tree.manifest.sha256
  sha256sum "$seed_root/world.sav" > /artifacts/seed_world.sha256
  printf '{"run_id":"%s","dfhack_port":%s,"provider_credentials":false,"seed_copy_equal":true}\n' \
    "$FORTGYM_RUN_ID" "$DFHACK_PORT" > /artifacts/entrypoint_attestation.json
fi

export TERM=xterm-256color
export DFHACK_HEADLESS=1
export DFHACK_DISABLE_CONSOLE=1
export SDL_VIDEODRIVER=dummy
export HOME=/home/dfh

script -qefc /opt/dwarf-fortress/dfhack /dev/null &
launcher_pid=$!

terminate_launcher() {
  kill -TERM "$launcher_pid" 2>/dev/null || true
  wait "$launcher_pid" 2>/dev/null || true
}
trap terminate_launcher TERM INT

rpc_ready=0
for _attempt in $(seq 1 120); do
  if /opt/dwarf-fortress/dfhack-run lua "print('FORTGYM_RPC_READY')" \
    2>/dev/null | grep -q FORTGYM_RPC_READY; then
    rpc_ready=1
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    wait "$launcher_pid" || true
    printf 'DFHack exited before RPC readiness\n' >&2
    exit 70
  fi
  sleep 1
done
if (( rpc_ready == 0 )); then
  printf 'DFHack RPC readiness timeout\n' >&2
  terminate_launcher
  exit 70
fi

/opt/dwarf-fortress/dfhack-run load-save "$FORTGYM_RUNTIME_SAVE"

map_ready=0
for _attempt in $(seq 1 180); do
  if /opt/dwarf-fortress/dfhack-run lua \
    "print(dfhack.isMapLoaded() and 'FORTGYM_MAP_READY' or 'FORTGYM_MAP_WAIT')" \
    2>/dev/null | grep -q FORTGYM_MAP_READY; then
    map_ready=1
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    wait "$launcher_pid" || true
    printf 'DFHack exited before map readiness\n' >&2
    exit 70
  fi
  sleep 1
done
if (( map_ready == 0 )); then
  printf 'DFHack map readiness timeout\n' >&2
  terminate_launcher
  exit 70
fi

if [[ -d /artifacts ]]; then
  printf '{"run_id":"%s","dfhack_port":%s,"rpc_ready":true,"map_ready":true}\n' \
    "$FORTGYM_RUN_ID" "$DFHACK_PORT" > /artifacts/runtime_readiness.json
fi

wait "$launcher_pid"
