"""Unavailable-runtime rollbacks use synthetic games and model receipts only."""

from copy import deepcopy
import hashlib
import json
import shutil

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.eval.campaign import read_campaign_progress
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_restart import (
    SCHEMA,
    apply_restart,
    prepare_restart,
    validate_discontinuities,
)
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_unavailable_restart import UNAVAILABLE_KIND, restart_history
from tests.test_campaign_codex_keyboard import Environment, decision
from tests.test_keyboard_runtime import CONDITION, environment, policy, saved as saved


def model(screen, memory, feedback):
    response = decision(screen, memory, feedback)
    response["native_action_dispatched"] = False
    response["transport_receipt"]["reasoning_effort_requested"] = CONDITION["reasoning_effort"]
    return response


class UnavailableEnvironment(Environment):
    def __init__(self, native, tick, fail_after):
        super().__init__()
        self.native, self.tick, self.fail_after = native, tick, fail_after
        self.missing = False

    def observe(self):
        if self.missing:
            raise json.JSONDecodeError("native gone", "", 0)
        return {**super().observe(), "viewscreen_type": "viewscreen_dwarfmodest", "time": self.tick}

    def screen_capture(self):
        self.observe()
        return environment().screen_capture()

    def apply(self, action, state):
        super().apply(action, state)
        keys = action["params"]["keys"]
        boundary = {
            "dfroot": str(self.native),
            "save_name": "fixture",
            "year": 30,
            "year_tick": self.tick,
            "paused": True,
            "viewscreen_type": "<type: viewscreen_dwarfmodest>",
        }
        receipts = [
            {
                "schema_version": "fortgym.campaign-keyboard-native/v1",
                "ok": True,
                "mode": "key" if index else "probe",
                "keys_sent": int(index > 0),
                "command_mutation": "completed" if index else "not_attempted",
                "before": deepcopy(boundary),
                "after": deepcopy(boundary),
                **({"key": keys[index - 1]} if index else {}),
            }
            for index in range(len(keys) + 1)
        ]
        return {
            "accepted": True,
            "result": {
                "schema_version": "fortgym.campaign-keyboard-execution/v1",
                "ok": True,
                "control_profile": CONDITION["control_profile"],
                "command_mutation": "completed",
                "keys_sent": len(keys),
                "keys_confirmed": len(keys),
                "native_receipts": receipts,
            },
        }

    def advance(self, ticks, state):
        if len(self.actions) == self.fail_after:
            self.missing = True
            raise RuntimeError("Keyboard clock preflight could not attest native UI")
        return super().advance(ticks, state)

    def capture(self, destination):
        if self.missing:
            self.attempt = {"schema_version": "fortgym.native-menu-save-attempt/v1"}
            raise json.JSONDecodeError("native gone", "", 0)
        return super().capture(destination)


def source_failure(folder, checkpoint, latest, *, fail_after=3, restart=None, revision="a" * 40,
                   declared_condition=CONDITION, model_callback=model):
    folder.mkdir()
    manifest = verify_checkpoint(checkpoint)
    native = folder / "runtime-0/runtime"
    env = UnavailableEnvironment(
        native, manifest["payload"]["native_save"]["year_tick"], fail_after
    )
    options = {}
    if restart is not None:
        options = {"restart_source": restart[1], "restart_declaration": restart[2]}
    result = run_keyboard_segment(
        agent=policy(declared_condition, model_callback),
        environment=env,
        snapshotter=env,
        output=folder / "segment-0",
        condition=declared_condition,
        checkpoint=checkpoint,
        latest_usage=latest,
        steps=fail_after,
        expected_cursor=manifest["payload"]["next_step"],
        revision=revision,
        **options,
    )
    assert result["status"] == "checkpoint_failed"
    native.parent.mkdir(parents=True)
    shutil.copytree(checkpoint / "game", native / "data/save/fixture")
    runtime = {
        "schema_version": "fortgym.isolated-experiment-runtime/v1",
        "code_revision": revision,
        "experiment": result,
        "source_checkpoint_file_sha256": hashlib.sha256(
            (checkpoint / "checkpoint.json").read_bytes()
        ).hexdigest(),
        "native_load_verified": True,
        "cleanup_verified": True,
        "listener_closed": True,
        "remaining_live_processes": [],
        "loaded": {
            "dfroot": str(native),
            "save_name": "fixture",
            "map_loaded": True,
            "paused": True,
            "year": 30,
            "year_tick": manifest["payload"]["native_save"]["year_tick"],
        },
    }
    (native.parent / "result.json").write_text(json.dumps(runtime))
    return (
        checkpoint,
        folder,
        {
            "schema_version": SCHEMA,
            "source_segment": 0,
            "source_revision": revision,
            "restored_next_step": result["first_step"],
            "lost_trace_next_step": result["next_step"],
            "failure_kind": UNAVAILABLE_KIND,
        },
    )


@pytest.fixture
def unavailable(tmp_path, saved):
    checkpoint, latest, _ = saved
    return source_failure(tmp_path / "source", checkpoint, latest)


