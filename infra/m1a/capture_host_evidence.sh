#!/usr/bin/env bash
set -euo pipefail

repo_root="${FORTGYM_REPO_ROOT:-$(git rev-parse --show-toplevel)}"
image="${FORTGYM_M1A_IMAGE:-fortgym-df:m1a-stock-0.47.05-r8}"
venv="${FORTGYM_M1A_VENV:-/opt/fortgym-m1a/venv}"
output="${1:?usage: capture_host_evidence.sh OUTPUT_DIRECTORY}"

install -d -m 0755 "$output"

{
  date -u +%Y-%m-%dT%H:%M:%SZ
  uname -a
  lsb_release -ds
  printf 'boot_id=' && cat /proc/sys/kernel/random/boot_id
  printf 'docker_server=' && docker version --format '{{.Server.Version}}'
  python3 --version
} > "$output/host-facts.txt"

lscpu > "$output/lscpu.txt"
free -m > "$output/memory-final.txt"
df -h / > "$output/disk-final.txt"
ss -Hlnpt > "$output/listeners-final.txt"
docker ps -a --no-trunc > "$output/docker-containers-final.txt"
docker image inspect "$image" > "$output/image-inspect-final.json"
docker history --no-trunc "$image" > "$output/image-history.txt"
dpkg-query -W -f='${binary:Package}\t${Version}\n' \
  | LC_ALL=C sort > "$output/host-packages.tsv"
"$venv/bin/pip" freeze | LC_ALL=C sort > "$output/python-packages.txt"

git -C "$repo_root" status --short --branch > "$output/repo-status-final.txt"
git -C "$repo_root" rev-parse HEAD > "$output/repo-head-final.txt"
sha256sum \
  "$repo_root/infra/m1a/Dockerfile" \
  "$repo_root/infra/m1a/entrypoint.sh" \
  "$repo_root/infra/m1a/run_probe.sh" \
  "$repo_root/infra/m1a/e0_replay.yaml" \
  "$repo_root/infra/m1a/summarize_run.py" \
  "$repo_root/infra/m1a/capture_host_evidence.sh" \
  > "$output/probe-code.sha256"

docker save "$image" | zstd -T0 -8 -o "$output/fortgym-df-m1a.tar.zst"
sha256sum "$output/fortgym-df-m1a.tar.zst" \
  > "$output/fortgym-df-m1a.tar.zst.sha256"
