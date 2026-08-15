# Fort-Gym Environment Layer — design v1

Status: v1, decision-grade, 2026-08-15. Supersedes v0 (`45c6c0c6c`) after a
four-lens adversarial panel (doctrine, engineering, science, cost/ops); every
MUST/SHOULD finding is dispositioned in §10. Branch `claude/g7v5-truth-repair`
(local-only; go/no-go **reviewed tip `ccfac2c93`**). Repo facts re-read from
this checkout on 2026-08-15; VM facts quoted from
`docs/decisions/2026-08-15-fable-sol-go-no-go.md`.

## 1. Purpose and the question

Chris's question, verbatim: **"How well can frontier models manage a complex
living population of people?"**

A frontier-model *evaluation* program, not an RL environment. DF earns its
place because the agent never controls a dwarf: it digs, builds, orders,
assigns labor, waits; individuals with their own needs and moods decide the
rest. The credibility claim, stated before a critic states it for us: *an
untuned 20-year-old game, plus a published, bounded, pre-registered
perturbation schedule that the world executes through its own mechanisms.*

**Construct.** "Population complexity" is operational: census size, distinct
labor roles held, unmet-need diversity, social/mood incident rate; a run counts
toward a population claim only above a declared minimum. The fresh seven-dwarf
seed at 60–100 steps (≤250k ticks, ~0.6 of a 403,200-tick year; natural waves
land at ~200k+) is the *bootstrap* regime — good for instrument tests, not for
the claim. Density is bought with **staged mid-life seeds** (pop
15–25, DF-grown, provenance recorded), not by shortening below the growth
horizon; each campaign keeps one long-horizon no-fixture arm as the check.

**Inferential target.** A cell's interval covers within-condition variance
(model sampling + provider routing + DF trajectory, confounded); it licenses
"on this seed under this perturbation", never "model X manages populations
better" — that needs ≥3–5 seeds and a pre-registered combination rule (§5).

Where we are: one fort per 2-vCPU VM, ~5 h per 200-step run, every comparison
n=1, the only paid pair (G7-v3) descriptive-only, G7-v5 calibration approved,
its paid pair NO-GO ($23.30 spendable).

What "good" looks like: **cells, not anecdotes** — N OpenRouter arms × M seeds
× K declared perturbations (+ a no-fixture control cell) × R replicates, R
*derived* from measured variance; reported as the full outcome vector, an
ordinal PASS-count with UNKNOWN-count beside it, and per-fixture time-to-event
predicates; **real DF 0.47.05**, unknown-not-fail; **publicly replayable**
(trace, seed/perturbation/mask/image digests, fixture markers at
`fortgym.live/r/<token>`); **population questions answered from DF's own
bookkeeping**, never a judge.

## 2. Why not rebuild

Measured, not asserted: the committed v5 calibration trace advances at 98.9
ticks/s (82 steps, 188,116 ticks, 1,902.7 s), so a 2,500-tick step costs 25.3 s
and a 200-step run spends ~1.4 h inside DF against ~5 h of model latency —
**~22 % of wall clock**, not "a small fraction". That is the per-fort CPU budget
and does not shrink with parallelism; the other 78 % does. A GPU rewrite would
attack the fifth and forfeit the credibility of a game nobody built for the
models. DF Classic is freeware, not open source: we wrap, observe and command
via DFHack, never modify the engine. **Recorded decision (Chris, 2026-08-15):
stay on DF, kill the tax, build the environment layer DF never had.** 99
ticks/s is the M1 regression baseline.

## 3. Design principles (doctrine preserved, two added)

1. **Evidence first.** Verdicts and predicates derive only from real DF state
   deltas with replayable evidence; command acceptance is not progress.
2. **Unknown, never fail** — and never silent: `unknown` stays in every
   denominator.
3. **Frozen, versioned protocols.** v3 history, v4 rejected, v5 current. New
   measurement ships as a new version with its own calibration and a dated
   change-log entry naming the defect or planned expansion; frozen before the
   first arm; never revised in response to results.