def prepare(fixture):
    checkpoint, source, declaration = fixture
    return prepare_restart(
        checkpoint, source, declaration, (source / "segment-0/loop/usage.jsonl").read_bytes()
    )


def test_preparation_preserves_known_loss_and_unknown_remainder(unavailable):
    record = prepare(unavailable)
    assert record["lost_elapsed_ticks"] == 20
    assert record["lost_elapsed_ticks_complete"] is False
    assert record["lost_uncommitted_ticks"] is None
    assert record["lost_uncommitted_decisions"] == 1
    assert record["retained_usage"]["accounted_responses"] == 4
    assert record["retained_usage"]["total_tokens"] == 400
    assert record["actions_replayed"] is False


def test_restart_preserves_usage_memory_and_unknown_loss_through_checkpoint(tmp_path, unavailable):
    checkpoint, source, declaration = unavailable
    original = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    seen = []

    def callback(screen, memory, feedback):
        seen.append((memory, feedback))
        return model(screen, memory, feedback)

    env = environment()
    env.tick = verify_checkpoint(checkpoint)["payload"]["native_save"]["year_tick"]
    output = tmp_path / "resumed"
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
    assert result["checkpoint_verified"] is True
    assert len(env.actions) == 1
    assert result["usage"]["accounted_responses"] == 5
    assert seen[0][0] == read(checkpoint / "agent.json")["memory"]
    feedback = seen[0][1]["infrastructure_restart"]
    assert feedback["lost_elapsed_ticks_complete"] is False
    assert feedback["lost_uncommitted_ticks"] is None
    loop = CampaignLoop.resume(
        output / "checkpoint",
        agent=policy(CONDITION, model),
        environment=env,
        output=tmp_path / "continued",
        latest_usage_path=output / "loop/usage.jsonl",
    )
    loop.step()
    loop.checkpoint(tmp_path / "next", snapshotter=env, code_revision="c" * 40)
    progress = read_campaign_progress(loop.trace)
    assert progress["elapsed_ticks"] == 30
    assert progress["native_save_loss_restarts"] == 1
    assert progress["discarded_native_ticks"] is None
    assert progress["confirmed_discarded_native_ticks"] == 20
    assert progress["discarded_native_ticks_complete"] is False
    assert all(p.read_bytes() == content for p, content in original.items())


def test_repeated_failure_carries_history_newer_than_old_save(tmp_path, unavailable):
    checkpoint, source, _ = unavailable
    first = prepare(unavailable)
    repeated = source_failure(
        tmp_path / "second",
        checkpoint,
        source / "segment-0/loop/usage.jsonl",
        restart=unavailable,
        revision="b" * 40,
    )
    second = prepare(repeated)
    history = restart_history(checkpoint, repeated[1] / "segment-0", second)
    assert history == [first]
    assert second["retained_usage"]["accounted_responses"] == 7
    env = environment()
    env.tick = verify_checkpoint(checkpoint)["payload"]["native_save"]["year_tick"]
    loop = CampaignLoop.resume(
        checkpoint,
        agent=policy(CONDITION, model),
        environment=env,
        output=tmp_path / "third",
        latest_usage_path=repeated[1] / "segment-0/loop/usage.jsonl",
    )
    apply_restart(loop, second, prior_discontinuities=history)
    assert loop.discontinuities == [first, second]
    assert len(env.actions) == 0
    loop.step()
    assert loop.agent.usage["accounted_responses"] == 8
    progress = read_campaign_progress(loop.trace)
    assert progress["native_save_loss_restarts"] == 2
    assert progress["confirmed_discarded_native_ticks"] == 40
    assert progress["discarded_native_ticks"] is None


def test_first_input_failure_can_resume_without_inventing_committed_progress(tmp_path, saved):
    checkpoint, latest, _ = saved
    fixture = source_failure(tmp_path / "first-input", checkpoint, latest, fail_after=1)
    record = prepare(fixture)
    assert record["lost_trace_next_step"] == record["restored_next_step"] == 1
    assert record["lost_elapsed_ticks"] == 0
    assert record["lost_uncommitted_ticks"] is None
    assert record["retained_usage"]["accounted_responses"] == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("lost_elapsed_ticks_complete", True),
        ("lost_elapsed_ticks_complete", None),
        ("lost_uncommitted_ticks", 0),
        ("lost_uncommitted_decisions", 0),
        ("source_start_agent_sha256", "bad"),
        ("failure_kind", "partial_interruption_pending_save"),
    ],
)
def test_unknown_loss_cannot_be_relabelled_as_complete(unavailable, key, value):
    record = prepare(unavailable)
    record[key] = value
    with pytest.raises(ValueError):
        validate_discontinuities([record])


