"""Fixture lifecycle and retained-evidence tests; no real native process is started."""

import json
from types import SimpleNamespace

import pytest

from fort_gym.bench import dfhack_exec
from fort_gym.bench.run import campaign_environment
from scripts import campaign_production_probe as probe
from tests.test_production_observer_probe import boundary


@pytest.fixture
def worker_fixture(tmp_path, monkeypatch):
    runtime = tmp_path / "isolated/runtime"
    args = SimpleNamespace(
        runtime=runtime, output=tmp_path / "probe", intervals=2, ticks=250
    )
    monkeypatch.setenv("DFROOT", str(runtime))
    monkeypatch.setenv("DFHACK_HOST", "127.0.0.1")
    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(dfhack_exec, "run_dfhack", lambda *a, **k: None)
    calls = []
    state = {"year": 30, "year_tick": 100, "pause_state": True}
    settings = {
        "advance": "normal",
        "capture": "normal",
        "start": "normal",
        "stop": "normal",
    }

    class Observer:
        owner = "a" * 32

        def __init__(self, *args):
            pass

        def command(self, operation):
            calls.append(operation)
            if settings.get(operation) == "error":
                raise TimeoutError(f"{operation} timed out")
            if operation == "capture":
                value = boundary(runtime, self.owner, state["year_tick"])
                if settings["capture"] == "incomplete":
                    value["inventory"]["complete"] = False
                return value
            return {"installed": operation == "start"}

    def advance(ticks, before):
        calls.append("advance")
        if settings["advance"] == "error":
            raise TimeoutError("advance timed out")
        actual = 12 if settings["advance"] == "interrupted" else ticks
        state["year_tick"] += actual
        receipt = {"ok": actual == ticks, "ticks_advanced": actual}
        if settings["advance"] == "mismatch":
            receipt["ticks_advanced"] += 1
        return dict(state), receipt

    monkeypatch.setattr(probe, "ProductionObserverProbe", Observer)
    monkeypatch.setattr(
        campaign_environment,
        "NativeCampaignEnvironment",
        lambda **kwargs: SimpleNamespace(
            observe=lambda: dict(state),
            advance=advance,
            close=lambda: calls.append("close"),
        ),
    )
    return args, calls, settings


def test_worker_retains_hashed_native_boundaries_and_never_claims_production(
    worker_fixture,
):
    args, calls, _ = worker_fixture
    result = probe.worker(args)
    assert result["status"] == "completed" and result["observer_stopped"]
    assert result["ticks_requested"] == result["ticks_advanced"] == 500
    assert result["intervals_completed"] == 2
    assert calls == [
        "start",
        "capture",
        "advance",
        "capture",
        "advance",
        "capture",
        "stop",
        "close",
    ]
    assert result["production_coverage"] == "inconclusive"
    assert (
        result["model_calls"]
        == result["gameplay_keys"]
        == result["workshop_jobs_queued"]
        == 0
    )
    for name, digest in result["artifacts"].items():
        assert probe.file_digest(args.output / name) == digest
    assert json.loads((args.output / "result.json").read_text()) == result


@pytest.mark.parametrize("operation", ["start", "capture", "advance", "stop"])
def test_worker_retains_failure_and_attempts_stop_even_after_start_timeout(
    worker_fixture, operation
):
    args, calls, settings = worker_fixture
    settings[operation] = "error"
    with pytest.raises(TimeoutError):
        probe.worker(args)
    result = json.loads((args.output / "result.json").read_text())
    assert result["status"] == "failed"
    assert calls[-2:] == ["stop", "close"]
    assert result["production_coverage"] == "inconclusive"
    assert result["observer_stopped"] is (operation != "stop")


def test_partial_native_advance_is_retained_without_retry_or_keys(worker_fixture):
    args, calls, settings = worker_fixture
    settings["advance"] = "interrupted"
    result = probe.worker(args)
    assert result["status"] == "interrupted"
    assert result["ticks_requested"] == 250 and result["ticks_advanced"] == 12
    assert calls.count("advance") == 1
    assert (args.output / "boundary-01.json").is_file()


@pytest.mark.parametrize(
    "operation,value", [("capture", "incomplete"), ("advance", "mismatch")]
)
def test_bad_evidence_is_retained_before_failing(worker_fixture, operation, value):
    args, calls, settings = worker_fixture
    settings[operation] = value
    with pytest.raises(ValueError):
        probe.worker(args)
    assert calls[-2:] == ["stop", "close"]
    assert (
        args.output
        / ("boundary-00.json" if operation == "capture" else "advance-01.json")
    ).is_file()
    assert json.loads((args.output / "result.json").read_text())["status"] == "failed"


def test_wrong_runtime_rejected_before_rpc_or_output(worker_fixture, monkeypatch):
    args, calls, _ = worker_fixture
    monkeypatch.setenv("DFROOT", "/some-active-game")
    with pytest.raises(ValueError, match="caller-owned"):
        probe.worker(args)
    assert not args.output.exists() and calls == []


