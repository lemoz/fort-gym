"""Loss-aware rollback keeps original prompt history and all failed-attempt usage."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.agent.keyboard_prompt import MEMORY_PROMPT
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_restart import prepare_restart, validate_discontinuities
from fort_gym.bench.run.keyboard_restart_prompt import restart_prompt_state
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_keyboard_partial_restart import pending_failure
from tests.test_keyboard_restart import prepare
from tests.test_keyboard_prompt import condition, changed_decision
from tests.test_keyboard_runtime import environment, policy, saved as saved


@pytest.fixture
def modal(tmp_path, saved, monkeypatch):
    return pending_failure(tmp_path, saved, monkeypatch, modal=True, prompt_changed=True)


def test_modal_restart_retains_zero_tick_failure_and_original_prompt_boundary(modal):
    checkpoint, source, _ = modal
    record = prepare(modal)
    initial = read(source / "segment-0/agent-before.json")
    assert record["lost_elapsed_ticks"] == 20
    assert record["lost_uncommitted_ticks"] == 0 and record["lost_uncommitted_decisions"] == 1
    assert record["retained_usage"]["dispatched_requests"] == 4
    assert record["retained_usage"]["total_tokens"] == 400
    assert record["retained_prompt_changes"] == initial["prompt_changes"]
    assert record["retained_prompt_changes"][0]["usage"] == {
        "dispatched_requests": 1,
        "total_tokens": 100,
    }
    state = restart_prompt_state(read(checkpoint / "agent.json"), record)
    assert state["memory"] == read(checkpoint / "agent.json")["memory"]
    assert state["memory"] != read(source / "segment-0/agent-after.json")["memory"]
    assert state["usage"] == record["retained_usage"]


def test_modal_restart_and_subsequent_checkpoint_preserve_prompt_usage_and_memory(tmp_path, modal):
    checkpoint, source, declaration = modal
    immutable = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    seen = []

    def callback(screen, memory, feedback):
        seen.append((memory, deepcopy(feedback)))
        return changed_decision(screen, memory, feedback)

    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    result = run_keyboard_segment(
        agent=policy(condition(), callback),
        environment=env,
        snapshotter=env,
        output=tmp_path / "resumed",
        condition=condition(),
        checkpoint=checkpoint,
        latest_usage=source / "segment-0/loop/usage.jsonl",
        steps=1,
        expected_cursor=1,
        revision="b" * 40,
        restart_declaration=declaration,
        restart_source=source,
    )
    assert result["checkpoint_verified"] is True and result["usage"]["total_tokens"] == 500
    assert len(env.actions) == 1
    assert seen[0][0] == read(checkpoint / "agent.json")["memory"]
    assert seen[0][1]["infrastructure_restart"]["lost_elapsed_ticks"] == 20
    assert "prompt_change" not in result  # The existing change is retained, not applied again.
    record = prepare(modal)
    resumed = tmp_path / "resumed/checkpoint"
    agent_state = read(resumed / "agent.json")
    assert agent_state["prompt_changes"] == record["retained_prompt_changes"]
    continuation = CampaignLoop.resume(
        resumed,
        agent=policy(condition(), callback),
        environment=env,
        output=tmp_path / "continued",
        latest_usage_path=tmp_path / "resumed/loop/usage.jsonl",
    )
    assert continuation.agent.prompt_profile == MEMORY_PROMPT
    assert continuation.agent.usage["dispatched_requests"] == 5
    continuation.step()
    continuation.checkpoint(tmp_path / "next", snapshotter=env, code_revision="c" * 40)
    assert read(tmp_path / "next/agent.json")["prompt_changes"] == record["retained_prompt_changes"]
    assert read(tmp_path / "next/runner.json")["discontinuities"] == [record]
    assert all(p.read_bytes() == value for p, value in immutable.items())


@pytest.fixture
def repeated_modal(tmp_path, modal, monkeypatch):
    checkpoint, source, _ = modal
    return pending_failure(
        tmp_path / "second",
        (
            checkpoint,
            source / "segment-0/loop/usage.jsonl",
            int((checkpoint / "game/world.sav").read_text()),
        ),
        monkeypatch,
        modal=True,
        restart=modal,
    )


def test_repeated_rollback_retains_both_losses_and_original_prompt(tmp_path, modal, repeated_modal):
    first, second = prepare(modal), prepare(repeated_modal)
    checkpoint, source, declaration = repeated_modal
    assert second["retained_usage"]["accounted_responses"] == 7
    assert second["retained_usage"]["total_tokens"] == 700
    assert second["retained_prompt_changes"] == first["retained_prompt_changes"]
    before = read(source / "segment-0/agent-before.json")
    assert before["usage"] == first["retained_usage"]
    assert before["memory"] == read(checkpoint / "agent.json")["memory"]
    assert "prompt_change" not in read(source / "segment-0/result.json")
    immutable = {
        p: p.read_bytes() for root in (modal[1], source) for p in root.rglob("*") if p.is_file()
    }
    env = environment()
    env.tick = int((checkpoint / "game/world.sav").read_text())
    output = tmp_path / "third"
    result = run_keyboard_segment(
        agent=policy(condition(), changed_decision),
        environment=env,
        snapshotter=env,
        output=output,
        condition=condition(),
        checkpoint=checkpoint,
        latest_usage=source / "segment-0/loop/usage.jsonl",
        steps=1,
        expected_cursor=1,
        revision="c" * 40,
        restart_declaration=declaration,
        restart_source=source,
    )
    assert result["checkpoint_verified"] is True
    assert result["usage"]["total_tokens"] == 800 and len(env.actions) == 1
    assert read(output / "checkpoint/runner.json")["discontinuities"] == [first, second]
    state = read(output / "checkpoint/agent.json")
    assert state["prompt_changes"] == first["retained_prompt_changes"]
    assert all(p.read_bytes() == value for p, value in immutable.items())


@pytest.mark.parametrize(
    "mutation",
    [
        "restart_missing",
        "restart_usage",
        "restart_prompt",
        "restart_checkpoint",
        "history_missing",
        "history_changed",
        "initial_usage",
        "tail_history",
    ],
)
def test_repeated_rollback_rejects_lost_or_changed_history(repeated_modal, mutation):
    _, source, _ = repeated_modal
    segment = source / "segment-0"
    if mutation.startswith("restart_"):
        path = segment / "restart.json"
        if mutation == "restart_missing":
            path.unlink()
            with pytest.raises((ValueError, FileNotFoundError)):
                prepare(repeated_modal)
            return
        value = read(path)
        if mutation == "restart_usage":
            value["retained_usage"]["total_tokens"] -= 100
        elif mutation == "restart_prompt":
            value["retained_prompt_changes"] = []
        else:
            value["checkpoint_sha256"] = "f" * 64
    elif mutation.startswith("history_"):
        path = segment / "result.json"
        value = read(path)
        if mutation == "history_missing":
            value["discontinuities"] = []
        else:
            value["discontinuities"][0]["lost_elapsed_ticks"] += 1
    elif mutation == "initial_usage":
        path = segment / "agent-before.json"
        value = read(path)
        value["usage"]["total_tokens"] -= 100
    else:
        path = segment / "loop/trace.jsonl"
        values = [json.loads(line) for line in path.read_text().splitlines()]
        values[-1]["discontinuities"] = []
        path.write_text("".join(json.dumps(row) + "\n" for row in values))
        with pytest.raises(ValueError):
            prepare(repeated_modal)
        return
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(ValueError):
        prepare(repeated_modal)


@pytest.mark.parametrize(
    "mutation",
    [
        "initial_memory",
        "returned_memory",
        "initial_usage",
        "history_usage",
        "history_missing",
        "change_missing",
        "change_cursor",
        "change_result",
        "decision_profile",
        "old_decision_profile",
        "duplicated_decision_profile",
        "pause",
        "extra_clock_error",
        "clock_elapsed",
        "final_clock",
        "native_view",
        "source_save",
    ],
)
def test_changed_modal_source_never_dispatches_or_restores(modal, mutation):
    checkpoint, source, _ = modal
    segment = source / "segment-0"
    if mutation in {"initial_memory", "initial_usage", "history_usage", "history_missing"}:
        path = segment / "agent-before.json"
        value = read(path)
        if mutation == "initial_memory":
            value["memory"] = "injected plan"
        elif mutation == "initial_usage":
            value["usage"]["total_tokens"] += 1
        elif mutation == "history_usage":
            value["prompt_changes"][0]["usage"]["total_tokens"] += 1
        else:
            value.pop("prompt_changes")
    elif mutation in {"change_missing", "change_cursor"}:
        path = segment / "prompt-change.json"
        value = read(path)
        if mutation == "change_missing":
            path.unlink()
            with pytest.raises((ValueError, FileNotFoundError)):
                prepare(modal)
            return
        value["next_step"] += 1
    elif mutation == "returned_memory":
        path = segment / "agent-after.json"
        value = read(path)
        value["memory"] = "not the returned response"
    elif mutation == "change_result":
        path = segment / "result.json"
        value = read(path)
        value.pop("prompt_change")
    elif mutation in {"old_decision_profile", "duplicated_decision_profile"}:
        path = segment / "loop/trace.jsonl"
        values = [json.loads(line) for line in path.read_text().splitlines()]
        if mutation == "old_decision_profile":
            values[-1]["events"][0]["data"]["receipt"].pop("prompt_profile")
        else:
            values[-2]["events"].append(deepcopy(values[-1]["events"][0]))
            values[-1]["events"] = values[-1]["events"][1:]
        path.write_text("".join(json.dumps(row) + "\n" for row in values))
        with pytest.raises(ValueError):
            prepare(modal)
        return
    elif mutation == "source_save":
        (source / "runtime-0/runtime/data/save/fixture/world.sav").write_text("newer world")
        with pytest.raises(ValueError):
            prepare(modal)
        return
    else:
        path = segment / "loop/failures.jsonl"
        value = json.loads(path.read_text())
        if mutation == "decision_profile":
            value["events"][0]["receipt"].pop("prompt_profile")
        elif mutation == "pause":
            value["tick_receipt"]["repause"]["paused"] = False
        elif mutation == "extra_clock_error":
            value["tick_receipt"]["resume_error"] = "unknown"
        elif mutation == "clock_elapsed":
            value["tick_receipt"]["ticks_advanced"] = True
        elif mutation == "final_clock":
            value["native_after"]["year_tick"] += 1
        else:
            value["native_after_apply"]["viewscreen_type"] = "viewscreen_dwarfmodest"
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(ValueError):
        prepare(modal)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lost_uncommitted_ticks", None),
        ("lost_uncommitted_ticks", True),
        ("lost_uncommitted_ticks", 1),
        ("source_prompt_state_sha256", "invalid"),
        ("retained_prompt_changes", None),
        ("retained_usage", {}),
        ("failure_kind", "partial_interruption_pending_save"),
        ("lost_elapsed_ticks_complete", False),
        ("source_start_agent_sha256", "a" * 64),
    ],
)
def test_discontinuity_cannot_erase_known_zero_or_prompt_provenance(modal, field, value):
    record = prepare(modal)
    record[field] = value
    with pytest.raises(ValueError):
        validate_discontinuities([record])


def test_wrong_selected_prompt_fails_before_output_or_model_call(tmp_path, modal):
    from tests.test_keyboard_runtime import CONDITION

    checkpoint, source, declaration = modal
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="Prompt profile differs"):
        run_keyboard_segment(
            agent=policy(CONDITION),
            environment=None,
            snapshotter=None,
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
    assert not output.exists()


def test_restart_still_requires_explicit_new_failure_kind(modal):
    checkpoint, source, declaration = modal
    declaration.pop("failure_kind")
    with pytest.raises(ValueError):
        prepare_restart(
            checkpoint, source, declaration, (source / "segment-0/loop/usage.jsonl").read_bytes()
        )
