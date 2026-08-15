# Fable vs Sol paid-run GO/NO-GO decision packet

**Status:** DECISION-GRADE
**Prepared:** 2026-08-15 (all live values re-fetched this session; timestamps inline)
**Prepared on branch:** `claude/g7v5-truth-repair` (local-only; never pushed)
**Reviewed tip:** `ccfac2c9314662e675dcd1dd685f167c8158e530` — the branch tip read at
finalization. The commission tip was `153b98163`; it advanced by three parallel documentation
commits while this packet was being written (see "Concurrent work, disclosed" below).
**Scope:** whether to spend money on a fresh, exact Fable-5 vs GPT-5.6-Sol paired run of
`fort-eval-easy-p1-g7-v5` on the fixed `seed_region3_fresh` embark, and what must be true
before that spend is legitimate.

**Out of scope:** re-running, re-scoring, or re-interpreting the frozen G7-v3 Fable/Sol pair;
changing any measurement source, hook, manifest, or frozen evidence artifact. This packet
**adds** a decision record. It changes no gate, no constant, and no digest.

**Reading note on history.** Everything in this packet that describes 2026-07-19 through
2026-07-21 is reproduced as recorded at the time. Where the world has since moved (funding,
deployment, calendar risk), the change is written as a **dated annotation**, never as an edit
to the earlier record. Nothing historical was rewritten to produce this packet.

**Concurrent work, disclosed.** This packet was prepared while a parallel documentation pass
was committing to the same branch. Between commission (`153b98163`) and finalization, three
commits landed — `0fa8591fd` (record G7-v5 measurement calibration as performed),
`8a334dfcc` (drop the stale Attempt 28 plan from README), and `ccfac2c93` (record independent
review and refresh funding in the evidence index) — touching `CLAUDE.md`, `README.md`, five
`docs/*.md` files, `docs/decisions/2026-07-21-g7v5-calibration-independent-review.md`, and
`experiments/evidence/EVIDENCE_INDEX.json`. This packet **adds one file and changes nothing
else.** All eight §0 states were re-read against the finalized tip; the calibration bundle
(`f41f1a80…`, recomputed) and the lock constants (still `False` / `None`) are byte-unchanged
by that parallel work. Where the refreshed index and this packet describe the same live
numbers, they agree.

---

## §0 — Eight-state table

Each row is one independently verifiable state of the system. "Basis" is what was actually
read; "Verified" is when it was read **this session** unless the row is explicitly historical.

| # | State | Value on 2026-08-15 | Basis | Verified (UTC) |
|---|---|---|---|---|
| 1 | **Local source** | Branch `claude/g7v5-truth-repair`, tip `ccfac2c93`. Local-only (no upstream configured). 36 commits ahead of `origin/main` (`82ee3e078`, unchanged since 2026-07-13), 0 behind. Contains `origin/codex/remove-g7-duration-gate` (`47c035f11`) as a direct ancestor → a push would be a clean fast-forward, zero conflicts. Working tree clean apart from this packet. | `git rev-parse`, `git rev-list --left-right --count`, `git merge-base --is-ancestor`, `git status --porcelain` in the worktree | 2026-08-15 17:19–17:21 |
| 2 | **Review** | Two independent reviews returned **APPROVE** on 2026-07-21: scientific-validity/provenance (3 advisories, 0 blocking) and unlock-semantics (12-step runbook, Appendix D). Reviewer of record as stated in that review: *"Claude Opus 4.8 — independent scientific-validity & provenance reviewer, 2026-07-21, non-authoring"*. Earlier completeness objections were raised against a **stale** packet and are resolved. **But** the **bundle** on disk still carries `review_status: "pending"`, `reviewer: ""` — approval has not been *stamped*, because stamping requires Chris to designate the reviewer identity string and run the `--approve` rebuild. (The evidence **index** now records `approved-pending-unlock` with that reviewer string on all three calibration entries, via `ccfac2c93`; the index is documentary and no gate reads it. The gate reads the bundle, and the bundle still says `pending`.) | `experiments/evidence/fort_eval_easy_p1_g7_v5_live_calibration.json` (fields read directly, re-read at the finalized tip); `experiments/evidence/EVIDENCE_INDEX.json`; `docs/decisions/2026-07-21-g7v5-calibration-independent-review.md` (source of the verbatim runbook in Appendix D) | 2026-08-15 17:19 / 17:23 |
| 3 | **Deployment** | VM `34.41.155.134`: `/opt/fort-gym` HEAD = `47c035f117f2a8663c2b276160d546c49f47a5da` (detached), i.e. the research branch tip — **not** the reviewed branch tip. `fort-gym-api` and `dfhack-headless` both `active`; API active since 2026-07-17 17:00:18 UTC. The reviewed measurement code (13 commits past `47c035f`) is **not deployed**. | read-only `ssh`: `git -C /opt/fort-gym rev-parse HEAD`, `systemctl is-active`, `systemctl show -p ActiveEnterTimestamp` | 2026-08-15 17:19:50 / 17:21:15 |
| 4 | **Runtime** | Calibration scratch checkout `/var/tmp/fort-gym-calib-g7v5` still present, still pinned at `a8de39d03da48da32110776bf84ddfcbcb2ccefc`, 408 MB, all 10 evidence files present on the VM. Directory mtime 2026-07-21 → **25 days old**. Host `tmpfiles.d` carries a `/var/tmp … 30d` age rule but it is **commented out**, and `systemd-tmpfiles-clean.timer` is `static` (not enabled) — so the classic ~5-day fuse is a *conservative* assumption, not an observed live countdown. Treat it as a fuse anyway: nothing guarantees the box, the disk, or the policy stays as-is. | read-only `ssh`: `ls -ld`, `git rev-parse`, `du -sh`, `ls experiments/evidence/`, `grep /usr/lib/tmpfiles.d`, `systemctl is-enabled` | 2026-08-15 17:21:03 / 17:21:15 |
| 5 | **Artifact** | Calibration bundle `experiments/evidence/fort_eval_easy_p1_g7_v5_live_calibration.json` present in-repo, sha256 **recomputed this session** = `f41f1a80b63cdc0e323cf57dc914a28fc613cf183905e29828ede298baf59598` (matches the recorded digest). All three scenario traces + summaries + `p1_g7_v5_measurement_regressions.xml` present. Required regression node-ID set = **33**, counted from source. On the VM, 1298 historical run-artifact directories under `/opt/fort-gym/fort_gym/artifacts/`, including both frozen G7-v3 runs. | `shasum -a 256`; parse of `P1_CALIBRATION_REQUIRED_REGRESSION_TESTS` in `fort_gym/bench/eval/fort_eval_easy_p1.py`; read-only `ssh ls` | 2026-08-15 17:19–17:21 |
| 6 | **Eligibility** | **Locked.** `P1_MEASUREMENT_CALIBRATION_COMPLETE = False` and `P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str \| None = None` at `fort_gym/bench/eval/fort_eval_easy_p1.py:37-38`. While these hold, `validate_p1_declaration` refuses a real `MODEL_ARMS` arm, so **no paid v5 run can be launched at all** — through the CLI or the API. All three calibration runs are `task_verdict: "unknown"`, `public_eligibility: "ineligible"` (calibration), by design. | `sed -n '37,38p'` on the constants; `p1_task_verdict` at `fort_eval_easy_p1.py:899`; the three `*_summary.json` files | 2026-08-15 17:19 |
| 7 | **Publication** | Manifest `experiments/fort_eval_easy_p1_g7_v5.yaml` is `status: calibration`, `publication.calibration_results_public: false`, `comparability.pair_comparison_enabled: false` with reason *"calibration has one run per variant; no replicated claim is valid"*. Nothing from v5 is publishable today. The frozen G7-v3 pair remains **descriptive-only**: Fable eligible, Sol INELIGIBLE (cached-token requirement unsatisfied) → not one ranked table, not one aggregate mean. | manifest read (read-only); `EVIDENCE_INDEX.json` entries `g7v3-fable-2026-07`, `g7v3-gpt56-sol-2026-07` | 2026-08-15 17:19 |
| 8 | **Funding + approval** | **Not funded.** OpenRouter account credits remaining **$23.297755592**; the key in `~/.zshenv` has limit **$50.00** with **$28.188624357** remaining. Effective spendable ceiling is the smaller of the two = **$23.30**, against a historical pair cost of **$92.693946** (**$120.502129** at +30% margin). No Chris approval exists for (a) reviewer identity, (b) constant flip, (c) funding, (d) launch, (e) deploy-vs-scratch. | live `GET /api/v1/credits` and `GET /api/v1/key` (key value never printed) | 2026-08-15 17:19:45 |

