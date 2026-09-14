"""Configuration selection and launch packaging without a VM or inference."""

import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "experiments/keyboard_binding_comparison_20260911"


@pytest.fixture
def owner(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "comparison_owner", PLAN / "local_owner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "load_trial",
        lambda condition, trial: (
            json.loads(condition.read_text()),
            json.loads(trial.read_text()),
        ),
        raising=False,
    )
    return module


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
def test_each_model_uses_the_same_native_launcher_and_only_its_declared_configs(
    owner, name, replicate
):
    owner.TRIAL_ID = f"bindings-comparison-20260911-{name}-r{replicate}"
    row, condition = owner.selection()
    command = owner.native_arguments(row)
    assert command[:3] == ["-m", "scripts.campaign_keyboard_trial", "run"]
    assert command[command.index("--campaign-id") + 1] == owner.TRIAL_ID
    assert (
        command[command.index("--condition") + 1]
        == "/launch/" + name + "-condition.json"
    )
    assert command[command.index("--trial") + 1] == "/launch/" + name + "-trial.json"
    assert command[command.index("--revision") + 1] == owner.REVISION
    assert condition["steps_per_segment"] == owner.MAX_RESPONSES == 64
    assert (
        owner.COURIER_SECONDS
        == 64 * (condition["exchange_timeout_seconds"] + 120) + 300
    )
    with tarfile.open(fileobj=io.BytesIO(owner.launch_archive(row))) as archive:
        assert archive.getnames() == [
            "launch",
            "launch/" + row["condition"],
            "launch/" + row["trial"],
        ]
        for filename in (row["condition"], row["trial"]):
            entry = archive.getmember("launch/" + filename)
            assert entry.mode == 0o444
            assert archive.extractfile(entry).read() == (PLAN / filename).read_bytes()


@pytest.mark.parametrize(
    "value", [None, "../private", "bindings-comparison-20260911-sol-r3", "astra"]
)
def test_unknown_campaign_never_becomes_an_output_path(owner, value):
    owner.TRIAL_ID = value
    with pytest.raises(ValueError, match="predeclared"):
        owner.selection()


@pytest.fixture
def courier(owner, monkeypatch, tmp_path):
    """Exercise the host loop with an in-memory game and no provider or VM."""
    requests, answers, calls, delivered = [], [], [], []
    owner.TRIAL_ID = "bindings-comparison-20260911-sol-r1"
    _, condition = owner.selection()
    cursor = 0

    def publish(path, value):
        with path.open("x") as stream:
            json.dump(value, stream)

    def output(command):
        if "inspect" in command:
            return json.dumps({"Running": cursor < len(requests)})
        if "ls -1" in command[-1]:
            identifier = requests[cursor]["request_id"]
            return (
                identifier + "\n" + identifier
            )  # A repeated listing is not a new request.
        return "ready"

    def run(command, label, timeout):
        assert "cp" in command and label.startswith("request-copy-")
        publish(Path(command[-1]), requests[cursor])

    def answer(request, **kwargs):
        calls.append(request["request_id"])
        return answers[cursor]

    def deliver(command, **kwargs):
        nonlocal cursor
        if "publish-response" in command:
            delivered.append(json.loads(kwargs["input"]))
            cursor += 1
        else:
            assert "probe" in command
        kwargs["stdout"].write(b'{"published_and_read_verified": true}')
        return SimpleNamespace(returncode=0)

    for name, value in {
        "DOCKER": ["fake-docker"],
        "transport": SimpleNamespace(VM_ENV={}),
        "read": lambda path: json.loads(path.read_text()),
        "publish": publish,
        "validate_request": lambda request: None,
        "output": output,
        "run": run,
        "answer_request": answer,
        "observe_container_output": lambda command, **kwargs: kwargs["output"](command),
    }.items():
        monkeypatch.setattr(owner, name, value, raising=False)
    monkeypatch.setattr(owner.subprocess, "run", deliver)
    monkeypatch.setattr(owner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(owner.time, "monotonic", lambda: 0)

    def add(memory="", update="remember", valid=True, dispatched=True, feedback=None):
        identifier = f"{len(requests) + 1:032x}"
        requests.append(
            {
                "request_id": identifier,
                "memory": memory,
                "feedback": feedback,
                "screen": {"width": 120, "height": 40},
            }
        )
        result = {"action_grammar_valid": valid}
        if valid:
            result["action"] = {"memory_update": update}
        answers.append(({"result": result}, {"model_dispatched": dispatched}))

    decisions = []
    return SimpleNamespace(
        add=add,
        calls=calls,
        delivered=delivered,
        decisions=decisions,
        execute=lambda: owner.serve_model("test-game", tmp_path, condition, decisions),
    )


def test_courier_preserves_memory_and_never_reinfers_a_repeated_listing(courier):
    courier.add(update="build beds")
    courier.add(memory="build beds", update="beds queued", feedback={"accepted": True})
    courier.execute()
    assert len(courier.calls) == len(set(courier.calls)) == len(courier.delivered) == 2
    assert [row["decision_index"] for row in courier.decisions] == [0, 1]


def test_invalid_action_does_not_replace_memory(courier):
    courier.add(valid=False)
    courier.add(memory="", update="try again")
    courier.execute()
    assert len(courier.calls) == 2


@pytest.mark.parametrize(
    "memory,feedback,message",
    [
        ("borrowed", None, "memory chain"),
        ("", {"old": True}, "borrow prior feedback"),
    ],
)
def test_fresh_context_mismatch_stops_before_any_inference(
    courier, memory, feedback, message
):
    courier.add(memory=memory, feedback=feedback)
    with pytest.raises(AssertionError, match=message):
        courier.execute()
    assert courier.calls == []


def test_later_memory_mismatch_does_not_infer_the_bad_request(courier):
    courier.add(update="own memory")
    courier.add(memory="someone else's memory")
    with pytest.raises(AssertionError, match="memory chain"):
        courier.execute()
    assert len(courier.calls) == 1


def test_admission_pause_is_delivered_once_and_ends_normally(courier):
    courier.add(valid=False, dispatched=False)
    courier.execute()
    assert len(courier.calls) == len(courier.delivered) == 1
    assert courier.decisions == [{"decision_index": 0, "model_dispatched": False}]


def test_request_after_terminal_response_does_not_get_inferred(courier):
    courier.add(valid=False, dispatched=False)
    courier.add()
    with pytest.raises(AssertionError, match="response bound"):
        courier.execute()
    assert len(courier.calls) == 1


def test_response_cap_stops_before_extra_inference(courier, owner):
    owner.MAX_RESPONSES = 1
    courier.add(update="one")
    courier.add(memory="one")
    with pytest.raises(AssertionError, match="response bound"):
        courier.execute()
    assert len(courier.calls) == 1
