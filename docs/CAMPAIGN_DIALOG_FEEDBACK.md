# Nonfatal feedback on blocking native dialogs

The recorded reasoning-budget campaign reached a liaison meeting at native year
30, tick 220,140. Its next model-selected WAIT requested 2,500 ticks. The native
clock refused the already-blocking baseline, advanced zero ticks, and stayed
paused. The campaign loop treated that invalid choice as an unresolved failure.
See the [immutable terminal result](https://github.com/lemoz/fort-gym/blob/db4556fe1744e432f8e0c619dcc44e1e065f27b1/experiments/evidence/local_native_qwen35_year_two_dialog_failure_20260907.json).

The native campaign adapter now returns a definite pre-dispatch rejection for
non-INTERACT commands on an observed, paused, known interactable dialog. It
records which viewscreen blocks simulation. The campaign clock policy requests
zero native time for this specific rejection, preserving the model's original
action and requested ticks in the trace. The model receives the rejection and
the dialog observation on its next decision. Invalid choices still consume their
actual returned tokens and one decision from the existing limit.

No dialog option is selected automatically. Model-selected INTERACT actions still
pass through the existing paused-state, viewscreen, operation and visible-option
validation, with advance_ticks=0. Ordinary preflight rejections on the fortress
screen still receive model-requested advancement. Unknown screens, uncertain
native writes, calendar inconsistencies and invalid tick receipts are not
converted into successful steps or hidden by this feedback path.

This is a new implementation, not a hot patch of the completed campaign. Its
historical source, configuration, logs, charges and failure result stay frozen.
The old checkpoint 80 does not cover the final three committed decisions, and
this code does not make it a lossless resume or erase later charged responses.

Validation uses deterministic doubles with the recorded viewscreen, native
calendar and 2,500-tick request. It proves zero native command/clock dispatch for
the invalid WAIT, visible rejection on the next decision, model-selected
interaction, subsequent advancement and cumulative usage preservation. It does
not prove a real meeting can be completed, a native campaign can recover, or a
functioning fortress can reach year two. A separately declared bounded native
validation and gameplay attempt remain necessary. No deployment is included.
