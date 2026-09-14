# Interrupted native controller recovery

Window `20260909w` resumes checkpoint 775 after window v's controller stopped
following a failed read of its owned exchange directory. The underlying read
failure remains unverified; v did not retain that command's output. Native modal
deferral and model-selected continuation were observed in v, but its final
segment did not complete and no new save was created.

Recovery validates original partial evidence rather than creating replacement
terminal files. The native load and teardown receipt, unchanged on-disk save,
initial agent state, complete trace prefix, final input receipt, and cumulative
usage journal must reconcile. Gameplay memory comes only from the verified save;
usage, original prompt metadata, and all previous losses are retained. A digest
binds the complete prior loss history. New segments also retain that history
before their first model request, covering interruption before the first trace
row.

The restart retains 957 accounted responses and 30,345,981 campaign tokens;
69,004 historical failed-delivery tokens bring all-attempt usage to 30,414,985.
Actual subscription charge is unreported, not zero. Six recorded losses have a
48,429-tick known lower bound. V's final uncommitted time and an earlier remainder
remain unknown. Saved progress stays 198,600 ticks, not the higher unsaved clock.

The next declared window permits two segments of 32 decisions. It keeps Astra
Medium, the existing native keyboard/screen condition and memory-contract prompt,
and the inherited 1,024-dispatch / 40-million-token cumulative limits. Its host
operator opts into at most three attempts for exactly the owned read-only
exchange probes, retaining failure diagnostics. Model calls and game inputs are
never retried by this repair. This infrastructure/save-cadence experiment is not
a matched gameplay or cross-model comparison.

Regression tests exercise complete partial-evidence recovery, repeated restarts,
unknown elapsed time, prompt and usage continuity, missing first-row history, and
altered source receipts. Native acceptance still requires a fresh load, actual
continued play, a verified new checkpoint, and teardown. Passing tests or
preflight alone does not establish year-two or fortress sustainability success.
