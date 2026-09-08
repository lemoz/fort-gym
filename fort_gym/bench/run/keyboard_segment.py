"""One resumable native keyboard segment with retained terminal evidence."""

from __future__ import annotations

from pathlib import Path

from ..agent.campaign_keyboard import CodexKeyboardAgent
from ..agent.keyboard_exchange import publish
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import CampaignLoop, CampaignPreDispatchPause
from .keyboard_config import validate_condition, positive


def run_keyboard_segment(
    *,
    agent: CodexKeyboardAgent,
    environment,
    snapshotter,
    output: Path,
    condition: dict,
    checkpoint: Path,
    latest_usage: Path,
    steps: int,
    expected_cursor: int,
    revision: str,
    budget_extension: dict | None = None,
    restart_declaration: dict | None = None,
    restart_source: Path | None = None,
) -> dict:
    """Resume only the verified loaded game; never choose or repair gameplay."""
    validate_condition(condition)
    for key in (
        "model", "reasoning_effort", "transport", "control_profile", "observation_profile",
        "max_dispatches", "max_total_tokens", "max_advance_ticks",
    ):
        if agent.configuration.get(key) != condition[key]:
            raise ValueError("Keyboard agent differs from its declared condition")
    positive(steps, "segment size", maximum=64)
    manifest = verify_checkpoint(checkpoint)
    if manifest["payload"]["next_step"] != expected_cursor:
        raise ValueError("Source checkpoint cursor differs from the declared window")
    restart = None
    if (restart_declaration is None) != (restart_source is None):
        raise ValueError("Restart source and explicit declaration are required together")
    if restart_source is not None:
        from .keyboard_restart import prepare_restart

        assert restart_declaration is not None
        restart = prepare_restart(checkpoint, restart_source, restart_declaration, latest_usage.read_bytes())
    output.mkdir(mode=0o700, exist_ok=False)
    loop = None
    result = {
        "schema_version": "fortgym.keyboard-segment/v1",
        "source_revision": revision,
        "campaign_id": manifest["payload"]["campaign_id"],
        "first_step": expected_cursor,
        "checkpoint_verified": False,
        "status": "failed",
        "stop_reason": "unsettled_failure",
        "autonomous_gameplay": True,
        "private_measurement_profile": getattr(environment, "private_measurement_profile", None),
    }
    try:
        capture = environment.screen_capture()
        if [capture["width"], capture["height"]] != condition["screen_size"]:
            raise ValueError("Actual native display differs from the declared condition")
        publish(output / "initial-screen.json", capture)
        loop = CampaignLoop.resume(
            checkpoint,
            agent=agent,
            environment=environment,
            output=output / "loop",
            latest_usage_path=latest_usage,
            observation_profile=condition["observation_profile"],
            advance_policy=condition["advance_policy"],
            budget_extension=budget_extension,
        )
        if restart is not None:
            from .keyboard_restart import apply_restart

            apply_restart(loop, restart)
            publish(output / "restart.json", restart)
            result["discontinuities"] = loop.discontinuities
        publish(output / "agent-before.json", agent.export_campaign_state())
        publish(output / "native-before.json", environment.observe())
        result["stop_reason"] = "segment_limit"
        for _ in range(steps):
            try:
                loop.step()
            except CampaignPreDispatchPause as error:
                result["stop_reason"] = "budget_limited_pause"
                result["pause_detail"] = str(error)
                break
        result["status"] = "bounded_segment_complete"
    except Exception as error:
        result.update(
            stop_reason="unsettled_failure", error_type=type(error).__name__, error=str(error)
        )
    finally:
        if loop is not None:
            if loop.discontinuities:
                result["discontinuities"] = loop.discontinuities
            result["next_step"] = loop.next_step
            result["committed_elapsed_ticks"] = loop.committed_elapsed_ticks
            result["recovery_requires_reconciliation"] = loop.failed or not loop.at_boundary
            try:
                if loop.at_boundary:
                    loop.checkpoint(
                        output / "checkpoint", snapshotter=snapshotter, code_revision=revision
                    )
                    verify_checkpoint(output / "checkpoint")
                    result["checkpoint_verified"] = True
                else:
                    # Preserve the real native tail, but never call it resumable.
                    snapshotter.capture(output / "unreconciled-native-save")
                    result["unreconciled_native_snapshot_retained"] = True
            except Exception as error:
                result.update(
                    status="checkpoint_failed",
                    checkpoint_error_type=type(error).__name__,
                    checkpoint_error=str(error),
                )
            # Retain successful and failed save checks for independent audit.
            # These private captures are not a public summary or a save retry.
            attempt = getattr(snapshotter, "attempt", None)
            if isinstance(attempt, dict) and attempt:
                try:
                    publish(output / "save-attempt.json", attempt)
                    result["private_save_attempt_retained"] = True
                except Exception as evidence_error:
                    result["save_attempt_retention_error_type"] = type(evidence_error).__name__
        try:
            publish(output / "native-after.json", environment.observe())
            publish(output / "final-screen.json", environment.screen_capture())
        except Exception as error:
            result["final_observation_error_type"] = type(error).__name__
        publish(output / "agent-after.json", agent.export_campaign_state())
        result["usage"] = agent.export_campaign_state()["usage"]
        publish(output / "result.json", result)
    return result