4. **Fixtures perturb the world, never the measurement — in either direction.**
   No false credit (nothing a fixture creates is credited) and **no false
   debit** (nothing a fixture causes is charged unless the arm could
   demonstrably have prevented it; §5).
5. **Disclosure and pre-registration.** Every fixture, mask, image digest and
   provider route is in trace, summary and condition key; schedules, params and
   profiles are frozen with a timestamp before any arm runs; post-hoc selection
   invalidates the cell.
6. **No engine modification.** DFHack is a bounded, audited transport; the
   seven governed families + allowlisted `INTERACT` remain the whole surface.
7. **Two planes, one firewall.** Observer plane may be richer; the agent — text
   *and* rendered image — sees only what the declared mask admits.
8. **The agent shapes conditions.** No per-dwarf control action, ever.
9. **Provider policy.** OpenRouter only; no Anthropic model except the approved
   OpenRouter Fable arm; pinned arm names; provider pinned per run.
10. **Validated fields only.** The evaluator credits or debits no criterion
    from a field whose `calibration` is not `validated` (§4.2).

## 4. Architecture — the four pillars

Amendments after the panel: (a) a **population axis**; (b) fixtures schedule by
**elapsed tick with a clamp**; (c) **process-per-run first**, `DFRuntime`
threading later; (d) v5 re-locks at M1b — the reviewed-tip tag is the v5
reproducibility guarantee (§6).

### 4.1 Isolation — process-per-run + one DF container per run

**Today.** One `dfhack-headless` unit (expect PTY, `PRINT_MODE:TEXT`, RPC on
`127.0.0.1:5000`). Runs are *daemon threads in one API process*
(`api/server.py:938`), so every module global is shared (`config.py`
`DFROOT`/`DFHACK_RUN`, `get_settings()`, one `_screenshot_client`);
`jobs.py:34-37` clamps dfhack parallelism to 1; `seed_reset` restarts the
shared service. The autoboot patch (`infra/ansible/files/dfhack-core-
autoboot.patch`) is a delta on an *uncommitted* delta — its context lines do
not exist upstream — and its source tree `/Users/cdossman/dfhack-work/src/`
**no longer exists**; `group_vars/all.yml` fetches DF/DFHack 50.12 with an
empty checksum while the VM runs 0.47.05-r8. Both build paths are dead.

**What changes.** *Topology, named:* one harness OS process per run
(`fort-gym experiment` supervised by the API), `DFROOT`/`DFHACK_HOST`/
`DFHACK_PORT` injected by env (`config.py` already reads them) — globals become
correct by construction without touching digest-bound modules; one `fortgym-df`
container per run on **host networking**, loopback bind on a distinct port (the
patch honors `DFHACK_PORT`), so nothing is exposed and there is no
bridge-vs-loopback problem; `exec_lua` moves to the native RPC path
(`dfhack_client._run_command`, host/port already parameterized) so the 20 Hz
tick poll is not ~500 `docker exec`s per step; per-run screenshot client keyed
by `run_id`; env allowlist (no `OPENROUTER_MODEL`, no provider keys in DF); a
**harness-level, manifest-independent, default-ON kill switch** (per-run
USD/token ceiling; a trip aborts with a terminal record). Image: DF 0.47.05
tarball vendored with a pinned checksum, DFHack `0.47.05-r8` + the *complete*
patch series in-repo with `git apply --check` in CI (M0), scripts submodule
pinned, one staged save, `seed_region2` never present. `DFRuntime` threading
lands with the contract (M4). `POST /runs` gains an `environment` block
(`image@sha256`, `df_version: 0.47.05-r8`, `dfhack_ref`, `dfhack_port`,
`cpu`/`mem_gb` `<measured>`, `seed_save`, `seed_world_sha256`), echoed in
summary next to `seed_attestation`.

**Kills**: one-fort-per-VM, shared globals, env ambush, wrong-run screenshot,
human-as-cap. **Does not**: change the action surface, evaluator or DF; touch
prod; publish any image.

### 4.2 State contract — one state schema, one action schema

