"""Evidence for explicit loss after a partial keyboard interruption and pending save.

This validates retained files only. It never settles the old trace, chooses a
game input, retries saving, or claims forward recovery of unsaved game state.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..agent.keyboard_exchange import read
from ..agent.standard_input import parse_response
from ..env.native_key_catalog import NATIVE_PROFILE
from ..tick_receipt import validate_clean_interruption_receipt
from .campaign_save import CampaignSaveError
from .keyboard_save_probe import validate_identity_probe

PARTIAL_KIND = "partial_interruption_pending_save"
PARTIAL_STAGE = "identity_after_save_request_pending"
PARTIAL_FIELDS = frozenset(
    {
        "failure_kind",
        "source_failure_sha256",
        "source_runtime_sha256",
        "lost_uncommitted_ticks",
        "lost_uncommitted_decisions",
    }
)


def _hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Partial restart evidence must be a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_partial_discontinuity(row: dict) -> None:
    if (
        row.get("failure_kind") != PARTIAL_KIND
        or row.get("save_failure_stage") != PARTIAL_STAGE
        or type(row.get("lost_uncommitted_decisions")) is not int
        or row["lost_uncommitted_decisions"] != 1
        or type(row.get("lost_uncommitted_ticks")) is not int
        or not 0 < row["lost_uncommitted_ticks"] <= 2550
        or type(row.get("lost_elapsed_ticks")) is not int
        or row["lost_elapsed_ticks"] < row["lost_uncommitted_ticks"]
        or any(
            not isinstance(row.get(key), str) or re.fullmatch(r"[a-f0-9]{64}", row[key]) is None
            for key in ("source_failure_sha256", "source_runtime_sha256")
        )
    ):
        raise ValueError("Partial restart lacks its accounted uncommitted failure")


def _post_input(failure: dict, action: dict, root: str, save_name: str) -> dict:
    execution = failure.get("execute", {})
    result = execution.get("result", {})
    keys = action["params"]["keys"]
    receipts = result.get("native_receipts")
    if (
        execution.get("accepted") is not True
        or result.get("schema_version") != "fortgym.campaign-keyboard-execution/v1"
        or result.get("ok") is not True
        or result.get("command_mutation") != "completed"
        or result.get("control_profile") != NATIVE_PROFILE
        or not keys
        or any(
            type(result.get(key)) is not int or result[key] != len(keys)
            for key in ("keys_sent", "keys_confirmed")
        )
        or not isinstance(receipts, list)
        or len(receipts) != len(keys) + 1
    ):
        raise ValueError("Partial restart lacks complete model-selected input receipts")
    before = failure["native_before"]
    for index, item in enumerate(receipts):
        if (
            not isinstance(item, dict)
            or item.get("schema_version") != "fortgym.campaign-keyboard-native/v1"
            or item.get("ok") is not True
            or item.get("mode") != ("key" if index else "probe")
            or type(item.get("keys_sent")) is not int
            or item["keys_sent"] != int(index > 0)
            or item.get("command_mutation") != ("completed" if index else "not_attempted")
            or (index and item.get("key") != keys[index - 1])
        ):
            raise ValueError("Partial restart has an incomplete native key receipt")
        for boundary in (item.get("before"), item.get("after")):
            if not isinstance(boundary, dict) or (
                boundary.get("dfroot") != root
                or boundary.get("save_name") != save_name
                or boundary.get("paused") is not True
                or type(boundary.get("year")) is not int
                or boundary["year"] != before["year"]
                or type(boundary.get("year_tick")) is not int
                or boundary["year_tick"] != before["year_tick"]
            ):
                raise ValueError("Partial restart input crossed its paused native calendar")
    last = receipts[-1]["after"]
    if last.get("viewscreen_type") != "<type: viewscreen_dwarfmodest>":
        raise ValueError("Partial restart lacks the recorded post-input gameplay screen")
    return {
        "year": last["year"],
        "year_tick": last["year_tick"],
        "time": last["year_tick"],
        "pause_state": True,
        "viewscreen_type": "viewscreen_dwarfmodest",
    }


def _pending_save(segment: Path, native: dict, root: str, save_name: str) -> str:
    from .campaign_loop import _clock

    path = segment / "save-attempt.json"
    digest = _hash(path)
    attempt = read(path)
    if attempt.get("schema_version") != "fortgym.native-menu-save-attempt/v1":
        raise ValueError("Partial restart lacks a retained menu-save attempt")
    before = validate_identity_probe(
        json.loads(attempt["identity_before_raw"]), Path(root), identified=True
    )
    operation = json.loads(attempt["save_operation_raw"])
    if (
        before != attempt.get("identity_before")
        or before["native_boundary"]["save_name"] != save_name
        or before["stack"][0]["type"] != "<type: " + native["viewscreen_type"] + ">"
        or "capture_errors" in attempt
        or "copied_native_save" in attempt
        or operation.get("schema_version") != "fortgym.native-menu-save/v4"
        or operation.get("ok") is not True
        or "error" in operation
        or operation.get("menu_stack_restored") is not False
        or operation.get("backup_setting_restored") is not True
        or type(operation.get("gameplay_keys_sent")) is not int
        or operation["gameplay_keys_sent"] != 0
        or type(operation.get("native_logic_calls_requested")) is not int
        or operation["native_logic_calls_requested"] != 1
        or operation.get("native_before") != before["native_boundary"]
        or operation.get("native_after")
        != {**before["native_boundary"], "autosave_requested": True}
        or operation.get("original_stack") != before["stack"]
        or operation.get("ui_before") != before["ui"]
        or operation.get("ui_after") != before["ui"]
        or "save_operation" in attempt
        or "identity_after" in attempt
        or not isinstance(attempt.get("identity_after_raw"), str)
        or re.match(
            r"^\(lua command\):[0-9]+: Identity probe requires a paused fortress with no pending save\nstack traceback:\n",
            attempt["identity_after_raw"],
        )
        is None
        or attempt.get("world_after") != native
        or attempt.get("screen_after") != read(segment / "final-screen.json")
        or _clock(attempt["world_before"]) != _clock(native)
        or (before["native_boundary"]["year"], before["native_boundary"]["year_tick"])
        != (native["year"], native["year_tick"])
    ):
        raise ValueError("Partial restart does not identify this pending-save failure stage")
    return digest


def inspect_partial_failure(
    segment: Path,
    checkpoint: Path,
    result: dict,
    returned: dict,
    tail: list[dict],
    latest: bytes,
) -> dict:
    """Reject malformed source structures through the restart validation boundary."""
    try:
        return _inspect_partial_failure(segment, checkpoint, result, returned, tail, latest)
    except (
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        CampaignSaveError,
    ) as error:
        raise ValueError("Partial restart evidence is incomplete or malformed") from error


def _inspect_partial_failure(
    segment: Path,
    checkpoint: Path,
    result: dict,
    returned: dict,
    tail: list[dict],
    latest: bytes,
) -> dict:
    from .campaign_loop import _clock

    failure_path = segment / "loop/failures.jsonl"
    failure_digest = _hash(failure_path)
    raw = failure_path.read_bytes()
    failures = [json.loads(line) for line in raw.splitlines()]
    if not raw.endswith(b"\n") or len(failures) != 1 or not tail:
        raise ValueError("Partial restart requires exactly one retained uncommitted failure")
    failure = failures[0]
    if (
        type(failure.get("step")) is not int
        or failure["step"] != result["next_step"]
        or failure.get("error_type") != "ValueError"
        or failure.get("message") != "Native tick operation did not finish or interrupt cleanly"
        or result.get("error_type") != "ValueError"
        or result.get("error") != failure["message"]
        or result.get("checkpoint_error") != "Native menu identity probe returned malformed JSON"
        or result.get("private_save_attempt_retained") is not True
    ):
        raise ValueError("Partial restart does not match its original clock and save failure")
    initial = read(checkpoint / "agent.json")
    runner = read(checkpoint / "runner.json")
    inherited = runner.get("discontinuities", [])
    if (
        read(segment / "agent-before.json") != initial
        or returned.get("budget_extensions") != initial.get("budget_extensions")
        or result.get("discontinuities", []) != inherited
        or any(row.get("discontinuities", []) != inherited for row in tail)
    ):
        raise ValueError("Partial restart changed prior memory, limits or loss history")
    events = failure.get("events", [])
    if len(events) != 1 or events[0].get("type") != "codex_keyboard_decision":
        raise ValueError("Partial restart lacks its retained model response")
    decision = events[0]["receipt"]
    action = parse_response(
        failure["action"],
        max_advance_ticks=initial["configuration"]["max_advance_ticks"],
        control_profile=NATIVE_PROFILE,
    )
    receipt = decision["transport_receipt"]
    journal = [
        json.loads(line)
        for line in latest[len((checkpoint / "usage.jsonl").read_bytes()) :].splitlines()
    ]
    completed = [row for row in journal if row.get("type") == "decision_finished"]
    if (
        decision.get("action") != action
        or decision.get("action_grammar_valid") is not True
        or returned.get("memory") != action["memory_update"]
        or receipt.get("accepted") is not True
        or receipt.get("dispatched") is not True
        or receipt.get("model_requested") != initial["configuration"]["model"]
        or receipt.get("reasoning_effort_requested") != initial["configuration"]["reasoning_effort"]
        or [row.get("step") for row in completed]
        != list(range(result["first_step"], result["next_step"] + 1))
        or completed[-1].get("decision_returned") is not True
        or completed[-1].get("usage") != returned["usage"]
        or returned["usage"]["total_tokens"] - completed[-2]["usage"]["total_tokens"]
        != receipt.get("total_tokens")
    ):
        raise ValueError("Partial restart discarded or changed the uncommitted response usage")
    runtime_path = segment.parent / ("runtime-" + segment.name.split("-")[1]) / "result.json"
    runtime = read(runtime_path)
    if (
        runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
        or runtime.get("code_revision") != result["source_revision"]
        or runtime.get("experiment") != result
        or runtime.get("source_checkpoint_file_sha256") != _hash(checkpoint / "checkpoint.json")
        or runtime.get("native_load_verified") is not True
        or runtime.get("cleanup_verified") is not True
        or runtime.get("listener_closed") is not True
        or runtime.get("remaining_live_processes") != []
    ):
        raise ValueError("Partial restart lacks identified source runtime teardown")
    root, save_name = runtime["loaded"]["dfroot"], runtime["loaded"]["save_name"]
    parent = read(checkpoint / "checkpoint.json")["payload"]
    saved = parent["native_save"]
    previous = saved["year"] * 403200 + saved["year_tick"]
    for row in tail:
        span = row["tick_advance"]
        start, end = (
            span["start_year"] * 403200 + span["start_tick"],
            _clock(row["state_after_advance"]),
        )
        if (
            start != previous
            or type(span["ticks_advanced"]) is not int
            or span["ticks_advanced"] < 0
            or end - start != span["ticks_advanced"]
            or end != span["end_year"] * 403200 + span["end_tick"]
        ):
            raise ValueError("Partial restart committed trace calendar is inconsistent")
        previous = end
    from ..eval.campaign import read_campaign_progress

    if (
        result.get("committed_elapsed_ticks")
        != read_campaign_progress(segment / "loop/trace.jsonl")["elapsed_ticks"]
    ):
        raise ValueError("Partial restart committed progress differs from its trace")
    post_input = _post_input(failure, action, root, save_name)
    native, tick = read(segment / "native-after.json"), failure["tick_receipt"]
    before = {**failure["native_before"], "time": failure["native_before"]["year_tick"]}
    after = {**failure["native_after"], "time": failure["native_after"]["year_tick"]}
    if (
        failure.get("requested_ticks") != action["advance_ticks"]
        or _clock(before) != _clock(tail[-1]["state_after_advance"])
        or _clock(after) != _clock(native)
        or after["viewscreen_type"] != native["viewscreen_type"]
        or type(tick.get("ticks_advanced")) is not int
        or tick["ticks_advanced"] <= 0
        or validate_clean_interruption_receipt(
            tick,
            requested_ticks=action["advance_ticks"],
            state_after_apply=before,
            state_after_advance=after,
        )
        != "interrupt_baseline_mismatch"
        or validate_clean_interruption_receipt(
            tick,
            requested_ticks=action["advance_ticks"],
            state_after_apply=post_input,
            state_after_advance=after,
        )
        is not None
    ):
        raise ValueError("Partial restart is not the attested post-input clock-baseline mismatch")
    return {
        "failure_kind": PARTIAL_KIND,
        "save_failure_stage": PARTIAL_STAGE,
        "source_save_attempt_sha256": _pending_save(segment, native, root, save_name),
        "source_failure_sha256": failure_digest,
        "source_runtime_sha256": _hash(runtime_path),
        "lost_uncommitted_decisions": 1,
        "lost_uncommitted_ticks": tick["ticks_advanced"],
    }
