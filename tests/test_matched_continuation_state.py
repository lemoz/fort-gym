"""Synthetic continuation gates are contract tests, not native gameplay proof."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/keyboard_binding_comparison_continuations_20260911"


@pytest.fixture
def state(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    spec = importlib.util.spec_from_file_location(
        "continuation_state", BASE / "continuation_state.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "continuation_state", module)
    return module


@pytest.fixture
def boundary():
    condition = json.loads(
        (ROOT / "experiments/keyboard_binding_comparison_20260911/sol-condition.json").read_text()
    )
    agent = {"memory": "the model's own saved memory", "usage": {"total_tokens": 123}}
    origin = {
        "agent": agent,
        "feedback": {"accepted": False, "reason": "original feedback"},
        "metrics": {"population": 7, "wood_stock": None},
        "condition": condition,
        "manifest": {
            "sha256": "a" * 64,
            "payload": {"native_save": {"year": 30, "year_tick": 19701}},
        },
        "window": {"expected_campaign_id": "bindings-comparison-20260911-sol-r1"},
        "prefix_sha256": {"trace.jsonl": "b" * 64, "usage.jsonl": "c" * 64},
        "dispatch_prefix_sha256": {"trace.jsonl": "b" * 64, "usage.jsonl": "e" * 64},
        "checkpoint": Path("/synthetic/checkpoint"),
    }
    request = {
        k: condition[k]
        for k in (
            "model",
            "reasoning_effort",
            "control_profile",
            "prompt_profile",
            "bindings_sha256",
        )
    }
    request.update(
        memory=agent["memory"],
        feedback=deepcopy(origin["feedback"]),
        screen={"width": 120, "height": 40},
    )
    loaded = {
        "agent": deepcopy(agent),
        "history": {"discontinuities": []},
        "before": {
            "year": 30,
            "year_tick": 19701,
            "pause_state": True,
            "metrics": deepcopy(origin["metrics"]),
            "menu": "reloaded default",
        },
        "prefix_sha256": deepcopy(origin["dispatch_prefix_sha256"]),
        "request": request,
        "metrics": lambda before: before["metrics"],
    }
    return origin, loaded


def test_load_gate_preserves_own_state_without_requiring_identical_menu(state, boundary):
    result = state.verify_loaded_state(boundary[0], **boundary[1])
    assert result["passed"] is True
    assert result["model_calls_by_gate"] == result["gameplay_inputs_by_gate"] == 0
    assert result["new_checkpoint_verified"] is False
    assert boundary[0]["agent"]["memory"] not in json.dumps(result)
    assert boundary[0]["feedback"]["reason"] not in json.dumps(result)
    assert result["exact_decision_started_marker_verified"] is True
    assert result["original_prefix_sha256"] == boundary[0]["prefix_sha256"]
    assert result["first_dispatch_prefix_sha256"] == boundary[0]["dispatch_prefix_sha256"]


def test_native_loop_marker_is_exact_and_does_not_reset_saved_usage(state):
    assert state.decision_started_bytes(64) == b'{"type": "decision_started", "step": 64}\n'
    for value in (True, 0, 63, 65, "64", None):
        with pytest.raises(ValueError):
            state.decision_started_bytes(value)


def test_a_saved_prefix_without_the_started_marker_is_not_a_dispatch_boundary(state, boundary):
    origin, loaded = boundary
    loaded["prefix_sha256"] = deepcopy(origin["prefix_sha256"])
    with pytest.raises(ValueError, match="pending-dispatch"):
        state.verify_loaded_state(origin, **loaded)


@pytest.mark.parametrize(
    "name,replicate",
    [
        ("sol", 1),
        ("terra", 1),
        ("astra", 1),
        ("terra", 2),
        ("sol", 2),
        ("astra", 2),
    ],
)
def test_all_six_declared_slots_use_the_same_gate(state, boundary, name, replicate):
    origin, loaded = boundary
    identity = f"bindings-comparison-20260911-{name}-r{replicate}"
    condition = json.loads(
        (
            ROOT / "experiments/keyboard_binding_comparison_20260911" / f"{name}-condition.json"
        ).read_text()
    )
    origin["condition"] = condition
    origin["window"]["expected_campaign_id"] = identity
    for key in (
        "model",
        "reasoning_effort",
        "control_profile",
        "prompt_profile",
        "bindings_sha256",
    ):
        loaded["request"][key] = condition[key]
    result = state.verify_loaded_state(origin, **loaded)
    assert result["passed"] is True and result["campaign_id"] == identity


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("agent", "memory", "human strategy"),
        ("agent", "usage", {"total_tokens": 0}),
        ("history", "discontinuities", [{"restart": True}]),
        ("before", "year_tick", 19702),
        ("before", "year", True),
        ("before", "pause_state", False),
        ("before", "metrics", {"population": 8}),
        ("prefix_sha256", "trace.jsonl", "d" * 64),
        ("prefix_sha256", "usage.jsonl", "d" * 64),
        ("request", "memory", ""),
        ("request", "feedback", None),
        ("request", "model", "gpt-6-astra"),
        ("request", "reasoning_effort", "high"),
        ("request", "control_profile", "assisted"),
        ("request", "prompt_profile", "different"),
        ("request", "bindings_sha256", "d" * 64),
        ("request", "screen", {"width": 80, "height": 25}),
    ],
)
def test_changed_load_is_rejected(state, boundary, target, field, value):
    origin, loaded = boundary
    loaded[target][field] = value
    with pytest.raises(ValueError):
        state.verify_loaded_state(origin, **loaded)


def test_feedback_keeps_rejection_and_clock_result_without_inventing_advice(state):
    assert state.prior_feedback({"last_result": None}) is None
    runner = {
        "last_result": {
            "accepted": False,
            "why": "blocking_native_menu",
            "result": {"keys_confirmed": 0, "command_mutation": "none"},
            "tick_feedback": {"requested_ticks": 2000, "ticks_advanced": 0},
        }
    }
    value = state.prior_feedback(runner)
    assert value == {
        "accepted": False,
        "reason": "blocking_native_menu",
        "keys_confirmed": 0,
        "command_mutation": "none",
        "simulation": runner["last_result"]["tick_feedback"],
    }
    runner["last_result"]["restart"] = {}
    with pytest.raises(ValueError, match="restart"):
        state.prior_feedback(runner)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', "[]"])
def test_ambiguous_evidence_is_rejected(state, tmp_path, raw):
    path = tmp_path / "evidence.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        state.read(path)


def test_gate_runs_before_transport_and_once_per_window(state, boundary, monkeypatch, tmp_path):
    import window_courier as courier

    origin, loaded = boundary
    requests, gates, reads = [], [], []
    native = SimpleNamespace(
        verify_checkpoint=lambda _: origin["manifest"],
        metrics=loaded["metrics"],
        owner=SimpleNamespace(
            publish=lambda path, value: gates.append(value),
            answer_request=lambda request, **kwargs: requests.append(request) or "reply",
        ),
    )
    remote = {key: value for key, value in loaded.items() if key not in {"request", "metrics"}}
    monkeypatch.setattr(courier, "collect_loaded", lambda *_: reads.append(True) or remote)
    answer = courier.gated_answer(native, origin, "synthetic-owned-game", tmp_path)
    assert requests == gates == reads == []
    assert answer(loaded["request"]) == "reply"
    assert answer(loaded["request"]) == "reply"
    assert len(requests) == 2 and len(gates) == len(reads) == 1


def test_gate_failure_never_calls_transport(state, boundary, monkeypatch, tmp_path):
    import window_courier as courier

    origin, loaded = boundary
    calls = []
    native = SimpleNamespace(
        verify_checkpoint=lambda _: origin["manifest"],
        metrics=loaded["metrics"],
        owner=SimpleNamespace(
            publish=lambda *args: calls.append("publish"),
            answer_request=lambda *args, **kwargs: calls.append("model"),
        ),
    )
    remote = {key: value for key, value in loaded.items() if key not in {"request", "metrics"}}
    remote["before"]["year_tick"] += 1
    monkeypatch.setattr(courier, "collect_loaded", lambda *_: remote)
    with pytest.raises(ValueError, match="advanced"):
        courier.gated_answer(native, origin, "synthetic-owned-game", tmp_path)(loaded["request"])
    assert calls == []


def test_changed_parent_is_rejected_before_even_reading_the_game(
    state, boundary, monkeypatch, tmp_path
):
    import window_courier as courier

    calls = []
    native = SimpleNamespace(verify_checkpoint=lambda _: {"sha256": "changed"})
    monkeypatch.setattr(courier, "collect_loaded", lambda *_: calls.append("read game"))
    with pytest.raises(ValueError, match="Parent changed"):
        courier.gated_answer(native, boundary[0], "synthetic-owned-game", tmp_path)(
            boundary[1]["request"]
        )
    assert calls == []


def test_collect_loaded_uses_only_fixed_readonly_paths(state):
    import window_courier as courier

    calls = []

    def output(command):
        calls.append(command)
        return "{}"

    native = SimpleNamespace(owner=SimpleNamespace(DOCKER=["fake-docker"], output=output))
    assert set(courier.collect_loaded(native, "owned-game")) == {
        "agent",
        "history",
        "before",
        "prefix_sha256",
    }
    assert len(calls) == 4
    assert all(command[:3] == ["fake-docker", "exec", "owned-game"] for command in calls)
    assert [command[3] for command in calls[:3]] == ["/bin/cat"] * 3
    assert all(command[-1].startswith("/evidence/astra/segment-0/") for command in calls[:3])
    assert calls[-1][3:5] == ["/opt/python/bin/python3.11", "-c"]
    assert calls[-1][-1] == courier.PREFIX_DIGEST_SCRIPT