**Today.** Inline Lua → `StateReader.from_dfhack` whitelist → `attach_*`
sensors → ~6,000 lines of runner glue that *reconstructs* ownership. The
whitelist once dropped `wood_usable`; the bool-`walkable` quirk is defended in
three separate readers; no sensor reads per-citizen stress, needs or mood.

**What changes.** `fortgym.state/v1`: one schema, one Lua reader entrypoint,
emitted every step on the observer plane. Ownership becomes fields (`owner:
{run_id,action_id}`, `claims[]` on every action result; `origin: fixture` on
fixture-authored entities, deaths and items). Every section carries
`sensor_health` (`complete`, `truncated`, `errors[]`), **`provenance`** (the DF
structure path each value was read from — `g7_evidence.lua`'s `cause_source`
pattern) and **`calibration: validated | diagnostic | unvalidated`** —
`validated` = a live paired check against DF's own UI on a paused fort,
recorded in the calibration bundle. A read-only **population
axis** (`citizens[]`: id, name-hash, age class, labors, job, `stress_level`,
top unmet needs, health, z; `events[]` from DF announcements/incidents) ships
`diagnostic` until it clears principle 10. `fortgym.action/v1` formalizes the
governed families with bounds; the evaluator reads the schema.

**Kills**: Lua archaeology, evaluator coupling to runner internals, confident
integers nobody validated. **Does not**: change what counts as evidence; give
the agent unit control or the raw schema.

### 4.3 Fixture library — declarable, bounded world perturbations

**Today.** Two world-perturbing hooks work (`calibration_kill_one.lua`,
`calibration_seed_brew_inputs.lua`), hand-wired in `runner.py`, single-latched
(scalar summary field), digest-bound, guarded by a one-trigger-site source
test. **`measurement_calibration` already includes sensor fault injection**:
`death_cause_fallback` flips the evidence hook's mode (`runner.py:3234`),
`sensor_dropout` overwrites the live `fort_metrics` read (`runner.py:3274`) —
runner-side, in no fixture file.

