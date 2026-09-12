"""Verify settled native save history for ordinary portable-owner windows.

This consumes retained native receipts and saves, never a running game. It
uses the current v4 semantic save contract; historical recovery protocols
retain their dedicated auditors.
"""

from pathlib import Path
import json

from ..agent.campaign_keyboard import CodexKeyboardAgent, initial_usage
from ..agent.keyboard_exchange import digest, read
from ..agent.keyboard_prompt import BASE_PROMPT
from ..eval.campaign import read_campaign_progress
from ..eval.campaign_profile import metrics_from_state
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import reconciled_usage
from .keyboard_segment_audit import _clock, _require, verify_save_boundary, verify_saved_segment
from .keyboard_window_audit import settled_segment_spans


def trace(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def verify_trace_clocks(segment: Path, first: int, end: int) -> None:
    """Reconcile each action's calendar, not merely a whole-window tick sum."""
    before, after = read(segment / "native-before.json"), read(segment / "native-after.json")
    previous = _clock(before, "pause_state")
    rows = trace(segment / "checkpoint/trace.jsonl")
    for row in rows[first:end]:
        clock = row["tick_advance"]
        start = _clock(
            {"year": clock["start_year"], "year_tick": clock["start_tick"], "paused": True},
            "paused",
        )
        finish = _clock(
            {"year": clock["end_year"], "year_tick": clock["end_tick"], "paused": True}, "paused"
        )
        _require(
            start == previous
            and finish == _clock(row["state_after_advance"], "pause_state")
            and type(clock["ticks_advanced"]) is int
            and finish - start == clock["ticks_advanced"] >= 0,
            "Per-action native calendar is discontinuous",
        )
        previous = finish
    _require(
        len(rows) == end and previous == _clock(after, "pause_state"),
        "Final native calendar differs from the saved trace",
    )


def fresh_segment(native: Path, inputs: dict, revision: str) -> dict:
    segment = native / "segment-0"
    result, runtime = read(segment / "result.json"), read(native / "runtime-0/result.json")
    checkpoint = segment / "checkpoint"
    manifest = verify_checkpoint(checkpoint)
    payload = manifest["payload"]
    start, after = read(segment / "native-before.json"), read(segment / "native-after.json")
    initial, state = read(segment / "agent-before.json"), read(checkpoint / "agent.json")
    rows = trace(checkpoint / "trace.jsonl")
    cursor = payload["next_step"]
    origin = {
        "kind": "independent_native_snapshot/v1",
        "source_snapshot_receipt_sha256": inputs["declaration"]["source_snapshot_receipt_sha256"],
        "condition_sha256": digest(inputs["condition"]),
        "initial_memory": "empty",
        "borrowed_prior_campaign_usage": False,
    }
    agent = CodexKeyboardAgent(
        decision=lambda *args: {},
        **{
            key: inputs["condition"][key]
            for key in (
                "model",
                "reasoning_effort",
                "control_profile",
                "max_dispatches",
                "max_total_tokens",
                "max_advance_ticks",
            )
        },
    )
    agent.initialize_prompt(
        profile=inputs["condition"].get("prompt_profile", BASE_PROMPT),
        source_snapshot_receipt_sha256=origin["source_snapshot_receipt_sha256"],
    )
    agent.set_campaign_context(campaign_id=inputs["campaign_id"])
    _require(
        initial == agent.export_campaign_state(),
        "Fresh initial agent is not its declared empty prompt/configuration state",
    )
    _require(
        type(cursor) is int
        and 1 <= cursor <= inputs["limit"]
        and payload["campaign_id"] == inputs["campaign_id"]
        and payload["code_revision"] == revision
        and payload["parent_sha256"] is None
        and payload["last_committed_step"] == cursor - 1
        and result.get("schema_version") == "fortgym.keyboard-segment/v1"
        and result.get("status") == "bounded_segment_complete"
        and result.get("first_step") == 0
        and type(result.get("first_step")) is int
        and result.get("next_step") == cursor
        and result.get("checkpoint_verified") is True
        and result.get("recovery_requires_reconciliation") is False
        and result.get("campaign_id") == inputs["campaign_id"]
        and result.get("source_revision") == revision
        and result.get("origin") == read(segment / "origin.json") == origin
        and not any(k.endswith("error") or k.endswith("error_type") for k in result),
        "Fresh segment is not its settled independent checkpoint",
    )
    _require(
        runtime["experiment"] == result
        and runtime["code_revision"] == revision
        and runtime.get("source_snapshot_receipt_sha256")
        == origin["source_snapshot_receipt_sha256"]
        and all(
            runtime.get(k) is True
            for k in ("native_load_verified", "cleanup_verified", "listener_closed")
        )
        and runtime.get("remaining_live_processes") == []
        and _clock(runtime["loaded"], "paused")
        == _clock(inputs["original"]["after"], "paused")
        == _clock(start, "pause_state"),
        "Fresh native runtime did not load its bound snapshot and clean up",
    )
    _require(
        initial["memory"] == ""
        and initial["usage"] == initial_usage()
        and initial["campaign_id"] == state["campaign_id"] == inputs["campaign_id"]
        and read(segment / "history-before.json") == {"discontinuities": []}
        and read(checkpoint / "runner.json").get("discontinuities", []) == []
        and read(segment / "agent-after.json") == state
        and all(
            initial.get(k) == state.get(k)
            for k in ("configuration", "budget_extensions", "prompt_changes")
        )
        and all(inputs["condition"].get(k) == v for k, v in initial["configuration"].items()),
        "Fresh agent conditions, prompt, usage or inherited history differ",
    )
    _require(
        reconciled_usage(state, (checkpoint / "usage.jsonl").read_bytes())
        == state["usage"]
        == result["usage"]
        and all(
            type(state["usage"].get(k)) is int and state["usage"][k] == cursor
            for k in ("accounted_responses", "returned_responses", "dispatched_requests")
        ),
        "Fresh saved usage is unsettled",
    )
    _require(
        [row.get("step") for row in rows] == list(range(cursor))
        and all(
            type(row["step"]) is int
            and row.get("run_id") == inputs["campaign_id"]
            and not row.get("discontinuities", [])
            for row in rows
        ),
        "Fresh trace is not its consecutive independent history",
    )
    advanced = [row["tick_advance"]["ticks_advanced"] for row in rows]
    elapsed = _clock(after, "pause_state") - _clock(start, "pause_state")
    progress = read_campaign_progress(checkpoint / "trace.jsonl")
    _require(
        all(type(ticks) is int and ticks >= 0 for ticks in advanced)
        and sum(advanced)
        == elapsed
        == progress["elapsed_ticks"]
        == result["committed_elapsed_ticks"]
        and not (segment / "loop/failures.jsonl").exists()
        and all(
            (checkpoint / name).read_bytes() == (segment / "loop" / name).read_bytes()
            for name in ("trace.jsonl", "usage.jsonl")
        ),
        "Fresh trace, saved calendar or worker history differ",
    )
    verify_save_boundary(payload["native_save"], after)
    verify_trace_clocks(segment, 0, cursor)
    return {
        "segment_index": 0,
        "first_step": 0,
        "next_step": cursor,
        "new_responses": cursor,
        "new_tokens": state["usage"]["total_tokens"],
        "new_saved_ticks": elapsed,
        "saved_elapsed_ticks": elapsed,
        "usage": state["usage"],
        "inherited_discontinuities": [],
        "uninterrupted_campaign": True,
        "prior_checkpoint_sha256": None,
        "checkpoint_sha256": manifest["sha256"],
        "initial_metrics": metrics_from_state(start),
        "saved_metrics": metrics_from_state(after),
        "source_checkpoint_fresh_load_verified": True,
        "native_cleanup_verified": True,
        "final_fresh_reload_verified": False,
    }


def audit_native(native: Path, origin: Path, inputs: dict, revision: str) -> list[dict]:
    value, declaration = read(native / "result.json"), inputs["declaration"]
    _require(
        declaration["snapshot_profile"] == "native_menu_preserving_save/v4",
        "Run audit requires the declared v4 semantic save profile",
    )
    _require(
        read(native / "condition.json") == inputs["condition"]
        and value.get("source_revision") == revision
        and value.get("campaign_id") == inputs["campaign_id"]
        and value.get("runtime_cleanup_verified") is True
        and value.get("status") in ("completed", "paused")
        and not any(k.endswith("error") or k.endswith("error_type") for k in value),
        "Native window is not settled",
    )
    if inputs["mode"] == "fresh":
        _require(
            read(native / "trial.json") == declaration
            and value.get("schema_version") == "fortgym.keyboard-fresh-trial-result/v1"
            and value.get("source_snapshot_receipt_sha256")
            == declaration["source_snapshot_receipt_sha256"]
            and all(
                value.get(k) is True
                for k in (
                    "native_load_verified",
                    "source_snapshot_unchanged",
                    "new_checkpoint_verified",
                )
            ),
            "Fresh native result lacks its original load/save boundary",
        )
        report = fresh_segment(native, inputs, revision)
        result = read(native / "segment-0/result.json")
        _require(
            result == value["segment"]
            and (value["status"], result["stop_reason"])
            == (
                ("completed", "segment_limit")
                if report["next_step"] == inputs["limit"]
                else ("paused", "budget_limited_pause")
            ),
            "Fresh stop classification differs from its saved boundary",
        )
        return [report]
    _require(read(native / "window.json") == declaration, "Native declaration changed")
    # These derived checks do not rewrite the retained declaration or add launch gates.
    window = {
        **declaration,
        "source_native_revision": revision,
        "expected_campaign_id": inputs["campaign_id"],
        "window_end_decision": declaration["continuation_from_next_step"] + inputs["limit"],
    }
    history = read(origin / "runner.json").get("discontinuities", [])
    spans = settled_segment_spans(value, window, inherited_discontinuities=history)
    prior = origin
    rows = trace(prior / "trace.jsonl")
    metrics = metrics_from_state(rows[-1]["state_after_advance"])
    reports: list[dict] = []
    for span in spans:
        _require(
            read(native / f"segment-{span.index}/result.json") == value["segments"][span.index],
            "Native result omitted or changed a segment",
        )
        report = verify_saved_segment(
            native,
            prior,
            span,
            campaign_id=inputs["campaign_id"],
            revision=revision,
            expected_initial_metrics=metrics,
        )
        verify_trace_clocks(native / f"segment-{span.index}", span.first_step, span.next_step)
        if reports:
            reports[-1]["final_fresh_reload_verified"] = True
        reports.append(report)
        prior = native / f"segment-{span.index}/checkpoint"
        metrics = report["saved_metrics"]
    return reports
