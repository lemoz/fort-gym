# Portable runtime native acceptance

This separate setup identity imports the verified private runtime export into a
new bounded local Colima profile, builds the unchanged source context, and loads
both a native seed and an existing model checkpoint without advancing gameplay.
It does not relaunch or change any frozen comparison attempt. The original full
VM remains stopped and unchanged. One VM/game may run at a time, with mandatory
container and VM teardown and retained logs on failure.

The new VM uses the same checksum-bound cached guest distribution and existing
local tools, with 2 CPUs, 3 GiB RAM, an 8 GiB root disk and a 10 GiB data disk.
Private native outputs use project-owned external storage; only those outputs
are writable mounts. The exact seed/checkpoint mounts are read-only. No account,
home directory, Docker socket or model transcript directory is a game mount.

The original seccomp policy is retained for this bounded compatibility check,
not recommended as a general policy for unrelated engines. Record the actual
engine version and configuration. Do not weaken the policy to make a test pass.

The source context and exported image remain immutable. A failed native attempt
retains its identity and artifacts; do not overwrite it. Image IDs, native load
receipts and teardown observations belong in the follow-up result. Paused load
acceptance does not prove full owner/courier save-and-resume or autonomous play.