**What changes.** A registry `fixtures/<id>/<version>/{fixture.lua,
fixture.yaml, evidence/, tests}`; the v5 hooks are *copied* in, never moved
(v5's digest reads their paths). Nouns: `calibration_scenario` keeps
its meaning; the schedule of world perturbations in scored runs is a
**`perturbation_schedule`** (`fixtures=` key field). The firewall is
**structural**: `world_perturbation` fixtures execute through an
`apply_fixture` capability built with no handle to the ledger, sensor readers
or `measurement_calibration_mode`, so a sensor write is a type error; a
positive test enumerates every scenario-conditional runner branch and fails on
any unclassified one; the one-trigger-site test becomes "one registry-driven
apply site, applicable set from the frozen manifest only, no direct hook call".
`fixture_applications[]` becomes a list — a summary-schema change, therefore
g8-v1. Scheduling is by **elapsed tick since seed attestation**
(`observed_run_elapsed_ticks`, wrap-safe), with a clamp (§5).

```yaml
perturbation_schedule: {id: brewer_loss_v1, version: 1}
fixtures:
  - {id: key_worker_death, version: 1, at: {elapsed_tick: 60000, deadline_step: 30}, params: {labor: brewing}}
  - {id: drink_shock, version: 1, at: {elapsed_tick: 120000, deadline_step: 60}, params: {remove_units: 40}}
```

### 4.4 Visibility mask — observation as declared config

**Today.** `encode_observation` returns the full state (`redact_noise` is a
passthrough); no artifact defines the manifest's profile; the adapter builds
the minimap from raw `obs_json["fort"]` (`governed_llm.py:1570`). Visibility is
prompt discipline.

**What changes.** An `ObservationProfile` is a JSON allow-list of state paths
with bounds, cadence and render options applied to `fortgym.state/v1` to
produce `agent_view`; adapters *and the renderer* consume only `agent_view`;
render parameters (dimensions, palette, downsampling) join the profile digest;
each trace row stores `state`, `agent_view` and the rendered artifact. Profiles
are development or held-out material like seeds (§5); a profile chosen after
seeing arm results invalidates the cell.

## 5. The fixture library in depth

**Taxonomy** (validated live on 0.47.05-r8; `stress_level` and `cur_season`
writes are counter edits and are struck; `siege` deferred).

| Family | Candidates | Native mechanism |
|---|---|---|
| population | `key_worker_death`, `migrant_wave` | blood-loss kill (proven); **native only** — a staged save frozen just before DF's own wave (`create-unit` fabricates population → `synthetic_entity: true`, barred from population claims) |
| provisioning | `drink_shock`, `food_shock`, `seed_loss` | bounded removal of an **absolute** unit count (proportional shocks tax preparation) |
| mood/social | `stress_pressure` (diagnostic) | native causes only; the stress *sensor* is the read-out |
| infrastructure | `building_loss`, `stockpile_wipe` | `dfhack.buildings.deconstruct`; item removal |

**Contract.** Procedurally: bounded (literal caps in yaml, re-asserted in
Lua), single-shot, schedule-gated, disclosed (trace event with pre/post
evidence, `fixture_applications[]`, replay marker), engine-consistent,
fail-closed, and digest-bound with **split binding** — `measurement_code_sha256`
covers sensors/evaluator/runner/loader; `fixtures=` hashes declared fixture
sources + resolved params in schedule order, so an unused registry entry moves
no existing key. Then **seven tests, cheapest kill first**: (1) *Ledger
fence*: same seed with/without the fixture under `dfhack-governed-scripted`;
every evidence-ledger delta across the application step is zero or justified
in yaml (kills the `onItemCreated` contamination class; today the brew hook's
safety is a comment). (2) *Non-triviality*: the null arm does not pass. (3)
*Recoverability*: a scripted competent arm recovers inside the run budget,
which also calibrates the recovery window **W**. (4) *Blame-separability*: for
every scored criterion the fixture can reach, evidence distinguishes fixture
from agent causation. (5) *Arm-blindness*: inputs are a pure function of world
state and declared tick; two arms' invocations are byte-identical modulo tick
error. (6) *Native bookkeeping*: visible in DF's own records, no counter
written. (7) *Pre-registration*: id, version, params, schedule frozen with a
timestamp before the first arm; a parameter change mints a new version. Failing
1, 4 or 5 bars the fixture from scored runs; 2, 3 or 6 makes it
diagnostic-only; 7 invalidates the cell. Tests 1–3 plus a **null-baseline** run
are the four artifacts in `fixtures/<id>/<version>/evidence/`, published with
any result using the fixture.

**No false debit.** `gates.py:491-498` FAILs the death criterion on any
HUNGER/THIRST death (`g7_evidence.lua:341-345`); a thirst death after
`drink_shock` is byte-identical to neglect. So every `fixture.yaml` carries
`criteria_reachable[]` naming each outcome-vector criterion it can causally
reach, with a proof note; direct effects carry `origin: fixture`; for each
reachable criterion the condition's manifest declares a **re-basing** (e.g.
neglect deaths counted only after `applied_tick + W`) or the criterion resolves
`unknown` in that condition. Never `fail` by authorship.

**Endpoints.** Primary per campaign and per fixture, pre-registered with the
confidence procedure and analysis-code digest: the full outcome vector; its
ordinal PASS-count (0–6) with UNKNOWN beside it — a summary of the vector,
never a leaderboard scalar; per-fixture time-to-event predicates analysed as
censored data (Kaplan–Meier/log-rank, or "recovered within W"): `drink_shock`
→ ticks to regain pre-shock stock, thirst deaths after W; `key_worker_death` →
ticks until the labor is held again; `building_loss` → ticks to an owned
replacement; plus a **preparedness vector** at the fixture tick (days-of-supply,
labor redundancy, beds/capita) and persistence at T+2W. Every campaign has a
**no-fixture control cell** (same seed/steps/profile). Multiplicity: Holm or BH
over the declared family; the rest is exploratory.

