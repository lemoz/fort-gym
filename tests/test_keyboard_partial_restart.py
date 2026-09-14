"""Synthetic partial-action save failure; no native or model calls are made."""

import hashlib
import json
import shutil
from copy import deepcopy

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.env.native_key_catalog import NATIVE_PROFILE
from fort_gym.bench.run import campaign_loop
from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_partial_restart import PARTIAL_KIND, PARTIAL_STAGE
from fort_gym.bench.run.keyboard_restart import SCHEMA, validate_discontinuities
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_campaign_codex_keyboard import Environment, decision
from tests.test_keyboard_clock_boundary import BoundaryEnvironment
from tests.test_keyboard_restart import prepare
from tests.test_keyboard_runtime import CONDITION, environment, policy, saved as saved
from tests.test_keyboard_save_dfhack import identified_receipt


@pytest.fixture
def partial(tmp_path, saved, monkeypatch):
    return pending_failure(tmp_path, saved, monkeypatch)


def pending_failure(tmp_path, saved, monkeypatch, *, modal=False, prompt_changed=False, restart=None):
    checkpoint, usage, tick = saved
    source = tmp_path / "partial-source"
    source.mkdir(parents=True)
    native = source / "runtime-0/runtime"

    class PartialEnvironment(BoundaryEnvironment):
        def screen_capture(self):
            return environment().screen_capture()

        def apply(self, action, state):
            super().apply(action, state)
            if modal and len(self.actions) == 3:
                self.view = "viewscreen_topicmeetingst"
            boundary = {
                "dfroot": str(native),
                "save_name": "fixture",
                "year": 30,
                "year_tick": self.tick,
                "paused": True,
                "viewscreen_type": "<type: " + self.view + ">",
                "focus": "topicmeeting" if modal and len(self.actions) == 3 else "dwarfmode/Default",
            }
            keys = action["params"]["keys"]
            receipts = []
            for index in range(len(keys) + 1):
                item = {
                    "schema_version": "fortgym.campaign-keyboard-native/v1",
                    "ok": True,
                    "mode": "key" if index else "probe",
                    "keys_sent": int(index > 0),
                    "command_mutation": "completed" if index else "not_attempted",
                    "before": deepcopy(boundary),
                    "after": deepcopy(boundary),
                }
                if index:
                    item["key"] = keys[index - 1]
                receipts.append(item)
            return {
                "accepted": True,
                "result": {
                    "schema_version": "fortgym.campaign-keyboard-execution/v1",
                    "ok": True,
                    "control_profile": NATIVE_PROFILE,
                    "command_mutation": "completed",
                    "keys_sent": len(keys),
                    "keys_confirmed": len(keys),
                    "native_receipts": receipts,
                },
            }

        def advance(self, ticks, state):
            if len(self.actions) < 3:
                self.view = "viewscreen_topicmeetingst" if modal and len(self.actions) == 2 else "viewscreen"
                return Environment.advance(self, ticks, state)
            if modal:
                return self.observe(), {
                    "ok": False, "requested": ticks, "ticks_advanced": 0,
                    "start_year": 30, "start_tick": self.tick, "end_year": 30, "end_tick": self.tick,
                    "paused_before": True, "paused_after": True, "elapsed_ms": 620,
                    "repause_requested": True, "repause_effective": True,
                    "repause": {"ok": True, "paused": True, "attempts": 1,
                                "attempt_records": [{"attempt": 1, "nopause_disabled": True, "paused": True}]},
                    "error": "interrupt_baseline_invalid", "interrupt_safety_error": True,
                    "calendar_safety_error": False, "final_pause_state": True,
                    "final_viewscreen_type": self.view,
                }
            return super().advance(ticks, state)

        def capture(self, destination):
            operation = identified_receipt(native)
            before = operation.pop("identity_before")
            operation.pop("identity_after")
            boundary = {
                "dfroot": str(native),
                "save_name": "fixture",
                "year": 30,
                "year_tick": self.tick,
                "paused": True,
                "autosave_requested": False,
            }
            before["native_boundary"] = boundary
            before["stack"] = [
                {
                    "type": "<type: viewscreen_textviewerst>",
                    "kind": "native",
                    "address": "1",
                    "focus": "textviewer",
                    "dismissed": False,
                },
                {
                    "type": "<type: viewscreen_meetingst>",
                    "kind": "native",
                    "address": "2",
                    "focus": "meeting",
                    "dismissed": False,
                },
                {
                    "type": "<type: viewscreen_dwarfmodest>",
                    "kind": "native",
                    "address": "3",
                    "focus": "dwarfmode/Default",
                    "dismissed": False,
                },
            ]
            before["ui"]["focus"] = "textviewer"
            if modal:
                before["stack"][0].update(type="<type: viewscreen_topicmeetingst>", focus="topicmeeting")
                before["ui"]["focus"] = "topicmeeting"
            operation.update(
                native_before=boundary,
                native_after={**boundary, "autosave_requested": True},
                menu_stack_restored=False,
                original_stack=before["stack"],
                ui_before=before["ui"],
                ui_after=before["ui"],
            )
            self.attempt = {
                "schema_version": "fortgym.native-menu-save-attempt/v1",
                "identity_before_raw": json.dumps(before),
                "identity_before": before,
                "save_operation_raw": json.dumps(operation),
                "identity_after_raw": "(lua command):7: Identity probe requires a paused fortress "
                "with no pending save\nstack traceback:\n\t[C]: in function 'assert'",
                "world_before": self.observe(),
                "world_after": self.observe(),
                "screen_before": self.screen_capture(),
                "screen_after": self.screen_capture(),
            }
            raise CampaignSaveError("Native menu identity probe returned malformed JSON")

    env = PartialEnvironment()
    env.tick = tick
    condition, callback, prompt = CONDITION, decision, None
    if prompt_changed or restart:
        from tests.test_keyboard_prompt import condition as changed_condition, changed_decision, declaration

        condition, callback = changed_condition(), changed_decision
        if prompt_changed:
            prompt = declaration(checkpoint)
    original_validator = campaign_loop.validate_clean_interruption_receipt

    def old_baseline(receipt, **options):
        # Reproduce the old source's pre-keypress baseline only in this fixture.
        options["state_after_apply"] = {
            **options["state_after_apply"],
            "viewscreen_type": "viewscreen",
        }
        return original_validator(receipt, **options)

    with monkeypatch.context() as old_source:
        old_source.setattr(campaign_loop, "validate_clean_interruption_receipt", old_baseline)
        result = run_keyboard_segment(
            agent=policy(condition, callback),
            environment=env,
            snapshotter=env,
            output=source / "segment-0",
            condition=condition,
            checkpoint=checkpoint,
            latest_usage=usage,
            steps=3,
            expected_cursor=1,
            revision="a" * 40,
            prompt_change=prompt,
            restart_declaration=restart[2] if restart else None,
            restart_source=restart[1] if restart else None,
        )
    assert result["status"] == "checkpoint_failed" and result["next_step"] == 3
    assert result["usage"]["accounted_responses"] == (7 if restart else 4)
    native.parent.mkdir(parents=True)
    shutil.copytree(checkpoint / "game", native / "data/save/fixture")
    runtime = {
        "schema_version": "fortgym.isolated-experiment-runtime/v1",
        "code_revision": "a" * 40,
        "experiment": result,
        "source_checkpoint_file_sha256": hashlib.sha256(
            (checkpoint / "checkpoint.json").read_bytes()
        ).hexdigest(),
        "native_load_verified": True,
        "cleanup_verified": True,
        "listener_closed": True,
        "remaining_live_processes": [],
        "loaded": {"dfroot": str(native), "save_name": "fixture"},
    }
    (native.parent / "result.json").write_text(json.dumps(runtime))
    return (
        checkpoint,
        source,
        {
            "schema_version": SCHEMA,
            "source_segment": 0,
            "source_revision": "a" * 40,
            "restored_next_step": 1,
            "lost_trace_next_step": 3,
            "failure_kind": "modal_clock_baseline_pending_save" if modal else PARTIAL_KIND,
        },
    )


