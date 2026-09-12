"""Independent keyboard campaigns from a verified loaded starting snapshot.

The runtime owner verifies/copies/loads the snapshot and supplies its receipt.
This runner never borrows an older model's memory, usage, actions or campaign ID.
Once a first segment saves, normal keyboard continuation owns subsequent play.
"""

from pathlib import Path
import re

from ..agent.campaign_keyboard import CodexKeyboardAgent, initial_usage
from ..agent.keyboard_exchange import digest, publish
from ..agent.keyboard_prompt import BASE_PROMPT
from .campaign_loop import CampaignLoop, _clock
from .keyboard_config import positive, validate_condition
from .keyboard_segment import play_segment_steps, retain_segment_terminal


def run_keyboard_trial(
    *,
    agent: CodexKeyboardAgent,
    environment,
    snapshotter,
    output: Path,
    condition: dict,
    campaign_id: str,
    steps: int,
    source_snapshot_receipt_sha256: str,
    loaded_boundary: dict,
    revision: str,
) -> dict:
    """Start one explicitly independent trial after verified native loading."""
    validate_condition(condition)
    positive(steps, "initial segment size", maximum=64)
    if not isinstance(campaign_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,99}", campaign_id
    ):
        raise ValueError("Fresh trial needs a literal campaign identity")
    if not isinstance(source_snapshot_receipt_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", source_snapshot_receipt_sha256
    ):
        raise ValueError("Fresh trial requires the verified source snapshot receipt")
    if (
        agent.campaign_id is not None
        or agent.memory
        or agent.events
        or agent.prompt_changes
        or agent.budget_extensions
        or agent.usage != initial_usage()
    ):
        raise ValueError("Fresh trial cannot reuse or reset an existing agent")
    for key, value in agent.configuration.items():
        if condition.get(key) != value:
            raise ValueError("Fresh trial agent differs from its declared condition")
    if not isinstance(loaded_boundary, dict):
        raise ValueError("Loaded starting boundary must be explicit")
    expected = {
        "year": loaded_boundary.get("year"),
        "year_tick": loaded_boundary.get("year_tick"),
        "pause_state": loaded_boundary.get("paused"),
    }
    _clock(expected)
    output.mkdir(mode=0o700, exist_ok=False)
    result: dict = {
        "schema_version": "fortgym.keyboard-segment/v1",
        "source_revision": revision,
        "campaign_id": campaign_id,
        "first_step": 0,
        "checkpoint_verified": False,
        "status": "failed",
        "stop_reason": "unsettled_failure",
        "autonomous_gameplay": True,
        "private_measurement_profile": getattr(environment, "private_measurement_profile", None),
        "origin": {
            "kind": "independent_native_snapshot/v1",
            "source_snapshot_receipt_sha256": source_snapshot_receipt_sha256,
            "condition_sha256": digest(condition),
            "initial_memory": "empty",
            "borrowed_prior_campaign_usage": False,
        },
    }
    loop = None
    try:
        before = environment.observe()
        if _clock(before) != _clock(expected):
            raise ValueError("Fresh trial game differs from its verified loaded source")
        screen = environment.screen_capture()
        if [screen["width"], screen["height"]] != condition["screen_size"]:
            raise ValueError("Actual native display differs from the declared condition")
        publish(output / "initial-screen.json", screen)
        publish(output / "native-before.json", before)
        agent.initialize_prompt(
            profile=condition.get("prompt_profile", BASE_PROMPT),
            source_snapshot_receipt_sha256=source_snapshot_receipt_sha256,
        )
        loop = CampaignLoop(
            campaign_id=campaign_id,
            agent=agent,
            environment=environment,
            output=output / "loop",
            max_advance_ticks=condition["max_advance_ticks"],
            observation_profile=condition["observation_profile"],
            advance_policy=condition["advance_policy"],
        )
        publish(output / "agent-before.json", agent.export_campaign_state())
        publish(output / "history-before.json", {"discontinuities": []})
        publish(output / "origin.json", result["origin"])
        play_segment_steps(loop, steps, result)
    except Exception as error:
        result.update(
            stop_reason="unsettled_failure", error_type=type(error).__name__, error=str(error)
        )
    finally:
        retain_segment_terminal(
            loop=loop,
            agent=agent,
            environment=environment,
            snapshotter=snapshotter,
            output=output,
            result=result,
            revision=revision,
            fresh_start=True,
        )
    return result