@pytest.mark.parametrize(
    "intervals,ticks", [(0, 1), (33, 1), (True, 1), (1, 0), (1, 2001), (1, True)]
)
def test_invalid_limits_fail_before_output(worker_fixture, intervals, ticks):
    args, calls, _ = worker_fixture
    args.intervals, args.ticks = intervals, ticks
    with pytest.raises(ValueError):
        probe.worker(args)
    assert calls == [] and not args.output.exists()


@pytest.fixture
def launcher_fixture(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "checkpoint.json").write_text("fixture")
    args = SimpleNamespace(
        source=tmp_path / "source",
        checkpoint=checkpoint,
        output=tmp_path / "run",
        revision="b" * 40,
        port=5610,
        intervals=2,
        ticks=250,
    )
    monkeypatch.setattr(probe.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(
        probe, "verify_source", lambda value: calls.append(("source", value))
    )
    monkeypatch.setattr(
        probe,
        "verify_load_source",
        lambda *values: calls.append(("checkpoint", values)),
    )
    return args, calls


def test_launcher_uses_isolated_copy_clean_source_and_bounded_worker(
    launcher_fixture, monkeypatch
):
    args, calls = launcher_fixture

    def run_worker(command, *, env, stdout, timeout):
        assert timeout == 600
        assert "--ticks" in command and "--intervals" in command
        assert env["FORT_GYM_DFHACK_TRANSPORT"] == "native-rpc"
        assert env["FORT_GYM_DISABLE_DOTENV"] == "1"
        output = args.output / "probe"
        output.mkdir()
        (output / "result.json").write_text(json.dumps({"status": "completed"}))

    def run_isolated(**kwargs):
        assert kwargs["snapshot"] == args.checkpoint
        assert kwargs["source_kind"] == "campaign_checkpoint"
        assert kwargs["screen_size"] == (120, 40)
        kwargs["output"].mkdir()
        result = {
            "cleanup_verified": True,
            "experiment": kwargs["work"](kwargs["output"] / "runtime", {}, {}),
        }
        (kwargs["output"] / "result.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(probe, "run_worker", run_worker)
    monkeypatch.setattr(probe, "run_isolated", run_isolated)
    result = probe.run(args)
    assert result["cleanup_verified"] and result["original_checkpoint_unchanged"]
    assert result["production_coverage"] == "inconclusive"
    assert [name for name, _ in calls] == ["source", "checkpoint", "checkpoint"]


def test_launcher_retains_owned_cleanup_on_worker_failure(
    launcher_fixture, monkeypatch
):
    args, calls = launcher_fixture

    def fail(**kwargs):
        kwargs["output"].mkdir()
        (kwargs["output"] / "result.json").write_text('{"cleanup_verified":true}')
        raise RuntimeError("fixture worker failed")

    monkeypatch.setattr(probe, "run_isolated", fail)
    with pytest.raises(RuntimeError):
        probe.run(args)
    result = json.loads((args.output / "result.json").read_text())
    assert result["status"] == "failed" and result["cleanup_verified"]
    assert result["original_checkpoint_unchanged"]


def test_launcher_rejects_mac_before_creating_runtime(launcher_fixture, monkeypatch):
    args, calls = launcher_fixture
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="Linux"):
        probe.run(args)
    assert not args.output.exists() and calls == []


@pytest.mark.parametrize("which", ["source", "checkpoint"])
def test_launcher_rejects_nested_output_before_modifying_retained_source(
    launcher_fixture, which
):
    args, calls = launcher_fixture
    args.output = getattr(args, which) / "must-not-create"
    with pytest.raises(ValueError, match="outside retained"):
        probe.run(args)
    assert not args.output.exists() and calls == []


def test_launcher_records_failed_source_revalidation(launcher_fixture, monkeypatch):
    args, calls = launcher_fixture

    def verify(*unused):
        if args.output.exists():
            raise ValueError("checkpoint changed")

    monkeypatch.setattr(probe, "verify_load_source", verify)
    monkeypatch.setattr(
        probe,
        "run_isolated",
        lambda **kw: {
            "experiment": {"status": "completed"},
            "cleanup_verified": True,
        },
    )
    with pytest.raises(ValueError, match="checkpoint changed"):
        probe.run(args)
    result = json.loads((args.output / "result.json").read_text())
    assert result["status"] == "failed" and not result["original_checkpoint_unchanged"]


def test_launcher_cannot_report_completion_without_cleanup(
    launcher_fixture, monkeypatch
):
    args, calls = launcher_fixture
    monkeypatch.setattr(
        probe,
        "run_isolated",
        lambda **kw: {
            "experiment": {"status": "completed"},
            "cleanup_verified": False,
        },
    )
    with pytest.raises(ValueError, match="cleanup"):
        probe.run(args)
    result = json.loads((args.output / "result.json").read_text())
    assert result["status"] == "failed" and not result["cleanup_verified"]
