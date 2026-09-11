"""Synthetic rejected-input accounting contracts; not native gameplay evidence."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

BASE = Path(__file__).resolve().parents[1] / "experiments"
BASE /= "keyboard_binding_comparison_continuations_20260911"


@pytest.fixture
def review(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    return importlib.import_module("rejection_review")


@pytest.fixture
def rejection():
    class Rejected(ValueError):
        pass

    rejected = Rejected("original frozen parser rejection")
    rejected.action = {
        "type": "KEYSTROKE",
        "params": {"keys": ["SYM:0:>"]},
        "advance_ticks": 100,
        "memory_update": "attempted update, not applied",
    }
    rejected.invalid_keys = ["SYM:0:>"]
    record = {
        "record_origin": "model_input_rejection/v1",
        "action": deepcopy(rejected.action),
        "state_after_advance": {"year": 30, "year_tick": 16801, "pause_state": True},
        "execute": {
            "accepted": False,
            "validation_rejected": True,
            "why": str(rejected),
            "result": {
                "ok": False,
                "command_mutation": "not_attempted",
                "keys_sent": 0,
                "keys_confirmed": 0,
                "native_action_dispatched": False,
                "invalid_keys": rejected.invalid_keys.copy(),
            },
            "tick_feedback": {
                "requested_ticks": 100,
                "ticks_advanced": 0,
                "deferred": False,
                "clock_dispatched": False,
                "reason": "unsupported_native_keys",
            },
        },
        "tick_advance": {
            "schema_version": "fortgym.no-native-dispatch/v1",
            "ok": False,
            "error": "unsupported_native_keys",
            "requested": 100,
            "ticks_advanced": 0,
            "clock_dispatched": False,
            "start_year": 30,
            "start_tick": 16801,
            "end_year": 30,
            "end_tick": 16801,
            "paused_before": True,
            "paused_after": True,
        },
    }
    return record, rejected


def test_retained_typed_rejection_counts_no_keys_without_altering_it(review, rejection):
    before = deepcopy(rejection[0])
    assert review.verify_rejected_record(*rejection) == 0
    assert rejection[0] == before
    assert rejection[0]["action"] is not None


@pytest.mark.parametrize(
    "path,value",
    [
        (("record_origin",), "accepted"),
        (("action",), None),
        (("action", "memory_update"), "changed attempted memory"),
        (("action", "params", "keys"), ["d"]),
        (("state_after_advance", "year"), True),
        (("state_after_advance", "year_tick"), 16801.0),
        (("state_after_advance", "pause_state"), False),
        (("execute", "accepted"), True),
        (("execute", "validation_rejected"), False),
        (("execute", "why"), "different reason"),
        (("execute", "result", "ok"), True),
        (("execute", "result", "command_mutation"), "completed"),
        (("execute", "result", "keys_sent"), 1),
        (("execute", "result", "keys_confirmed"), False),
        (("execute", "result", "native_action_dispatched"), True),
        (("execute", "result", "invalid_keys"), []),
        (("execute", "tick_feedback", "requested_ticks"), 0),
        (("execute", "tick_feedback", "ticks_advanced"), 1),
        (("execute", "tick_feedback", "deferred"), True),
        (("execute", "tick_feedback", "clock_dispatched"), True),
        (("execute", "tick_feedback", "reason"), "accepted"),
        (("tick_advance", "schema_version"), "different"),
        (("tick_advance", "ok"), True),
        (("tick_advance", "error"), None),
        (("tick_advance", "requested"), 0),
        (("tick_advance", "ticks_advanced"), False),
        (("tick_advance", "clock_dispatched"), True),
        (("tick_advance", "start_year"), 29),
        (("tick_advance", "start_tick"), 16800),
        (("tick_advance", "end_year"), 31),
        (("tick_advance", "end_tick"), 16802),
        (("tick_advance", "paused_before"), False),
        (("tick_advance", "paused_after"), False),
    ],
)
def test_changed_attempt_dispatch_or_clock_fails(review, rejection, path, value):
    target = rejection[0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        review.verify_rejected_record(*rejection)


@pytest.fixture
def parser_boundary(monkeypatch, rejection):
    condition = {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "control_profile": "native_keyboard_bindings/v1",
        "bindings_sha256": "a" * 64,
        "max_advance_ticks": 1,
    }
    request = {**condition, "screen": {"synthetic_screen": True}}
    calls = []

    def rejected_receipt(result, **kwargs):
        calls.append((result, kwargs))
        return rejection[1]

    monkeypatch.setitem(
        sys.modules,
        "fort_gym.bench.agent.keyboard_rejection",
        SimpleNamespace(rejected_receipt=rejected_receipt),
    )
    monkeypatch.setitem(
        sys.modules,
        "fort_gym.bench.agent.keyboard_exchange",
        SimpleNamespace(digest=lambda value: "screen-digest" if value == "encoded" else None),
    )

    def encode_screen(screen, profile):
        assert screen == request["screen"] and profile == "text-profile"
        return "encoded"

    monkeypatch.setitem(
        sys.modules,
        "fort_gym.bench.env.screen_observation",
        SimpleNamespace(TEXT_PROFILE="text-profile", encode_screen=encode_screen),
    )
    return request, {"original": "provider result"}, condition, calls


def test_declared_profile_and_screen_are_bound_to_frozen_parser(review, rejection, parser_boundary):
    request, result, condition, calls = parser_boundary
    assert review.review_rejection(rejection[0], request, result, condition) == 0
    assert calls == [
        (
            result,
            {
                "screen_sha256": "screen-digest",
                "model": condition["model"],
                "reasoning_effort": "medium",
                "control_profile": "native_keyboard_bindings/v1",
                "max_advance_ticks": 1,
            },
        )
    ]


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "gpt-6-astra"),
        ("reasoning_effort", "high"),
        ("control_profile", "native_keyboard/v1"),
        ("bindings_sha256", "b" * 64),
        ("max_advance_ticks", True),
    ],
)
def test_changed_declared_request_fails_before_parser(
    review, rejection, parser_boundary, key, value
):
    request, result, condition, calls = parser_boundary
    request[key] = value
    with pytest.raises(ValueError, match="declared condition"):
        review.review_rejection(rejection[0], request, result, condition)
    assert calls == []


def test_terminal_route_reads_original_provider_rejection(review, monkeypatch, tmp_path):
    terminal = importlib.import_module("terminal_review")
    request, result = {"original": "request"}, {"original": "result"}
    (tmp_path / "request.json").write_text(json.dumps(request))
    (tmp_path / "response.json").write_text(json.dumps({"result": result}))
    calls = []
    monkeypatch.setattr(terminal, "review_rejection", lambda *args: calls.append(args) or 0)
    record, condition = {"original": "trace"}, {"original": "condition"}
    assert terminal.verify_input(record, None, tmp_path, condition, None, None) == 0
    assert calls == [(record, request, result, condition)]


def test_terminal_accepted_route_does_not_reconstruct_rejection(review, monkeypatch, tmp_path):
    terminal = importlib.import_module("terminal_review")
    calls = []
    monkeypatch.setattr(terminal, "verify_keys", lambda *args: calls.append(args) or 2)
    action, record, condition, index = {}, {}, {}, object()
    assert terminal.verify_input(record, action, tmp_path, condition, index, None) == 2
    assert calls == [(record, action, condition, index, None)]
