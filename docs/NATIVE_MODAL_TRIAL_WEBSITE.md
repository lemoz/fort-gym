# Recorded dialog-trial result

The campaign page and `/public/keyboard-campaigns` now include window v's
recorded outcome after the memory-contract trial and before its saved parent
when displayed newest first. This is separate from the live owner panel.

The versioned original manifest remains unchanged. A bounded allowlisted
projection binds it to checkpoint 775 and the preceding unsaved prompt trial,
reconciling cumulative responses, tokens and loss counts across both attempts.
Private notes, screen text, prompts, memory and arbitrary extra fields are not
projected. Missing or contradictory records produce an unavailable result, not
an empty success.

The card reports four verified paused-dialog deferrals followed by model-chosen
continuation, then the host read failure and teardown. Its 12724 newly unsaved
ticks are separate from 198600 saved ticks. The final incomplete decision's time
is unknown, even though no advance was requested. The underlying read failure is
also unknown; no OOM, model-failure, newer checkpoint, sustainability or year-two
claim is substituted. Reported charge remains unreported rather than zero.

This extends the existing FastAPI/static-JavaScript page, styles and dependencies.
Renderer tests validate actual generated text and newest-first ordering without
browser visual QA. API tests cover file and predecessor boundaries, usage/loss
reconciliation, privacy and false success claims. Local HTTP acceptance also
checks that recorded history and live status are separate and admin stays disabled.
No production deployment is part of this publication change.
