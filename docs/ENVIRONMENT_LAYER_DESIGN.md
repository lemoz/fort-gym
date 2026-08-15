# Fort-Gym Environment Layer — design v0

Status: v0, decision-grade draft, 2026-08-15. Branch `claude/g7v5-truth-repair`
(local-only, tip `5e1229e52` when authored). Everything cited below was read
from this checkout on 2026-08-15; VM facts are quoted from
`docs/decisions/2026-08-15-fable-sol-go-no-go.md`, not re-measured here.

## 1. Purpose and the question

Chris's question, verbatim: **"How well can frontier models manage a complex
living population of people?"**

This is a frontier-model *evaluation* program, not an RL training environment.
Dwarf Fortress earns its place because the agent never controls a dwarf. It
digs, builds, orders, assigns labor, and waits; seven-then-more individuals
with their own needs, moods, labors, and relationships decide everything else.
The agent shapes conditions. That is the managerial skill worth measuring, and
a 20-year-old game nobody tuned for this benchmark supplies it with third-party
credibility, public recognizability, and emergent difficulty no bespoke sim can
buy.

Where we are: one fortress per VM (2 vCPU, `fortgym.live`), ~5 h per 200-step
run dominated by model latency, every comparison n=1, and the only paid pair on
record (G7-v3 Fable/Sol) descriptive-only because one arm was ineligible
(`docs/FORT_EVAL_SPEC.md` §5.1). G7-v5 measurement calibration is done and
independently approved; the paid pair is still NO-GO on funding and one
un-executed unlock (go/no-go packet §1).

What "good" looks like in twelve months:

- **Cells, not anecdotes.** N frontier arms (OpenRouter-routed) × M seeds × K
  declared crisis scenarios × R replicates, R ≥ 3, each cell reported as
  outcome-vector pass rates *and* crisis-response predicates with confidence
  intervals, compared only inside one condition key (§5 of the spec).
- **On real DF 0.47.05**, unmodified, DFHack as bounded transport, evidence
  first, unknown-not-fail, exactly as today.
- **Publicly replayable**: every run's trace, seed digest, fixture schedule
  digest, observation-mask digest, and container image digest visible at
  `fortgym.live/r/<token>`, with fixture markers on the replay timeline.
- **Shorter, denser runs**: 60–100 steps that contain a declared crisis
  instead of 200 uneventful steps hoping one arrives.
- **Population questions answerable from DF state**: did the model notice the
  shock, how long until the fort recovered, how many preventable deaths, what
  happened to stress — read from DF's own bookkeeping, never from a judge.

## 2. Why not rebuild

The tax of the last two months was not simulation speed. A 200-step run costs
~5 h because a max-reasoning frontier model spends ~90 s per step; DF's 2,500
ticks per step are a small fraction of that. A GPU-optimized sim would shave the
part that does not dominate and leave the part that does. The multiplier we
actually need is *parallelism* — many fortresses per box, many arms per crisis —
and that is an infrastructure problem DF does not prevent us from solving. A
from-scratch sim would also be *ours*: tuned by the benchmark's authors, with
population dynamics we invented, and it would forfeit the credibility that comes
from a game the models have read about but nobody built for them.

DF Classic 0.47.05 is freeware, not open source. We wrap, observe, and command it
through DFHack; we never modify the engine, and we cannot ship a fork. That
constraint is also the asset. **Recorded decision (Chris, 2026-08-15): stay on
DF, kill the tax, build the environment layer DF never had.** This document is
the v0 design of that layer.

## 3. Design principles (doctrine preserved)

1. **Evidence first.** Score, verdict, and crisis-response predicates derive
   only from real DF state deltas with replayable evidence. Command acceptance
   is not progress (`CLAUDE.md` "Evidence Boundaries").
2. **Unknown, never fail.** Missing or truncated evidence yields `unknown`;
   never a synthesized zero, never a pass (`eval/gates.py` v5 branch).
