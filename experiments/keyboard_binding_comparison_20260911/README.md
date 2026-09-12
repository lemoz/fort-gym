# Matched displayed-key model comparison

Six fresh attempts, two each for GPT-6 Astra Medium, GPT-5.6 Sol Medium and
GPT-5.6 Terra Medium. The declaration fixes the same seed, native source/image,
120x40 screen-text observation, displayed-key bindings, prompt and resource caps.
Order is predeclared, not randomized. Save every 64 responses and compare all
attempts at decisions 64 and 128 before unequal-length continuation.

This is a preliminary repeated comparison, not a strong model ranking. Preserve
incomplete, rejected, infrastructure-failed and allowance-paused attempts in the
denominator. Stocks and sampled jobs are evidence, not production rates. A
human does not choose gameplay actions, rewrite memory or replay failed input.

The prior displayed-key Astra Year-Two campaign is historical context, not one
of these new replicates. All six fresh attempts use the same newer save/restart
implementation. The earlier native-key-name cohort also remains separate.
The standard-input-plus-shortcuts paired comparison remains a separate planned
condition; no shortcuts are silently included here.

Conditions and trials load through the existing native configuration parser.
The existing one-game local VM and pinned image are reused; no cloud VM or paid
API fallback is introduced. Every bounded attempt stops its VM and preserves
its original checkpoint, response receipts, trace and measured outcomes. Check
fresh account headroom and actual guest free space before each launch. Paid
subscription charges remain unreported, not zero. No reset or credit purchase.

The source plan is not an execution receipt. Launch and terminal results must be
separately recorded and published, with website playback of actual captured
screens and explicit action descriptions only.

## Local execution

The operator reuses the existing local runtime assets under
`fort_gym/artifacts/native-local-20260906/runtime-v2` and the frozen native
checkout named in `local_owner.py`. Those private game/runtime assets are not
part of the public repository. The existing image, seed, transport helper,
native source, CI result, VM configuration and seccomp file are checked before
launch. Commit and push this declaration before supplying its exact revision.

```sh
.venv/bin/python experiments/keyboard_binding_comparison_20260911/local_owner.py \
  --campaign-id bindings-comparison-20260911-sol-r1 \
  --declaration-revision COMMITTED_DECLARATION_SHA --preflight
```

Preflight reads account admission and local metadata without starting a VM or
calling a model. Remove `--preflight` to execute one bounded attempt. The owner
checks actual guest free space before creating the game container. It never
overwrites an existing attempt, buys credits, falls back to a paid API, deletes
historical volumes or grows the disk. The internal `/evidence/astra` folder name
is a legacy transport path for all models; campaign IDs and declared model
metadata identify the actual attempt.

After the owner exits and tears down the VM, run `terminal_review.py` with the
same campaign ID and declaration revision. This read-only audit reconciles
receipts, native key events, memory, elapsed time, usage and checkpoint files,
then writes a separate immutable review. It certifies a settled saved segment,
not a successful fortress or a model ranking. Infrastructure-failed or
pre-launch-paused attempts keep their original result and remain in the cohort;
they must not be rerun under the same identity or omitted because this audit
cannot certify them.
