"""Offline transport and inference doubles; no VM or provider calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run import keyboard_window_courier as module
from tests.test_keyboard_runtime import request

PROJECT = Path(__file__).resolve().parents[1]
CONDITION = read(PROJECT / "experiments/keyboard_matched_pilot_20260910/astra-condition.json")
WINDOW = read(PROJECT / "experiments/keyboard_matched_endurance_20260910/astra_r1-64-128.json")


class FakeExchange:
    def __init__(self, out, total=64):
        self.out, self.total = out, total
        self.responded, self.probes, self.calls = 0, 0, 0
        self.memory = "retained model memory"
        self.request_change, self.fail_delivery = {}, False
        self.dispatched, self.grammar = True, True
        self.stop_on_failure, self.ready = True, True

    def running(self):
        return self.responded < self.total

    def pending(self):
        # Previously answered requests remain visible, as on the native volume.
        return [f"{i + 1:032x}" for i in range(self.responded + 1)]

    def copy_request(self, identifier, directory):
        if not self.ready:
            self.ready = True
            return False
        directory.mkdir()
        value = {
            **request(),
            "schema_version": "fortgym.keyboard-exchange-request/v3",
            "request_id": identifier,
            "memory": self.memory,
            "model": CONDITION["model"],
            "reasoning_effort": CONDITION["reasoning_effort"],
            "prompt_profile": CONDITION["prompt_profile"],
            "max_advance_ticks": CONDITION["max_advance_ticks"],
            **self.request_change,
        }
        publish(directory / "request.json", value)
        return True

    def deliver(self, arguments, value, label):
        if arguments[0] == "probe":
            self.probes += 1
            return
        if self.fail_delivery:
            raise RuntimeError("Synthetic response delivery failure")
        self.responded += 1
        result = value["result"]
        if result["action_grammar_valid"]:
            self.memory = result["action"]["memory_update"]
        if self.dispatched is not True and self.stop_on_failure:
            self.total = self.responded

    def answer(self, value, **kwargs):
        self.calls += 1

        def decision(screen, **options):
            assert options["allowance_check"]()["allowed"] is True
            assert options["memory"] == self.memory
            return {
                "transport_receipt": {
                    "dispatched": self.dispatched,
                    "total_tokens": 10,
                    "reported_charge_usd": None,
                },
                "action_grammar_valid": self.grammar,
                "action": {"memory_update": "model-owned-memory-" + str(self.calls)},
            }

        return answer_request(
            value,
            **kwargs,
            decision=decision,
            allowance_check=lambda: {"allowed": True, "basis": "unit_fixture"},
        )


def serve(exchange, decisions=None, **options):
    module.serve_window(
        exchange,
        CONDITION,
        options.pop("window", WINDOW),
        initial_memory="retained model memory",
        executable=Path("/fixture/codex"),
        decisions=decisions if decisions is not None else [],
        answer=exchange.answer,
        wait=lambda _: None,
        **options,
    )


@pytest.mark.parametrize("segments", [1, 2, 4, 8])
def test_64_and_multisegment_windows_are_not_limited_to_32(tmp_path, segments):
    window = {**WINDOW, "max_segments": segments}
    exchange = FakeExchange(tmp_path, total=64 * segments)
    decisions = []
    serve(exchange, decisions, window=window)
    assert exchange.calls == exchange.responded == len(decisions) == 64 * segments
    assert exchange.probes == 1
    assert [row["decision_index"] for row in decisions] == list(range(64 * segments))
    assert all(row["model_dispatched"] is True for row in decisions)
    folders = sorted((tmp_path / "model").iterdir())
    assert len(folders) == len(decisions)
    for directory in folders:
        assert read(directory / "summary.json")["total_tokens"] == 10
        assert (directory / "claim.json").is_file() and (directory / "response.json").is_file()


def test_overrun_is_rejected_before_the_extra_inference(tmp_path):
    exchange = FakeExchange(tmp_path, total=65)
    with pytest.raises(ValueError, match="extra or retried"):
        serve(exchange)
    assert exchange.calls == exchange.responded == 64


@pytest.mark.parametrize(
    "change",
    [
        {"memory": "borrowed model memory"},
        {"request_id": "f" * 32},
        {"model": "gpt-5.6-sol"},
        {"reasoning_effort": "low"},
        {"max_advance_ticks": 1},
        {"screen": {"width": 1, "height": 1, "tiles": [[32, 7, 0]]}},
    ],
)
def test_changed_request_does_not_reach_inference(tmp_path, change):
    exchange = FakeExchange(tmp_path, total=1)
    exchange.request_change = change
    with pytest.raises(ValueError):
        serve(exchange)
    assert not list(tmp_path.glob("model/*/claim.json"))
    assert exchange.responded == 0


def test_not_ready_does_not_create_a_directory_that_blocks_later_copy(tmp_path):
    exchange = FakeExchange(tmp_path, total=1)
    exchange.ready = False
    serve(exchange)
    assert exchange.calls == 1


@pytest.mark.parametrize("dispatched", [False, None])
def test_budget_pause_or_unknown_call_is_retained_without_retry(tmp_path, dispatched):
    exchange = FakeExchange(tmp_path)
    exchange.dispatched, exchange.grammar = dispatched, False
    decisions = []
    serve(exchange, decisions)
    assert exchange.calls == 1 and decisions[0]["model_dispatched"] is dispatched
    assert (tmp_path / "model" / f"{1:032x}" / "response.json").is_file()


@pytest.mark.parametrize("dispatched", [False, None])
def test_native_retry_after_pause_or_unknown_outcome_is_rejected(tmp_path, dispatched):
    exchange = FakeExchange(tmp_path, total=2)
    exchange.dispatched, exchange.grammar, exchange.stop_on_failure = dispatched, False, False
    with pytest.raises(ValueError, match="extra or retried"):
        serve(exchange)
    assert exchange.calls == 1


def test_invalid_grammar_retains_usage_and_preserves_memory(tmp_path):
    exchange = FakeExchange(tmp_path, total=3)
    exchange.grammar = False
    decisions = []
    serve(exchange, decisions)
    assert exchange.calls == 3 and exchange.memory == "retained model memory"
    assert all(
        row["model_dispatched"] is True and row["action_grammar_valid"] is False
        for row in decisions
    )


def test_failed_delivery_retains_the_response_and_cannot_reinfer(tmp_path):
    exchange = FakeExchange(tmp_path, total=1)
    exchange.fail_delivery = True
    decisions = []
    with pytest.raises(RuntimeError, match="delivery failure"):
        serve(exchange, decisions)
    assert exchange.calls == 1 and len(decisions) == 1
    assert (tmp_path / "model" / f"{1:032x}" / "response.json").is_file()
    with pytest.raises(FileExistsError):
        serve(exchange)
    assert exchange.calls == 1


def test_deadline_prevents_a_new_inference(tmp_path):
    exchange = FakeExchange(tmp_path)
    _, bound = module.window_bounds(CONDITION, WINDOW)
    clock = iter([0, 0, bound])
    with pytest.raises(TimeoutError, match="deadline"):
        serve(exchange, clock=lambda: next(clock))
    assert exchange.calls == 0


@pytest.mark.parametrize(
    "change",
    [
        {"steps_per_segment": True},
        {"steps_per_segment": 65},
        {"max_segments": 17},
        {"max_segments": 0},
        {"continuation_from_next_step": 1270},
        {"reset_memory": True},
        {"reset_usage": True},
        {"strategy_intervention": True},
        {"budget_extension": {}},
        {"prompt_change": {}},
        {"restart": {}},
    ],
)
def test_invalid_window_admits_no_transport_or_model_calls(tmp_path, change):
    exchange = FakeExchange(tmp_path)
    with pytest.raises(ValueError):
        serve(exchange, window={**WINDOW, **change})
    assert not list(tmp_path.iterdir()) and exchange.calls == 0


def adapter(tmp_path, output=lambda _: ""):
    return module.DockerExchange(
        "owned-fixture", tmp_path, ["fixture-docker"], {}, output, lambda *args: None
    )


def test_adapter_delivers_exact_bytes_as_game_user_and_verifies_readback(tmp_path):
    calls = []

    def process(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(b'{"published_and_read_verified":true}\n')
        return SimpleNamespace(returncode=0)

    exchange = adapter(tmp_path)
    exchange.process = process
    value = {"request_sha256": "a" * 64, "result": {"fixture": True}}
    exchange.deliver(["publish-response", "--request-id", "b" * 32], value, "delivery")
    assert calls[0][0][:5] == [
        "fixture-docker",
        "exec",
        "-i",
        "owned-fixture",
        "/opt/python/bin/python3.11",
    ]
    assert json.loads(calls[0][1]["input"]) == value
    assert calls[0][1]["timeout"] == 20
    with pytest.raises(FileExistsError):
        exchange.deliver([], value, "delivery")
    assert len(calls) == 1


@pytest.mark.parametrize("body,code", [(b'{"published_and_read_verified":false}', 0), (b"{}", 1)])
def test_adapter_cannot_promote_failed_delivery(tmp_path, body, code):
    def process(command, **kwargs):
        kwargs["stdout"].write(body)
        return SimpleNamespace(returncode=code)

    exchange = adapter(tmp_path)
    exchange.process = process
    with pytest.raises(ValueError, match="not verified"):
        exchange.deliver([], {}, "delivery")


def test_adapter_uses_only_owned_literal_read_probes(tmp_path, monkeypatch):
    calls = []

    def observe(command, **options):
        calls.append((command, options))
        return ""

    monkeypatch.setattr(module, "observe_container_output", observe)
    exchange = adapter(tmp_path)
    assert exchange.pending() == []
    assert exchange.copy_request("a" * 32, tmp_path / "absent") is False
    assert not (tmp_path / "absent").exists()
    assert len(calls) == 2
    for command, options in calls:
        assert command[:5] == ["fixture-docker", "exec", "owned-fixture", "/bin/sh", "-c"]
        assert options["max_live_read_attempts"] == 3
        assert options["inspect_command"] == exchange.inspection
    with pytest.raises(ValueError):
        exchange.copy_request("../not-owned", tmp_path / "escape")
    assert len(calls) == 2


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_unknown_liveness_is_not_a_completed_window(tmp_path, value):
    exchange = adapter(tmp_path, output=lambda _: json.dumps({"Running": value}))
    with pytest.raises(ValueError, match="liveness is unknown"):
        exchange.running()
