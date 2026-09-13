# Shared native game serialization for batch jobs

The `/jobs` API uses a singleton `JobRegistry`. Previously, its concurrency cap
only applied inside each batch: two separately submitted DFHack batches could
enter their run callbacks at the same time, despite both reporting a parallelism
of one. Their game actions could consequently overlap on the shared fortress.

## Change

Every DFHack run callback now holds a registry-wide execution lock until the
callback returns or raises. The existing per-batch cap of one remains in place.
The execution lock is separate from the metadata lock, so job polling and mock
workers remain available while native work is running or waiting. An exception
or a missing run ID fails that batch and releases the shared lock; later batches
can still proceed. Each successful batch retains its own run IDs and completion
timestamp.

A waiting batch retains the existing `running` job status with no completed run
IDs. No new API fields, cancellation behavior, queue ordering guarantee, or
fairness policy are introduced.

## Scope and limitations

This protects callbacks submitted through the **same registry**, including
separate `/jobs` requests in the singleton API process. It is not a distributed
lease and does not coordinate separate server processes, independent registry
instances, direct `/runs` requests, CLI runs, or manual controls. Native campaign
ownership still requires the existing single-owner coordinator and operating
bounds. Do not mix these other entry points on a shared game based on this lock.

This isolated release candidate is based on
`617bf4ce51e8162f0f31a5b27c54a762fb2e4021`. It does not modify the frozen active
Astra runtime or sequence, deploy a server, publish website assets, create a VM,
or change model, prompt, budget, or observation conditions.

It inherits the earlier combined candidate's 32-recording website snapshot.
The newer public 35-recording assets remain on the separate website branch and
must be carried forward before any eventual combined promotion.

## Verification

The regression `test_distinct_dfhack_batches_do_not_overlap_shared_game` failed
before the source change: its second callback entered while the first callback
was deliberately blocked. All test callbacks are local fakes; these tests do not
connect to DFHack or call a model.

Coverage includes separate native batches, release after exceptions and missing
run IDs, concurrently available mock workers and metadata reads, all runs in
multi-run batches, repeated `start` calls, and two independent HTTP submissions
through FastAPI's in-process test client.

Focused check:

```sh
python -m pytest -q tests/test_job_native_serialization.py \
  tests/test_job_native_serialization_api.py tests/test_jobs.py tests/test_api_routes.py
ruff check fort_gym/bench/run/jobs.py tests/test_job_native_serialization.py \
  tests/test_job_native_serialization_api.py
```

The focused check passed 31 tests. The six new regression cases also passed 20
consecutive repetitions (120 case executions). Scoped Ruff and a scoped mypy
check (`--follow-imports=silent`) both passed. Full-tree Ruff reports nine
inherited findings, down from ten because the touched scheduler no longer has
an unused local; full-tree mypy retains the 465-error, 27-file baseline across
181 checked source files.

Full-suite results are recorded in the release review; a draft development PR
is not approval to merge or deploy this change.
