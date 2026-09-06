"""Versioned campaign clock policy; never invent a model action or requested ticks."""

ACCEPTED_ONLY = "accepted_only/v1"
MODEL_REQUESTED = "model_requested/v1"
POLICIES = {ACCEPTED_ONLY, MODEL_REQUESTED}


def requested_ticks(ticks: int, execution: dict, policy: str) -> int:
    if policy not in POLICIES:
        raise ValueError("Unsupported campaign advance policy")
    if execution.get("accepted") is True:
        return ticks
    if policy == ACCEPTED_ONLY:
        return 0
    result = execution.get("result")
    receipt = result if isinstance(result, dict) else execution
    if execution.get("accepted") is False and receipt.get("command_mutation") == "not_attempted":
        # A definite preflight rejection is still followed by the time the model
        # requested. Native pathfinding/jobs may then update while the game runs.
        return ticks
    # Transport failures, partial writes and rollback claims are not ordinary
    # preflight rejections. Preserve the failed boundary, without extra game time.
    raise ValueError("Campaign command lacks a definite accepted or preflight-rejected outcome")