---

## §1 — Decision summary

### Recommendation: **NO-GO**

Two independent hard gates are open, and either alone is sufficient to block:

1. **Funding.** The spendable ceiling is **$23.30**. The pair costs **$92.693946** at the
   historical figure. We can fund **25.1%** of the run. A paid pair launched today would
   run out of money mid-flight, which does not produce a cheap partial result — it produces
   an **invalid** result, because a truncated arm cannot satisfy the manifest's evidence
   requirements and the pair loses comparability. Spending $23 to guarantee an unusable
   artifact is strictly worse than spending nothing.

2. **Unlock not executed.** `P1_MEASUREMENT_CALIBRATION_COMPLETE` is still `False`. This is
   not a formality — it is the mechanical gate. `validate_p1_declaration` raises for a real
   model arm while the constant is `False`, so both the CLI (`fort-gym experiment`) and the
   API (`POST /runs`) will reject a v5 paid launch with a `400` before a single token is
   billed. **Even fully funded, today's launch cannot start.**

Note the ordering property that makes this comfortable rather than alarming: the system
**fails closed**. There is no configuration in which we accidentally spend money on an
unvalidated v5 run. The lock is doing its job.

### What is *not* blocking

The science is in good shape. The calibration campaign did what it was built to do, the
verdict-truthfulness bug is fixed, and the review came back APPROVE on both axes. This is a
NO-GO on **money and one un-executed flip**, not a NO-GO on validity.

- **Verdict fix landed.** `p1_task_verdict` now returns the **validity-gated** `g7.status`
  (commit `557e5d6fb`). Live-confirmed: `task_verdict = "unknown"` in all three calibration
  runs, while `gameplay_outcome` stayed visible (`pass` for the owned-layout scenario,
  `fail` for the two single-step scenarios). The gate no longer launders a gameplay pass
  into a task pass when provenance is unknown.
- **`usage.calls == 0 → evidence_ok = False → validity/provenance UNKNOWN` is correct
  behavior, by design, and must not be "fixed."** The calibration campaign was
  **provider-free** (`dfhack-governed-scripted`). It made zero model calls, so it has zero
  provenance evidence, so it reports UNKNOWN. The index says this in terms worth repeating:
  *do not weaken `evidence_ok` to force a pass.* Calibration completeness is judged
  separately by `p1_measurement_calibration_is_complete`, which does not require
  validity/provenance pass.

### GO-blockers checklist

| # | Blocker | State | Who clears it |
|---|---|---|---|
| B1 | Reviewer identity designated + bundle rebuilt with `--approve` (`review_status` still `pending`, `reviewer` still empty) | **OPEN** | Chris (§7a) |
| B2 | `P1_MEASUREMENT_CALIBRATION_COMPLETE` flipped to `True` + evidence sha256 constant set, per Appendix D | **OPEN** | Chris (§7b) |
| B3 | Funding ≥ pair estimate + margin ($120.502129), on both account credits **and** key limit | **OPEN** — short **$97.204374** on credits | Chris (§7d) |
| B4 | Explicit approval to spend on the paid pair | **OPEN** | Chris (§7e) |
| B5 | Execution host decided: deploy reviewed tip to prod, or scratch-checkout as calibration did | **OPEN** | Chris (§7f) |
| B6 | Zero active runs at launch time (preflight) | not yet checked at launch time | operator, immediately pre-launch |
| B7 | v5 provider preflight re-run and passing **before** the paid launch | **OPEN** | operator, after B1–B5 |
| — | Independent scientific-validity review | **CLEAR** (APPROVE, 0 blocking) | — |
| — | Independent unlock-semantics review | **CLEAR** (APPROVE, 12-step runbook) | — |
| — | Verdict truthfulness (`p1_task_verdict`) | **CLEAR** (`557e5d6fb`, live-confirmed ×3) | — |
| — | Measurement regression suite | **CLEAR** (33/33 required node IDs green) | — |
| — | Seed attestation identity across calibration runs | **CLEAR** (identical, `9c923f9e…`) | — |

---

## §2 — Costs and funding

### 2a — Live pricing (fetched 2026-08-15 17:20:07 UTC, `GET /api/v1/models`)

USD per token, as returned by OpenRouter. Per-million figures are derived for readability.

| Arm | OpenRouter model | Prompt | Completion | Cache read | Cache write | Context |
|---|---|---|---|---|---|---|
| `dfhack-governed-llm-fable5` | `anthropic/claude-fable-5` | `0.00001` ($10.00/M) | `0.00005` ($50.00/M) | `0.000001` ($1.00/M) | `0.0000125` ($12.50/M); 1h `0.00002` | 1,000,000 |
| `dfhack-governed-llm-gpt56-sol` | `openai/gpt-5.6-sol` | `0.000005` ($5.00/M) | `0.00003` ($30.00/M) | `0.0000005` ($0.50/M) | `0.00000625` ($6.25/M) | 1,050,000 |
| `dfhack-governed-llm-gpt56-sol` **≥272K prompt tokens** | `openai/gpt-5.6-sol` (override tier) | `0.00001` ($10.00/M) | `0.000045` ($45.00/M) | `0.000001` ($1.00/M) | `0.0000125` ($12.50/M) | — |

**Pricing is unchanged from the last recorded snapshot.** Two notes on the Sol long-context tier,
stated precisely because the packet is a spending document:

- The override triggers at `min_prompt_tokens: 272000` and it is a **step**, not a ramp — the
  moment a request's prompt crosses 272K tokens, that request bills at the higher tier
  entirely.
- On re-fetch, the Sol prompt price **exactly doubles** across the tier ($5.00 → $10.00/M),
  while the completion price rises **1.5×** ($30.00 → $45.00/M) and cache read/write double.
  The shorthand "doubles past 272K" holds for prompt and cache; completion is 1.5×. Above
  272K, Sol's prompt price equals Fable's, and Sol's completion price is 90% of Fable's — the
  cost advantage Sol enjoys in short context largely evaporates in long context.
