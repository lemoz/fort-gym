"""No-copy restart ownership and exact-save guards; no real game is launched."""

import fcntl
import hashlib
import json
import shutil
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from scripts import campaign_restart as module
from scripts.campaign_output_pause_smoke import OutputPauseFixtureAgent, exercise
from tests.test_campaign_loop import TestEnvironment


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    previous = tmp_path.resolve() / "first"
    previous.mkdir()
    env = TestEnvironment()
    exercise(
        output=previous,
        agent=OutputPauseFixtureAgent(),
        environment=env,
        checkpoint=None,
        snapshotter=env,
        revision="test-revision",
    )
    runtime = previous / "runtime"
    (runtime / "data/save").mkdir(parents=True)
    shutil.copytree(previous / "checkpoint/game", runtime / "data/save/campaign-resume")
    port = 5501
    monkeypatch.setattr(
        module.socket, "socket", lambda: nullcontext(SimpleNamespace(bind=lambda address: None))
    )
    receipt = {
        "schema_version": "fortgym.isolated-experiment-runtime/v1",
        "code_revision": "test-revision",
        "runtime_path": str(runtime),
        "port": port,
        "cleanup_verified": True,
        "native_load_verified": True,
        "listener_closed": True,
        "remaining_live_processes": [],
        "experiment": {"provider_calls": 0, "next_step": 0},
    }
    receipt_path = previous / "result.json"
    receipt_path.write_text(json.dumps(receipt))
    calls = []

    def launch(**kwargs):
        calls.append(kwargs)
        kwargs["validate_runtime"]()
        kwargs["validate_source"]()
        kwargs["result"].update(native_load_verified=True, cleanup_verified=True)
        return kwargs["result"]

    monkeypatch.setattr(module, "runtime_live_members", lambda runtime: {})
    monkeypatch.setattr(module, "_run_prepared_runtime", launch)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=2000000))
    args = {
        "previous_output": previous,
        "previous_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "checkpoint_sha256": hashlib.sha256(
            (previous / "checkpoint/checkpoint.json").read_bytes()
        ).hexdigest(),
        "output": tmp_path.resolve() / "resumed",
        "revision": "test-revision",
        "minimum_free_bytes": 1000000,
        "growth_allowance_bytes": 1000,
    }
    return args, receipt, calls


def test_restart_reuses_exact_bytes_once_and_keeps_prior_evidence(prepared):
    args, _, calls = prepared
    previous = args["previous_output"]
    receipt_bytes = (previous / "result.json").read_bytes()
    save = previous / "runtime/data/save/campaign-resume/world.sav"
    save_bytes = save.read_bytes()
    result = module.restart_latest_checkpoint(**args)
    assert len(calls) == 1
    assert result["runtime_reused_without_save_replacement"] is True
    assert result["capacity_preflight"]["runtime_copy_bytes"] == 0
    assert calls[0]["runtime"] == previous / "runtime"
    assert not (args["output"] / "runtime").exists()
    assert save.read_bytes() == save_bytes
    assert (previous / "result.json").read_bytes() == receipt_bytes
    claim = json.loads((previous / "restart-claim.json").read_text())
    assert claim["checkpoint_file_sha256"] == args["checkpoint_sha256"]
    args["output"] = previous.parent / "third"
    with pytest.raises(module.CampaignSaveError, match="already been claimed"):
        module.restart_latest_checkpoint(**args)
    assert len(calls) == 1 and not args["output"].exists()


@pytest.mark.parametrize(
    "fault",
    [
        "receipt_digest",
        "checkpoint_digest",
        "revision",
        "cleanup",
        "port",
        "path",
        "bytes",
        "empty_error",
        "unfinished_worker",
    ],
)
def test_invalid_boundary_rejected_before_allocation(prepared, fault):
    args, receipt, calls = prepared
    previous = args["previous_output"]
    if fault == "receipt_digest":
        args["previous_receipt_sha256"] = "0" * 64
    elif fault == "checkpoint_digest":
        args["checkpoint_sha256"] = "0" * 64
    elif fault == "bytes":
        (previous / "runtime/data/save/campaign-resume/world.sav").write_bytes(b"changed save")
    else:
        field, value = {
            "revision": ("code_revision", "other-source"),
            "cleanup": ("cleanup_verified", False),
            "port": ("port", 5000),
            "path": ("runtime_path", str(previous.parent / "unrelated-runtime")),
            "empty_error": ("error", ""),
            "unfinished_worker": ("experiment", None),
        }[fault]
        receipt[field] = value
        path = previous / "result.json"
        path.write_text(json.dumps(receipt))
        args["previous_receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(module.CampaignSaveError):
        module.restart_latest_checkpoint(**args)
    assert not calls and not args["output"].exists()
    assert not (previous / "restart-claim.json").exists()


def test_concurrent_owner_rejected_without_a_claim(prepared):
    args, _, calls = prepared
    with (args["previous_output"] / "result.json").open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(module.CampaignSaveError, match="Another caller"):
            module.restart_latest_checkpoint(**args)
    assert not calls and not args["output"].exists()


@pytest.mark.parametrize("fault", ["live", "space", "occupied", "checkpoint_revision"])
def test_fresh_runtime_state_prevents_restart(prepared, monkeypatch, fault):
    args, _, calls = prepared
    if fault == "live":
        monkeypatch.setattr(module, "runtime_live_members", lambda runtime: {12: "123"})
    elif fault == "space":
        monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1000999))
    elif fault == "checkpoint_revision":
        monkeypatch.setattr(
            module, "verify_checkpoint", lambda path: {"payload": {"code_revision": "other"}}
        )
    else:

        def occupied(address):
            raise OSError("fixture occupied port")

        monkeypatch.setattr(
            module.socket, "socket", lambda: nullcontext(SimpleNamespace(bind=occupied))
        )
    with pytest.raises((module.CampaignSaveError, OSError)):
        module.restart_latest_checkpoint(**args)
    assert not calls and not args["output"].exists()
    assert not (args["previous_output"] / "restart-claim.json").exists()