**Scheduling.** `at.elapsed_tick` is relative to seed attestation (the seed
starts at `cur_year_tick` 16,801; `advance_ticks` ≤ 2,500 is agent-chosen).
When the declared tick falls inside a requested advance the harness **clamps**
the advance to land on it, applies, resumes; declared/applied tick, tick error
and applied step are recorded against a manifest tolerance (past it =
out-of-condition); a run reaching `deadline_step` unfired terminates
`fixture_window_not_reached` = `unknown`, never pooled with crisis runs; a
minimum post-fixture window must be achieved. Fixture-application failure is
**infrastructure-aborted**: out of the denominator, published with its trace,
replaced only under a predeclared replacement budget; exceeding it invalidates
the cell.

**Comparability.** condition = the existing P1 key (`forteval/v1` fields) **+**
`fixtures=` + `image=` + `df=` + `dfhack=` + measurement-cap constants
(`fort_metrics.lua:38-40` are outcome-determining) → `forteval/v2` in g8-v1.
Fixtures, schedules, params and observation profiles are development or
held-out material under spec §6 (amendment required). The registry is split:
**public** (contract, source, bounds, resolved params, four proofs of every
fixture in a published result, at publication) and **held-out** (exact schedule
instances for future ranked windows), rotated like seeds.

**Statistics.** Unmeasured variance is the design's largest hole and it is
nearly free to close: **E0** = 10 `dfhack-governed-scripted` replicates on one
seed (σ_world, $0, M1a) plus 10 on the cheapest OpenRouter arm (σ_total,
~$10–30, M2). R is derived from E0 at a pre-registered power; hard floors R ≥ 5
for any binary endpoint, R ≥ 8 for a headline two-arm comparison (3/3 vs 0/3 is
p = 0.10; 8/8 vs 0/8 is 0.00016); when budget binds, cut cells, never R.
Unknown-rate is co-primary with a predeclared cell maximum (>20 % → VOID), plus
bounded reporting (all-unknown-pass/-fail) until scan-cap truncation is shown
flat in fort size. Arms in one comparison share temperature, cache policy,
reasoning effort and completion limit (`generation.temperature` joins the
identity fields — today Fable omits it, Sol sends 0.1, unrecorded); provider
pinning is *implemented* (today `sticky_routing` is a YAML string) and "one
provider, one resolved model per run, identical across a cell" is a validity
gate; cached-token eligibility is decided before any campaign, with a per-arm
pre-flight. Arm × replicate slots are balanced; co-tenancy and
infrastructure-abort rate are recorded per arm. 1–2-seed results are
seed-specific; a model-level claim needs ≥3–5 seeds and a pre-registered
stratified combination (seed as stratum), which spec §5 currently forbids (§9).

**First three, then spikes.** 1. `key_worker_death` (proven hook, labor
generalized). 2. `drink_shock` (absolute units; sensors exist). 3.
`building_loss` (cheap, native). Research spikes, not scored: `migrant_wave`
(native only; `create-unit` is first-riskiest on doctrine even where it works),
`stress_pressure` (needs a validated sensor).

**Doctrinal boundary.** Legitimate: native mechanism, bounded, pre-registered,
identical across arms, applied at a world tick never in reaction to an arm,
disclosed everywhere, creates nothing credited *and causes nothing debited
without re-basing*, passes tests 1, 4, 5. Cheating: spawning drink or beds,
removing an obstacle for one arm, editing a sensor or evaluator, firing
undeclared or post hoc, a severity nobody defended. Fixture *and*
`calibration_scenario` on one run stays ineligible.

## 6. Roadmap