- G7-v5 runs 200 steps with memory off, so per-request prompts are not expected to approach
  272K. The tier is documented because a runaway observation payload is exactly the kind of
  thing that quietly triples a bill, and the run has **no expenditure cap**
  (`cost_and_kill.expenditure_cap.enabled: false`, `per_run_usd: null`).

### 2b — Live credits and key (fetched 2026-08-15 17:19:45 UTC)

Key value never printed; sourced from `~/.zshenv` into the request header only.

| Quantity | Value |
|---|---|
| Account `total_credits` | `3025` |
| Account `total_usage` | `3001.702244408` |
| **Account credits remaining** | **`23.297755592`** (≈ $23.30) |
| Key label | `sk-or-v1-598…2a2` |
| Key limit | `50` |
| Key usage this cycle | `21.811375643` |
| **Key limit remaining** | **`28.188624357`** (≈ $28.19) |
| Key `usage_daily` / `usage_weekly` / `usage_monthly` | `0` / `0` / `0.049571403` |
| Free tier | `false` |

**Effective spendable ceiling = min(credits, key remaining) = $23.297755592.** Account credits
bind first: even if the key limit were raised to $500, the account has $23.30 of purchasing
power. **Both** dials must move (§7d).

> **Annotation, 2026-08-15:** these values supersede — but do not overwrite — the
> `funding_state` block as recorded in `EVIDENCE_INDEX.json` on 2026-07-19, which described a
> `$10` key limit with `$2.006599125` remaining. The key limit has since been raised to `$50`.
> That index block was independently refreshed on this branch by the parallel documentation
> pass (`ccfac2c93`) and now carries `verified_at: 2026-08-15` with
> `previous_verified_at: 2026-07-19` preserved; its figures ($23.30 account, $28.19 key,
> account is the binding constraint) **agree with the values fetched here**, which were
> obtained independently from the live API. The conclusion recorded on 2026-07-19 ("NOT safely
> funded… purchasing credits or raising the key limit is a HARD GATE requiring Chris's
> separate explicit approval") is **still correct on 2026-08-15**, for the same reason and by
> a wider margin than the raised key limit alone suggests.

### 2c — Pair estimate, margin, and the gap

**Basis of the estimate.** `$92.693946` is not a model; it is the **observed sum of the frozen
G7-v3 pair** — Fable `$56.14648677` + Sol `$36.54745875` — both 200-step runs on the same
`seed_region3_fresh` embark under the same 200-step / 2500-ticks-per-step budget. That is the
best available anchor. It is also an anchor with known bias in both directions:

- *Possibly low:* G7-v5's `governed_structured_state_v3_owned_layout` observation profile is
  richer than v3's, so per-step prompts are plausibly larger. Both arms request
  `reasoning_effort: max` and `max_completion_tokens: 128000`. A run that plays *better*
  costs *more*, because it survives to step 200 and keeps thinking.
- *Possibly high:* both arms use prompt caching (Fable explicit ephemeral, Sol automatic),
  and cache reads are 10× cheaper than fresh prompt tokens on both arms.

Neither correction is quantified, which is exactly why the +30% margin exists.

| Line | Amount (USD) |
|---|---|
| Historical pair (Fable `$56.14648677` + Sol `$36.54745875`) | **`92.693946`** |
| +30% margin | **`120.502129`** |
| Live account credits remaining | `23.297755592` |
| **Gap: credits → pair estimate** | **`69.396190`** |
| **Gap: credits → pair + 30%** | **`97.204374`** |
| Live key limit remaining | `28.188624357` |
| Gap: key → pair estimate | `64.505322` |
| Gap: key → pair + 30% | `92.313506` |
| Share of pair estimate currently funded | **25.1%** |
| Share of pair + 30% currently funded | **19.3%** |

At the observed ~$23/day account burn, current credits are roughly **one day** of runway —
before any fort-gym spend at all.

**Burn trend (account credits remaining, as recorded):**

| Date | Remaining (USD) | Event | Implied burn |
|---|---|---|---|
| 2026-07-19 | `72.37` | first funding snapshot in the evidence index | — |
| 2026-07-20 | `54.55` | | ≈ $17.82/day |
| 2026-07-21 | `14.99` | calibration campaign day | ≈ $39.56/day |
| 2026-08-11 | `15.41` | **+$850 topped up** in the interval | ≈ $40/day sustained |
| 2026-08-15 | `23.30` | **+$100 topped up** in the interval | ≈ $23/day sustained |

> **⚠ The burn is not fort-gym's.** Fort-gym has made **zero** paid calls since the frozen
> G7-v3 pair — the entire 2026-07-21 calibration campaign was provider-free
> (`usage.calls == 0`). The ~$23–40/day is a **different, non-fort-gym key on the same
> OpenRouter account**. Three consequences that matter for this decision:
> 1. **$850 was topped up and consumed** between 07-21 and 08-11 without funding anything in
>    this project. Topping up "enough for the pair" does not reserve it for the pair.
> 2. **Any funding decision has a shelf life of about a day.** Credits added on Monday are
>    gone by Wednesday unless the pair launches immediately or the spend is ring-fenced.
> 3. Therefore §7d should be read as *fund **and** launch within the same window*, or
>    *ring-fence first* — e.g. a dedicated key with its own limit, so the pair's money cannot
>    be drained by the other consumer.

---

## §3 — Launch plan (for execution **only after** every §7 gate clears)

### Sequencing: strictly sequential, Fable first

Fable's arm runs to completion and is verified **before** Sol's arm is created. Reasons:

1. **Shared-resource reality.** One `dfhack-headless` instance, one seed save, one runtime
   save (`preserve_save: false`, `seed_save: seed_region3_fresh`, `runtime_save: region1`).
   Concurrent runs would contend for the same DF process and the same save slot. This is not
   a performance preference; it is a correctness requirement.
2. **Budget containment.** If Fable's arm produces an invalid or ineligible result, we learn
   it for ~$56 instead of ~$93. With no expenditure cap configured, the sequential gate *is*
   the cost control.
3. **Blast radius.** A mid-run infrastructure abort on arm 1 is recoverable
   (`infrastructure_abort_is_policy_failure: false`); an abort that corrupts arm 2's starting
   state while arm 1 is mid-flight is not cleanly diagnosable.

### Execution host: two options, Chris chooses (§7f)

**Option A — deploy the reviewed tip to production `/opt/fort-gym`.**

- *For:* one canonical deployment; the API's registry, share-link, and artifact paths all work
  the way they do for every other recorded run; artifacts land in
  `/opt/fort-gym/fort_gym/artifacts/<run_id>/` alongside the 1298 existing runs, where the
  frozen G7-v3 pair already lives.
- *Against:* `/opt/fort-gym` is currently at `47c035f` and has been stable since
  2026-07-17. Deploying moves prod 13 commits forward, including the measurement changes.
  This is a **gated** action — it changes the state of a live service and must not happen as
  a side effect of launching a run.
- *Requires:* explicit approval (§7f), a recorded pre-deploy SHA (`47c035f117f2a8663c2b276160d546c49f47a5da`),
  a service restart, and a post-deploy re-verification that
  `p1_measurement_calibration_is_complete()` is `True` on that host.

**Option B — scratch checkout, exactly as the calibration campaign ran.**

- *For:* prod is untouched. This is the **proven** path — all three calibration runs executed
  from `/var/tmp/fort-gym-calib-g7v5`, and we know why: the home directory is `0750`, which
  blocks dfhack-as-`ubuntu`, and `/opt` is blocked by the harness. That constraint has not
  changed.
- *Against:* artifacts land outside the canonical artifact root and must be deliberately
  rescued into the repo (the same rescue that is currently on a fuse, §7 non-blocking). The
  scratch tree is not what the API serves.
- *Requires:* a **fresh** checkout at the reviewed tip. Do **not** reuse
  `/var/tmp/fort-gym-calib-g7v5` — it is pinned to `a8de39d03` and still holds the
  calibration evidence we have not yet rescued. Overwriting it destroys unreplaceable
  artifacts.

**Recommendation if forced to choose:** Option B for the run itself (proven, prod-safe),
with the reviewed tip deployed to prod separately and deliberately afterwards, once the paid
artifacts are safely in the repo.

### Run identity

Run IDs are **server-assigned** (`uuid.uuid4().hex`, `fort_gym/bench/run/storage.py:307`) —
they cannot be chosen. They are immutable once created. **Record both IDs the instant each
run is created**, before anything else: they are the only handle on the artifacts, and the
frozen pair's IDs (`a55b2c2c…`, `cb997bee…`) are exactly this shape.

Each new run must be appended to `EVIDENCE_INDEX.json` as a **new** entry. The index is
append-only; existing terminal artifacts are never rewritten.

### Preflight sequence (all must pass, in order)

1. **Zero active runs.** Query the registry and confirm no run is `running`/`pending`/`paused`.
   Two concurrent dfhack runs corrupt each other's save state.
2. **Unlock verified on the execution host.** `p1_measurement_calibration_is_complete()`
   returns `True` *on the host that will run it*. Per Appendix D step 10, this returns `False`
   on the Mac (no `generated/` dir → remote proto digest is `None`); that is expected off-VM
   and is **not** a failure. It must be `True` on the run host.
3. **Proto runtime digest matches** `9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f`.
4. **Seed attestation eligible** and world sha256
   `070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d`.
5. **v5 provider preflight run and passing — this is mandatory and must precede launch.**
   The manifest declares
   `provider_preflight_evidence: experiments/evidence/fort_eval_easy_p1_provider_preflight_20260712.json`
   with `provider_preflight_inherits_from: fort-eval-easy-p1-g7-v3`. That file is dated
   **2026-07-12** and was taken against **G7-v3**. It records `resolved_model` values that are
   now 34 days stale (`openai/gpt-5.6-sol-20260709`, `anthropic/claude-5-fable-20260609`) and
   routing that may have changed (Fable resolved via **Amazon Bedrock**). Its `cache_verified:
   true` for both arms is the *only* evidence standing between us and repeating the Sol
   cached-token ineligibility that made the entire G7-v3 pair unpublishable. **Re-run it under
   v5 and confirm `cache_verified: true` for both arms before spending $93.** A fresh
   preflight costs cents; skipping it risks the whole pair.
6. **Both arms' `provider_model_id` recorded.** The manifest sets
   `provider_model_id: resolved_at_run` for both; the resolved value is part of per-arm
   identity under `comparability.model_arm_identity.per_arm_identity_fields` and must be
   captured.
7. **`usage_logging_required: true`** — confirm usage logging is on. Without it the run
   cannot establish provenance and produces an ineligible artifact at full price.

---

## §4 — Stop conditions

The manifest's declared `cost_and_kill.stop_on` list is authoritative. Stop the run
immediately, do not retry blind, and record the terminal reason on:

- `provenance_violation`
- `rollback_unverified`
- `contamination_signal`
- `missing_required_evidence_after_retry_budget`
- `declared_step_or_tick_ceiling` (200 steps / 2500 ticks per step / 500,000 ticks)

Operational stop conditions added for this specific spend:

| Trigger | Action |
|---|---|
| Fable arm ends anything other than valid + eligible | **Do not launch Sol.** Diagnose first. The pair is worthless if arm 1 is unusable, and Sol's ~$37 buys nothing. |
| Cumulative spend crosses **$120.502129** (pair + 30%) | Stop. This is the approved envelope; there is no configured `expenditure_cap`, so the operator **is** the cap. |
| Either arm's cache hit rate collapses vs. the fresh preflight | Stop and investigate before continuing. Cache behavior is a cost diagnostic (`cache_hit_rate_is_cost_diagnostic: true`) and, for Sol, the historical eligibility failure mode. |
| Any request crosses 272K prompt tokens on Sol | Flag immediately — cost per token steps up (§2a) and the estimate no longer holds. |
| Infrastructure abort (dfhack crash, VM issue) | Not a policy failure (`infrastructure_abort_is_policy_failure: false`). Record it, restore, and **do not** silently re-roll the arm without recording that the first attempt happened. |
| A dfhack-headless restart appears necessary | **Chris-approved only.** Seven restarts occurred across this lifecycle, every one of them approved. Keep that record perfect. |
| Account credits fall below the remaining-run estimate mid-flight | Stop. A truncated arm is an invalid arm; better to lose the partial than to also lose the ability to diagnose it. |

---

## §5 — Publication plan

**A v5 result is publishable only if BOTH conditions hold, independently:**

1. **Validity + provenance pass** — `evidence_ok` true, `usage.calls > 0` with complete usage
   logging, no contamination signal, declared condition and arm recorded.
2. **Eligibility** — `public_eligibility: eligible`. This is a *separate* gate.
   `validity_and_outcome_separate: true` in the manifest is the design commitment: a valid
   run that **fails the task** is publishable (`valid_failures_publishable: true`), and must
   be published with the **same prominence as a success**
   (`publish_failure_with_same_prominence_as_success: true`). An **invalid** run is not
   publishable at any prominence (`invalid_results_remain_unpublishable: true`).

**Sol's cached-token risk is inherited and unresolved.** In the frozen G7-v3 pair, Sol was
ruled INELIGIBLE because the frozen cached-token requirement was unsatisfied — despite the
2026-07-12 preflight recording `cache_verified: true` for that arm. That is the single most
expensive lesson in this project's history: **$36.55 spent on an unpublishable arm, which
also cost the publishability of the $56.15 arm it was supposed to be compared against.** The
v5 manifest inherits this preflight (`provider_preflight_inherits_from: fort-eval-easy-p1-g7-v3`).
The mitigation is §3 preflight step 5, and it is not optional.

**Pair comparison is currently disabled** (`pair_comparison_enabled: false`, reason:
*"calibration has one run per variant; no replicated claim is valid"*). Enabling it is the
optional manifest change in §7c. Note what a single paired run can and cannot support:
`runs_per_variant: 1` means **one run per arm**. The manifest's own comparison rule says
stochastic diagnostics *"may be compared only across replicated matched-condition runs and
never determine one-run pass/fail."* A single pair yields a per-arm pass/fail on the
declared success predicates — **not** a ranked capability claim between the two models.

**The frozen G7-v3 pair stays exactly where it is.** Fable
`a55b2c2cbef54825bc7784bdb8e51855` ($56.14648677, eligible, 0 deaths, FAILED) and Sol
`cb997beed6d94a3680f2637556cc529d` ($36.54745875, INELIGIBLE, 10 deaths, FAILED) remain
descriptive-only: *"Fable was safer and more risk-aware; Sol was more capable and productive
but collapse-prone."* Not one ranked table, not one aggregate mean. Nothing in this packet
re-adjudicates them. (Naming caution preserved from the index: "Sol" here is the `gpt56-sol`
**model arm**, not the Sol/Sol Ultra/Terra/Luna code-review agents referenced elsewhere.)

---

## §6 — Exact commands

> ### ⛔ DO NOT RUN
>
> Every command below is **blocked** until §7 (a), (b), (d), (e), and (f) are approved.
> They are written out so the approved path is unambiguous and so nobody improvises at
> spend time. Today they would either fail closed at `validate_p1_declaration` (good) or
> spend money we do not have (bad). Placeholders in `<angle brackets>` must be filled.

### 6.1 — Preflight (DO NOT RUN)

```bash
# DO NOT RUN — preflight, on the execution host, at the reviewed tip
# 1) unlock is live on THIS host (must print True; False on the Mac is expected, not a failure)
python3 -c "from fort_gym.bench.eval.fort_eval_easy_p1 import p1_measurement_calibration_is_complete as f; print(f())"

# 2) zero active runs
curl -sS -u "$FORT_GYM_ADMIN_USER:$FORT_GYM_ADMIN_PASSWORD" \
  http://127.0.0.1:8000/runs \
  | python3 -c "import json,sys; rs=json.load(sys.stdin); print('active:', sum(1 for r in rs if r.get('status') in ('running','pending','paused')))"

# 3) v5 provider preflight — MANDATORY, must pass before any paid launch
#    (re-verify cache_verified == true for BOTH arms; see §3 preflight step 5)
```

### 6.2 — Path A: CLI, both arms from the frozen manifest (DO NOT RUN)

```bash
# DO NOT RUN — runs BOTH variants (runs_per_variant: 1) in one process, sequentially
fort-gym experiment experiments/fort_eval_easy_p1_g7_v5.yaml
# prints: <experiment_id>
#         <artifacts_dir>
```

**Trade-off:** simplest, and it is the manifest verbatim — but it launches **both** arms from
one invocation. There is no built-in pause between them, so **it does not support the
verify-Fable-before-Sol gate** of §3. Choose this only if the sequential gate is being
enforced some other way.

### 6.3 — Path B: API, two separate calls (DO NOT RUN) — **supports the Fable-then-Sol gate**

```bash
# DO NOT RUN — ARM 1: Fable. Create, then STOP and verify before touching arm 2.
curl -sS -u "$FORT_GYM_ADMIN_USER:$FORT_GYM_ADMIN_PASSWORD" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/runs \
  -d '{
        "backend": "dfhack",
        "model": "dfhack-governed-llm-fable5",
        "max_steps": 200,
        "ticks_per_step": 2500,
        "preserve_save": false,
        "seed_save": "seed_region3_fresh",
        "runtime_save": "region1",
        "evaluation_protocol": "fort-eval-easy-p1-g7-v5"
      }'
# -> RunInfo JSON. RECORD run_id IMMEDIATELY (server-assigned uuid4 hex; immutable).

# DO NOT RUN — verify arm 1 terminal state before spending on arm 2
curl -sS -u "$FORT_GYM_ADMIN_USER:$FORT_GYM_ADMIN_PASSWORD" \
  http://127.0.0.1:8000/runs/<FABLE_RUN_ID>

# GATE: proceed to arm 2 ONLY if arm 1 is valid AND eligible (§4). Otherwise stop.

# DO NOT RUN — ARM 2: Sol
curl -sS -u "$FORT_GYM_ADMIN_USER:$FORT_GYM_ADMIN_PASSWORD" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:8000/runs \
  -d '{
        "backend": "dfhack",
        "model": "dfhack-governed-llm-gpt56-sol",
        "max_steps": 200,
        "ticks_per_step": 2500,
        "preserve_save": false,
        "seed_save": "seed_region3_fresh",
        "runtime_save": "region1",
        "evaluation_protocol": "fort-eval-easy-p1-g7-v5"
      }'
```

Notes on the API path, read from `fort_gym/bench/api/server.py:873` and
`fort_gym/bench/api/schemas.py:68`:

- `POST /runs` calls `validate_p1_declaration(...)` **first** and returns HTTP `400` on
  failure. **This is the mechanism that blocks a paid v5 launch today** — while
  `P1_MEASUREMENT_CALIBRATION_COMPLETE` is `False`, a real model arm is rejected before any
  provider call. It fails closed, at zero cost.
- Auth is HTTP **Basic** (`fort_gym/bench/api/auth.py:20`): user from `FORT_GYM_ADMIN_USER`
  (default `admin`), password from `FORT_GYM_ADMIN_PASSWORD`. If the password is unset the
  endpoint returns `503` unless `FORT_GYM_INSECURE_ADMIN=1` (local dev only — never for a
  paid run).
- While the manifest is `status: calibration`, `create_run` deliberately **does not** mint a
  permanent share link; a calibration protocol stays admin-only until explicitly activated
  (§7c). Expect no public evidence link unless the manifest is flipped to `active`.
- Each call starts a background thread and returns immediately. The `run_id` in the response
  is the only durable handle — record it before doing anything else.

### 6.4 — Post-run (DO NOT RUN)

```bash
# DO NOT RUN — after each arm completes
shasum -a 256 <artifacts_dir>/<run_id>/summary.json \
              <artifacts_dir>/<run_id>/trace.jsonl \
              <artifacts_dir>/<run_id>/seed_attestation.json
# Append ONE new entry per run to experiments/evidence/EVIDENCE_INDEX.json (append-only;
# never rewrite an existing terminal entry). Record cost_usd from the provider usage log.
```

---

## §7 — Approvals required

Every lettered item below is **Chris-only**. None may be inferred, bundled, or treated as
implied by another. Approving (d) is not approving (e).

- [ ] **(a) Designate the independent reviewer identity and approve the bundle rebuild.**
      The bundle still reads `review_status: "pending"`, `reviewer: ""`. The review itself
      returned APPROVE on 2026-07-21; what is missing is the identity string to stamp and
      permission to run the `--approve` rebuild on the VM (Appendix D step 3). The reviewer of
      record from the review is *"Claude Opus 4.8 — independent scientific-validity &
      provenance reviewer, 2026-07-21, non-authoring"*; Chris confirms or replaces that
      string. The rebuild re-runs the 33-test suite and regenerates the regression XML with a
      **new** hash — the bundle JSON and the XML must be copied back as a **mandatory pair**.

- [ ] **(b) Approve the unlock constants flip, executed strictly per Appendix D.**
      `fort_gym/bench/eval/fort_eval_easy_p1.py` lines 37–38 only, exact line shape preserved
      (including the `: str | None` annotation). This is digest-safe **by construction**: the
      normalization regexes at `:238` and `:244` replace both RHS values with `<LOCK_VALUE>`
      before hashing, so `measurement_code_sha256` stays `261a1fba…` (proven PRE == POST). A
      malformed edit that the regex fails to match moves the digest and **re-locks v5, failing
      closed** — annoying, never dangerous. Verify the recomputed bundle sha256 equals the
      printed `S` (Appendix D step 5) before writing it into the constant.

- [ ] **(c) OPTIONAL — flip the manifest `status: calibration → active`.**
      Only needed for strict public/paired v5 results. **Not** needed for paid-arm
      launchability. `status`, `publication.calibration_results_public`,
      `comparability.pair_comparison_enabled`, and `comparability.pair_comparison_reason` are
      all normalized out of `manifest_semantic_digest` (`:260-269`), so flipping them does not
      disturb the bundle — but it does flip `requires_public_eligibility` / `strict_publication`
      and it does start minting permanent share links on new runs. Defer unless publication is
      wanted immediately.

- [ ] **(d) Approve funding — both dials.**
      Account credits **and** key limit. Short **$97.204374** on credits against the +30%
      envelope; the key needs headroom for `$120.502129` (currently `$28.188624357`).
      **Read §2c's burn warning before funding:** ~$23–40/day is being consumed by a
      **different, non-fort-gym key on the same account**, and $850 has already evaporated
      this way. Fund-and-launch in the same window, or ring-fence the pair's budget on its own
      key.

- [ ] **(e) Approve the paid pair launch itself.**
      Separate from (d). Funding the account is not authorization to spend it here. Expected
      **$92.693946**, envelope **$120.502129**, and there is **no configured expenditure cap**
      — the operator is the cap.

- [ ] **(f) Choose the execution host: Option A (deploy reviewed tip to prod) or Option B
      (scratch checkout).** See §3. Option A is a **gated prod change** touching a service
      that has been stable since 2026-07-17; it must be approved explicitly and never happen
      as a side effect of launching a run.

### Non-blocking (do not gate the GO/NO-GO, but should be decided)

- [ ] **Old task `019ebc73-3687-7ac0-ac33-4d130bfb25be` — archive.** Superseded; archive so
      the active queue reflects reality.
- [ ] **Rescue the `/var/tmp` calibration artifacts — ~5-day fuse (soft).**
      `/var/tmp/fort-gym-calib-g7v5` (408 MB, pinned at `a8de39d03`) is **25 days old**. The
      host's `/var/tmp … 30d` rule is commented out and `systemd-tmpfiles-clean.timer` is
      `static`, so the countdown is **not** demonstrably live — but this is unreplaceable
      provider-free calibration evidence sitting in a directory whose entire social contract
      is "temporary." Copy off-VM. **Do not reuse this directory for a new run** — it is the
      only copy of some of these artifacts.
- [ ] **Push / PR the branch.** `claude/g7v5-truth-repair` is local-only with **no upstream**.
      It contains `origin/codex/remove-g7-duration-gate` (`47c035f11`) as a direct ancestor and
      is 13 commits past it, 36 past `origin/main`, **0 behind** — a clean fast-forward over
      `47c035f`, zero conflicts. The work is currently single-copy on one machine.
- [ ] **Stale `~/fort-gym-test` on the VM** (last touched 2025-12-11). Decide: delete or keep.
      Note the home directory is `0750`, which is why dfhack cannot run as `ubuntu` from
      there — the reason calibration ran from `/var/tmp` at all.

---

## Appendix A — Open advisories (all non-blocking; 0 blocking findings)

From the 2026-07-21 independent scientific-validity review (APPROVE, 3 advisories) plus items
surfaced during preparation. Recorded so they are not rediscovered as surprises.

**A1 — `g7 = None` guard is unreachable.** `p1_task_verdict` handles a `None`/empty `g7`
mapping defensively, but no call path supplies one. Dead defensive code: harmless, and worth a
note so a future reader does not infer a real failure mode from its presence.

**A2 — Runner re-persist ordering.** The runner's persistence ordering around terminal-state
writes is sound in observed paths but is not proven minimal. No observed misordering across
the three calibration runs. Flagged for a future audit, not for this spend.

**A3 — Legacy v3/v4 fail-on-empty semantics.** Older protocol versions treat empty evidence
differently from v5's explicit UNKNOWN. This does not affect v5 runs; it is a compatibility
wart that could confuse a cross-version comparison. Do not cross-version compare.

**A4 — The step-32 fixture gate is brittle-but-fail-closed.** The brew fixture fires when
`step == P1_BREW_INPUT_FIXTURE_STEP` (`= 32`, `fort_gym/bench/run/runner.py:96`), chosen as the
WAIT immediately before the owned-layout plan's brew ORDER at index 33. It is guarded by four
simultaneous conditions: governed dfhack mode **and** scenario ==
`owned_layout_and_provisioning` **and** no fixture already fired **and**
`seed_attestation.eligible is True`. If the plan's step indices ever shift, the fixture fires
at the wrong moment or not at all — and the confirmation check
(`created_count == 8`, all-PLANT, off-farm, still-adjacent, 8 integer item IDs) then raises
`measurement_calibration_fixture_failed` and **terminates the run**. Brittle to plan edits,
but it fails **closed** and loudly. It cannot silently contaminate.

**A5 — Spawned plants are technically edible.** The fixture places 8
`MUSHROOM_HELMET_PLUMP` PLANT items, and dwarves can eat plump helmets. Two honest
observations, in tension, both recorded:
- *No contamination path exists.* The fixture spawns **INPUTS**, never DRINK. Brew credit
  derives **only** from DRINK-item deltas under order-job attribution. The ordinary G7 ledger
  credits the drink, never the raw plant stock the fixture seeds. An eaten plant produces no
  brew credit; it simply fails to become one.
- *The margin was, however, generous.* The prior run `calib-g7v5-owned-20260720a` failed with
  `brew = 0` from pure input starvation — one late qty-1 brew order lost the eat-vs-brew race,
  and `brewable_plant_units` was `0` all run. The fix combined 8 seeded inputs with standing
  brew orders plus a second brewer (plan edit `67b798b80`). Together these made the
  brew-criterion win **effectively certain** rather than merely possible. That is defensible
  for a *measurement calibration* — the objective was to prove the meter reads a real brew,
  not to test whether a scripted plan can win a race — but it should be stated plainly rather
  than left for a reader to notice. The `20260720a` run is superseded; its artifacts are
  VM-only. Precedent for a bounded, disclosed fixture: the kill fixture, commit `3119806b2`.

**A6 — Source-text gating test.** `tests/test_g7_evidence.py` asserts on the runner's **source
text** (e.g. `RUNNER_SOURCE.count("trigger_p1_brew_input_calibration_fixture()") == 1`, and
that the call does not appear in the death branch). This is a genuinely strong guarantee —
it catches a second, unintended trigger site that behavioral tests would miss — but it is
coupled to source formatting and will break on innocuous refactors. Keep it; expect it to
complain.

---

## Appendix B — Digests

Recomputed or re-read this session where marked. Nothing here was accepted on faith from a
prior document alone.

| Object | sha256 | Note |
|---|---|---|
| Calibration bundle `fort_eval_easy_p1_g7_v5_live_calibration.json` | `f41f1a80b63cdc0e323cf57dc914a28fc613cf183905e29828ede298baf59598` | **recomputed 2026-08-15**, matches |
| `manifest_semantic_sha256` | `b85957669eb02668f965f103e42b1feaf88cdad7ecc8e45fc5eb2b78d8269cc6` | frozen manifest, lifecycle fields normalized out |
| `measurement_code_sha256` | `261a1fba89ce1a320a3248a37cbee26b37971ef6c2240705d6bdce51088c9b4c` | lock constants normalized out; PRE == POST across the flip |
| `remote_proto_runtime_sha256` | `9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f` | VM-side protos; `None` on the Mac (expected) |
| `calibration_manifest_sha256` | `fb61209de1a26d453292bce8c228c1617622509868290b014573d577c020c136` | raw manifest bytes |
| `seed_world_sha256` | `070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d` | `seed_region3_fresh` |
| `seed_attestation.json` (identical across **all three** calibration runs **and** both frozen G7-v3 runs) | `9c923f9e2ee8ce25344fc88d66f54f2c0262d9f62317c1b44946cd73f6ee01e8` | same embark, provably |
| owned-layout trace `.jsonl` | `0ce3899fbaef8d90ccca7dee2e7bbc47bc62382d9e68b3f44fc38ce778403073` | 115 steps |
| owned-layout `_summary.json` | `2c07304aa58ceededb5a51d976407443d2953ea99c65862ec340cb5fd34b4af8` | |
| death-fallback trace `.jsonl` | `2385d1b3f4c100ad5737f653c98235e7292471b09cefbef2d2b7600cd52af05c` | 1 step |
| death-fallback `_summary.json` | `205016815cadb584c51acc39c1807be47c3ada8ec3108af0e4c31a9c4e2ab43f` | |
| sensor-dropout trace `.jsonl` | `47475ad8cd5d3e69668ea27f9c69e14208d0fbd8554012ed70a3dc3c874354cc` | 1 step |
| sensor-dropout `_summary.json` | `fc59b94a951dd616ab0b04046874ed9e64a11207b9421cee4d912021f7af5fca` | |
| regression report `p1_g7_v5_measurement_regressions.xml` | `a2469336c9ce32cc96941cf5fa5fe6e1d341e6e6c96e2591da6d49ece96d616e` | **will change** on the `--approve` rebuild |
| Frozen G7-v3 Fable `summary.json` | `39a5000d22020f10d9bc84e4510e95828be5d2c00d54d3527e6d12fe665c2307` | historical, VM-only |
| Frozen G7-v3 Fable `trace.jsonl` | `5fd4611e96bef262f584cd2aac116879ca4ea0123cd59483cd933f931e231612` | historical, VM-only |
| Frozen G7-v3 Sol `summary.json` | `db5649b4d85138db23ea2aba9fc9bf98a60efd7499b0efb3db9aea2d1ca64941` | historical, VM-only |
| Frozen G7-v3 Sol `trace.jsonl` | `e740af41ac282a6a1bcd81419ede361656c3f36c05dd2a1f099e58da5e4a4dc7` | historical, VM-only |

**Commits referenced in this packet**

| Commit | Meaning |
|---|---|
| `557e5d6fb` | verdict fix — `p1_task_verdict` returns validity-gated `g7.status` |
| `a8de39d03da48da32110776bf84ddfcbcb2ccefc` | calibration campaign commit; boolean-walkable fixture fix; `/var/tmp` checkout pin |
| `34b00ade2` | bounded brewable-input calibration fixture (code) |
| `f629cb7fd` | fixture bounds/gating/digest-binding tests |
| `67b798b80` | plan edit — early + persistent brew demand, second brewer |
| `3119806b2` | kill-fixture precedent |
| `82ee3e078` | `origin/main`, unchanged since 2026-07-13 |
| `47c035f117f2a8663c2b276160d546c49f47a5da` | research branch tip = currently deployed `/opt/fort-gym` |
| `153b98163` | branch tip at packet commission |
| `ccfac2c93` | branch tip at packet finalization (reviewed tip) |

---

## Appendix C — Manifest fields (`experiments/fort_eval_easy_p1_g7_v5.yaml`, read-only)

| Field | Value |
|---|---|
| `manifest_id` / `schema_version` | `fort-eval-easy-p1-g7-v5` / `fort-eval.manifest/v1` |
| `status` | `calibration` |
| `frozen_date` | `2026-07-14` |
| `provider_preflight_evidence` | `experiments/evidence/fort_eval_easy_p1_provider_preflight_20260712.json` |
| `provider_preflight_inherits_from` | `fort-eval-easy-p1-g7-v3` |
| `task.task_id` / `task_version` | `g7_survival` / `g7-v5` |
| `task.seed` / `seed_split` | `seed_region3_fresh` / `fixed_seed_pilot` |
| **Success predicates** | operational farm plots ≥ 1; completed stills ≥ 1; governed brew output units ≥ 1; authoritatively classified preventable deaths ≤ 0; final owned accessible layout rooms ≥ 3; owned completed beds ≥ 3 |
| `outcome_vector` | `outcome-vector-v1`; `numeric_composite: false`; no action-variety, objective-text, peak-layout, or global-unowned-state credit |
| Diagnostics (recorded, **do not** affect gate status) | `duration_ticks`, `population` (matched cohort only), `score_v5_scalar` (diagnostic only), `peak_layout`, `cache_read_rate` (does not affect gameplay validity) |
| Observation / action | `governed_structured_state_v3_owned_layout`, vision on, observer map agent not visible / `legal_semantic_dfhack_v1`, debug completion off |
| Knowledge / memory | `none`, no documents, no live web / `off`, no cross-episode state |
| Budget | 200 steps × 2500 ticks = 500,000 max ticks |
| Model arms | `dfhack-governed-llm-fable5` (`explicit_system_ephemeral` cache) and `dfhack-governed-llm-gpt56-sol` (`automatic` cache, `prompt_cache_key: per_run_session_id`); both `reasoning_effort: max`, `max_completion_tokens: 128000`, `sticky_routing: per_run_session_id`, `provider_model_id: resolved_at_run` |
| Provider policy | `legacy_direct_anthropic_api: prohibited`; Fable runs **via OpenRouter only** (`direct_anthropic_api: false`) |
| `comparability.pair_comparison_enabled` | `false` — *"calibration has one run per variant; no replicated claim is valid"* |
| `cost_and_kill.expenditure_cap.enabled` | **`false`** (`per_run_usd: null`, `per_cell_usd: null`) — no automatic spend ceiling |
| `cost_and_kill.pricing_status` / `usage_logging_required` | `must_be_recorded_per_run` / `true` |
| `publication` | `calibration_results_public: false`; `valid_failures_publishable: true`; `validity_and_outcome_separate: true`; `invalid_results_remain_unpublishable: true`; `publish_failure_with_same_prominence_as_success: true` |
| `base_config` / `variants` / `runs_per_variant` | dfhack, 200 steps, 2500 ticks, `preserve_save: false`, `seed_save: seed_region3_fresh`, `runtime_save: region1` / `fable5-memory-off`, `gpt56-sol-memory-off` / **1** |

---

## Appendix D — Approved unlock runbook (verbatim)

Embedded byte-for-byte, exactly as the independent unlock-semantics review (APPROVE,
2026-07-21) produced it: 12 entries — a PRECONDITION, steps 1–10, and a closing ORDER
RATIONALE. **Do not paraphrase it when executing — follow it literally, in order.**

*Provenance of this copy, disclosed.* The scratch recovery file
`docs/decisions/.unlock_runbook_recovered.json` was the original carrier and was slated for
deletion here once embedded. The parallel documentation pass consumed and removed it first,
committing the same verbatim text into
`docs/decisions/2026-07-21-g7v5-calibration-independent-review.md` (`0fa8591fd`). This
appendix is therefore transcribed from that committed copy rather than from the scratch file,
and was validated on transcription: 12 entries, first entry `PRECONDITION…`, entries 1–10 in
order, last entry `ORDER RATIONALE…`. The scratch dotfile is gone either way, as intended;
no unique content was lost.

```json
[
  "PRECONDITION (verified by this review, no action): VM /var/tmp/fort-gym-calib-g7v5 is at a8de39d03 with protos hashing 9d7949fe and all 3 raw run artifacts present; branch measurement_code=261a1fba and manifest_semantic=b8595766 both already match the bundle; measurement sources are unchanged a8de39d03..HEAD. The only missing inputs are (a) bundle approval and (b) the two-constant flip.",
  "1. On the VM, cd /var/tmp/fort-gym-calib-g7v5 and confirm `git rev-parse HEAD` == a8de39d03da48da32110776bf84ddfcbcb2ccefc. Do NOT edit fort_eval_easy_p1.py here — a dirty contract file would fail the build's clean-checkout gate.",
  "2. On the VM, make the tree clean for the gate by removing ONLY the 8 untracked prior-build outputs under experiments/evidence/ (the bundle json, the 3 *.jsonl traces, the 3 *_summary.json, and p1_g7_v5_measurement_regressions.xml). The build recreates them. Then verify `git status --porcelain --untracked-files=all` prints nothing. (generated/ and fort_gym/artifacts/ are gitignored and correctly do not count.)",
  "3. On the VM (protos required here; the Mac cannot build), run: DF_PROTO_ENABLED=1 python3 scripts/build_p1_live_calibration_bundle.py --owned-run calib-g7v5-owned-20260721a --death-run calib-g7v5-death-20260721a --dropout-run calib-g7v5-dropout-20260721a --reviewer \"<independent-reviewer-id>\" --approve . This re-runs the 33-test suite, regenerates the regression xml (new hash), recopies traces/summaries, writes review_status='approved'+reviewer, and PRINTS {\"sha256\":\"S\",...}. Record S exactly.",
  "4. scp FROM the VM into the branch worktree experiments/evidence/, overwriting at minimum the approved fort_eval_easy_p1_g7_v5_live_calibration.json AND the regenerated p1_g7_v5_measurement_regressions.xml (mandatory pair). Recopy the 3 traces + 3 summaries too (byte-identical, keeps the set consistent). Preserve bytes exactly; do not reformat.",
  "5. In the branch worktree, RECOMPUTE the bundle digest to defend against transport drift: `shasum -a 256 experiments/evidence/fort_eval_easy_p1_g7_v5_live_calibration.json`. Confirm it equals S. Use this verified value as the constant. If it differs from S, stop — do not proceed.",
  "6. In fort_gym/bench/eval/fort_eval_easy_p1.py change ONLY the two RHS values, preserving exact line shape: line 37 -> `P1_MEASUREMENT_CALIBRATION_COMPLETE = True`; line 38 -> `P1_MEASUREMENT_CALIBRATION_EVIDENCE_SHA256: str | None = \"<S>\"`. Keep the ': str | None' annotation, single line, no reformat (normalization regexes at :238/:244 require this; a malformed edit moves measurement_code_sha256 and re-locks v5, failing closed).",
  "7. OPTIONAL (separate reviewed publication activation — only if you want strict public/paired v5 results now): in experiments/fort_eval_easy_p1_g7_v5.yaml flip status: calibration -> active (and publication.calibration_results_public / comparability.pair_comparison_* as desired). These are normalized out of manifest_semantic_digest (:260-269) so they don't disturb the bundle; they flip requires_public_eligibility/strict_publication (public_protocols.py:163,243; server.py:627,647). Skip entirely if you only need paid-arm launchability.",
  "8. DO NOT touch any other file in P1_MEASUREMENT_CODE_RELATIVE_PATHS (hook/*, fort_gym/bench/**, scripts/run_p1_live_calibration.py, scripts/build_p1_live_calibration_bundle.py). Any byte change there moves measurement_code_sha256 and re-locks v5. Optionally advance the 3 EVIDENCE_INDEX.json entries to review_status:approved/reviewer for truthfulness (documentary; no gate reads it).",
  "9. Commit on branch claude/g7v5-truth-repair (eval: prefix). No new 'calibration commit' is recorded anywhere — calibration_fort_gym_commit stays a8de39d03. The commit simply carries the approved bundle + regenerated xml + the two flipped constants (+ optional manifest/index edits).",
  "10. VERIFY GREEN on a host whose protos hash 9d7949fe (the VM or the intended run host): import fort_gym.bench.eval.fort_eval_easy_p1 and assert p1_measurement_calibration_is_complete() is True, and that validate_p1_declaration for a real MODEL_ARMS arm no longer raises. NOTE: on the Mac (no generated/ dir) the function returns False because remote_proto digest is None — this is expected off-VM and is NOT a failure.",
  "ORDER RATIONALE (why every check stays green): the flip in step 6 is normalized out of measurement_code_sha256 (proven PRE==POST==261a1fba), so it neither disturbs the bundle nor needs a rebuild afterward; the bundle is fully finalized in step 3 BEFORE S is captured, so bundle-file-sha256==S holds at :607; approve+reviewer are stamped by the tool at a clean a8de39d03 with a freshly passing suite (:619-625); manifest_semantic and remote_proto recompute-match (:612,:614); calibration_fort_gym_commit stays bound to the summaries (:365)."
]
```

---

## What could not be verified this session

Stated so no reader mistakes an assumption for a measurement.

1. **Registry active-run count (`0/0`).** The API registry is in-memory and requires HTTP
   Basic admin credentials, which are not readable under read-only VM access. *Verified
   instead:* `fort-gym-api` and `dfhack-headless` are `active`, the API has been up
   continuously since 2026-07-17 17:00:18 UTC, port 8000 is listening, and 1298 artifact
   directories exist on disk. The `0/0` figure is carried forward from the prior verification
   and is **consistent** with a long-idle service, but it was **not** re-measured today. The
   §3 preflight re-checks it at launch time, which is when it actually matters.
2. **`/var/tmp` eviction timing.** The `30d` rule in `tmpfiles.d` is commented out and
   `systemd-tmpfiles-clean.timer` is `static` (not enabled), so the "~5 days to eviction"
   figure is a **conservative planning assumption**, not an observed countdown. The artifacts
   are 25 days old and unreplaceable; rescue them regardless.
3. **Actual G7-v5 pair cost.** `$92.693946` is the observed **G7-v3** pair sum, not a v5
   measurement. v5's richer observation profile could push it higher; caching could pull it
   lower. Neither is quantified — hence the +30% margin.
4. **Live cache behavior for both arms under v5.** The only cache evidence is the 2026-07-12
   **G7-v3** preflight (`cache_verified: true` for both arms, resolved models now 34 days
   stale). Given that Sol's G7-v3 arm was ruled INELIGIBLE on cached tokens *despite* that
   file, the inherited evidence is necessary but demonstrably not sufficient. §3 preflight
   step 5 exists for this reason.
5. **That the reviewed tip actually runs on the VM.** The reviewed measurement code is 13
   commits past what is deployed at `/opt/fort-gym` (`47c035f`). It has never been executed
   on the deployment host. Appendix D step 10's green-verify is the check, and it has not
   been performed.
6. **Whether the ~$23/day non-fort-gym burn will continue.** It is observed, not explained.
   The consuming key was not identified — identifying it would require enumerating account
   keys, which is outside read-only scope and outside this packet's mandate. Funding
   decisions in §7d should assume it continues.
