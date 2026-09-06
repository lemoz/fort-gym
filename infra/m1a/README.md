# M1a private feasibility probe

This directory implements the bounded Environment Layer M1a question without
changing production or lifting the production API's one-DF clamp.

The candidate image is assembled from the preserved, checksum-pinned DF
`0.47.05` and stock DFHack `0.47.05-r8` archives. It intentionally does not
apply `dfhack-core-autoboot.patch`: stock `0.47.05-r8` already starts the TCP
listener and reads `DFHACK_PORT`, while the repository patch is a second-stage
delta against a later experimental tree. The image is private and ephemeral.

Hard controls:

- distinct host-network loopback ports and server-side run nonces;
- fresh container and seed copy per run;
- provider-key and provider-route rejection in the DF container;
- `env -i`, scripted agent, memory off, and `usage.calls == 0` verification in
  the harness;
- CPU and memory bounds, no restart policy, dropped capabilities, and
  no-new-privileges;
- any non-loopback listener is a hard stop;
- no production endpoints or services are referenced;
- raw evidence stays private and checksum-backed.

`run_probe.sh isolation` creates two simultaneous forts, advances only the
first, and records both nonces, ports, populations, and ticks. `matrix` runs
fresh provider-free scripted harness processes at concurrency 1, 2, 4, and 8.
`e0` runs ten additional fresh, serial scripted attempts. The sizing ladder is
never pooled into the E0 cohort.

The ten-run cohort is named **E0-R feasibility**: conditional replay dispersion
under one seed, scripted policy, image, host class, and concurrency 1. It is not
general world variance, not a g8 result, and not sufficient by itself to size a
model comparison. A final scientific E0-R needs the frozen attempt ledger,
full state/checkpoint contract, replacement rules, and analysis contract
recorded in the M1a decision packet.

This probe does not implement M1b process supervision, native-RPC Lua
replacement, API changes, provider pinning, publication, or deployment.