| # | Milestone | Scope | Exit criteria | Effort / cost | Deps |
|---|---|---|---|---|---|
| **M0** | Preserve and unblock ($0) | Copy `/var/tmp/fort-gym-calib-g7v5` off-box (read-only), sha256s into `EVIDENCE_INDEX`; tag `g7v5-reviewed-tip`=`ccfac2c93`, `g7v5-design-v0`=`45c6c0c6c`, push branch+tags; seed corpus backed up with sha256s; DFHack source decision — rebuild from public `0.47.05-r8` and commit the full patch series, else back up `/opt/dwarf-fortress` and declare the image *binary-seeded*; fix `group_vars` URLs; **erratum** for `df_version: df-51.11` (`fort_eval_easy_p1.py:807-840`, `public_protocols.py:222/238`) with affected run ids; change log started | Artifacts in ≥2 places; `git apply --check` passes or binary-seed recorded; erratum published | days | Chris: push, source knowledge |
| **M1a** | Feasibility + sizing, ephemeral host | Build image on a throwaway spot VM (never prod, never the Mac); 2→4→8 scripted containers concurrently, host network, distinct ports; **E0** σ_world half | Sizing table (DF vs harness CPU, RSS, disk, ticks/s ≥ 90 % of 99); two forts side by side = first thing Chris sees; σ_world published | ≤1 wk, ~$0.50–5 | M0 |
| **M1b** | Process-per-run isolation | API supervises `fort-gym experiment` processes; env-injected DF endpoints; native-RPC `exec_lua`; per-run screenshot; env allowlist; default-ON kill switch; provider pinning; co-tenancy recorded; `jobs.py` clamp lifted | 8 concurrent scripted runs, identical `seed_attestation`, no cross-talk; a tripped cap aborts with a terminal record; **prod untouched** | 2–3 wk | M1a |
| **M2** | Fixtures v0 + population sensor + **g8-v1** | Registry, structural firewall, classification test, clamp scheduling, split digest, `forteval/v2` key; first three fixtures with four proofs each; staged mid-life seeds (scripted arm advanced to the first natural wave ≥ pop 15, provenance recorded); population sensor with paired-UI check (diagnostic); E0 σ_total half; frozen g8-v1 manifest (primaries, R from E0, confidence procedure, replacement rule, control cell) | Fixtures fire within tolerance; proofs archived; scripted control and one cheap arm land at *different* primary-endpoint values | 3–4 wk (M2-min for E1: one fixture + key + manifest, ~2 wk) | M1b |
| **E1** | First replicated crisis comparison (provisional) | 2 arms × 1 seed × (`key_worker_death` + control) × R = 8 at ≤100 steps = 32 runs; ring-fenced key | Provisional finding under g8-v1: ordinal endpoint, time-to-labor-recovery, unknown-rate; replayable; public registry entry live at publication | ~1 wk; **≈ $600–750** (Fable $0.281/step, Sol-class $0.183/step; ~$1k at +30 %); fixture cells only: 16 runs ≈ $370 | M2-min, funding, arm pre-flight |
| M3 | Visibility mask v0 | Allow-list over state; renderer under the mask; both planes + rendered artifact recorded; profiles `governed_v3_owned_layout`, `population_v1` | Adapter cannot read outside the mask (test); profile digest incl. render params | 1–2 wk | M2 |
| M4 | State contract + **g8-v2** | `fortgym.state/v1`, `fortgym.action/v1`, ownership/origin/provenance/calibration fields, `DFRuntime` threading, evaluator on schema, stewardship vector for staged seeds, calibration + independent review | Schema CI; ownership from fields, reconstruction deleted; population axis `validated` or explicitly not | 8–12 wk | M1–M3 |
| M5 | Replicated multi-crisis campaign (provisional) | Sized from E1: e.g. 3 arms × 1–2 seeds × (2 fixtures + control) × R 8–12 | Provisional report per spec §9 | 3–4 wk; **≈ $1.3k–3.0k per seed** (72–108 runs at $18–28) | M4, funding |
| M6 | Ranked cells + public replay | Held-out schedule split, ≥3–5 seeds, stratified rule (spec amendment), replay markers | First ranked cell (spec §9) | 3–4 wk | M5 |

**Sequencing.** M0 costs nothing and is time-critical (single-copy evidence,
single-copy reviewed tip, vanished source). M1a answers "can two DF processes
coexist" for the price of a coffee before three weeks of refactoring. First
paid signal is E1 at week ~7–8, not 12–18. Infrastructure is ≲1 % of any
campaign (an 8-vCPU spot host is cents per hour against $600+ of model spend):
burst, don't buy; keep the e2-standard-2 for the site/API; size in two columns
(scripted duty cycle = CPU ceiling; LLM duty cycle ≈ 22 % DF = packing).

