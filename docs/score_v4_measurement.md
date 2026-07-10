# score-v4 stable-floor measurement boundary

Status: implemented for the post-Attempt-10 candidate on 2026-07-10.

## Why the boundary exists

G7 Attempt 10 proved that DF 0.47.05 frozen liquid is floor-shaped while
frozen. The observation, room detector, legacy work metrics, and BUILD-site
finder all counted that seasonal ice as ordinary permanent floor. A Still built
on the advertised footprint disappeared when the ice thawed into open air.

Correcting those floor counts changes inputs to work, completion, complexity,
room, and scalar calculations. Runs recorded before and after the correction
must therefore not share a leaderboard bucket even though no coefficient
changed.

## Boundary

- `score_version` advances from 3 to 4.
- Frozen liquid has its own count and `i` glyph; it contributes zero stable
  floor or enclosed-room interior credit.
- Structured BUILD helpers reject frozen liquid before mutation.
- All score-v3 artifacts remain historical and are never rewritten.
- Public leaderboards already partition by score version and seed, so v3 and v4
  results cannot aggregate together.

## G7 handling

The scalar threshold remains exactly 150. This is conservative: score-v4 only
removes transient false floor/room credit and changes no positive coefficient.
Every survival, duration, population, room, bed, rubric, legality, and evidence
predicate is unchanged. Deterministic G7 gate version 2 requires score-v4 for
new attempts and reports score-v3 attempts as version-ineligible.

