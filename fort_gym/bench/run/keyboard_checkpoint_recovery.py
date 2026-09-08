"""Recover a settled native save-validation failure without replay or usage reset."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from ..agent.keyboard_exchange import publish, read
from ..eval.campaign import read_campaign_progress
from .campaign_checkpoint import create_checkpoint, verify_checkpoint
from .campaign_loop import _clock, reconciled_usage
from .campaign_save import save_inventory
from .keyboard_recovery_source import _bytes, _rows
from .keyboard_restart import validate_discontinuities

SCHEMA = "fortgym.settled-keyboard-checkpoint-recovery/v1"
SOURCE_FILES = (
    "result.json",
    "agent-before.json",
    "agent-after.json",
    "native-after.json",
    "loop/trace.jsonl",
    "loop/usage.jsonl",
)


def compare_reloaded_observations(expected: dict, loaded: dict, *, reindex_pending: bool) -> dict:
    """Compare persisted observations, explicitly retaining derived-cache differences.

    Job metrics report connectivity as unknown while the native pathfinding
    reindex flag is set. This permits only that transition, never changed jobs,
    positions, materials, terrain, citizens or supplies. It does not run reindex.
    """
    if type(reindex_pending) is not bool:
        raise ValueError("Native pathfinding flag must be an observed boolean")
    left, right = (json.loads(json.dumps(value, allow_nan=False)) for value in (expected, loaded))
    left.pop("viewscreen_type", None)
    right.pop("viewscreen_type", None)
    changed: list[list] = []

    def walk(a, b, path=()):
        if type(a) is not type(b):
            changed.append(list(path))
        elif isinstance(a, dict):
            if set(a) != set(b):
                changed.append(list(path))
            else:
                for key in a:
                    walk(a[key], b[key], (*path, key))
        elif isinstance(a, list):
            if len(a) != len(b):
                changed.append(list(path))
            else:
                for index, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, (*path, index))
        elif a != b:
            changed.append(list(path))

    walk(left, right)
    permitted: list[list] = []
    if reindex_pending and changed:
        before = left.get("crew", {}).get("jobs", {})
        after = right.get("crew", {}).get("jobs", {})
        counts = tuple(
            "construct_building_walk_group_" + suffix
            for suffix in ("connected", "disconnected", "unknown")
        )
        valid_counts = (
            all(
                type(jobs.get(key)) is int and jobs[key] >= 0
                for jobs in (before, after)
                for key in counts
            )
            and sum(before[key] for key in counts) == sum(after[key] for key in counts)
            and after[counts[0]] == after[counts[1]] == 0
        )
        for path in changed:
            if len(path) == 3 and path[:2] == ["crew", "jobs"] and path[-1] in counts:
                if valid_counts:
                    permitted.append(path)
            elif (
                len(path) == 5
                and path[:3] == ["crew", "jobs", "entries"]
                and path[-1] in ("target_walk_group_connectivity", "walk_group_connectivity")
            ):
                old = before["entries"][path[3]][path[-1]]
                new = after["entries"][path[3]][path[-1]]
                if old in ("connected", "disconnected", "unknown") and new == "unknown":
                    permitted.append(path)
    return {
        "all_observations_equal": not changed,
        "persistent_observations_equal": all(path in permitted for path in changed),
        "pending_pathfinding_reindex": reindex_pending,
        "changed_paths": changed,
        "expected_derived_paths": permitted,
    }


def inspect_settled_checkpoint_source(*, parent: Path, segment: Path) -> dict:
    """Attest complete committed gameplay plus a copied, not yet accepted save."""
    for directory in (parent, segment, segment / "loop", segment / "checkpoint"):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Checkpoint recovery inputs must be retained regular directories")
    if (segment / "checkpoint/checkpoint.json").exists():
        raise ValueError("Source already has a checkpoint; use normal continuation")
    for filename in ("failures.jsonl", "pauses.jsonl"):
        path = segment / "loop" / filename
        if path.exists() and _bytes(path):
            raise ValueError("Unsettled or no-action tails require their own reconciliation")
    original = verify_checkpoint(parent)
    state, before, final = (
        read(parent / "agent.json"),
        read(segment / "agent-before.json"),
        read(segment / "agent-after.json"),
    )
    result, rows = read(segment / "result.json"), _rows(segment / "loop/trace.jsonl")
    first, cursor = original["payload"]["next_step"], result.get("next_step")
    if (
        state != before
        or result.get("schema_version") != "fortgym.keyboard-segment/v1"
        or result.get("status") != "checkpoint_failed"
        or result.get("stop_reason") != "segment_limit"
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not False
        or result.get("checkpoint_error") != "Native screen changed during menu-preserving save"
        or re.fullmatch("[a-f0-9]{40}", result.get("source_revision", "")) is None
        or result.get("campaign_id") != state["campaign_id"]
        or result.get("first_step") != first
        or type(result.get("first_step")) is not int
        or type(cursor) is not int
        or not first < cursor <= first + 64
        or [row.get("step") for row in rows] != list(range(cursor))
        or any(
            type(row.get("step")) is not int or row.get("run_id") != state["campaign_id"]
            for row in rows
        )
        or any(
            final.get(key) != state.get(key)
            for key in ("schema_version", "campaign_id", "configuration", "budget_extensions")
        )
    ):
        raise ValueError("Source is not one settled native checkpoint-validation failure")
    for filename in ("trace.jsonl", "usage.jsonl"):
        if not _bytes(segment / "loop" / filename).startswith(_bytes(parent / filename)):
            raise ValueError("Recovery must retain the exact checkpoint trace and usage prefix")
    inherited = validate_discontinuities(read(parent / "runner.json").get("discontinuities", []))
    tail = rows[first:]
    if (
        result.get("discontinuities", []) != inherited
        or any(
            row.get("discontinuities", []) != inherited
            or row.get("execute", {}).get("accepted") is not True
            for row in tail
        )
        or final["memory"] != tail[-1]["action"]["memory_update"]
        or reconciled_usage(final, _bytes(segment / "loop/usage.jsonl")) != final["usage"]
        or result["usage"] != final["usage"]
        or any(
            final["usage"][key] != state["usage"][key] + len(tail)
            for key in (
                "dispatched_requests",
                "returned_responses",
                "accounted_responses",
            )
        )
    ):
        raise ValueError("Recovery cannot change memory, settled responses, usage or loss history")
    native = read(segment / "native-after.json")
    if native != rows[-1]["state_after_advance"]:
        raise ValueError("Save validation changed the last committed observation")
    _clock(native)
    progress = read_campaign_progress(segment / "loop/trace.jsonl")
    if (
        progress["elapsed_ticks"] is None
        or progress["elapsed_ticks"] != result["committed_elapsed_ticks"]
    ):
        raise ValueError("Retained trace does not establish cumulative native time")
    return {
        "schema_version": SCHEMA,
        "campaign_id": state["campaign_id"],
        "source_revision": result["source_revision"],
        "parent_sha256": original["sha256"],
        "first_step": first,
        "next_step": cursor,
        "year": native["year"],
        "year_tick": native["year_tick"],
        "elapsed_ticks": progress["elapsed_ticks"],
        "usage": final["usage"],
        "discontinuities": inherited,
        "source_files": {
            name: hashlib.sha256(_bytes(segment / name)).hexdigest() for name in SOURCE_FILES
        },
        "forensic_save_inventory": save_inventory(segment / "checkpoint/game"),
    }


def recover_settled_checkpoint(
    *,
    plan: dict,
    parent: Path,
    segment: Path,
    agent,
    environment,
    snapshotter,
    native_probe,
    output: Path,
    revision: str,
) -> dict:
    """Checkpoint a freshly loaded latest save, preserving every committed row."""

    def unchanged():
        if inspect_settled_checkpoint_source(parent=parent, segment=segment) != plan:
            raise ValueError("Retained checkpoint recovery source changed")

    unchanged()
    runtime = environment.expected_dfroot.resolve()
    if snapshotter.dfroot.resolve() != runtime:
        raise ValueError("Snapshotter differs from the loaded recovery runtime")
    for retained in (parent, segment, runtime):
        if output.resolve() == retained.resolve() or retained.resolve() in output.resolve().parents:
            raise ValueError("Recovery output must be outside retained inputs and runtime")
    saved = runtime / "data/save/campaign-resume"
    files = save_inventory(saved)

    def without_log(values):
        return [row for row in values if row["path"] != "events-dfhack.log"]

    if without_log(files) != without_log(plan["forensic_save_inventory"]):
        raise ValueError("Loaded native files differ from the latest copied save")
    old_log = segment / "checkpoint/game/events-dfhack.log"
    if old_log.exists() and not _bytes(saved / "events-dfhack.log").startswith(_bytes(old_log)):
        raise ValueError("Reload changed the original load-log prefix")
    probe, observed = native_probe(), environment.observe()
    if probe.get("dfroot") != str(runtime) or probe.get("paused") is not True:
        raise ValueError("Native reindex probe belongs to a different runtime boundary")
    comparison = compare_reloaded_observations(
        read(segment / "native-after.json"), observed, reindex_pending=probe.get("pending")
    )
    if (
        _clock(observed) != plan["year"] * 403200 + plan["year_tick"]
        or not comparison["persistent_observations_equal"]
    ):
        raise ValueError("Loaded latest save differs from retained committed state")
    state, runner = read(segment / "agent-after.json"), deepcopy(read(parent / "runner.json"))
    rows = _rows(segment / "loop/trace.jsonl")
    from .runner import _action_history_entry

    runner["history"] = [
        _action_history_entry(
            step=row["step"],
            action=row["action"],
            requested_ticks=row["action"]["advance_ticks"],
            tick_info=row["tick_advance"],
            execute_result=row["execute"],
            state_before=rows[row["step"] - 1]["state_after_advance"] if row["step"] else {},
            advance_state=row["state_after_advance"],
            metrics_snapshot={},
        )
        for row in rows[-12:]
    ]
    runner["last_result"] = rows[-1]["execute"]
    agent.restore_campaign_state(state, campaign_id=plan["campaign_id"])
    if agent.export_campaign_state() != state:
        raise ValueError("Recovery model state differs before saving")
    output.mkdir(mode=0o700, exist_ok=False)
    publish(output / "recovery-plan.json", plan)
    publish(output / "native-reindex-probe.json", probe)
    publish(output / "loaded-observation.json", observed)
    publish(output / "reload-comparison.json", comparison)

    class CheckedSave:
        def capture(self, destination):
            unchanged()
            try:
                result = snapshotter.capture(destination)
            finally:
                attempt = getattr(snapshotter, "attempt", None)
                if isinstance(attempt, dict) and attempt:
                    publish(output / "save-attempt.json", attempt)
            unchanged()
            if agent.export_campaign_state() != state:
                raise ValueError("Recovery changed model state during saving")
            return result

    checkpoint = create_checkpoint(
        output / "checkpoint",
        campaign_id=plan["campaign_id"],
        agent=agent,
        snapshotter=CheckedSave(),
        trace_path=segment / "loop/trace.jsonl",
        last_committed_step=plan["next_step"] - 1,
        code_revision=revision,
        parent=parent,
        runner_state=runner,
        usage_path=segment / "loop/usage.jsonl",
    )
    unchanged()
    result = {
        "schema_version": SCHEMA,
        "checkpoint_verified": True,
        "checkpoint_sha256": checkpoint["sha256"],
        "next_step": plan["next_step"],
        "elapsed_ticks": plan["elapsed_ticks"],
        "usage": state["usage"],
        "model_calls": 0,
        "replayed_actions": 0,
        "new_ticks_requested": 0,
        "original_failure_preserved": True,
        "new_discontinuity_created": False,
    }
    publish(output / "result.json", result)
    return result