**Protocol change log** (`docs/PROTOCOL_CHANGELOG.md`, M0): one entry per
version — v3, v4, v5 from WDSLL/FINDINGS evidence — plus two **pre-declared**
entries, g8-v1 (M2: fixtures, population sensor, key v2) and g8-v2 (M4: state
contract), each frozen before its first arm and revised only for a demonstrated
measurement defect, itself logged. The honest record is four versions and zero
valid model results; the log is how that reads as rigor, not churn.

**Branch and G7-v5.** The PR to `main` is a **measurement-code PR** — the full
G7-v5 stack, 17 digest-bound files, ~5.2k insertions over `origin/main`,
unchanged since `ccfac2c93` — review it as such. **v5 re-locks at M1b, not M4**
(config.py, seed_reset.py, runner.py, encoder.py are digest-bound; the digest
reads paths unguarded, so a moved file crashes rather than re-digests — hooks
are copied, never moved, and a clear-error guard is added). The
`g7v5-reviewed-tip` tag is the guarantee: the paid pair, if funded, runs from a
scratch checkout at `ccfac2c93` whatever M1b does. Prod deploy stays go/no-go
§7f, never bundled into a milestone approval.

## 7. Risks and open questions (residual)

| Risk / question | Kind | Mitigation or owner |
|---|---|---|
| Patch series cannot be reconstructed from upstream | blocker | M0 branch (b): binary-seeded image, disclosed as such |
| Bay 12 redistribution terms unsourced; 0.47.05 tarball URL unverified | licensing | Vendored checksum-pinned copy; private images; **Chris confirms** |
| Native `migrant_wave` (staged pre-wave save) may not reproduce a wave in-window | technical | Spike; if it fails no population fixture ships — never `create-unit` |
| $23.30 spendable; other keys drain ~$23/day | cost | Ring-fenced key per campaign; kill switch demonstrated first |

## 8. Non-goals and firewalls

- Not an RL environment; no reward shaping or gym API. No engine
  modification, DF source, or 50.x migration; no Hard/Discovery work; no
  per-dwarf control; no public DF image; no direct Anthropic API and no
  Anthropic arm beyond the approved OpenRouter Fable exception.
- No new leaderboard scalar; the ordinal PASS-count is published only beside
  the full vector and UNKNOWN-count.
- No re-ranking or re-scoring of v3/v4/v5. **Correcting a provenance label is
  not re-scoring and is required** (erratum, M0). No change to v5 unlock,
  verdict or eligibility semantics.
- **Narrative firewall.** G7-v3's Fable/Sol pair is motivation only. No g8
  report may say "confirms", "consistent with", "replicates" or "as previously
  found" of it; any joint mention restates n=1, one seed, Sol ineligible, in
  the same sentence.

## 9. Decisions requested from Chris

1. **Approve the direction** — four pillars as amended (§4), the fixture
   contract with seven tests and no-false-debit, the endpoint/R rules (§5) —
   knowing R ≥ 8 raises the price of every comparison in exchange for results
   that survive review.
2. **Approve M0 + M1a now**: $0 + ≤$5, no prod contact, no paid model calls;
   includes pushing branch + tags. M1b is approved by M1a's table.
3. **Fund E1** (≈$600–750; ~$370 without the control cell) on a ring-fenced
   key, or name the envelope and E1 shrinks cells, not R. Name the second arm
   (Sol-class needs the cached-token decision first).
4. **Confirm the DFHack source history** and licensing posture; if the patch
   series cannot be reconstructed, accept a binary-seeded image.
5. **Doctrine vs engineering — the v5 label.** `df_version: df-51.11` is wrong
   in digest-bound code; fixing it re-locks v5 and needs a provider-free
   re-calibration + reviewer re-stamp (hours, ~$0). (a) erratum only, fix
   forward in g8; (b) fix, re-calibrate, re-stamp before any v5 pair.
   Recommend (b) if the pair runs, else (a).
6. **Spec amendments**: §6 development/held-out to cover fixtures, schedules,
   params, profiles; §5 to admit a pre-registered stratified combination across
   seed strata (else model-level claims are impossible by construction).
