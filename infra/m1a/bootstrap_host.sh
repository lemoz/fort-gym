#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'bootstrap_host.sh must run as root\n' >&2
  exit 64
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  bzip2 \
  ca-certificates \
  docker.io \
  jq \
  netcat-openbsd \
  python3 \
  python3-pip \
  python3-venv \
  rsync \
  sysstat \
  util-linux \
  zstd
systemctl enable --now docker

install -d -m 0755 /opt/fortgym-m1a
printf 'FORTGYM_M1A_HOST_READY\n'
