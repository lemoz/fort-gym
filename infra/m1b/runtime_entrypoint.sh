#!/usr/bin/env bash
set -euo pipefail

# M1b runtime entrypoint for the checksum-pinned M1a stock image. The script is
# bind-mounted and invoked through /bin/bash so it does not mutate the image.

provider_vars=(
  ANTHROPIC_API_KEY
  ANTHROPIC_BASE_URL
  ANTHROPIC_MODEL
  GEMINI_API_KEY
  GEMINI_MODEL
  GOOGLE_API_KEY
  GOOGLE_GENAI_API_KEY
  LLM_MODEL
  LLM_PROVIDER
  LLM_ROUTE
  OPENAI_API_KEY
  OPENAI_BASE_URL
  OPENAI_MODEL
  OPENROUTER_API_KEY
  OPENROUTER_BASE_URL
  OPENROUTER_MAX_COST_USD
  OPENROUTER_MAX_TOTAL_TOKENS
  OPENROUTER_MODEL
  OPENROUTER_PROVIDER_NAME
  OPENROUTER_STRICT_SUPERVISED
)
for provider_var in "${provider_vars[@]}"; do
  if [[ -n "${!provider_var:-}" ]]; then
    printf 'provider material is forbidden in the DF runtime: %s\n' "$provider_var" >&2
    exit 64
  fi
done

: "${DFHACK_PORT:?DFHACK_PORT is required}"
: "${FORTGYM_RUN_ID:?FORTGYM_RUN_ID is required}"
: "${FORTGYM_RUN_NONCE:?FORTGYM_RUN_NONCE is required}"
: "${FORTGYM_CONTRACT_SHA256:?FORTGYM_CONTRACT_SHA256 is required}"
: "${FORTGYM_RUNTIME_PREPARED:?FORTGYM_RUNTIME_PREPARED is required}"
: "${FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256:?FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256 is required}"
: "${FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256:?FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256 is required}"
: "${FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256:?FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256 is required}"
: "${FORTGYM_EXPECTED_SEED_TREE_SHA256:?FORTGYM_EXPECTED_SEED_TREE_SHA256 is required}"
: "${FORTGYM_EXPECTED_SEED_WORLD_SHA256:?FORTGYM_EXPECTED_SEED_WORLD_SHA256 is required}"
: "${FORTGYM_RUNTIME_SAVE:=region3}"
: "${FORTGYM_ALLOW_TEST_FAULTS:=0}"
: "${FORTGYM_ALLOW_TEST_FAULT_PROFILE:=0}"
: "${FORTGYM_FAULT_PROFILE:=}"
: "${FORTGYM_COHORT_SHA256:=}"

write_startup_terminal() {
  local terminal_code=$1
  local injected=$2
  local terminal_path=/artifacts/startup-terminal.json
  local temporary_path="${terminal_path}.tmp.$$"
  printf '{"schema":"fortgym.m1b-startup-terminal/v1","run_id":"%s","contract_sha256":"%s","terminal_code":"%s","injected":%s}\n' \
    "$FORTGYM_RUN_ID" "$FORTGYM_CONTRACT_SHA256" "$terminal_code" "$injected" \
    > "$temporary_path"
  # This terminal receipt contains only public run identity and a typed reason.
  # The container runs as root, while the supervising host process is the
  # unprivileged fortgym account, so the completed receipt must be readable by
  # that account after the bind-mounted write.
  chmod 644 "$temporary_path"
  mv -f "$temporary_path" "$terminal_path"
}

if [[ ! "$DFHACK_PORT" =~ ^[0-9]+$ ]] || (( DFHACK_PORT < 1024 || DFHACK_PORT > 65535 )); then
  printf 'invalid DFHACK_PORT: %s\n' "$DFHACK_PORT" >&2
  exit 64
