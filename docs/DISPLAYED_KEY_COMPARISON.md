# Displayed-key comparison reporting

The shared reader compares only explicitly indexed, reviewed public outcome
records against a source-pinned experiment declaration. It never discovers
private native artifacts, contacts a provider, controls a game, publishes a
website or declares a fortress successful. The existing historical cohorts and
their scored protocols remain unchanged.

```sh
.venv/bin/python -m scripts.campaign_displayed_key_comparison \
  --index experiments/evidence/keyboard_binding_comparison_20260911_index.json \
  --boundary 64
```

The index pins the cohort file, every condition/trial file and each selected
public result by SHA-256. Result references also include immutable repository
revisions for evidence links. All declared model/replicate slots remain in the
output. With no result reference, a slot is `no_published_result`, not failed,
unstarted or zero progress. Live owner status belongs to the separate observer.
The initial empty index is therefore not an experimental outcome.

## Publication contract

After an attempt settles, inspect its native result, original model receipts,
checkpoint and teardown. Produce an allowlisted public result with schema
`fortgym.public-displayed-key-result/v1`; do not copy a private audit wholesale.
Commit that immutable result before adding its file/digest/revision reference
under the campaign ID and decision boundary in the index. The reader checks
matching source/image/seed, exact condition/trial hashes, model/replicate,
Medium effort, decision limit and the absence of human gameplay rescue.
It is not a substitute for that native audit or the publisher's privacy review.

A result contains the declared matching fields, outcome `status`, `responses`,
`returned_tokens`, nullable `reported_charge_usd`, `terminal_audit_sha256`,
explicit native/VM teardown booleans and a nullable `checkpoint`. A checkpoint
contains its `next_step`, `sha256`, `saved_elapsed_ticks` and nullable observed
metrics: population, recorded deaths, food/drinks, completed beds/workshops/
farms, functional rooms and stone/wood stocks. A complete `saved` boundary
requires the exact declared response count, known returned tokens, checkpoint
and verified teardown. The source tests show the full record shape using
clearly synthetic fixtures, not gameplay evidence.

Keep budget pauses, infrastructure failures and gameplay collapses in the
denominator with their original classification and any earlier verified save.
Unknown usage stays unknown. A result at decision 128 never substitutes for
missing decision-64 evidence. `all_attempts_reported` includes failed attempts;
`all_saved_boundaries_reached` answers a different question. Neither implies a
strong model ranking, functioning fortress, production rate or self-sufficiency.

The report is suitable for the website's comparison table, but merely adding
or running this reader does not deploy a website or make missing outcomes real.
