# Corrected portable owner acceptance

Repeat the two-decision fresh / two-decision own-save acceptance on source
d4a54b7eb and its exact new image. The first attempt never started its game or
called a model because a Docker stderr warning contaminated the returned ID.
Keep that failed identity and all evidence. This is a new campaign identity,
not a rewrite of the frozen comparison or the failed acceptance result.

The original condition bytes, prompt, controls, seed and bounds are unchanged.
Only Docker stdout/stderr handling changed. Mandatory one-VM teardown and
fresh subscription admission remain. Native/model outputs use the existing
external project mount's owner-acceptance-v2 directory. Unique operation
evidence is under fort_gym/artifacts/portable-owner-acceptance-20260912/v2.
Continuation must bind the actual new checkpoint before launching.