def mutate(fixture, relative, keys, value):
    path = fixture[1] / relative
    multiple = path.suffix == ".jsonl"
    rows = (
        [json.loads(line) for line in path.read_text().splitlines()] if multiple else [read(path)]
    )
    row = rows[-1]
    for key in keys[:-1]:
        row = row[key]
    row[keys[-1]] = value
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.parametrize(
    "relative,keys,value",
    [
        ("segment-0/result.json", ("source_revision",), "b" * 40),
        ("segment-0/result.json", ("status",), "bounded_segment_complete"),
        ("segment-0/result.json", ("checkpoint_verified",), True),
        ("segment-0/result.json", ("recovery_requires_reconciliation",), False),
        ("segment-0/result.json", ("committed_elapsed_ticks",), 999),
        ("segment-0/result.json", ("final_observation_error_type",), "ValueError"),
        ("segment-0/agent-before.json", ("memory",), "changed"),
        ("segment-0/agent-before.json", ("usage", "total_tokens"), 0),
        ("segment-0/agent-after.json", ("memory",), "changed"),
        ("segment-0/agent-after.json", ("usage", "accounted_responses"), 3),
        ("segment-0/agent-after.json", ("budget_extensions",), [{}]),
        ("segment-0/save-attempt.json", ("identity_after",), {}),
        ("segment-0/loop/failures.jsonl", ("step",), 4),
        ("segment-0/loop/failures.jsonl", ("tick_receipt",), {}),
        ("segment-0/loop/failures.jsonl", ("native_after",), {}),
        ("segment-0/loop/failures.jsonl", ("action", "memory_update"), "changed"),
        ("segment-0/loop/failures.jsonl", ("events",), []),
        ("segment-0/loop/failures.jsonl", ("execute",), None),
        ("segment-0/loop/failures.jsonl", ("execute", "result", "keys_confirmed"), True),
        (
            "segment-0/loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "key"),
            "D_PAUSE",
        ),
        (
            "segment-0/loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "after", "paused"),
            False,
        ),
        (
            "segment-0/loop/failures.jsonl",
            ("execute", "result", "native_receipts", 1, "after", "dfroot"),
            "/other",
        ),
        ("segment-0/loop/failures.jsonl", ("native_after_apply", "pause_state"), False),
        ("segment-0/loop/failures.jsonl", ("native_after_apply", "year_tick"), 1),
        (
            "segment-0/loop/failures.jsonl",
            ("events", 0, "receipt", "transport_receipt", "total_tokens"),
            0,
        ),
        (
            "segment-0/loop/failures.jsonl",
            ("events", 0, "receipt", "transport_receipt", "model_requested"),
            "other",
        ),
        ("runtime-0/result.json", ("native_load_verified",), False),
        ("runtime-0/result.json", ("cleanup_verified",), False),
        ("runtime-0/result.json", ("listener_closed",), False),
        ("runtime-0/result.json", ("remaining_live_processes",), [123]),
        ("runtime-0/result.json", ("loaded", "paused"), False),
        ("runtime-0/result.json", ("loaded", "year_tick"), 1),
        ("runtime-0/result.json", ("source_checkpoint_file_sha256",), "a" * 64),
    ],
)
def test_changed_failure_evidence_is_rejected(unavailable, relative, keys, value):
    mutate(unavailable, relative, keys, value)
    with pytest.raises(ValueError):
        prepare(unavailable)


@pytest.mark.parametrize(
    "kind",
    [
        "new_save",
        "new_checkpoint",
        "final_observation",
        "trace_tail",
        "failure_tail",
        "missing_receipt",
        "old_kind",
    ],
)
def test_no_silent_promotion_or_old_failure_fallback(unavailable, kind):
    checkpoint, source, declaration = unavailable
    segment = source / "segment-0"
    if kind == "new_save":
        (source / "runtime-0/runtime/data/save/fixture/world.sav").write_text("newer")
    elif kind == "new_checkpoint":
        (segment / "checkpoint").mkdir()
    elif kind == "final_observation":
        (segment / "native-after.json").write_text("{}")
    elif kind in ("trace_tail", "failure_tail"):
        path = segment / ("loop/trace.jsonl" if kind == "trace_tail" else "loop/failures.jsonl")
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
    elif kind == "missing_receipt":
        (source / "runtime-0/result.json").unlink()
    else:
        declaration.pop("failure_kind")
    with pytest.raises(ValueError):
        prepare(unavailable)


def test_dropped_loss_history_is_rejected(tmp_path, unavailable):
    checkpoint, source, _ = unavailable
    repeated = source_failure(
        tmp_path / "second",
        checkpoint,
        source / "segment-0/loop/usage.jsonl",
        restart=unavailable,
        revision="b" * 40,
    )
    mutate(repeated, "segment-0/result.json", ("discontinuities",), [])
    result = read(repeated[1] / "segment-0/result.json")
    runtime = read(repeated[1] / "runtime-0/result.json")
    runtime["experiment"] = result
    (repeated[1] / "runtime-0/result.json").write_text(json.dumps(runtime))
    with pytest.raises(ValueError):
        prepare(repeated)


def test_apply_cannot_drop_already_saved_losses(unavailable):
    from types import SimpleNamespace

    record = prepare(unavailable)
    previous = deepcopy(record)
    previous["source_result_sha256"] = "b" * 64
    loop = SimpleNamespace(
        agent=SimpleNamespace(export_campaign_state=lambda: {"usage": record["retained_usage"]}),
        discontinuities=[previous],
    )
    with pytest.raises(ValueError, match="erase"):
        apply_restart(loop, record, prior_discontinuities=[])
    assert loop.discontinuities == [previous]
