"""Interrupted-worker recovery uses synthetic originals, never a VM or model call."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.agent.keyboard_prompt import MEMORY_PROMPT
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_restart import prepare_restart, validate_discontinuities
from fort_gym.bench.run.keyboard_restart_prompt import restart_prompt_state
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_terminated_restart import TERMINATED_KIND
from tests.test_keyboard_runtime import CONDITION, environment, policy, saved as saved
from tests.test_keyboard_unavailable_restart import source_failure, model
from tests.test_keyboard_modal_restart import modal as modal
from tests.test_keyboard_prompt import condition


def interrupted(folder, checkpoint, latest, *, previous=None, fail_after=3, config=CONDITION):
    def callback(*args):
        value = model(*args)
        if config.get("prompt_profile"):
            value["prompt_profile"] = config["prompt_profile"]
        return value

    fixture = source_failure(
        folder,
        checkpoint,
        latest,
        restart=previous,
        fail_after=fail_after,
        declared_condition=config,
        model_callback=callback,
    )
    _, source, declaration = fixture
    segment = source / "segment-0"
    path = segment / "loop/failures.jsonl"
    failure = json.loads(path.read_text())
    failure.update(error_type="KeyboardInterrupt", message="Campaign termination requested")
    path.write_text(json.dumps(failure) + "\n")
    runtime = read(source / "runtime-0/result.json")
    runtime.pop("experiment")
    (source / "runtime-0/result.json").write_text(json.dumps(runtime))
    for name in ("result.json", "agent-after.json", "save-attempt.json"):
        (segment / name).unlink()
    (source / "result.json").write_text(
        json.dumps(
            {
                "schema_version": "fortgym.keyboard-window-result/v1",
                "status": "failed",
                "source_revision": declaration["source_revision"],
                "campaign_id": read(checkpoint / "agent.json")["campaign_id"],
                "original_checkpoint_unchanged": True,
                "segments": [],
            }
        )
    )
    return checkpoint, source, {**declaration, "failure_kind": TERMINATED_KIND}


@pytest.fixture
def terminated(tmp_path, saved):
    checkpoint, latest, _ = saved
    return interrupted(tmp_path / "interrupted", checkpoint, latest)


def prepare(fixture):
    checkpoint, source, declaration = fixture
    return prepare_restart(
        checkpoint, source, declaration, (source / "segment-0/loop/usage.jsonl").read_bytes()
    )


def test_missing_terminal_files_are_not_fabricated_or_required(terminated):
    checkpoint, source, _ = terminated
    originals = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    record = prepare(terminated)
    assert record["lost_elapsed_ticks"] == 20
    assert (
        record["lost_uncommitted_ticks"] is None and record["lost_elapsed_ticks_complete"] is False
    )
    assert record["retained_usage"]["accounted_responses"] == 4
    assert record["retained_usage"]["total_tokens"] == 400
    assert record["retained_prompt_changes"] == []
    assert "save_failure_stage" not in record
    assert all(p.read_bytes() == value for p, value in originals.items())
    assert set(originals) == {p for p in source.rglob("*") if p.is_file()}
    assert (
        restart_prompt_state(read(checkpoint / "agent.json"), record)["memory"]
        == read(checkpoint / "agent.json")["memory"]
    )


def test_unknown_loss_survives_real_loop_restore_checkpoint_and_continuation(tmp_path, terminated):
    checkpoint, source, declaration = terminated
    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    seen = []

    def callback(screen, memory, feedback):
        seen.append((memory, deepcopy(feedback)))
        return model(screen, memory, feedback)

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
    assert result["checkpoint_verified"] is True and result["usage"]["total_tokens"] == 500
    assert len(env.actions) == 1 and seen[0][0] == read(checkpoint / "agent.json")["memory"]
    assert seen[0][1]["infrastructure_restart"]["lost_uncommitted_ticks"] is None
    loop = CampaignLoop.resume(
        output / "checkpoint",
        agent=policy(CONDITION, model),
        environment=env,
        output=tmp_path / "continued",
        latest_usage_path=output / "loop/usage.jsonl",
    )
    loop.step()
    loop.checkpoint(tmp_path / "again", snapshotter=env, code_revision="c" * 40)
    assert read(tmp_path / "again/runner.json")["discontinuities"] == [prepare(terminated)]
    assert read(tmp_path / "again/agent.json")["usage"]["total_tokens"] == 600


def test_interruption_before_first_commit_keeps_zero_lower_bound_not_zero_total(tmp_path, saved):
    fixture = interrupted(tmp_path / "first", saved[0], saved[1], fail_after=1)
    record = prepare(fixture)
    assert record["lost_elapsed_ticks"] == 0 and record["lost_uncommitted_ticks"] is None
    assert record["lost_trace_next_step"] == record["restored_next_step"] == 1
    assert record["retained_usage"]["accounted_responses"] == 2


def test_prompt_history_and_failed_usage_survive_repeated_interruption(tmp_path, modal):
    checkpoint, source, _ = modal
    first = interrupted(
        tmp_path / "terminated",
        checkpoint,
        source / "segment-0/loop/usage.jsonl",
        previous=modal,
        config=condition(),
    )
    second = interrupted(
        tmp_path / "again",
        checkpoint,
        first[1] / "segment-0/loop/usage.jsonl",
        previous=first,
        fail_after=1,
        config=condition(),
    )
    a, b = prepare(first), prepare(second)
    assert a["retained_usage"]["total_tokens"] == 700
    assert b["retained_usage"]["total_tokens"] == 800
    assert a["retained_prompt_changes"] == b["retained_prompt_changes"]
    assert a["retained_prompt_changes"][0]["profile"] == MEMORY_PROMPT
    assert a["retained_prompt_changes"][0]["usage"]["total_tokens"] == 100
    assert (
        restart_prompt_state(read(checkpoint / "agent.json"), b)["memory"]
        == read(checkpoint / "agent.json")["memory"]
    )
    assert len(read(second[1] / "segment-0/history-before.json")["discontinuities"]) == 2
    (second[1] / "segment-0/history-before.json").unlink()
    with pytest.raises(ValueError, match="complete retained prior loss history"):
        prepare(second)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lost_uncommitted_ticks", 0),
        ("lost_elapsed_ticks_complete", True),
        ("lost_uncommitted_decisions", True),
        ("save_failure_stage", "identity_before_save"),
        ("source_failure_sha256", "bad"),
        ("retained_prompt_changes", None),
        ("termination_stage", "done"),
        ("actions_replayed", True),
    ],
)
def test_discontinuity_rejects_missing_loss_and_false_completion(terminated, field, value):
    record = prepare(terminated)
    record[field] = value
    with pytest.raises(ValueError):
        validate_discontinuities([record])


@pytest.mark.parametrize(
    "change",
    [
        "final_agent",
        "final_result",
        "save_attempt",
        "newer_save",
        "failure_kind",
        "failure_clock",
        "native_after",
        "key_count",
        "initial_memory",
        "initial_usage",
        "source_revision",
        "runtime_cleanup",
        "runtime_checkpoint",
        "tail_step",
        "tail_history",
        "tail_profile",
        "tail_tokens",
        "final_tokens",
        "journal_pending",
        "journal_source",
        "initial_prompt",
    ],
)
def test_changed_originals_are_rejected_before_any_game_call(terminated, change):
    checkpoint, source, declaration = terminated
    segment = source / "segment-0"
    if change in {"final_agent", "final_result", "save_attempt"}:
        names = {
            "final_agent": "agent-after.json",
            "final_result": "result.json",
            "save_attempt": "save-attempt.json",
        }
        (segment / names[change]).write_text("{}")
    elif change == "newer_save":
        (source / "runtime-0/runtime/data/save/fixture/world.sav").write_text("newer")
    elif change == "source_revision":
        declaration["source_revision"] = "c" * 40
    else:
        if change.startswith("initial_"):
            path = segment / "agent-before.json"
            value = read(path)
            if change == "initial_memory":
                value["memory"] = "injected strategy"
            elif change == "initial_usage":
                value["usage"]["total_tokens"] -= 1
            else:
                value["prompt_changes"] = []
        elif change.startswith("runtime_"):
            path = source / "runtime-0/result.json"
            value = read(path)
            if change == "runtime_cleanup":
                value["cleanup_verified"] = False
            else:
                value["source_checkpoint_file_sha256"] = "f" * 64
        elif change.startswith("tail_"):
            path = segment / "loop/trace.jsonl"
            values = [json.loads(line) for line in path.read_text().splitlines()]
            if change == "tail_step":
                values[-1]["step"] += 1
            elif change == "tail_history":
                values[-1]["discontinuities"] = [{"bad": 1}]
            elif change == "tail_profile":
                values[-1]["events"][0]["data"]["receipt"]["prompt_profile"] = MEMORY_PROMPT
            else:
                values[-1]["events"][0]["data"]["receipt"]["transport_receipt"]["total_tokens"] += 1
            path.write_text("".join(json.dumps(v) + "\n" for v in values))
            with pytest.raises(ValueError):
                prepare(terminated)
            return
        elif change.startswith("journal_"):
            path = segment / "loop/usage.jsonl"
            raw = path.read_text()
            if change == "journal_pending":
                raw += json.dumps({"type": "decision_started", "step": 4}) + "\n"
            else:
                raw = raw.replace("runtime-test", "other-test")
            path.write_text(raw)
            with pytest.raises(ValueError):
                prepare(terminated)
            return
        else:
            path = segment / "loop/failures.jsonl"
            value = json.loads(path.read_text())
            if change == "failure_kind":
                value["error_type"] = "ValueError"
            elif change == "failure_clock":
                value["tick_receipt"] = {"ticks_advanced": 0}
            elif change == "native_after":
                value["native_after"] = value["native_after_apply"]
            elif change == "key_count":
                value["execute"]["result"]["keys_confirmed"] = 0
            else:
                value["events"][0]["receipt"]["transport_receipt"]["total_tokens"] += 1
        path.write_text(json.dumps(value) + "\n")
    with pytest.raises(ValueError):
        prepare(terminated)