7. **G7-v5 paid pair**: independent of this roadmap; run from the tagged
   reviewed tip under existing gates, or leave it calibration-complete.

## 10. Panel dispositions

IDs: D doctrine, E engineering, S science, O cost/ops; -M must, -S should. All
56 accepted (merged rows share a disposition); 4 carry a partial refutation or
correction (bold).

| Finding | Disposition | Where / why |
|---|---|---|
| D-M1 false debit | accepted | §3.4; §5 no-false-debit |
| D-M2 no empirical floor | accepted | §5 tests, four proofs |
| D-M3, E-S7 migrant_wave fabricates | accepted | §5 taxonomy, spikes |
| D-M4 df-51.11 provenance | accepted; part refuted | M0 erratum, §8; **refused for the frozen v5 key (retro-edit)**; §9.5 |
| D-M5 grep firewall | accepted | §4.3 structural capability |
| D-M6 completeness ≠ correctness | accepted | §4.2; principle 10 |
| D-S1 digest swallows registry | accepted | §5 split binding |
| D-S2, S-S16 tunables / held-out | accepted | §4.4, §5 split registry; §9.6 |
| D-S3, E-M4, S-M5 tick scheduling | accepted | §4.3, §5 scheduling |
| D-S4 fixture-failure disposition | accepted | §5 scheduling |
| D-S5 Fable/Sol narrative | accepted | §8 |
| D-S6, S-M3 R ≥ 3 | accepted | §5 statistics |
| D-S7 registry after finding | accepted | E1 exit |
| D-S8 protocol churn | accepted | §3.3; §6 change log |
| E-M1, O-M6 image unbuildable, source gone | accepted | §4.1; M0 |
| E-M2 transport undefined | accepted | §4.1; M1a exit |
| E-M3 process-per-run | accepted | §4.1; M1b; DFRuntime → M4 |
| E-M5, S-S18 taxonomy vs contract | accepted | §5 taxonomy |
| E-S1 §2 premise | accepted | §2 |
| E-S2 cpu/mem literal | accepted | §4.1 |
| E-S3, O-M5 cap no-op | accepted | §4.1; M1b |
| E-S4 seed corpus | accepted | M0 |
| E-S5 registry deletes guard | accepted | §4.3 |
| E-S6 v5 re-locks at M1 | accepted | §6 Branch |
| E-S8 estimates | accepted | §6 effort column |
| S-M1 construct validity | accepted | §1; M2 staged seeds |
| S-M2 conjunctive endpoint | accepted | §5 endpoints; M2 exit; §8 |
| S-M4 variance unmeasured | accepted | §5 E0; M1a |
| S-M6 informative censoring | accepted | §5 statistics |
| S-M7 arm control | accepted | §5 statistics |
| S-M8, O-M4 late answer / M5 unpriced | accepted | §6 E1, M5; §9.3 |
| S-S9 provider pinning | accepted | §5; M1b |
| S-S10 multiplicity | accepted | §5 endpoints |
| S-S11 proportional shock | accepted, modified | §5 absolute units; **"reduce to K days" refuted — it erases preparation** |
| S-S12 key regression | accepted | §5 comparability |
| S-S13 seeds / combination | accepted | §1, §5, M6; §9.6 |
| S-S14, O-S4 control cell / visibility | accepted | §5; E1, M1a |
| S-S15 censored recovery | accepted | §5 endpoints |
| S-S17 co-tenancy | accepted | §5; M1b |
| O-M1 rescue /var/tmp | accepted, corrected | M0; **"5-day fuse" overstated — go/no-go row 4 shows the rule commented out**; single-copy still makes it M0 |
| O-M2 tag + push | accepted | M0; header |
| O-M3 sizing / prod build | accepted | M1a |
| O-M7 prod action | accepted | M1b "prod untouched" |
| O-S1 PR framing | accepted | §6 Branch |
| O-S2 cost framing | accepted, corrected | §6 sequencing; **packing ≈ 22 % DF (E-S1), not 10×** |
| O-S3 key before M4 | accepted | `forteval/v2` in M2 |
