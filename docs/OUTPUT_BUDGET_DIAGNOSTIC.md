# Exact-prompt output-budget diagnostic

Status: prepared, not run. No real model generation or native game is established
by this implementation. The active goal remains sustained autonomous gameplay and
cross-model evaluation, not success on this one diagnostic.

## Question and fixed comparison

The final long-v2 response used its 2,048 completion tokens entirely on reasoning
and returned no action. The [declared diagnostic](../experiments/diagnostics/local_llama_output_budget_v1.json)
replays that exact retained prompt once at 2,048 and once at 4,096 output tokens.
The same pinned Qwen3.5 9B weights, llama.cpp build, template, grammar, messages,
sampling and seed are retained. Every serialized request field except
`max_tokens` must match before any network call can occur.

This is one matched prompt, with one attempt at each allowance. It can show
whether the larger allowance returns a syntactically valid action on that prompt;
it cannot establish native legality, policy quality, sustainable production or
a model ranking. No action is executed, no game is loaded, and the old fortress
and its failure record remain unchanged.

## Inputs and execution

`scripts/campaign_output_replay.py` accepts a local plan, the authorized private
source file, a literal loopback model endpoint and a new private output directory.
It does not fetch from the test host, start a model server or create infrastructure.
The exact base-condition file and retained failure file are SHA-256 bound. The
baseline request must reproduce the retained request digest. Missing, mismatched
or incomplete source material stops before any network request.

At most two requests run sequentially, with a combined 30,000-accounted-token
ceiling and per-request prompt-plus-output ceilings. The original 600-second
generation read timeout is unchanged; it is an execution bound, not an estimate.
A fully accounted output-limit response permits the separately declared comparison
case. A transport, accounting, identity or malformed-action failure stops without
retry. No hosted provider or automatic WAIT is available through this path.

The caller must launch the existing verified temporary llama.cpp runtime and
independently verify teardown. The result does not claim either on the caller's
behalf. The runner retains each exact request, private response/events and spend
journal separately. Its summary contains action type/syntax, elapsed request time,
accounted usage and explicit completeness, not raw prompts, reasoning or coordinates.
Zero local model API charges do not imply zero electricity, hardware or host cost.

## Current boundary

The tool approval reviewer rejected reading/copying the private source from the
stopped test-host run, including a metadata-only inspection. No transfer or model
request occurred, and no alternate remote access path was attempted. The exact
replay remains unrun until that single project-artifact transfer is authorized.
The source is the failure file for `local-long-v2-qwen35-20260906-a`, segment two,
cursor 42. It belongs in the owning project's ignored local inference artifacts,
not Git, the public website or a hosted model service.

Synthetic regression tests exercise digest/cursor rejection, exact baseline
reconstruction, output-only request differences, accounted output stops, response
failure without retry, literal loopback restriction and missing-source behavior.
These tests do not substitute for the real comparison.

Validation: 14 replay tests and 134 combined replay/local-adapter/output-recovery
tests passed. Changed-file Ruff and targeted mypy pass. No paid model request,
temporary model server, remote game or VM was started for this preparation.
