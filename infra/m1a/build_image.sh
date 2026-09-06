#!/usr/bin/env bash
set -euo pipefail

repo_root="${FORTGYM_REPO_ROOT:-$(git rev-parse --show-toplevel)}"
image="${FORTGYM_M1A_IMAGE:-fortgym-df:m1a-stock-0.47.05-r8}"
inputs="$repo_root/infra/m1a/_inputs"
artifacts="$repo_root/infra/m1a/_artifacts"

df_sha=ac74a6dbb7d7d9621f430405080322ab50c35f6632352ff2ea923f6dc5affca3
dfhack_sha=2eab7ca38a25eb15e6b2f1005a44968d58fae53f618ea9e4a31e1cd74d31926f

test -f "$inputs/df_47_05_linux.tar.bz2"
test -f "$inputs/dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2"
test -f "$inputs/seed_region3_fresh/world.sav"
install -d -m 0755 "$artifacts"
printf '%s  %s\n' "$df_sha" "$inputs/df_47_05_linux.tar.bz2" | sha256sum -c -
printf '%s  %s\n' "$dfhack_sha" "$inputs/dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2" | sha256sum -c -

docker pull ubuntu:22.04
base_digest="$(docker image inspect ubuntu:22.04 --format '{{index .RepoDigests 0}}')"
test -n "$base_digest"

docker build --no-cache \
  --build-arg "BASE_IMAGE=$base_digest" \
  --build-arg "DF_ARCHIVE_SHA256=$df_sha" \
  --build-arg "DFHACK_ARCHIVE_SHA256=$dfhack_sha" \
  --label "org.opencontainers.image.revision=$(git -C "$repo_root" rev-parse HEAD)" \
  --tag "$image" \
  --file "$repo_root/infra/m1a/Dockerfile" \
  "$repo_root"

docker image inspect "$image" > "$artifacts/image-inspect.json"
printf '%s\n' "$base_digest" > "$artifacts/base-image-digest.txt"
docker image inspect "$image" --format '{{.Id}}'
