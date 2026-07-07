# Score-v3 proposal (OPERATOR REVIEW — not yet ratified)

Status: PROPOSED 2026-07-06. Nothing here is active. Per the WDSLL
non-negotiables, score-matrix changes require operator approval before any
gate attempt runs under them. On ratification this lands as one version
boundary (`score_version: 3`), with a WDSLL corrections-log entry; every
prior run stays v1/v2 and is not comparable across the boundary.

## Evidence forcing the change

1. **Legacy-plan complexity payments.** `complexity_score` (weight 15 in the
   scalar) and the rubric's `fortress_breadth`/`plan_coherence` dimensions
   still pay from the retired `two_room_workshop` plan rectangles. An agent
   that builds real rooms anywhere else earns zero from them — the scoring
   layer silently punishes exactly the plan-agnostic play the gates now
   require, and on a fresh seed (G6) those fields read garbage. Confirmed by
   adversarial review 2026-07-05; rubric half already built as draft PR #37.
2. **Goodhart-by-monoculture.** Endurance probe `ad70df06` (250 steps):
   after finishing one room at step 98, the agent produced **26 chairs for
   13 dwarves** over ~150 steps and scored 5.35× its step-100 mark. Every
   chair is real world-change — v2's fake-progress defenses held — but v2
   pays real production linearly, so the optimal long-horizon policy is
   mass-producing the cheapest item instead of building. The score should
   pay for a fortress, not a chair factory.

## The three changes

### 1. Demand-capped production utility (replaces linear per-item payment)

Produced-goods deltas remain the only production that pays (v2 rule kept:
queues earn nothing). New: each item type pays full value only up to the
fort's demand, defined as current population; surplus pays 20%.

```
paid_delta(type) = full_rate * min(new_items, max(0, population - items_already_paid_at_full))
                 + surplus_rate * remaining_new_items
full_rate = 1.0, surplus_rate = 0.2   (per item, per type, cumulative over the run)
```

Chair #1 through #13 (at pop 13) pay 1.0; chair #14 onward pays 0.2. Beds,
doors, tables, chairs, barrels, bins all capped the same way. Workshop
usability payments unchanged from v2.

### 2. Plan-agnostic complexity (scalar) + rubric dims

- Scalar `complexity_score` inputs move from `fortress_complexity_*`
  (legacy rects) to the flood-fill facts: `fort_functional_rooms`,
  `fort_enclosed_spaces`, and capped `fort_constructions`. Weight stays 15;
  exact coefficients set during implementation against the calibration
  table (below) so magnitudes stay comparable.
- Rubric `fortress_breadth`/`plan_coherence`: adopt draft PR #37 as-is
  (breadth keys on real structure evidence; coherence pays
  `min(fort_functional_rooms, 2) * 2.0`).

### 3. Calibration appendix + rubric-bar review (implementation requirement)

Before v3 ships, the scorer runs offline over the existing recorded traces
(runs 1–9 of the G4 lineage plus the G2/G3 passes and the DeepSeek exploit
run) producing a v2-vs-v3 table in the PR. Two acceptance checks:
- the DeepSeek exploit run and the chair-factory probe must both rank below
  every G4-passing run under v3;
- the parked question of the rubric ≥70 gate bar (calibrated on v1-scale
  inputs) gets re-examined against the same table, with any bar change
  proposed separately — changing a gate threshold is its own operator
  decision, never bundled silently.

## What does not change

Evidence boundaries, provenance gating, gameplay-proof rules, all gate
criteria, the replay/trace format, and every recorded score. v3 is a
scoring lens, not a measurement change.