def test_partial_restart_retains_extra_response_and_partial_ticks(partial):
    record = prepare(partial)
    assert record["lost_elapsed_ticks"] == 23
    assert record["lost_uncommitted_ticks"] == 3 and record["lost_uncommitted_decisions"] == 1
    assert record["restored_next_step"] == 1 and record["lost_trace_next_step"] == 3
    assert record["retained_usage"]["total_tokens"] == 400
    assert record["retained_usage"]["accounted_responses"] == 4
    assert record["retained_usage"]["total_cost_usd"] is None
    assert record["save_failure_stage"] == PARTIAL_STAGE
    assert (
        record["source_failure_sha256"]
        == hashlib.sha256((partial[1] / "segment-0/loop/failures.jsonl").read_bytes()).hexdigest()
    )


def test_partial_restart_continues_without_replay_and_survives_resume(tmp_path, partial):
    checkpoint, source, declaration = partial
    record = prepare(partial)
    original = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    seen = []

    def callback(screen, memory, feedback):
        seen.append((memory, feedback))
        return decision(screen, memory, feedback)

    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    output = tmp_path / "restart"
    result = run_keyboard_segment(
        agent=policy(CONDITION, callback),
        environment=env,
        snapshotter=env,
        output=output,
        condition=CONDITION,
        checkpoint=checkpoint,
        latest_usage=source / "segment-0/loop/usage.jsonl",
        steps=1,
        expected_cursor=1,
        revision="b" * 40,
        restart_declaration=declaration,
        restart_source=source,
    )
    assert result["checkpoint_verified"] is True and result["next_step"] == 2
    assert result["usage"]["total_tokens"] == 500 and result["usage"]["returned_responses"] == 5
    assert len(env.actions) == 1
    assert seen[0][0] == read(checkpoint / "agent.json")["memory"]
    assert seen[0][1]["infrastructure_restart"]["lost_uncommitted_decisions"] == 1
    assert read(output / "checkpoint/runner.json")["discontinuities"] == [record]
    loop = campaign_loop.CampaignLoop.resume(
        output / "checkpoint",
        agent=policy(CONDITION),
        environment=env,
        output=tmp_path / "continued",
        latest_usage_path=output / "loop/usage.jsonl",
    )
    loop.step()
    loop.checkpoint(tmp_path / "next", snapshotter=env, code_revision="c" * 40)
    from fort_gym.bench.eval.campaign import read_campaign_progress

    progress = read_campaign_progress(loop.trace)
    assert progress["native_save_loss_restarts"] == 1 and progress["discarded_native_ticks"] == 23
    assert progress["elapsed_ticks"] == 30  # Excludes both lost committed and partial ticks.
    assert loop.agent.usage["total_tokens"] == 600
    assert read(tmp_path / "next/runner.json")["discontinuities"] == [record]
    assert all(path.read_bytes() == content for path, content in original.items())