def test_failed_launch_keeps_single_use_claim(prepared, monkeypatch):
    args, _, _ = prepared

    def failed(**kwargs):
        raise RuntimeError("fixture launch failure")

    monkeypatch.setattr(module, "_run_prepared_runtime", failed)
    with pytest.raises(RuntimeError, match="launch failure"):
        module.restart_latest_checkpoint(**args)
    assert (args["previous_output"] / "restart-claim.json").exists()
    args["output"] = args["output"].parent / "retry"
    with pytest.raises(module.CampaignSaveError, match="already been claimed"):
        module.restart_latest_checkpoint(**args)


@pytest.mark.parametrize("location", ["previous", "receipt", "runtime", "save"])
def test_link_paths_never_reused(prepared, location):
    args, _, calls = prepared
    previous = args["previous_output"]
    path = {
        "previous": previous,
        "receipt": previous / "result.json",
        "runtime": previous / "runtime",
        "save": previous / "runtime/data/save/campaign-resume",
    }[location]
    target = path.with_name(path.name + "-retained")
    path.rename(target)
    path.symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(module.CampaignSaveError):
        module.restart_latest_checkpoint(**args)
    assert not calls and not args["output"].exists()


@pytest.mark.parametrize("fail_at", [None, "before_spawn", "before_load", "after_load"])
def test_shared_lifetime_rechecks_save_and_always_reaps_after_spawn(tmp_path, monkeypatch, fail_at):
    from scripts import campaign_load_smoke as launcher

    runtime, output = tmp_path / "runtime", tmp_path / "phase"
    runtime.mkdir()
    output.mkdir()
    events = []
    validations = 0

    def validate_runtime():
        nonlocal validations
        validations += 1
        events.append("validate_runtime")
        if (validations == 1 and fail_at == "before_spawn") or (
            validations == 2 and fail_at == "before_load"
        ):
            raise module.CampaignSaveError("fixture save changed")

    def validate_source():
        events.append("validate_source")
        if fail_at == "after_load":
            raise module.CampaignSaveError("fixture checkpoint changed")

    def spawn(*args, **kwargs):
        events.append("spawn")
        return SimpleNamespace(pid=987654, wait=lambda timeout: 0)

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "runtime_live_members", lambda path: {})
    monkeypatch.setattr(launcher.os, "killpg", lambda *args: events.append("reap"))
    monkeypatch.setattr(
        launcher.socket,
        "socket",
        lambda: nullcontext(SimpleNamespace(connect_ex=lambda address: 111)),
    )
    monkeypatch.setattr(launcher, "rpc", lambda *args: events.append("load"))
    monkeypatch.setattr(
        launcher,
        "wait_status",
        lambda *args, **kwargs: {
            "year": 30,
            "year_tick": 10,
            "paused": True,
            "save_name": "campaign-resume",
        },
    )
    args = {
        "runtime": runtime,
        "output": output,
        "environment": {},
        "expected": {"year": 30, "year_tick": 10},
        "result": {"port": 5501, "cleanup_verified": False},
        "validate_runtime": validate_runtime,
        "validate_source": validate_source,
    }
    if fail_at is not None:
        with pytest.raises(module.CampaignSaveError, match="fixture"):
            launcher._run_prepared_runtime(**args)
    else:
        assert launcher._run_prepared_runtime(**args)["native_load_verified"] is True
    if fail_at == "before_spawn":
        assert events == ["validate_runtime"]
        assert not (output / "runtime.log").exists()
    else:
        assert events[:3] == ["validate_runtime", "spawn", "validate_runtime"]
        assert events[-1] == "reap"
        assert json.loads((output / "result.json").read_text())["cleanup_verified"] is True
        assert ("load" in events) is (fail_at != "before_load")
