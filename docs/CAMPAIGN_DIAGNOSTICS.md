# Campaign diagnostics

Read progress on the host from exported evidence or a host-readable evidence
mount. Do not run whole-trace Python parsing inside a live game container.
Read-only diagnostics consume memory and can disrupt the experiment.

```sh
python -m scripts.campaign_trace_summary /absolute/path/to/trace.jsonl --starting-step 711
```

The reader captures the initial file length and processes one JSON record at a
time. A partial trailing record is excluded; malformed complete records, step
gaps and records larger than 2 MiB fail. It reports committed trace progress,
not checkpoint verification. It sends no game input and makes no model call.
The CLI refuses to run in a Docker container. Container-internal evidence should
be exported by the existing owner; do not start an ad-hoc analysis process there.

## Window s: infrastructure failure, not a model-performance result

The retained s container exited with OOMKilled=true after 28 returned responses.
Twenty-seven decisions committed 5200 new unsaved ticks; the final five-key
action has no clock receipt or final calendar observation. The independently
verified save remains checkpoint 711 / 192600 ticks. Last observed population
was 12 with zero recorded deaths. Full game/container/VM teardown was verified.

A live diagnostic parsed the full trace inside the 1536 MiB game container.
Host reconstruction on macOS of that 101326551-byte trace used 844972032 bytes
peak RSS. The replacement streaming reader used 20643840 bytes on the same
trace. These host measurements identify an avoidable source of memory pressure,
not the exact Linux OOM victim or definitive root cause. This attempt is
potentially observer-influenced and must not become a clean Astra failure score.

The versioned [failure record](../experiments/evidence/astra_native_keyboard_oom_failure_20260908.json)
retains 842 responses / 26990171 campaign tokens / 27059175 all-attempt tokens.
Actual dollar charges remain unreported. Three earlier recorded losses total
29891 ticks; this new unsaved branch has not yet been restarted. Its missing
terminal clock evidence remains unknown, not zero.

The record is committed experiment evidence, **not yet website-integrated**.
The local campaign page still displays the preceding r record. The next delivery
step is a distinct website failure record and a restart path that retains s usage,
its three inherited losses and its unresolved final action. No new run, new save,
clock-fix native acceptance, PR merge or production deployment is implied.
