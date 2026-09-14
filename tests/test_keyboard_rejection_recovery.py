"""Historical rejected input settles forward, without deleting failed usage."""

import json
from copy import deepcopy

import pytest

from fort_gym.bench.agent.codex_transport import CodexTransportError
from fort_gym.bench.agent.keyboard_exchange import digest, publish, read
from fort_gym.bench.agent.keyboard_rejection import KeyboardInputRejected
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_loop import CampaignLoop, reconciled_usage
from fort_gym.bench.run.keyboard_recovery import inspect_recovery_source, reconcile_loaded_tail
from fort_gym.bench.run.keyboard_rejection_journal import RECORD
from fort_gym.bench.run.keyboard_rejection_recovery import journal_record
from tests.test_campaign_codex_keyboard import agent, decision, start
from tests.test_keyboard_recovery import NativeFixture, loaded_fixture
from tests.test_keyboard_rejection import rejected


@pytest.fixture
def source(tmp_path):
    first = start(tmp_path)
    first.step()
    parent = tmp_path / "parent"
    first.checkpoint(parent, snapshotter=first.environment, code_revision="fixture")
    segment, exchange = tmp_path / "failed", tmp_path / "exchange"
    segment.mkdir()
    exchange.mkdir()

    def captured(screen, memory, feedback):
        response = rejected(screen, memory, feedback)
        request = {
            "schema_version": "fortgym.keyboard-exchange-request/v1",
            "request_id": "b" * 32, "screen": screen, "memory": memory,
            "feedback": feedback, "control_profile": "native_keyboard/v2",
            "observation_profile": "native_screen_text/v1", "max_advance_ticks": 2000,
        }
        publish(exchange / "request.json", request)
        publish(exchange / "response.json", {"request_sha256": digest(request), "result": response})
        return response

    env = NativeFixture()
    env.tick = first.environment.tick
    loop = CampaignLoop.resume(
        parent, agent=agent(), environment=env, output=segment / "loop",
        latest_usage_path=first.journal,
    )
    publish(segment / "agent-before.json", loop.agent.export_campaign_state())
    loop.step()
    loop.step()
    loop.agent.decision = captured
    current_decide = loop.agent.decide

    def historical_decide(*args):
        try:
            return current_decide(*args)
        except KeyboardInputRejected as error:
            raise CodexTransportError(
                "Keyboard decision or subscription identity failed",
                read(exchange / "response.json")["result"],
            ) from error

    loop.agent.decide = historical_decide
    with pytest.raises(CodexTransportError):
        loop.step()
    env.capture(segment / "unreconciled-native-save")
    publish(segment / "agent-after.json", loop.agent.export_campaign_state())
    publish(segment / "native-after.json", env.observe())
    publish(segment / "result.json", {
        "schema_version": "fortgym.keyboard-segment/v1", "status": "failed",
        "stop_reason": "unsettled_failure", "first_step": 1, "next_step": 3,
        "checkpoint_verified": False, "recovery_requires_reconciliation": True,
        "unreconciled_native_snapshot_retained": True, "committed_elapsed_ticks": 30,
        "usage": loop.agent.export_campaign_state()["usage"],
    })
    return {"parent": parent, "segment": segment, "exchange": exchange}


def test_failed_rejection_recovers_newest_state_and_continues_without_replay(tmp_path, source):
    plan = inspect_recovery_source(**source)
    assert plan["failed_step"] == 3 and plan["next_step"] == 4
    originals = {p: p.read_bytes() for root in source.values()
                 for p in root.rglob("*") if p.is_file()}
    original_journal = source["segment"] / "loop/usage.jsonl"
    final = read(source["segment"] / "agent-after.json")
    with pytest.raises(ValueError, match="unresolved"):
        reconciled_usage(final, original_journal.read_bytes())
    env = loaded_fixture(tmp_path, source)
    env.tick = 153
    result = reconcile_loaded_tail(
        **source, plan=plan, agent=agent(lambda *a: pytest.fail("No model during recovery")),
        environment=env, snapshotter=env, output=tmp_path / "recovery", revision="fixture",
    )
    assert result["next_step"] == 4 and result["elapsed_ticks"] == 30
    assert result["usage"] == final["usage"]
    assert result["model_calls"] == result["native_input_commands"] == result["native_ticks_requested"] == 0
    assert all(p.read_bytes() == content for p, content in originals.items())
    recovered = tmp_path / "recovery"
    journal = (recovered / "usage.jsonl").read_bytes()
    assert journal.startswith(original_journal.read_bytes())
    records = [json.loads(line) for line in journal.splitlines()]
    assert records[-2]["decision_returned"] is False
    assert records[-1]["type"] == RECORD
    assert records[-1]["original_failure_reclassified_as_success"] is False
    assert reconciled_usage(final, journal) == final["usage"]
    checkpoint = verify_checkpoint(recovered / "checkpoint")
    assert checkpoint["payload"]["parent_sha256"] == plan["parent_checkpoint_sha256"]
    assert read(recovered / "checkpoint/agent.json") == final
    rows = [json.loads(line) for line in (recovered / "trace.jsonl").read_bytes().splitlines()]
    assert [r["step"] for r in rows] == list(range(4))
    assert rows[-1]["record_origin"] == "verified_input_rejection_reconciliation/v1"
    assert rows[-1]["action"]["params"]["keys"] == ["BUILJOB_FARM_SPRING", "SELECT"]
    assert rows[-1]["tick_advance"]["ok"] is False
    assert rows[-1]["execute"]["result"]["keys_confirmed"] == 0
    seen = []

    def following(screen, memory, feedback):
        seen.append((memory, feedback))
        return decision(screen, memory, feedback)

    next_env = NativeFixture()
    next_env.tick = 153
    loop = CampaignLoop.resume(
        recovered / "checkpoint", agent=agent(following), environment=next_env,
        output=tmp_path / "next", latest_usage_path=recovered / "usage.jsonl",
    )
    assert next_env.actions == []
    loop.step()
    assert len(next_env.actions) == 1 and loop.next_step == 5
    assert seen[0][0] == "xxx"
    assert seen[0][1]["accepted"] is False
    assert "BUILJOB_FARM_SPRING" in seen[0][1]["reason"]
    assert "BUILDJOB_FARM_SPRING" not in seen[0][1]["reason"]
    assert seen[0][1]["simulation"]["runtime_reloaded"] is True
    assert loop.agent.usage["total_tokens"] == 500
    assert reconciled_usage(loop.agent.export_campaign_state(), loop.journal.read_bytes()) == loop.agent.usage
    loop.checkpoint(tmp_path / "next-checkpoint", snapshotter=next_env, code_revision="fixture")


