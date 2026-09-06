#!/usr/bin/env bash
set -euo pipefail

repo_root="${FORTGYM_REPO_ROOT:-$(git rev-parse --show-toplevel)}"
image="${FORTGYM_M1A_IMAGE:-fortgym-df:m1a-stock-0.47.05-r8}"
venv="${FORTGYM_M1A_VENV:-/opt/fortgym-m1a/venv}"
client_root="${FORTGYM_M1A_CLIENT_ROOT:-/opt/fortgym-m1a/client}"
evidence_root="${FORTGYM_M1A_EVIDENCE_ROOT:-$repo_root/infra/m1a/_artifacts/evidence}"
batch_id="${FORTGYM_M1A_BATCH_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
port_base="${FORTGYM_M1A_PORT_BASE:-55000}"
container_memory="${FORTGYM_M1A_CONTAINER_MEMORY:-4g}"

declare -a active_containers=()
declare -a active_pids=()

cleanup_active() {
  local pid container
  for pid in "${active_pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for container in "${active_containers[@]:-}"; do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  active_pids=()
  active_containers=()
}
trap cleanup_active EXIT INT TERM

mapfile -t sibling_sets < <(
  for path in /sys/devices/system/cpu/cpu*/topology/thread_siblings_list; do
    cat "$path"
  done | sort -Vu
)
if (( ${#sibling_sets[@]} < 8 )); then
  mapfile -t online_cpus < <(lscpu -p=CPU,ONLINE | awk -F, '$1 !~ /^#/ && $2 == "Y" {print $1}')
  sibling_sets=()
  for ((i=0; i<${#online_cpus[@]}; i+=2)); do
    sibling_sets+=("${online_cpus[$i]},${online_cpus[$((i+1))]}")
  done
fi
if (( ${#sibling_sets[@]} < 8 )); then
  printf 'need at least eight CPU sibling slots, found %s\n' "${#sibling_sets[@]}" >&2
  exit 70
fi

df_cpu_for_slot() {
  local pair="${sibling_sets[$1]}"
  printf '%s\n' "${pair%%,*}"
}

harness_cpu_for_slot() {
  local pair="${sibling_sets[$1]}"
  if [[ "$pair" == *,* ]]; then
    printf '%s\n' "${pair##*,}"
  else
    printf '%s\n' "$pair"
  fi
}

rpc_lua() {
  local container="$1" port="$2" code="$3"
  docker exec -e "DFHACK_PORT=$port" "$container" \
    /opt/dwarf-fortress/dfhack-run lua "$code" \
    | sed -E $'s/\x1B\\[[0-9;]*[mK]//g' \
    | sed '/^[[:space:]]*$/d'
}

wait_ready() {
  local container="$1" port="$2" run_id="$3" deadline=$((SECONDS + 180)) output listener
  while (( SECONDS < deadline )); do
    if ! docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null | grep -qx true; then
      docker logs "$container" >&2 || true
      return 1
    fi
    listener="$(ss -Hlnpt "sport = :$port" 2>/dev/null || true)"
    if [[ "$listener" == *"0.0.0.0:$port"* || "$listener" == *"[::]:$port"* || "$listener" == *"*:$port"* ]]; then
      printf 'non-loopback listener is a hard stop: %s\n' "$listener" >&2
      return 1
    fi
    if [[ "$listener" == *"127.0.0.1:$port"* ]]; then
      output="$(rpc_lua "$container" "$port" \
        "local f=io.open('/run/fortgym/run-id'); local n=f and f:read('*a') or ''; if f then f:close() end; print(n:gsub('%s+$',''), dfhack.isMapLoaded() and 'MAP_LOADED' or 'MAP_NOT_LOADED', df.global.cur_year or -1, df.global.cur_year_tick or -1)" \
        2>/dev/null || true)"
      if [[ "$output" == *"$run_id"* && "$output" == *"MAP_LOADED"* ]]; then
        printf '%s\n' "$output"
        return 0
      fi
    fi
    sleep 1
  done
  docker logs "$container" >&2 || true
  return 1
}

start_container() {
  local stage_dir="$1" slot="$2" run_id="$3" port="$4"
  local container="fortgym-m1a-$run_id" df_cpu
  df_cpu="$(df_cpu_for_slot "$slot")"
  install -d -m 0777 "$stage_dir/$run_id/container"
  docker run --detach --tty \
    --name "$container" \
    --label fortgym.m1a=true \
    --label "fortgym.m1a.batch=$batch_id" \
    --network host \
    --cpuset-cpus "$df_cpu" \
    --memory "$container_memory" \
    --memory-swap "$container_memory" \
    --pids-limit 256 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --security-opt seccomp=unconfined \
    --restart no \
    --env "DFHACK_PORT=$port" \
    --env "FORTGYM_RUN_ID=$run_id" \
    --env FORTGYM_RUNTIME_SAVE=region3 \
    --volume "$stage_dir/$run_id/container:/artifacts" \
    "$image" >/dev/null
  active_containers+=("$container")
  if ! wait_ready "$container" "$port" "$run_id" \
    > "$stage_dir/$run_id/readiness.txt"; then
    docker logs "$container" \
      > "$stage_dir/$run_id/startup-failure.log" 2>&1 || true
    docker inspect --size "$container" \
      > "$stage_dir/$run_id/container-inspect.failure.json" 2>&1 || true
    ss -Hlnpt > "$stage_dir/$run_id/listeners.failure.txt" 2>&1 || true
    return 1
  fi
}

stop_containers() {
  local container
  for container in "${active_containers[@]:-}"; do
    docker logs "$container" > "$evidence_root/$batch_id/logs-$container.txt" 2>&1 || true
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  active_containers=()
}

run_harness_group() {
  local label="$1" count="$2"
  local stage_dir="$evidence_root/$batch_id/$label" slot run_id port harness_cpu pid rc=0
  install -d -m 0755 "$stage_dir"
  active_pids=()
  active_containers=()

  for ((slot=0; slot<count; slot++)); do
    run_id="${label}-r$(printf '%02d' $((slot + 1)))"
    port=$((port_base + slot + 1))
    start_container "$stage_dir" "$slot" "$run_id" "$port"
    docker inspect --size "fortgym-m1a-$run_id" \
      > "$stage_dir/$run_id/container-inspect.before.json"
  done

  for ((slot=0; slot<count; slot++)); do
    run_id="${label}-r$(printf '%02d' $((slot + 1)))"
    port=$((port_base + slot + 1))
    harness_cpu="$(harness_cpu_for_slot "$slot")"
    install -d -m 0755 "$stage_dir/$run_id/harness"
    (
      cd "$repo_root"
      env -i \
        "PATH=$venv/bin:/usr/bin:/bin" \
        HOME=/tmp/fortgym-m1a-home \
        LANG=C.UTF-8 \
        DFHACK_ENABLED=1 \
        DF_PROTO_ENABLED=1 \
        "DFROOT=$client_root" \
        DFHACK_HOST=127.0.0.1 \
        "DFHACK_PORT=$port" \
        FORT_GYM_MEMORY_WINDOW=0 \
        "ARTIFACTS_DIR=$stage_dir/$run_id/harness" \
        taskset -c "$harness_cpu" \
        "$venv/bin/fort-gym" experiment "$repo_root/infra/m1a/e0_replay.yaml"
    ) > "$stage_dir/$run_id/harness.log" 2>&1 &
    pid=$!
    active_pids+=("$pid")
    printf '%s\t%s\t%s\t%s\n' "$run_id" "$pid" "$port" "$harness_cpu" \
      >> "$stage_dir/harness-pids.tsv"
  done

  while :; do
    local running=0
    for pid in "${active_pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        running=1
      fi
    done
    {
      date -u +%Y-%m-%dT%H:%M:%SZ
      docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.BlockIO}}\t{{.PIDs}}' \
        "${active_containers[@]}" 2>&1 || true
      for container in "${active_containers[@]}"; do
        docker top "$container" -eo pid,ppid,pcpu,rss,vsz,etime,args 2>&1 || true
      done
      harness_processes="$(pgrep -d, -f "$venv/bin/fort-gym experiment" || true)"
      if [[ -n "$harness_processes" ]]; then
        ps -o pid=,ppid=,%cpu=,rss=,vsz=,etime=,command= \
          -p "$harness_processes" 2>&1 || true
      fi
    } >> "$stage_dir/resource-samples.txt"
    (( running == 0 )) && break
    sleep 5
  done

  for pid in "${active_pids[@]}"; do
    wait "$pid" || rc=1
  done
  active_pids=()

  for ((slot=0; slot<count; slot++)); do
    run_id="${label}-r$(printf '%02d' $((slot + 1)))"
    python3 "$repo_root/infra/m1a/summarize_run.py" \
      "$stage_dir/$run_id/harness" "$stage_dir/$run_id/run-summary.json" || rc=1
    docker inspect --size "fortgym-m1a-$run_id" \
      > "$stage_dir/$run_id/container-inspect.after.json" || rc=1
  done
  stop_containers
  return "$rc"
}

run_isolation() {
  local stage_dir="$evidence_root/$batch_id/isolation" run_id port slot
  install -d -m 0755 "$stage_dir"
  active_containers=()
  for slot in 0 1; do
    run_id="isolation-r$(printf '%02d' $((slot + 1)))"
    port=$((port_base + slot + 1))
    start_container "$stage_dir" "$slot" "$run_id" "$port"
  done

  {
    printf 'phase\trun_id\tport\tmap_loaded\tyear\ttick\tpopulation\tnonce\n'
    for slot in 0 1; do
      run_id="isolation-r$(printf '%02d' $((slot + 1)))"
      port=$((port_base + slot + 1))
      printf 'before\t%s\t%s\t' "$run_id" "$port"
      rpc_lua "fortgym-m1a-$run_id" "$port" \
        "local f=io.open('/run/fortgym/run-id'); local n=f:read('*a'); f:close(); local p=0; for _,u in ipairs(df.global.world.units.active) do if dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) then p=p+1 end end; print(dfhack.isMapLoaded() and 1 or 0, df.global.cur_year, df.global.cur_year_tick, p, (n:gsub('%s+$','')))" \
        | tail -n 1 | tr ' ' '\t'
    done
  } > "$stage_dir/side-by-side.tsv"

  install -d -m 0755 "$stage_dir/isolation-r01/harness"
  (
    cd "$repo_root"
    env -i \
      "PATH=$venv/bin:/usr/bin:/bin" \
      HOME=/tmp/fortgym-m1a-home \
      LANG=C.UTF-8 \
      DFHACK_ENABLED=1 \
      DF_PROTO_ENABLED=1 \
      "DFROOT=$client_root" \
      DFHACK_HOST=127.0.0.1 \
      "DFHACK_PORT=$((port_base + 1))" \
      FORT_GYM_MEMORY_WINDOW=0 \
      "ARTIFACTS_DIR=$stage_dir/isolation-r01/harness" \
      taskset -c "$(harness_cpu_for_slot 0)" \
      "$venv/bin/fort-gym" experiment "$repo_root/infra/m1a/e0_replay.yaml"
  ) > "$stage_dir/isolation-r01/harness.log" 2>&1
  python3 "$repo_root/infra/m1a/summarize_run.py" \
    "$stage_dir/isolation-r01/harness" \
    "$stage_dir/isolation-r01/run-summary.json"

  {
    for slot in 0 1; do
      run_id="isolation-r$(printf '%02d' $((slot + 1)))"
      port=$((port_base + slot + 1))
      printf 'after\t%s\t%s\t' "$run_id" "$port"
      rpc_lua "fortgym-m1a-$run_id" "$port" \
        "local f=io.open('/run/fortgym/run-id'); local n=f:read('*a'); f:close(); local p=0; for _,u in ipairs(df.global.world.units.active) do if dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) then p=p+1 end end; print(dfhack.isMapLoaded() and 1 or 0, df.global.cur_year, df.global.cur_year_tick, p, (n:gsub('%s+$','')))" \
        | tail -n 1 | tr ' ' '\t'
    done
  } >> "$stage_dir/side-by-side.tsv"
  ss -Hlnpt > "$stage_dir/listeners.txt"
  stop_containers
}

install -d -m 0755 "$evidence_root/$batch_id"
lscpu > "$evidence_root/$batch_id/lscpu.txt"
for path in /sys/devices/system/cpu/cpu*/topology/thread_siblings_list; do
  printf '%s\t' "$path"
  cat "$path"
done > "$evidence_root/$batch_id/thread-siblings.tsv"
docker image inspect "$image" > "$evidence_root/$batch_id/image-inspect.json"
git -C "$repo_root" status --short --branch > "$evidence_root/$batch_id/repo-status.txt"
git -C "$repo_root" rev-parse HEAD > "$evidence_root/$batch_id/repo-head.txt"

command="${1:-all}"
case "$command" in
  isolation)
    run_isolation
    ;;
  matrix)
    shift
    if (( $# == 0 )); then
      set -- 1 2 4 8
    fi
    for count in "$@"; do
      run_harness_group "matrix-n$count" "$count"
    done
    ;;
  single)
    shift
    if (( $# != 1 )) || [[ ! "$1" =~ ^[A-Za-z0-9._-]+$ ]]; then
      printf 'usage: %s single LABEL\n' "$0" >&2
      exit 64
    fi
    printf 'attempt_id\tstarted_utc\tport\tplanned_classification\n' \
      > "$evidence_root/$batch_id/single-attempt-plan.tsv"
    printf '%s\t%s\t%s\tengineering_replacement\n' \
      "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$((port_base + 1))" \
      >> "$evidence_root/$batch_id/single-attempt-plan.tsv"
    run_harness_group "$1" 1
    ;;
  e0)
    e0_port_base="$port_base"
    {
      printf 'attempt_id\tchronological_position\tport\tplanned_classification\n'
      for attempt in $(seq 1 10); do
        printf 'e0-a%02d\t%s\t%s\tprimary\n' \
          "$attempt" "$attempt" "$((e0_port_base + attempt))"
      done
    } > "$evidence_root/$batch_id/e0-attempt-plan.tsv"
    printf 'attempt_id\tstarted_utc\tended_utc\tclassification\n' \
      > "$evidence_root/$batch_id/e0-attempt-events.tsv"
    for attempt in $(seq 1 10); do
      attempt_id="e0-a$(printf '%02d' "$attempt")"
      port_base=$((e0_port_base + attempt - 1))
      started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      run_harness_group "$attempt_id" 1
      printf '%s\t%s\t%s\taccepted\n' \
        "$attempt_id" "$started_utc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >> "$evidence_root/$batch_id/e0-attempt-events.tsv"
    done
    port_base="$e0_port_base"
    ;;
  all)
    run_isolation
    for count in 1 2 4 8; do
      run_harness_group "matrix-n$count" "$count"
    done
    for attempt in $(seq 1 10); do
      run_harness_group "e0-a$(printf '%02d' "$attempt")" 1
    done
    ;;
  *)
    printf 'usage: %s {isolation|matrix [N...]|single LABEL|e0|all}\n' "$0" >&2
    exit 64
    ;;
esac

cleanup_active
trap - EXIT INT TERM
if docker ps -a --filter label=fortgym.m1a=true --format '{{.Names}}' | grep -q .; then
  printf 'M1a cleanup residue detected\n' >&2
  exit 1
fi
printf '%s\n' "$evidence_root/$batch_id"
