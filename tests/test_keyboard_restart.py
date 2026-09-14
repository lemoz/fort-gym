import json
import shutil
from copy import deepcopy

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from fort_gym.bench.run.campaign_save import CampaignSaveError
from fort_gym.bench.run.keyboard_restart import SCHEMA, prepare_restart, validate_discontinuities
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_keyboard_runtime import CONDITION, environment, policy, saved as saved
from tests.test_campaign_codex_keyboard import decision


@pytest.fixture
def failed(tmp_path, saved):
    checkpoint, usage, tick = saved
    source = tmp_path / "failed-source"
    source.mkdir()
    env = environment()
    env.tick = tick

    class SaveFailure:
        def capture(self, destination):
            raise CampaignSaveError("Native save completion was not observed before timeout")

    result = run_keyboard_segment(
        agent=policy(CONDITION),
        environment=env,
        snapshotter=SaveFailure(),
        output=source / "segment-0",
        condition=CONDITION,
        checkpoint=checkpoint,
        latest_usage=usage,
        steps=2,
        expected_cursor=1,
        revision="a" * 40,
    )
    assert result["status"] == "checkpoint_failed"
    native = source / "runtime-0/runtime/data/save/fixture"
    native.parent.mkdir(parents=True)
    shutil.copytree(checkpoint / "game", native)
    declaration = {
        "schema_version": SCHEMA,
        "source_segment": 0,
        "source_revision": "a" * 40,
        "restored_next_step": 1,
        "lost_trace_next_step": 3,
    }
    return checkpoint, source, declaration


def prepare(failed):
    checkpoint, source, declaration = failed
    latest = (source / "segment-0/loop/usage.jsonl").read_bytes()
    return prepare_restart(checkpoint, source, declaration, latest)


@pytest.mark.parametrize("failure_kind", ["timeout", "presave", "dismissed"])
def test_restart_retains_all_usage_memory_and_discontinuity_after_continuation(
    tmp_path, failed, failure_kind
):
    if failure_kind in {"presave", "dismissed"}:
        from tests.test_keyboard_presave_restart import retain_presave_evidence

        retain_presave_evidence(
            failed,
            "Snapshot cannot hide a dismissed screen" if failure_kind == "dismissed"
            else "Identity probe requires a native screen",
        )
    checkpoint, source, declaration = failed
    record = prepare(failed)
    assert record["retained_usage"]["total_tokens"] == 300
    assert record["lost_elapsed_ticks"] == 20
    assert record["uninterrupted_campaign"] is record["actions_replayed"] is False
    original = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    seen = []

    def callback(screen, memory, feedback):
        seen.append((memory, feedback))
        return decision(screen, memory, feedback)

    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    output = tmp_path / "restarted"
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
    assert result["usage"]["total_tokens"] == 400 and result["usage"]["returned_responses"] == 4
    assert seen[0][0] == read(checkpoint / "agent.json")["memory"]
    assert seen[0][1]["infrastructure_restart"]["lost_trace_next_step"] == 3
    assert len(env.actions) == 1  # No lost input replay.
    assert read(output / "checkpoint/runner.json")["discontinuities"] == [record]
    rows = [json.loads(line) for line in (output / "loop/trace.jsonl").read_text().splitlines()]
    assert rows[-1]["discontinuities"] == [record]
    continuation = CampaignLoop.resume(
        output / "checkpoint",
        agent=policy(CONDITION),
        environment=env,
        output=tmp_path / "continued",
        latest_usage_path=output / "loop/usage.jsonl",
    )
    assert continuation.discontinuities == [record]
    continuation.step()
    continuation.checkpoint(tmp_path / "next", snapshotter=env, code_revision="c" * 40)
    assert read(tmp_path / "next/runner.json")["discontinuities"] == [record]
    from fort_gym.bench.eval.campaign import read_campaign_progress

    progress = read_campaign_progress(continuation.trace)
    assert progress["uninterrupted_campaign"] is False
    assert progress["native_save_loss_restarts"] == 1 and progress["discarded_native_ticks"] == 20
    assert progress["elapsed_ticks"] == 30  # Lost ticks are not counted twice.
    assert (
        reconciled_usage(read(tmp_path / "next/agent.json"), continuation.journal.read_bytes())[
            "total_tokens"
        ]
        == 500
    )
    assert all(path.read_bytes() == content for path, content in original.items())


@pytest.mark.parametrize(
    "mutation",
    [
        "new_save",
        "missing_usage",
        "wrong_revision",
        "replay",
        "pending",
        "checkpoint_exists",
        "lost_counter",
    ],
)
def test_restart_refuses_newer_state_or_inconsistent_source(failed, mutation):
    checkpoint, source, declaration = failed
    if mutation == "new_save":
        (source / "runtime-0/runtime/data/save/fixture/world.sav").write_text("new state")
    elif mutation == "missing_usage":
        (source / "segment-0/loop/usage.jsonl").write_bytes(
            (checkpoint / "usage.jsonl").read_bytes()
        )
    elif mutation == "wrong_revision":
        declaration["source_revision"] = "b" * 40
    elif mutation == "replay":
        declaration["restored_next_step"] = 2
    elif mutation == "checkpoint_exists":
        folder = source / "segment-0/checkpoint"
        folder.mkdir(exist_ok=True)
        (folder / "checkpoint.json").write_text("newer checkpoint")
    else:
        path = source / "segment-0/result.json"
        value = read(path)
        value["recovery_requires_reconciliation" if mutation == "pending" else "next_step"] = True
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        prepare(failed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lost_elapsed_ticks", True),
        ("actions_replayed", True),
        ("uninterrupted_campaign", True),
        ("memory_policy", "latest_unsaved_memory"),
        ("checkpoint_sha256", "bad"),
    ],
)
def test_continuity_receipt_cannot_hide_restart(failed, field, value):
    record = deepcopy(prepare(failed))
    record[field] = value
    with pytest.raises(ValueError):
        validate_discontinuities([record])