3. **Frozen, versioned protocols.** G7-v3 is frozen history, G7-v4 rejected,
   G7-v5 current. The environment layer ships as a *new* protocol version with
   its own calibration; it never retro-edits v5's evaluator, sensors, or
   digests (`P1_MEASUREMENT_CODE_RELATIVE_PATHS` re-locks v5 on any byte change).
4. **Fixtures perturb the world, never the measurement.** A fixture may change
   what dwarves face; it may not touch a sensor, an evaluator, or an owned
   output ledger.
5. **Disclosure.** Every fixture application, observation mask, image digest,
   and provider route is written to trace, summary, and condition key. Nothing
   is applied that the frozen manifest did not declare.
6. **No engine modification.** DFHack is a bounded, audited command transport
   (`docs/DFHack_Governed_Agent.md`); the seven governed families plus
   allowlisted `INTERACT` remain the whole legal action surface.
7. **Two planes, one firewall.** Observer plane (replay, audit) may be richer
   than agent plane; the agent sees only what the declared mask admits
   (`docs/FORT_EVAL_SPEC.md` §3).
8. **The agent shapes conditions.** No per-dwarf control action is ever added;
   population management stays indirect, which is the point of the question.
9. **Provider policy.** OpenRouter only; no Anthropic model except the
   explicitly approved OpenRouter Fable arm; pinned arm names, never env
   overrides.

## 4. Architecture — the four pillars

Starting hypothesis, challenged where it deserved it. Two amendments fall out
of reading the code: (a) the state contract must add a **population axis** —
today no sensor reads per-citizen stress, needs, or mood, so the very thing the
question asks about is unobserved; (b) fixtures must schedule by **game tick**,
not step, or arms that `WAIT` differently see the crisis at different world
times.

### 4.1 Isolation — one containerized DF+DFHack per run

**Today.** One `dfhack-headless` systemd unit runs `LD_PRELOAD=hack/libdfhack.so
./dwarfort` under an expect PTY with `PRINT_MODE:TEXT`, `DFHACK_HEADLESS=1`,
`DFHACK_DISABLE_CONSOLE=1`, RPC on `127.0.0.1:5000`
(`infra/ansible/files/dfhack-headless.{service,sh}`, `-pty.exp`,
`docs/dfhack-headless-rpc.md`). The RPC autoboot is a local 87-line C++ patch
(`infra/ansible/files/dfhack-core-autoboot.patch`) applied to a DFHack source
tree rsynced from `/Users/cdossman/dfhack-work/src/` — the in-repo Ansible does
not pin that source, and `group_vars/all.yml` still names DF 50.12 while the VM
runs 0.47.05 (r8 per `docs/Actions_Headless_Safety.md`). Every DFHack call is a
process-global: `config.py` fixes `DFROOT`/`DFHACK_RUN`, `dfhack_exec.run_dfhack`
shells to that path, `dfhack_backend.*` and every hook are module functions.
`run/seed_reset.py` copies `data/seed_saves/<seed>` → `data/save/<runtime>`,
`sudo systemctl restart dfhack-headless`, `load-save`, waits `isMapLoaded`.
`run/jobs.py:34-37` clamps dfhack parallelism to 1 for exactly this reason.
`api/server.py:1367` keeps one `_screenshot_client`, so `/screenshot` shows
whatever DF process exists. `/etc/fort-gym.env` `OPENROUTER_MODEL` once
mis-attributed every governed run (WDSLL 2026-07-03); pinned registry names
mitigate it, unpinned arms are still exposed. `seed_region2` SIGABRTs DF at boot
by mere presence in `data/save/` (WDSLL 2026-07-07). DFHack-as-`ubuntu` could not
traverse the `0750` home, so calibration ran from `/var/tmp`.

