# DFHack-Governed Fortress Agent

## Goal

The governed path makes DFHack the command transport, not a cheat engine. The
agent issues bounded overseer commands that a human player could issue through
the UI, then the simulation must advance and produce observable state changes.
The UI remains useful for replay and inspection, but it is no longer the primary
control surface for this path.

## Legal Gameplay Boundary

Legal actions:

- Designate bounded dig/channel work.
- Place bounded buildings that create normal construction/jobs.
- Queue bounded manager or workshop production orders.
- Create stockpiles, zones, labor/admin assignments, and alerts once backed by
  audited helpers.
- Wait for a chosen number of ticks so dwarves can perform the work.

Illegal actions:

- Directly create items, material, food, drink, wealth, or dwarves.
- Instantly complete mining, construction, hauling, or production.
- Teleport units, mutate stocks, or write score state.
- Give mechanical score credit to `dfhack_assisted` debug helpers.

`hook/complete_dig_rect.lua` stays available only for explicit harness debugging.
It must not be treated as legal fortress gameplay.

## First Agent

`dfhack-governed-scripted` is the first governed model. It is intentionally
scripted so the runner and evaluator can prove the command substrate before an
LLM policy uses the same action surface.

The current plan is:

1. Dig the starter room.
2. Dig the connector east of the starter room.
3. Dig the workshop room.
4. Place a carpenter workshop in the completed workshop room.
5. Queue a small bed order.
6. Wait while dwarves resolve queued jobs.

The runner marks this model's structured `DIG`, `BUILD`, `ORDER`, and `WAIT`
actions as `dfhack_governed`, while older structured DFHack agents still get
`dfhack_assisted` progress zeroed for scalar scoring.

## Rubric Evaluation

The scalar score remains useful telemetry, but it is not enough. `summary.json`
now includes a `rubric` object over the last 100 trace rows with dimensions for:

- survival management
- shelter layout
- production economy
- fortress breadth
- responsiveness
- plan coherence
- anti-repetition
- legal evidence

The rubric returns a 0-100 score, per-dimension evidence, blockers, and a short
critique. It is designed to flag exactly the failure mode where score rises while
the fort stays narrow, repetitive, or non-legal.

## Next Helpers

The next action helpers should be added only after their legal semantics are
clear:

- bounded stockpile creation
- bounded activity zone creation
- labor/admin assignment through normal DF state
- richer read-only metadata for messages, announcements, jobs, units, and POIs

Each helper needs tests showing that it rejects unbounded or illegal state
mutation, and live traces showing that progress came from simulation resolution.
