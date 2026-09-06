# Local native runtime investigation

September 6, 2026. Status: **automatic native checkpoint recovery verified**.

## Latest result

Source `fad9d80c0a2e7aace8380b47b009db5edaf6bd2e` passed the automatic v3
checkpoint recovery fixture on isolated Colima 0.10.3 / Lima 2.2.0 tooling.
It saved cursor zero at year 30, tick 16801, stopped the first game process,
restored the exact checkpoint in a second process, and executed one fresh
20-tick WAIT. Both cleanup receipts and an independent recovery verifier passed;
the container and VM stopped. A real translated-process probe also confirmed
ownership detection when the executable link could not resolve.
See the [automatic recovery receipt](../experiments/evidence/local_native_automatic_recovery_20260906.json).

This provider-free fixture is not autonomous gameplay or year-two proof.
Synthetic usage is not model consumption; no final checkpoint followed the WAIT.
Global tools, old profiles and historical failure receipts remain unchanged.
The new toolchain's successful boot/reboot does not explain old startup failures.

The next experiment uses the [new local Qwen3.5 condition](../experiments/campaigns/local_native_qwen35_year_two_v1.json):
existing 9B quantized weights, optional thinking disabled, 4,096 output tokens,
and the unchanged digest-bound starting seed, not the fixture's post-WAIT state.
Its first autonomous segment started September 6 using the pinned local model
and an owned loopback-only reverse SSH tunnel into the isolated VM.
The running source remains frozen at `fad9d80c0`; the condition is published
separately. At 23:17 UTC, six model-selected WAIT actions had advanced 6,000
native ticks. Completion, final checkpoint and teardown are not yet claimed.
The changed seed, runtime and budgets are declared; this is
not a matched historical comparison. Year-two play and repeated model evaluation
remain open. No production deployment is claimed.

## Earlier incomplete harness attempt

The public harness at `43a53762c` now executed in a private derived image with
pinned Python 3.11 and retained provider-free dependencies. It captured a fresh
paused native seed, loaded that snapshot, and produced an independently verified
v3 campaign checkpoint at cursor zero. The automatic fixture stopped at first
process cleanup: its process scanner reported no owned PIDs while its listener
remained open. The outer container exited and both containers and the VM stopped.
See the [new harness execution evidence](../experiments/evidence/local_native_harness_checkpoint_20260906.json).

A follow-up diagnostic failed before container creation because the VM again
timed out at SSH readiness. Thus the successful boots below establish actual
compatibility, not reliable startup. The exact cause remains unresolved.
The scanner's independent-path correction has regression coverage but still
needs native confirmation. No restore phase, game action or model call occurred.
Private image, volume, saves and logs are retained; no historical evidence is
deleted or relabeled as passing recovery.

## Earlier successful load and reboot

A fresh isolated profile, `fort-gym-native-b`, loaded DF 0.47.05/DFHack
0.47.05-r8 successfully using the same retained image and the narrow
`personality(262144)` syscall allowance. It then shut down through the guest,
restarted, and automatically loaded a fresh container's fortress again. Both
loads were paused at year 30, tick 16801. The first driver's line-oriented JSON
parser missed successful readiness; an independent full-JSON probe verified it.
The corrected reboot driver completed automatically with exit code zero.

The [new versioned evidence](../experiments/evidence/local_native_load_reboot_20260906.json)
preserves that distinction. No campaign commands, model calls or checkpoints
occurred. Both test profiles and Hermes were observed stopped afterward. The
working profile retains about 1.8 GiB allocated within its 10 GiB virtual disk.
The old profile and its evidence remain unchanged. No global update or shared
network-state deletion was used. This configuration is working evidence, not a
controlled explanation of the first profile's failure.

Use guest-initiated `systemctl poweroff`, observe the owned profile stopped, then
run Colima lifecycle cleanup after stopping its containers. This shutdown path
has reboot proof; do not silently substitute the earlier failed restart route.

The next step after that reboot was to install the public campaign harness and
run the automatic v3 recovery fixture, with the partial result above. This seed starts
at a different native boundary from the previous shared-host snapshot; future
campaign conditions must declare that difference. Native loading alone does not
establish persistent campaign recovery, autonomous play or year-two progress.

## Earlier attempts (retained history)

The shared native host's free-space limit motivated a local development test.
The retained private M1b Linux/amd64 game image was checksum-verified and loaded
into a new, isolated Colima profile on the Mac. No cloud VM was created, no
provider was called, and no shared-host or production change was made.
The [versioned result](../experiments/evidence/local_native_compatibility_20260906.json)
records both attempts and their proof limits.

## What actually ran

The local VM had 2 CPUs, 3 GiB RAM and a 10 GiB virtual disk. Colima 0.8.1,
Lima 1.0.7, macOS 26.6.2 and Rosetta were observed. The first start reached
Linux SSH readiness and enabled Rosetta's binfmt handler. The game image's
identity matched the retained packet. Docker's active host context was not
changed. No SSH agent or home directory was shared. Colima added its standard
read-only image-cache mount alongside the empty read-only project share.

The game container had networking disabled, no published ports or host bind
mounts, all capabilities dropped, and no-new-privileges enabled. Its stock
DFHack launcher exited with `setarch` permission denied before RPC/map readiness.
The container exited 70, without an OOM kill. The first container and VM stopped.

A second attempt prepared a candidate syscall policy derived from the
[versioned Moby default](https://github.com/moby/moby/blob/v27.1.1/profiles/seccomp/default.json),
adding only `personality(262144)` while retaining default-deny behavior. The
existing VM never regained SSH readiness within the declared 180-second startup
bound. The local network helper reported a refused connection at its selected
guest SSH endpoint. The new container was **not created**, so the syscall change
has **no execution proof**. No privileged/unconfined fallback was run.

## Teardown and retained state

The second launcher is terminal. Independent checks observed the profile stopped,
its known host-agent PIDs and PID files absent, and the last SSH listener absent.
The unrelated Hermes profile remained stopped, and the Docker host context
remained `desktop-linux`. About 1.8 GiB of allocated local VM state was retained;
the virtual disk's maximum size is 10 GiB. Neither old data nor the failed test
container was deleted. Detailed logs and exact operator drivers remain in the
owning checkout's ignored `fort_gym/artifacts/native-local-20260906/` directory.

No new model charge or cloud reservation was incurred by these attempts. Local
hardware, energy, and application costs are not measured and are not reported as
zero. The standing cloud expiry and no-production-deploy boundary are unchanged.

## Decision after the earlier failures

The initial decision was to resolve the owned VM's SSH routing/startup failure,
then test the narrow syscall policy with the same retained image. Do not delete
shared Colima network state, prune profiles, or update global tooling as an
unexamined reset. [Lima documents the Rosetta route](https://lima-vm.io/docs/config/multi-arch/),
but that is not evidence this particular DFHack runtime works on it.

With native load now verified, this local route can run the automatic v3
checkpoint recovery fixture and a newly declared autonomous campaign. The
historical long-v2 tail must not be silently rolled back or reused as a clean
continuation. No new model-comparison row or year-two progress is claimed here.