fi
if [[ ! "$FORTGYM_RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
  printf 'invalid FORTGYM_RUN_ID\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_RUN_NONCE" =~ ^[a-f0-9]{32,64}$ ]]; then
  printf 'invalid FORTGYM_RUN_NONCE\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_CONTRACT_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_CONTRACT_SHA256\n' >&2
  exit 64
fi
if [[ "$FORTGYM_RUNTIME_PREPARED" != 1 ]]; then
  printf 'invalid FORTGYM_RUNTIME_PREPARED\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_EXPECTED_SEED_TREE_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_EXPECTED_SEED_TREE_SHA256\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_EXPECTED_SEED_WORLD_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  printf 'invalid FORTGYM_EXPECTED_SEED_WORLD_SHA256\n' >&2
  exit 64
fi
if [[ ! "$FORTGYM_RUNTIME_SAVE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
  printf 'invalid FORTGYM_RUNTIME_SAVE\n' >&2
  exit 64
fi
if [[ "$FORTGYM_ALLOW_TEST_FAULTS" != 0 && "$FORTGYM_ALLOW_TEST_FAULTS" != 1 ]]; then
  printf 'invalid FORTGYM_ALLOW_TEST_FAULTS\n' >&2
  exit 64
fi
if [[ -n "${FORTGYM_TEST_SUPPRESS_RPC_READY:-}" && "$FORTGYM_ALLOW_TEST_FAULTS" != 1 ]]; then
  printf 'test fault knob rejected outside explicit fault mode\n' >&2
  exit 64
fi
if [[ "$FORTGYM_ALLOW_TEST_FAULT_PROFILE" != 0 && "$FORTGYM_ALLOW_TEST_FAULT_PROFILE" != 1 ]]; then
  printf 'invalid FORTGYM_ALLOW_TEST_FAULT_PROFILE\n' >&2
  exit 64
fi
if [[ -n "$FORTGYM_FAULT_PROFILE" && "$FORTGYM_ALLOW_TEST_FAULT_PROFILE" != 1 ]]; then
  printf 'runtime fault profile rejected outside explicit fault mode\n' >&2
  exit 64
fi
if [[ "$FORTGYM_ALLOW_TEST_FAULT_PROFILE" == 1 ]]; then
  if [[ "$FORTGYM_FAULT_PROFILE" != oom_256m ]]; then
    printf 'unsupported runtime fault profile\n' >&2
    exit 64
  fi
  if [[ ! "$FORTGYM_COHORT_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
    printf 'invalid FORTGYM_COHORT_SHA256\n' >&2
    exit 64
  fi
elif [[ -n "$FORTGYM_COHORT_SHA256" ]]; then
  printf 'runtime fault cohort identity rejected outside explicit fault mode\n' >&2
  exit 64
fi

seed_root=/opt/seed_saves/seed_region3_fresh
runtime_root="/opt/dwarf-fortress/data/save/$FORTGYM_RUNTIME_SAVE"
test -f "$seed_root/world.sav"
test -d /artifacts

rm -rf /opt/dwarf-fortress/data/save
mkdir -p /opt/dwarf-fortress/data/save /run/fortgym
cp -a "$seed_root" "$runtime_root"
chmod -R u+w "$runtime_root"

printf '%s\n' "$FORTGYM_RUN_ID" > /run/fortgym/run-id
printf '%s\n' "$FORTGYM_RUN_NONCE" > /run/fortgym/run-nonce
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$FORTGYM_RUN_ID" "$FORTGYM_RUN_NONCE" "$FORTGYM_CONTRACT_SHA256" \
  "$FORTGYM_EXPECTED_SEED_TREE_SHA256" "$FORTGYM_EXPECTED_SEED_WORLD_SHA256" \
  "$FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256" "$FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256" \
  "$FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256" \
  > /run/fortgym/run-identity.tsv

cat > /opt/dwarf-fortress/dfhack-config/remote-server.json <<JSON
{
  "allow_remote": false,
  "port": ${DFHACK_PORT}
}
JSON

(
  cd "$seed_root"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum --zero
) > /artifacts/seed_tree.sha256z
(
  cd "$runtime_root"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum --zero
) > /artifacts/runtime_tree.before.sha256z
cmp /artifacts/seed_tree.sha256z /artifacts/runtime_tree.before.sha256z
seed_tree_sha256="$(sha256sum /artifacts/seed_tree.sha256z | awk '{print $1}')"
seed_world_sha256="$(sha256sum "$seed_root/world.sav" | awk '{print $1}')"
printf '%s  %s\n' "$seed_tree_sha256" seed_tree.sha256z \
  > /artifacts/seed_tree.manifest.sha256
printf '%s  %s\n' "$seed_world_sha256" world.sav \
  > /artifacts/seed_world.sha256
if [[ "$seed_tree_sha256" != "$FORTGYM_EXPECTED_SEED_TREE_SHA256" ]]; then
  printf 'seed tree SHA-256 mismatch: expected %s observed %s\n' \
    "$FORTGYM_EXPECTED_SEED_TREE_SHA256" "$seed_tree_sha256" >&2
  exit 65
fi
if [[ "$seed_world_sha256" != "$FORTGYM_EXPECTED_SEED_WORLD_SHA256" ]]; then
  printf 'seed world SHA-256 mismatch: expected %s observed %s\n' \
    "$FORTGYM_EXPECTED_SEED_WORLD_SHA256" "$seed_world_sha256" >&2
  exit 65
fi
printf '{"run_id":"%s","nonce":"%s","contract_sha256":"%s","dfhack_port":%s,"provider_material":false,"seed_copy_equal":true,"seed_tree_sha256":"%s","seed_world_sha256":"%s","image_manifest_sha256":"%s","image_config_sha256":"%s","image_archive_sha256":"%s"}\n' \
  "$FORTGYM_RUN_ID" "$FORTGYM_RUN_NONCE" "$FORTGYM_CONTRACT_SHA256" "$DFHACK_PORT" \
  "$seed_tree_sha256" "$seed_world_sha256" \
  "$FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256" "$FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256" \
  "$FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256" \
  > /artifacts/entrypoint_attestation.json

if [[ "$FORTGYM_FAULT_PROFILE" == oom_256m ]]; then
  nonce_sha256="$(printf '%s' "$FORTGYM_RUN_NONCE" | sha256sum | awk '{print $1}')"
  hold_path=/artifacts/pre-readiness-oom-hold-ready.json
  hold_temporary="${hold_path}.tmp.$$"
  printf '{"schema":"fortgym.m1b-pre-readiness-oom-hold-ready/v1","run_id":"%s","contract_sha256":"%s","nonce_sha256":"%s","cohort_sha256":"%s","fault_profile":"oom_256m","memory_bytes":268435456,"memory_swap_bytes":268435456}\n' \
    "$FORTGYM_RUN_ID" "$FORTGYM_CONTRACT_SHA256" "$nonce_sha256" \
    "$FORTGYM_COHORT_SHA256" > "$hold_temporary"
  # The hold receipt contains a nonce digest, never the raw nonce, and is read
  # by the unprivileged host monitor before it authorizes release.
  chmod 644 "$hold_temporary"
  sync -f "$hold_temporary"
  mv -f "$hold_temporary" "$hold_path"
  sync -f /artifacts

  expected_release_token="$(
    printf '%s\0%s\0%s\0%s' \
      fortgym.m1b-pre-readiness-oom-release-token/v1 \
      "$FORTGYM_RUN_ID" "$FORTGYM_CONTRACT_SHA256" "$FORTGYM_RUN_NONCE" \
      | sha256sum | awk '{print $1}'
  )"
  release_observed=0
  for _attempt in $(seq 1 600); do
    if [[ -f /artifacts/pre-readiness-oom-release ]]; then
      IFS= read -r observed_release_token \
        < /artifacts/pre-readiness-oom-release || true
      if [[ "$observed_release_token" != "$expected_release_token" ]]; then
        printf 'pre-readiness OOM release identity mismatch\n' >&2
        exit 66
      fi
      release_observed=1
      break
    fi
    sleep 1
  done
  if (( release_observed == 0 )); then
    printf 'pre-readiness OOM release timeout\n' >&2
    exit 70
  fi
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

capture_oom_counters_before_exit() {
  local launcher_status=$?
  if (( launcher_status == 137 )) && [[ "${FORTGYM_FAULT_PROFILE:-}" == oom_256m ]]; then
    local expected_ack observed_ack="" ack_received=0
    expected_ack="$(printf '%s\0%s\0%s\0%s' \
      fortgym.m1b-pre-readiness-oom-exit-ack/v1 \
      "$FORTGYM_RUN_ID" "$FORTGYM_CONTRACT_SHA256" "$FORTGYM_RUN_NONCE" \
      | sha256sum | awk '{print $1}')"
    # Keep PID 1 alive until the host has durably read kernel OOM counters.
    # The container's own report is never accepted as counter evidence.
    for _capture_attempt in $(seq 1 300); do
      if [[ -f /artifacts/pre-readiness-oom-exit-ack ]]; then
        IFS= read -r observed_ack < /artifacts/pre-readiness-oom-exit-ack || true
        [[ "$observed_ack" == "$expected_ack" ]] || exit 66
        ack_received=1
        break
      fi
      sleep 0.1
    done
    if (( ack_received == 0 )); then
      printf 'host OOM counter capture acknowledgement absent\n' >&2
      exit 70
    fi
  fi
  return "$launcher_status"
}

# Cover failures from load-save and the final wait as well as readiness loops.
trap capture_oom_counters_before_exit EXIT

exit_after_launcher_failure() {
  local launcher_status=0
  wait "$launcher_pid" || launcher_status=$?
  printf 'DFHack exited before %s readiness\n' "$1" >&2
  # Preserve signal exits (including 137) for independent fault classification.
  # A clean exit before readiness remains a startup failure, never success.
  if (( launcher_status == 0 )); then
    launcher_status=70
  fi
  exit "$launcher_status"
}

if [[ "${FORTGYM_TEST_SUPPRESS_RPC_READY:-0}" == 1 ]]; then
  printf 'synthetic RPC readiness suppression active\n' >&2
  write_startup_terminal rpc_readiness_timeout true
  terminate_launcher
  exit 70
fi

rpc_ready=0
for _attempt in $(seq 1 120); do
  if /opt/dwarf-fortress/dfhack-run lua "print('FORTGYM_RPC_READY')" \
    2>/dev/null | grep -q FORTGYM_RPC_READY; then
    rpc_ready=1
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    exit_after_launcher_failure RPC
  fi
  sleep 1
done
if (( rpc_ready == 0 )); then
  printf 'DFHack RPC readiness timeout\n' >&2
  write_startup_terminal rpc_readiness_timeout false
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
    exit_after_launcher_failure map
  fi
  sleep 1
done
if (( map_ready == 0 )); then
  printf 'DFHack map readiness timeout\n' >&2
  write_startup_terminal map_readiness_timeout false
  terminate_launcher
  exit 70
fi

if [[ -d /artifacts ]]; then
  printf '{"run_id":"%s","nonce":"%s","contract_sha256":"%s","dfhack_port":%s,"rpc_ready":true,"map_ready":true,"seed_tree_sha256":"%s","seed_world_sha256":"%s","image_manifest_sha256":"%s","image_config_sha256":"%s","image_archive_sha256":"%s"}\n' \
    "$FORTGYM_RUN_ID" "$FORTGYM_RUN_NONCE" "$FORTGYM_CONTRACT_SHA256" "$DFHACK_PORT" \
    "$seed_tree_sha256" "$seed_world_sha256" \
    "$FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256" "$FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256" \
    "$FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256" \
    > /artifacts/runtime_readiness.json
fi

wait "$launcher_pid"