**What changes.** An OCI image `fortgym-df` built from the DF 0.47.05 Linux
tarball fetched at build time plus DFHack built from a *pinned* source ref with
the autoboot patch. One container per run: own loopback, own `DFROOT`, own
`data/save/` holding exactly one staged runtime save, own PTY. The harness gets a
per-run `DFRuntime` handle (`exec_lua`, `rpc_endpoint`, `screen`, `save_dir`)
threaded through `dfhack_exec`, `dfhack_backend`, `seed_reset`, `Executor`, and
the screenshot route; module globals go away. Container env is an allowlist:
no `OPENROUTER_MODEL`, no provider keys inside DF; the agent factory refuses
unpinned model names for protocol runs. Seed staging is the entrypoint, not a
service restart. Feasibility from repo evidence: the deployed launch already
runs without X (TEXT mode, curses font, no `DISPLAY` in the unit), needs only a
PTY, ncurses/SDL libs, and TCP loopback — all container-native; `dfhack-run`
already forces a PTY via `script` on Linux (`dfhack_exec._maybe_wrap_with_script`).

**Interface sketch** (`POST /runs` gains an `environment` block; CLI
`fort-gym env {build,up,down,ls}`):

```json
{"backend":"dfhack","model":"dfhack-governed-llm-fable5",
 "evaluation_protocol":"fort-eval-easy-p2-g8-v1",
 "environment":{"image":"fortgym-df@sha256:…","df_version":"0.47.05",
   "dfhack_ref":"0.47.05-r8+autoboot-<patchsha>","cpu":1.0,"mem_gb":3,
   "seed_save":"seed_region3_fresh",
   "seed_world_sha256":"070b10a3…8a87d","env_allowlist":"protocol_v1"}}
```

Summary/trace record `environment.image_digest`, `container_id`, and the staged
save digest next to `seed_attestation`.

**Kills**: one-fortress-per-VM, global connection, env ambush, seed-dir
hygiene, permission traversal, restart-of-shared-service, wrong-run screenshot.
**Does not**: change the action surface, evaluator, or DF; run several forts in
one DF process; publish any image.

### 4.2 State contract — one versioned state schema, one action schema

**Today.** State is assembled in layers: inline Lua in
`dfhack_exec.read_game_state()` → `StateReader.from_dfhack` whitelist →
`attach_fort_metrics`/`attach_crew_metrics`/`attach_survival_evidence` in
`runner.py` (from `hook/fort_metrics.lua`, `job_metrics.lua`, `g7_evidence.lua`,
`work_metrics.lua`) → ~6,000 lines of runner glue that *reconstructs*
ownership (`governed_owned_buildings`, `_governed_owned_room_metrics`,
`_update_governed_owned_output_progress`). Actions are validated in
`env/actions.py` and dispatched by `env/executor.py` to bounded hooks
(`dfhack_backend.ALLOWED_*`, `LABOR_WHITELIST`). The whitelist once silently
dropped `wood_usable` (WDSLL 2026-07-08); `walkable` is a bool on 0.47.05;
`BrewDrink` does not exist (brew is a `CustomReaction`). No sensor reads
per-citizen stress, needs, mood, or relationships — `job_metrics.lua` reports
labors/jobs and hunger/thirst timers only for death classification.