@pytest.mark.parametrize("kind", [
    "hash", "step", "failure_context", "returned", "dispatch", "relabel", "unpaused",
    "receipt_tokens", "receipt_auth", "receipt_timed_out", "receipt_key_command",
    "receipt_bool_command", "receipt_screen", "receipt_valid_keys", "receipt_shape",
    "receipt_incomplete", "usage_regression", "usage_count", "duplicate", "bare",
])
def test_reconciliation_requires_complete_original_evidence(source, kind):
    final = read(source["segment"] / "agent-after.json")
    journal = (source["segment"] / "loop/usage.jsonl").read_bytes()
    extra = journal_record(segment=source["segment"], exchange=source["exchange"])
    receipt = extra["response"]["result"]["transport_receipt"]
    if kind == "hash":
        extra["original_journal_sha256"] = "0" * 64
    elif kind == "step":
        extra["step"] += 1
    elif kind == "failure_context":
        extra["original_failure"]["execute"] = {"accepted": True}
    elif kind == "returned":
        extra["decision_returned"] = True
    elif kind == "dispatch":
        extra["native_action_dispatched"] = True
    elif kind == "relabel":
        extra["original_failure_reclassified_as_success"] = True
    elif kind == "unpaused":
        extra["native_boundary"]["pause_state"] = False
    elif kind == "receipt_tokens":
        receipt["total_tokens"] += 1
    elif kind == "receipt_auth":
        receipt["auth_mode"] = "apikey"
    elif kind == "receipt_timed_out":
        receipt["timed_out"] = True
    elif kind == "receipt_key_command":
        receipt["native_game_commands"] = 1
    elif kind == "receipt_bool_command":
        receipt["native_game_commands"] = False
    elif kind == "receipt_screen":
        extra["response"]["result"]["screen_sha256"] = "0" * 64
    elif kind == "receipt_valid_keys":
        receipt["response"]["params"]["keys"] = ["SELECT"]
    elif kind == "receipt_shape":
        receipt["response"]["advance_ticks"] = True
    elif kind == "receipt_incomplete":
        receipt["usage_complete"] = False
    elif kind in ("usage_regression", "usage_count"):
        lines = [json.loads(line) for line in journal.splitlines()]
        lines[-1]["usage"]["total_tokens" if kind == "usage_regression" else "returned_responses"] -= 1
        journal = b"".join((json.dumps(line) + "\n").encode() for line in lines)
        import hashlib
        extra["original_journal_sha256"] = hashlib.sha256(journal).hexdigest()
    if kind.startswith("receipt_"):
        extra["original_failure"]["events"][0]["receipt"] = deepcopy(extra["response"]["result"])
    raw = (json.dumps(extra) + "\n").encode()
    if kind == "bare":
        raw = b""
    if kind == "duplicate":
        raw += raw
    with pytest.raises(ValueError):
        reconciled_usage(final, journal + raw)


@pytest.mark.parametrize("kind", ["memory", "calendar", "pause", "prefix", "failure", "usage"])
def test_inconsistent_retained_source_is_not_recoverable(source, kind):
    name = {
        "memory": "agent-after.json", "calendar": "native-after.json",
        "pause": "native-after.json", "prefix": "loop/trace.jsonl",
        "failure": "loop/failures.jsonl", "usage": "result.json",
    }[kind]
    path = source["segment"] / name
    if kind == "prefix":
        path.write_bytes(path.read_bytes().replace(b'"step": 0', b'"step": 9', 1))
    else:
        value = read(path)
        if kind == "memory":
            value["memory"] = "attempted memory applied"
        elif kind == "calendar":
            value["year_tick"] += 1
        elif kind == "pause":
            value["pause_state"] = False
        elif kind == "failure":
            value["execute"] = {"accepted": True}
        else:
            value["usage"]["total_tokens"] += 1
        path.write_text(json.dumps(value) + "\n")
    with pytest.raises(ValueError):
        inspect_recovery_source(**source)
