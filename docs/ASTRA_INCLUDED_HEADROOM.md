# Explicit included-allowance operating window

Window `20260910aa` continues original checkpoint 903 for at most 32 decisions.
It uses the new `campaign_astra_keyboard_included_headroom_20260910.json`
condition. The only condition changes are its identity and the included-usage
admission threshold, from 90 to 98 percent. The previous condition and sealed
prelaunch-paused window z are not rewritten or rerun.

The 90-percent value was a harness headroom default, not a provider rate limit
or the owner's dollar cap. This explicitly versioned operating adjustment uses
some remaining included allowance within the authorized ongoing experiment.
It does not alter provider limits, purchase anything, consume a reset, use an
API key or switch to a local model. A fresh account read remains required before
each invocation; any reached provider limit, unknown/stale allowance or observed
usage at or above 98 percent stops admission. This is a pre-call check, not an
atomic account-wide reservation or a guarantee that one response cannot exhaust
the remaining allowance.

[Official pricing documentation](https://learn.chatgpt.com/docs/pricing)
describes shared usage and variable consumption across tasks. Prompt size and
token totals do not give an exact remaining-message count. Actual campaign
charges remain unreported; neither the threshold nor the response allowance is
a dollar charge or spending reservation. Existing project spending bounds remain.

Astra Medium, memory-replacement prompt, native keyboard/v2, native screen
text/v1 at 120x40, maximum 2000 requested ticks per action, v4 native saves,
direct native RPC and the private food measurements stay unchanged. The saved
agent, all losses and usage, inherited 1152-dispatch/40-million-token ceilings
and normal checkpoint semantics remain. There is no budget extension, rollback,
replay, strategy intervention or human gameplay rescue in this window.

The local runtime retains one VM, 2 CPUs, 3 GiB VM memory, a 1536 MiB container,
256 tasks, no game-container network and mandatory teardown. This is another
exploratory continuation, not an independent or matched comparison attempt.
The prior provider-free reload and fresh-trial fixture are acceptance evidence,
not additional model decisions or elapsed campaign time.