**What changes.** `fortgym.state/v1`: one JSON schema, one Lua reader entrypoint
(`hook/state_v1.lua`, internally composing today's readers), emitted every step
on the observer plane. Ownership and attribution become fields, not
reconstruction: entities carry `owner:{run_id,action_id}` when a governed action
created them; every action result returns `claims[]`. Sensor health is
first-class on every section (`complete`, `truncated`, `errors[]`) so `unknown`
propagates by construction. A **population axis** is added, read-only:
`citizens[]` (id, name-hash, age class, labors, current job, `stress_level`,
top unmet needs, health flags, z) and `events[]` (migrant arrival, birth,
death, tantrum, siege, season change) from DF's own announcements/incidents.
`fortgym.action/v1` formalizes the seven governed families + `INTERACT` with
their bounds. The evaluator reads the schema, not runner internals.

**Interface sketch** (abridged):

```json
{"schema":"fortgym.state/v1","tick":312400,"season":"autumn",
 "citizens":[{"id":1043,"labors":["mine"],"job":"Dig","stress":31200,
   "unmet_needs":["Drink","Pray"],"health":[]}],
 "buildings":[{"id":77,"kind":"Still","stage":"complete",
   "owner":{"run_id":"…","action_id":"a-0034"}}],
 "stocks":{"drink":58,"food":112,"wood_usable":6},
 "events":[{"tick":311000,"kind":"migrant_wave","count":6}],
 "sensor_health":{"citizens":{"complete":true},"rooms":{"complete":false,
   "truncated":true,"errors":["component_scan_cap"]}}}
```

**Kills**: Lua archaeology, ad-hoc glue, silent whitelist drops, evaluator
coupling to runner internals; makes ownership a read, not a 6,000-line proof.
**Does not**: change what counts as evidence; give the agent unit control; hand
the schema to the agent — the agent view is §4.4's mask over it.

### 4.3 Fixture library — declarable, bounded world perturbations

**Today.** Two hooks work: `hook/calibration_kill_one.lua` (lowest-id citizen,
blood to zero, native death next tick) and `hook/calibration_seed_brew_inputs.lua`
(`LIMIT=8` `MUSHROOM_HELMET_PLUMP` beside a completed Still). They are wired by
hand in `runner.py` (death after seed attestation at step 1, brew at
`P1_BREW_INPUT_FIXTURE_STEP=32`, ~L3881/L3915), gated by
`measurement_calibration_scenario`, disclosed as a
`measurement_calibration_fixture` event and summary field, digest-bound via
`P1_MEASUREMENT_CODE_RELATIVE_PATHS`, guarded by a source-text test that allows
exactly one trigger site (`tests/test_g7_evidence.py:307`). Both are
calibration-only and force `public_eligibility: ineligible`.

**What changes.** Fixtures become a registry (`fixtures/<id>/<version>/`
{`fixture.lua`, `fixture.yaml`, tests}) applied by the runner at declared
points through the `DFRuntime`. A **Scenario** is a manifest-declared schedule
of fixture applications; its digest joins the condition key. Two classes:
`measurement_calibration` (never in scored runs, as today) and
`world_perturbation` (allowed in scored runs when declared in the frozen
manifest). Scheduling is by tick. See §5.

**Interface sketch:**

```yaml
scenario: {id: drink_shock_autumn, version: 1}
fixtures:
  - {id: drink_shock, version: 1, at: {tick: 300000},
     params: {fraction: 0.6}}          # bounded in fixture.yaml: fraction<=0.75
  - {id: key_worker_death, version: 1, at: {tick: 380000},
     params: {labor: brewing}}
disclosure: {trace_event: fixture_application, summary: fixture_applications,
             condition_key_field: fixtures}
```

**Kills**: bespoke wiring per fixture, one crisis per branch, the uneventful
year, n=1-per-crisis. **Does not**: alter sensors or evaluators; spawn anything
the outcome vector credits; fire undeclared.

### 4.4 Visibility mask — observation as declared config

**Today.** `env/encoder.py::encode_observation` renders text and returns
`clean_state`, where `redact_noise` is a passthrough placeholder — `obs_json` is
the full state. The manifest names
`observation.profile: governed_structured_state_v3_owned_layout`, but no
machine artifact defines it; the observer map stays out only because nobody
attaches it; the vision minimap is built by the agent from `obs_json["fort"]`
(`agent/governed_llm.py:1570`). Visibility is prompt discipline plus encoder
choices.

**What changes.** An `ObservationProfile` is a JSON allow-list of state paths
with bounds, cadence, and render options, applied to the `fortgym.state/v1`
record to produce `agent_view`. Adapters consume only `agent_view`. Each trace
row stores both `state` (observer plane) and `agent_view` (agent plane), so a
reviewer can diff exactly what the model could see. The profile digest is the
`observation_profile` field of the condition key.

**Interface sketch:**

```json
{"profile":"population_v1","allow":["tick","season","stocks.*","citizens[*].id",
  "citizens[*].labors","citizens[*].job","citizens[*].stress_band",
  "buildings[*]","events[*]","fort.minimap"],
 "deny":["citizens[*].name_hash","observer_map","sensor_health.*.errors"],
 "bounds":{"citizens":40,"events":12,"fort.minimap":"34x34"},
 "render":{"vision_minimap":true,"text_lines_max":180}}
```

**Kills**: prompt-discipline-as-firewall; makes "vision on/off" and
"population visible" declared, digested knobs; enables Hard/Discovery later.
**Does not**: hide anything from replay or audit; change scoring.

## 5. The fixture library in depth

**Taxonomy.**

| Family | Candidates | Native mechanism (validate live on 0.47.05-r8) |
|---|---|---|
| population | `key_worker_death`, `migrant_wave`, `child_cohort` | blood-loss kill (proven); `modtools/create-unit`; unit age fields |
| provisioning | `drink_shock`, `food_shock`, `seed_loss` | bounded item removal / forbid of matching stacks |
| mood/social | `stress_spike`, `strange_mood_denied` | `soul.personality.stress_level` write on N citizens |
| environment/threat | `early_winter`, `wild_animal_attack`, `siege` | `cur_season` write; hostile unit creation |
| infrastructure | `building_loss`, `stockpile_wipe` | `dfhack.buildings.deconstruct`; item removal |

**Fixture contract.** Every fixture is: **bounded** (literal caps in
`fixture.yaml` and re-asserted in Lua; enum plus small ints only);
**single-shot or scheduled** (fires once at a declared tick, refuses to
re-fire, records `applied_tick`/`applied_step`); **scenario-gated** (the runner
refuses any fixture absent from the frozen manifest); **disclosed**
(`fixture_application` trace event with pre/post evidence, `fixture_applications[]`
in summary, `fixtures=<sha256>` in the condition key, a marker in public
replay); **digest-bound** (fixture source + params hashed; fixture files sit in
the new protocol's measurement-code list); **engine-consistent** (only DF's own
mechanisms so DF's bookkeeping follows: deaths create incident records, migrants
have souls and needs, stock drops show in `ui.tasks.food`; never a counter
edit); **fail-closed** (partial application → `fixture_application_failed`
terminal, as today); **sensor-blind** (a test asserts no fixture file references
evidence globals or sensor scripts).

**Comparability.** `condition = seed_world_sha256 + scenario digest + observation
profile + action profile + budget + evaluator version`. Same seed + same fixture
schedule = one condition key; arms group inside it; R replicates form a cell.
Tick scheduling keeps world time equal across arms even when their `WAIT`
lengths differ (agents choose `advance_ticks` ≤ 2,500). DF is not
bit-deterministic across runs; comparability is about the condition, and
replicates absorb trajectory variance — never rank on one run (spec §9).

**Crisis-response predicates** (native state, no judge; part of a new
`crisis-vector-v1`): drink_shock → ticks until drink stock regains the
pre-shock level, deaths by thirst; key_worker_death → ticks until the lost
labor is held and stalled jobs resume; migrant_wave → beds and drink per
capita after T ticks, preventable deaths; stress_spike → stress trajectory,
tantrum incidents; building_loss → ticks until an owned replacement completes.

**First five, and why.**

1. `key_worker_death` — generalizes the proven kill hook to "the citizen
   holding labor L"; tests succession. Zero new mechanism risk.
2. `drink_shock` — the provisioning sensors already exist (v5 flows, brew
   output); the eat-vs-brew race is now the *test*, not a confound.
3. `migrant_wave` — the essence of "manage a population"; forces housing and
   food scaling; the one with the most mechanism risk, so it goes third.
4. `stress_spike` — makes mood management observable; depends on the
   population sensor.
5. `building_loss` — cheap, native, and it tests rebuild under pressure.

Deferred: `siege`, `early_winter` (heavier engine-consistency questions).

**Doctrinal boundary.** Legitimate: perturbs world state through native
mechanisms, is bounded, is declared in the frozen manifest before any arm runs,
is identical across arms in a condition, is applied at a world tick (never in
reaction to an arm's behavior; a condition-triggered fixture is allowed only if
the predicate is world-state, arm-agnostic, and declared), is disclosed
everywhere, and cannot create anything the outcome vector credits or read/modify
a sensor. Cheating: spawning drink or beds, removing an obstacle for one arm,
editing a sensor or evaluator, firing undeclared or post hoc, or letting a
"helpful" calibration fixture (brew inputs) into a scored run. Fixture *and*
`measurement_calibration_scenario` on the same run remains ineligible.

## 6. Roadmap

| # | Milestone | Scope | Exit criteria (observable) | Effort | Deps | Unblocks |
|---|---|---|---|---|---|---|
| M1 | Isolation + parallelism | Image recipe in-repo (build-time DF fetch, pinned DFHack ref + autoboot patch, PTY entrypoint, seed staging); `DFRuntime` handle threaded through exec/backend/seed_reset/executor/screenshot; env allowlist; dfhack parallelism in `jobs.py`; hard per-run/per-cell expenditure cap in runner | 8 concurrent `dfhack-governed-scripted` runs on one many-core box produce 8 valid traces with identical `seed_attestation`, no cross-talk; screenshot route resolves by run_id; image digest in summary; sizing table (vCPU/RAM per fort) recorded | 2–3 wk | DF tarball access; DFHack source pin (Chris) | n>1 immediately; every later milestone |
| M2 | Fixture library v0 + population sensor | Registry, manifest schema, tick scheduling, disclosure, sensor-blind tests; the five fixtures live-validated under pause on a throwaway container; read-only `population.lua` (citizens[], events[]) attached like the other sensors | Each fixture fires once at the declared tick with pre/post evidence; a forced partial application terminates fail-closed; a scripted run under `drink_shock` shows the drop in state and recovery predicates compute | 2–3 wk | M1 for parallel validation (design can start now) | Controlled crisis comparison; short dense runs |
| M3 | Visibility mask v0 | Allow-list mask over state; `agent_view` + `state` both recorded; profiles `governed_v3_owned_layout` (reproduces today's view) and `population_v1`; adapters read only `agent_view` | Trace rows carry both planes; a test proves the adapter cannot read outside the mask; profile digest in condition key | 1–2 wk | M2 sensor for `population_v1` | Declared visibility conditions; Hard/Discovery later |
| M4 | State contract v1 + action schema | `fortgym.state/v1`, `fortgym.action/v1`, ownership fields, single reader; runner glue shrinks; new protocol `fort-eval-easy-p2-g8-v1` with its own calibration + independent review | g8-v1 calibration bundle covering the three v5 scenario analogues passes; schema validation in CI; ownership derived from schema fields with runner reconstruction deleted, not duplicated | 4–6 wk | M1–M3 | Evaluator reads a contract; population outcome vectors |
| M5 | First replicated crisis campaign (provisional) | Chris-set budget: e.g. 3–4 arms × 1–2 seeds × 5 fixtures × 3 replicates at 60–100 steps; ring-fenced key; per-cell caps | Provisional report: per-cell pass rates + crisis predicates with CIs, every run replayable with fixture markers | 3–4 wk incl. runs | M1–M4, funding | The first defensible multi-model finding |
| M6 | Ranked cells + public replay | Held-out seed split, frozen manifest, predeclared R; replay UI fixture markers; public fixture registry page | First ranked cell per spec §9 | 3–4 wk | M5 | Publishable comparisons |

**Sequencing rule.** Value lands at M1 (n>1) and M2 (crises), before the big
refactor. M4 is deliberately last of the build milestones because it moves every
digest.

**Branch and G7-v5.** `claude/g7v5-truth-repair` is local-only, 42 commits
ahead of `origin/main` at `5e1229e52`, 0 behind, `47c035f11` a direct ancestor —
a clean fast-forward. Path: push it, open a PR to `main` (docs, evidence, this
design; no measurement-code change since the reviewed tip), then branch
`claude/env-layer-m1-isolation` from it. G7-v5 is *not* a dependency of this
roadmap and this roadmap is *not* a dependency of G7-v5: v5's unlock and paid
pair stay exactly as gated in the go/no-go packet (reviewer identity, constant
flip, funding, launch approval, host). If Chris runs the pair, it must run from a
checkout at the reviewed tip, because M1 onward touches
`P1_MEASUREMENT_CODE_RELATIVE_PATHS` and re-locks v5 by digest — the correct
behavior. The environment layer's first scored protocol is `g8-v1`, calibrated
on its own.

## 7. Risks and open questions

| Risk / question | Kind | Mitigation or owner |
|---|---|---|
| DFHack build not reproducible: Ansible rsyncs a local source tree, `group_vars` names DF 50.12, `dfhack_build` role references undefined `dfhack_source_ref` | technical | M1 pins ref + patch in an in-repo image recipe; **Chris confirms the source tree/ref** |
| Fixture mechanisms unproven on 0.47.05-r8 (`create-unit`, item removal, stress write, season write) | technical | Live dry-run under pause per fixture; fail-closed; defer any that need non-native edits |
| Tick scheduling vs agent `WAIT` choices; fixture lands mid-modal | technical | Fire at the first step boundary ≥ tick with `viewscreen` attested; record applied tick |
| DF nondeterminism across replicates | technical/credibility | Replicates + CIs; never one-run ranking (spec §9) |
| Box sizing and DF single-thread CPU; RAM per fort unknown | cost/infra | Measure in M1 (sizing table is an exit criterion); box choice after measurement |
| Parallelism multiplies spend rate; today `expenditure_cap.enabled:false`, operator is the cap | cost | Hard per-run/per-cell caps in M1; ring-fenced key (go/no-go §2c) |
| Population sensor over-reads (0.47.05 stress/needs semantics) | credibility | Validate against in-game UI on a paused fort; diagnostic until calibrated in g8-v1 |
| Fixtures perceived as "tuning the game" | doctrinal/credibility | §5 contract + boundary; public registry; fixtures never in calibration-only runs |
| State-contract migration re-locks v5 | doctrinal | By design: new protocol version, frozen v5 checkout, no retro-edit |
| DF version pinning (`df=` key field) | technical | Image digest + `dfhack_ref` in condition key; DF 0.47.05 only |
| Licensing: DF Classic is freeware; **no sourced statement of Bay 12's redistribution terms exists in this repo**; DFHack's own LICENSE governs DFHack | licensing / open | Build-time fetch from bay12games.com (as Ansible does today), private images only, no public registry until **Chris confirms** the terms |
| Anthropic exposure via unpinned arms | policy | Env allowlist; agent factory refuses `anthropic*` outside the approved OpenRouter Fable arm |
| Mac is Chris's daily driver | operational | All builds and runs on the box, never locally |

## 8. Non-goals

- Not an RL training environment; no reward shaping, no gym API for training.
- No engine modification, no DF source, no DF 50.x migration.
- No Hard or Discovery interface work (fixed-pixel, primitive inputs).
- No new scalar score; no re-ranking or re-scoring of G7-v3/v4/v5.
- No per-dwarf control actions.
- No public distribution of any container image containing DF.
- No direct Anthropic API, ever; no Anthropic arm beyond the approved
  OpenRouter Fable exception.
- No change to v5 unlock, verdict, or eligibility semantics.

## 9. Decision requested from Chris

1. **Approve the direction**: stay on DF, build the environment layer as the
   four pillars amended by §4 (population axis; tick-scheduled fixtures;
   contract ships as protocol `g8-v1`).
2. **Approve M1 now** (isolation + parallelism), with the box decision deferred
   to M1's measured sizing table.
3. **Approve the first five fixtures** in §5 for live validation.
4. **Approve pushing `claude/g7v5-truth-repair` and opening the PR** to `main`.
5. **Confirm the DFHack source tree/ref to pin** and the licensing posture
   (build-time fetch, private images) as an open question you own.
6. **Decide G7-v5's paid pair independently**: run it from the reviewed tip
   under the existing gates, or leave it as measurement-calibration-complete
   without a paid pair. Neither choice blocks this roadmap.