def mutate_file(source, relative, path, value):
    file = source / relative
    rows = (
        [json.loads(line) for line in file.read_text().splitlines()]
        if file.suffix == ".jsonl"
        else [read(file)]
    )
    row = rows[0]
    for key in path[:-1]:
        row = row[key]
    row[path[-1]] = value
    file.write_text("".join(json.dumps(item) + "\n" for item in rows))


@pytest.mark.parametrize(
    "file,path,value",
    [
        ("loop/failures.jsonl", ("step",), 4),
        ("loop/failures.jsonl", ("action", "memory_update"), "changed"),
        ("loop/failures.jsonl", ("events",), []),
        ("loop/failures.jsonl", ("execute",), None),
        ("loop/failures.jsonl", ("execute", "result", "keys_sent"), True),
        ("loop/failures.jsonl", ("execute", "result", "keys_confirmed"), True),
        (
            "loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "key"),
            "D_PAUSE",
        ),
        (
            "loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "after", "paused"),
            False,
        ),
        (
            "loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "after", "year_tick"),
            1,
        ),
        (
            "loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "after", "save_name"),
            "other",
        ),
        ("loop/failures.jsonl", ("tick_receipt", "ticks_advanced"), 0),
        ("loop/failures.jsonl", ("tick_receipt", "repause_effective"), False),
        (
            "loop/failures.jsonl",
            ("native_before", "viewscreen_type"),
            "viewscreen_dwarfmodest",
        ),
        ("save-attempt.json", ("identity_before_raw",), "null"),
        ("save-attempt.json", ("save_operation_raw",), "null"),
        ("save-attempt.json", ("identity_after_raw",), "unrelated failure"),
        ("save-attempt.json", ("identity_after",), {}),
        ("save-attempt.json", ("capture_errors",), {}),
        ("save-attempt.json", ("world_after", "year_tick"), 1),
        ("save-attempt.json", ("screen_after",), {}),
        ("agent-before.json", ("memory",), "changed"),
        ("agent-after.json", ("memory",), "changed"),
        ("agent-after.json", ("budget_extensions",), [{}]),
        ("result.json", ("committed_elapsed_ticks",), 999),
        ("result.json", ("recovery_requires_reconciliation",), False),
    ],
)
def test_partial_restart_rejects_changed_failure_evidence(partial, file, path, value):
    mutate_file(partial[1] / "segment-0", file, path, value)
    with pytest.raises(ValueError):
        prepare(partial)


