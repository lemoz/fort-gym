# PROVIDER-NET Linux helper and cgroup-BPF source

Status: checked-in M1b implementation source. It has not been built, installed,
loaded, or exercised on this macOS workstation. Passing the Python fake/static
tests is not the real PROVIDER-NET acceptance gate.

This package is the privileged half of
`fort_gym.bench.run.provider_network_isolation`. It has one policy: default
deny all IPv4/IPv6 connect and datagram-send operations, except TCP
`connect4` to the run's exact `127.0.0.1:<assigned DFHack port>`. Every hook
decision enters a pinned ring buffer. A nonzero kernel or userspace lost-event
counter fails validation.

The helper accepts only these shell-free vectors, in these exact orders:

```text
probe --bpf-object PATH --format json
prepare --bpf-object PATH --expected-helper-sha256 HEX --expected-bpf-object-sha256 HEX --cgroup PATH --pin-root PATH --identity-sha256 HEX --allow-connect4 127.0.0.1:PORT --negative-canary-poison IPV4:PORT --deny-connect6 --deny-sendmsg4 --deny-sendmsg6 --format json
enter --cgroup PATH --identity-sha256 HEX --require-python-policy loopback-port-only --guard-attestation PATH -- INNER_ARGV...
snapshot --cgroup PATH --pin-root PATH --identity-sha256 HEX --guard-attestation PATH --format json
inspect --cgroup PATH --pin-root PATH --identity-sha256 HEX --format json
cleanup --cgroup PATH --pin-root PATH --identity-sha256 HEX --format json
```

It never invokes a shell. `enter` recomputes the run/contract/nonce/endpoint
identity from the already-sanitized child environment, updates the privileged
pinned policy with the Python-evidence-path digest, joins the exact cgroup,
proves it is the sole member, and runs a fixed six-syscall negative canary from
inside that cgroup. The canary covers denied connect4 DNS/443/poison, connect6,
sendmsg4, and sendmsg6 without resolving a hostname or calling a provider. Any
result other than `EPERM`/`EACCES` fails before the harness. It then drops
groups/UID/GID and ambient privilege, sets `no_new_privs`, writes the bounded
guard attestation as the unprivileged caller, and only then calls `execve` on
the canonical inner worker vector. The outer isolated host must also deny
egress so a broken BPF policy cannot turn the canary into escaped traffic.

`prepare`, `inspect`, `snapshot`, and `cleanup` accept only one direct child of
the dedicated root-owned cgroup and bpffs roots compiled into the helper:

```text
/sys/fs/cgroup/fortgym-provider-net
/sys/fs/bpf/fortgym-provider-net
```

Cleanup refuses a nonempty cgroup, an identity mismatch, a partial resource
pair, unknown directory entries, or a symlink. It unpins only the fixed four
links and three maps under the exact identity-owned directory. This is the
foreign-process/foreign-resource safety boundary.

## Isolated-host build gate

Use a disposable, provider-free x86_64 Linux acceptance host with cgroup v2,
bpffs, clang/LLVM with the BPF target, libbpf headers/library, libelf, zlib, and
OpenSSL libcrypto already installed. Do not download dependencies during the
gate. Record `make toolchain-report` and the OS package manifest in the control
evidence before building.

From this directory:

```text
make static-contract
make clean all
make repro-check
```

`repro-check` builds twice with a fixed `SOURCE_DATE_EPOCH`, removes source-path
identity from both artifacts, strips them, and requires byte equality. Preserve
the emitted SHA-256 values. The controller must receive and independently
verify those exact helper and BPF-object digests.

Before a real probe, an administrator on that isolated host must create the two
dedicated roots as root-owned mode `0700` directories on their respective
mounted filesystems. Install the helper root-owned, setuid, and mode `4750`,
executable only by the dedicated Fort Gym service group. Install the BPF object
as a root-owned regular file with no group/world write bits. The helper verifies
both modes and hashes the helper plus object against the exact expected digests
immediately before attaching, closing the probe-to-prepare writable-artifact
swap. Never make the helper generally executable and never use it on a shared
host. `enter` rejects a real UID/GID of zero so the harness cannot run as root.

Then run the controller-driven `probe`; do not manually substitute JSON. A
valid probe opens and loads the exact BPF object and reports the SHA-256 of
`/proc/self/exe` and that object. `prepare` is the first attaching operation.
The real gate must retain the supervisor's port lease through snapshot,
validate the exact final report before terminalization, reconcile the exact
controller after an owner crash, run cleanup twice, and prove the foreign
canary unchanged.

The current workstation does not satisfy that gate: it is macOS, not isolated
x86_64 Linux, and no privileged hook was loaded here.
