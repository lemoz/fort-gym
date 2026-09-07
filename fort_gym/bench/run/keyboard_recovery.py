"""Forward-only native recovery, with no model call or gameplay replay."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..agent.keyboard_exchange import publish, read
from ..env.screen_observation import TEXT_PROFILE, encode_screen
from ..eval.campaign import read_campaign_progress
from .campaign_loop import CampaignLoop, _append, _clock
from .campaign_save import save_inventory
from .keyboard_recovery_source import SCHEMA, _bytes, _rows, inspect_recovery_source

def reconcile_loaded_tail(
    *,
    plan: dict,
    parent: Path,
    segment: Path,
    exchange: Path,
    agent,
    environment,
    snapshotter,
    output: Path,
    revision: str,
) -> dict:
    """Checkpoint the verified latest native state, retaining the failed receipt."""
    if (
        inspect_recovery_source(parent=parent, segment=segment, exchange=exchange)
        != plan
    ):
        raise ValueError("Recovery source changed after inspection")
    runtime = environment.expected_dfroot.resolve()
    if snapshotter.dfroot.resolve() != runtime:
        raise ValueError(
            "Recovery snapshotter is not bound to the loaded native runtime"
        )
    loaded_save = runtime / "data/save/campaign-resume"
    loaded_files = save_inventory(loaded_save)
    expected_files = plan["forensic_save_inventory"]
    # DFHack appends load events without rewriting any native save data.
    def without_log(values):
        return [row for row in values if row["path"] != "events-dfhack.log"]
    if without_log(loaded_files) != without_log(expected_files):
        raise ValueError("Loaded game files differ from the forensic native save")
    original_log = segment / "unreconciled-native-save/events-dfhack.log"
    if original_log.exists() and not _bytes(
        loaded_save / "events-dfhack.log"
    ).startswith(_bytes(original_log)):
        raise ValueError("Native load log does not preserve its original prefix")
    observed = environment.observe()
    if _clock(observed) != plan["year"] * 403200 + plan["year_tick"]:
        raise ValueError("Loaded native calendar differs from the failed tail")
    for retained in (parent, segment, exchange, runtime):
        if (
            output.resolve() == retained.resolve()
            or retained.resolve() in output.resolve().parents
        ):
            raise ValueError(
                "Recovery output must be outside retained inputs and runtime"
            )
    state, runner = read(segment / "agent-after.json"), read(parent / "runner.json")
    loop = CampaignLoop(
        campaign_id=plan["campaign_id"],
        agent=agent,
        environment=environment,
        output=output,
        max_advance_ticks=runner["max_advance_ticks"],
        observation_profile=runner["observation_profile"],
        advance_policy=runner["advance_policy"],
    )
    agent.restore_campaign_state(state, campaign_id=plan["campaign_id"])
    request = read(exchange / "request.json")
    failure = _rows(segment / "loop/failures.jsonl")[0]
    execution = {
        **failure["execute"],
        "tick_feedback": {
            "requested_ticks": failure["requested_ticks"],
            "ticks_advanced": 0,
            "deferred": False,
            "reason": "timeout_waiting_for_ticks",
            "failure_reconciled": True,
            "runtime_reloaded": True,
        },
    }
    screen = json.dumps(
        encode_screen(request["screen"], TEXT_PROFILE), ensure_ascii=False
    )
    row = {
        "run_id": plan["campaign_id"],
        "step": plan["failed_step"],
        "campaign_mode": True,
        "record_origin": "verified_failure_reconciliation/v1",
        "observation": {
            "observation_profile": TEXT_PROFILE,
            "screen_capture": request["screen"],
            "last_action_feedback": request["feedback"],
        },
        "observation_text": screen,
        "screen_text": screen,
        "action": failure["action"],
        "execute": execution,
        "state_after_advance": read(segment / "native-after.json"),
        "tick_advance": failure["tick_receipt"],
        "events": [
            {
                "type": "tool_call",
                "data": {
                    **event,
                    "run_id": plan["campaign_id"],
                    "step": plan["failed_step"],
                },
            }
            for event in failure["events"]
        ],
        "reconciliation": {
            "plan": plan,
            "original_failure": failure,
            "loaded_native_boundary": {
                "year": observed["year"],
                "year_tick": observed["year_tick"],
                "pause_state": True,
            },
            "original_failure_reclassified_as_success": False,
        },
    }
    with loop.journal.open("wb") as stream:
        stream.write(_bytes(segment / "loop/usage.jsonl"))
        stream.flush()
        os.fsync(stream.fileno())
    with loop.trace.open("xb") as stream:
        stream.write(_bytes(segment / "loop/trace.jsonl"))
        stream.flush()
        os.fsync(stream.fileno())
    _append(loop.trace, row)
    from .runner import _action_history_entry

    rows = _rows(loop.trace)
    loop.history = [
        _action_history_entry(
            step=item["step"],
            action=item["action"],
            requested_ticks=item["action"]["advance_ticks"],
            tick_info=item["tick_advance"],
            execute_result=item["execute"],
            state_before=rows[item["step"] - 1]["state_after_advance"]
            if item["step"]
            else {},
            advance_state=item["state_after_advance"],
            metrics_snapshot={},
        )
        for item in rows[-12:]
    ]
    loop.last_result, loop.next_step, loop.parent = execution, plan["next_step"], parent
    loop.committed_elapsed_ticks = read_campaign_progress(loop.trace)["elapsed_ticks"]
    loop.at_boundary = True
    publish(output / "recovery.json", plan)

    class VerifiedSnapshotter:
        def capture(self, destination):
            if (
                inspect_recovery_source(
                    parent=parent, segment=segment, exchange=exchange
                )
                != plan
            ):
                raise ValueError("Recovery source changed before native capture")
            saved = snapshotter.capture(destination)
            if (
                inspect_recovery_source(
                    parent=parent, segment=segment, exchange=exchange
                )
                != plan
            ):
                raise ValueError("Recovery source changed during native capture")
            if agent.export_campaign_state() != state:
                raise ValueError("Recovery changed model state during native capture")
            return saved

    checkpoint = loop.checkpoint(
        output / "checkpoint", snapshotter=VerifiedSnapshotter(), code_revision=revision
    )
    if (
        inspect_recovery_source(parent=parent, segment=segment, exchange=exchange)
        != plan
    ):
        raise ValueError("Recovery source changed during checkpoint capture")
    if agent.export_campaign_state() != state:
        raise ValueError("Recovery changed model memory, configuration or usage")
    result = {
        "schema_version": SCHEMA,
        "checkpoint_verified": True,
        "checkpoint_sha256": checkpoint["sha256"],
        "next_step": loop.next_step,
        "elapsed_ticks": loop.committed_elapsed_ticks,
        "usage": state["usage"],
        "model_calls": 0,
        "native_input_commands": 0,
        "native_ticks_requested": 0,
        "original_failure_reclassified_as_success": False,
        "original_sources_unchanged": True,
    }
    publish(output / "result.json", result)
    return result