@pytest.mark.parametrize(
    "path,value",
    [
        (("native_load_verified",), False),
        (("cleanup_verified",), False),
        (("remaining_live_processes",), [123]),
        (("source_checkpoint_file_sha256",), "a" * 64),
        (("loaded", "save_name"), "other"),
        (("loaded",), None),
    ],
)
def test_partial_restart_requires_runtime_identity_and_teardown(partial, path, value):
    mutate_file(partial[1], "runtime-0/result.json", path, value)
    with pytest.raises(ValueError):
        prepare(partial)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_kind",
        "unknown_kind",
        "new_save",
        "new_checkpoint",
        "symlink",
        "empty_failure",
        "missing_usage",
    ],
)
def test_partial_restart_never_falls_back_or_discards_new_save(partial, mutation):
    checkpoint, source, declaration = partial
    if mutation == "missing_kind":
        del declaration["failure_kind"]
    elif mutation == "unknown_kind":
        declaration["failure_kind"] = "other"
    elif mutation == "new_save":
        (source / "runtime-0/runtime/data/save/fixture/world.sav").write_text("newer save")
    elif mutation == "new_checkpoint":
        directory = source / "segment-0/checkpoint"
        directory.mkdir()
        (directory / "checkpoint.json").write_text("newer checkpoint")
    elif mutation == "symlink":
        path = source / "segment-0/save-attempt.json"
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif mutation == "empty_failure":
        (source / "segment-0/loop/failures.jsonl").write_text("")
    else:
        (source / "segment-0/loop/usage.jsonl").write_bytes(
            (checkpoint / "usage.jsonl").read_bytes()
        )
    with pytest.raises(ValueError):
        prepare(partial)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lost_uncommitted_ticks", True),
        ("lost_uncommitted_ticks", 0),
        ("lost_uncommitted_ticks", 24),
        ("lost_uncommitted_decisions", True),
        ("lost_uncommitted_decisions", 0),
        ("failure_kind", "unknown"),
        ("source_failure_sha256", "bad"),
        ("source_runtime_sha256", "bad"),
        ("save_failure_stage", "identity_before_save"),
    ],
)
def test_partial_discontinuity_cannot_hide_uncommitted_loss(partial, field, value):
    record = prepare(partial)
    record[field] = value
    with pytest.raises(ValueError):
        validate_discontinuities([record])


@pytest.mark.parametrize(
    "field",
    [
        "failure_kind",
        "lost_uncommitted_ticks",
        "lost_uncommitted_decisions",
        "source_failure_sha256",
        "source_runtime_sha256",
        "save_failure_stage",
        "source_save_attempt_sha256",
    ],
)
def test_partial_discontinuity_requires_complete_provenance(partial, field):
    record = prepare(partial)
    del record[field]
    with pytest.raises(ValueError):
        validate_discontinuities([record])
