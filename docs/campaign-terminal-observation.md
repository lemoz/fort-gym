# Terminal exchange observation

Window m completed its native decisions and checkpoint, but the outer owner's
exchange-directory read raised `subprocess.CalledProcessError` with exit 137.
The old handler caught only `RuntimeError`. The underlying cause of that command
failure is unverified; a stopped container's OOM flag cannot settle the cause of
an earlier child-process failure. The original failed operator record is retained.

`observe_container_output` now handles both error types and observation timeouts.
It performs a fresh state read and only returns terminal when the container has
an explicit exited/dead status, Running false, Restarting false and integer PID
zero. Unknown, inconsistent or live state propagates the original observation
error. Failed state inspection also retains the original error. No model call,
response publication or gameplay input is retried by this helper.

Before returning terminal, the owner must persist the original error and observed
state. Failed warning retention cannot become silent success. Terminal container
state is not native completion: the owner still reconciles the native result,
usage, checkpoint and teardown. A handled terminal read warning remains visible
in the owner evidence and must be preserved in any authored result.

The next private owner imports this tested helper rather than modifying or
restarting window m. Focused tests cover successful reads, both original error
types, observation timeout, live/ambiguous state, failed inspection and failed
warning retention. They do not claim that the historical exit-137 cause has been
reproduced or solved.
