# Decision record: G7-v5 measurement calibration independent review (2026-07-21)

*Recorded 2026-08-15. This document is a record of a review that already
happened; it does not itself approve, unlock, or authorize anything.*

## What was reviewed

The provider-free G7-v5 measurement calibration campaign of 2026-07-21, run at
fort_gym commit `a8de39d03da48da32110776bf84ddfcbcb2ccefc`, and its evidence
bundle `experiments/evidence/fort_eval_easy_p1_g7_v5_live_calibration.json`
(sha256 `f41f1a80b63cdc0e323cf57dc914a28fc613cf183905e29828ede298baf59598`).

Bound digests: manifest_semantic_sha256
`b85957669eb02668f965f103e42b1feaf88cdad7ecc8e45fc5eb2b78d8269cc6`;
measurement_code_sha256
`261a1fba89ce1a320a3248a37cbee26b37971ef6c2240705d6bdce51088c9b4c`;
remote_proto_runtime_sha256
`9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f`. 33/33
required regression node IDs green.

Scenarios: `calib-g7v5-owned-20260721a` (115 steps, gameplay PASS, 65 governed
brew units), `calib-g7v5-death-20260721a` (1 step, 1 authoritative death,
neglect unknown by design), `calib-g7v5-dropout-20260721a` (1 step, honest
unknowns from induced sensor loss). All three: `task_verdict=unknown`,
`public_eligibility=ineligible`, cost $0.00, shared seed_attestation sha
`9c923f9e2ee8ce25344fc88d66f54f2c0262d9f62317c1b44946cd73f6ee01e8`.

## Outcome

- **Scientific validity: APPROVE.** 3 advisories, 0 blocking findings.
- **Unlock semantics: APPROVE**, with the 12-step runbook reproduced verbatim
  below.
- Reviewer of record as stated by the review itself: `Claude Opus 4.8 —
  independent scientific-validity & provenance reviewer, 2026-07-21,
  non-authoring`. Chris has not yet designated the reviewer identity that will
  be stamped into the bundle, which is why the unlock has not been executed.
- Earlier completeness objections were raised against a stale packet and are
  resolved.

## What this review does NOT do

- It does **not** flip `P1_MEASUREMENT_CALIBRATION_COMPLETE`, which remains
  `False` in `fort_gym/bench/eval/fort_eval_easy_p1.py` (evidence sha `None`).
- It does **not** write the `independent_review` object back into the evidence
  bundle sidecar. That write-back is part of the gated `--approve` rebuild on
  the VM, not a documentation edit, and remains **deferred**.
- It does **not** authorize any spend. A paid G7-v5 run is separately gated on
  Chris's explicit approval and on funding.
- Because the campaign was provider-free (`usage.calls==0`), validity and
  provenance are UNKNOWN by design. An APPROVE here means the *measurement* is
  sound; it is not a policy-capability claim.

## Unlock runbook (recovered verbatim from the unlock-semantics review)

Reproduced exactly as written by the reviewer. Do not paraphrase or reorder
these steps; the order rationale at the end explains why each check stays green.

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
