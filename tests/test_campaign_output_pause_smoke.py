"""Synthetic game doubles test the fixture; no native acceptance is claimed."""

import hashlib
import json
import shutil
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.campaign_output_pause_smoke import (
    CAMPAIGN_ID,
    OutputPauseFixtureAgent,
    exercise,
    verify_recovery,
)
from tests.test_campaign_loop import TestEnvironment


@pytest.fixture
def recovery(tmp_path):
    first_output, second_output = tmp_path / "first", tmp_path / "second"
    first_output.mkdir()
    second_output.mkdir()
    first_env = TestEnvironment()
    first = exercise(
        output=first_output,
        agent=OutputPauseFixtureAgent(),
        environment=first_env,
        checkpoint=None,
        snapshotter=first_env,
        revision="fixture-test",
    )
    checkpoint = first_output / "checkpoint"
    resumed_env = TestEnvironment()
    resumed_env.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = exercise(
        output=second_output,
        agent=OutputPauseFixtureAgent(),
        environment=resumed_env,
        checkpoint=checkpoint,
        snapshotter=resumed_env,
        revision="fixture-test",
    )
    return first, resumed, checkpoint


def test_fixture_reconciles_zero_commands_then_one_fresh_decision(recovery):
    result = verify_recovery(*recovery)
    first, resumed, checkpoint = recovery
    assert first["next_step"] == 0 and resumed["next_step"] == 1
    assert resumed["restored"]["agent_state"] == first["agent_state"]
    assert first["agent_state"]["usage"]["total_tokens"] == 10
    assert resumed["agent_state"]["usage"]["total_tokens"] == 20
    assert resumed["agent_state"]["usage"]["dispatched_requests"] == 2
    assert result["native_output_pause_recovery_verified"] is True
    assert result["provider_calls"] == 0 and result["usage_kind"] == "synthetic_fixture_only"
    assert result["year_two_gameplay_verified"] is False
    assert result["final_resumable_checkpoint_created"] is False
    assert not (checkpoint.parent.parent / "second/checkpoint").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "first_advanced",
        "wrong_load",
        "unpaused",
        "wrong_cursor",
        "usage_reset",
        "replay",
        "wrong_history",
        "tick_count",
        "tick_start",
        "overshoot",
        "final_boundary",
        "provider_call",
        "synthetic_label",
    ],
)
def test_verifier_rejects_broken_recovery_evidence(recovery, fault):
    original, second, checkpoint = recovery
    first, resumed = deepcopy(original), deepcopy(second)
    row = resumed["actions"][0]
    if fault == "first_advanced":
        first["final"]["year_tick"] += 1
    elif fault == "wrong_load":
        resumed["initial"]["year_tick"] += 1
    elif fault == "unpaused":
        resumed["initial"]["pause_state"] = False
    elif fault == "wrong_cursor":
        resumed["restored"]["next_step"] = 1
    elif fault == "usage_reset":
        resumed["agent_state"]["usage"]["total_tokens"] = 10
    elif fault == "replay":
        row["action"]["advance_ticks"] = 10
    elif fault == "wrong_history":
        row["previous_step"] = 0
    elif fault == "tick_count":
        row["tick_advance"]["ticks_advanced"] += 1
    elif fault == "tick_start":
        row["tick_advance"]["start_tick"] -= 1
    elif fault == "overshoot":
        row["tick_advance"]["end_tick"] += 10000
        row["tick_advance"]["ticks_advanced"] += 10000
    elif fault == "final_boundary":
        resumed["final"]["year_tick"] -= 1
    elif fault == "provider_call":
        resumed["provider_calls"] = 1
    else:
        resumed["usage_kind"] = "real"
    with pytest.raises(ValueError):
        verify_recovery(first, resumed, checkpoint)


def test_fixture_agent_rejects_third_decision_and_modified_synthetic_usage(recovery):
    first, _, _ = recovery
    agent = OutputPauseFixtureAgent()
    agent.restore_campaign_state(first["agent_state"], campaign_id=CAMPAIGN_ID)
    assert agent.decide("", {})["advance_ticks"] == 20
    with pytest.raises(ValueError, match="only two"):
        agent.decide("", {})
    modified = deepcopy(first["agent_state"])
    modified["usage"]["dispatched_requests"] = 0
    with pytest.raises(ValueError, match="state or usage"):
        OutputPauseFixtureAgent().restore_campaign_state(modified, campaign_id=CAMPAIGN_ID)


@pytest.mark.parametrize("cleanup", [True, False])
def test_parent_uses_one_copy_one_checkpoint_and_serial_shared_lifetime(
    tmp_path, monkeypatch, cleanup
):
    from scripts import campaign_output_pause_smoke as module
    from scripts import campaign_restart as restart

    phases = []

    def isolated(**kwargs):
        phases.append("first")
        assert kwargs["checkpoint_copies"] == 1
        assert kwargs["minimum_free_bytes"] == 1001000
        output = kwargs["output"]
        output.mkdir()
        env = TestEnvironment()
        exercise(
            output=output,
            agent=OutputPauseFixtureAgent(),
            environment=env,
            checkpoint=None,
            snapshotter=env,
            revision="test-revision",
        )
        runtime = output / "runtime"
        (runtime / "data/save").mkdir(parents=True)
        shutil.copytree(output / "checkpoint/game", runtime / "data/save/campaign-resume")
        result = {
            "schema_version": "fortgym.isolated-experiment-runtime/v1",
            "code_revision": "test-revision",
            "runtime_path": str(runtime),
            "port": 5501,
            "native_load_verified": True,
            "cleanup_verified": cleanup,
            "listener_closed": cleanup,
            "remaining_live_processes": [],
            "experiment": {"provider_calls": 0, "next_step": 0},
        }
        module.write_new(output / "result.json", result)
        return result

    def restarted(**kwargs):
        phases.append("resumed")
        kwargs["validate_runtime"]()
        kwargs["validate_source"]()
        checkpoint = kwargs["runtime"].parent / "checkpoint"
        env = TestEnvironment()
        env.state = json.loads((checkpoint / "game/world.sav").read_text())
        exercise(
            output=kwargs["output"],
            agent=OutputPauseFixtureAgent(),
            environment=env,
            checkpoint=checkpoint,
            snapshotter=env,
            revision="test-revision",
        )
        kwargs["result"].update(native_load_verified=True, cleanup_verified=True)
        return kwargs["result"]

    monkeypatch.setattr(module, "run_isolated", isolated)
    monkeypatch.setattr(restart, "_run_prepared_runtime", restarted)
    monkeypatch.setattr(restart, "runtime_live_members", lambda runtime: {})
    monkeypatch.setattr(
        restart.socket, "socket", lambda: nullcontext(SimpleNamespace(bind=lambda address: None))
    )
    monkeypatch.setattr(restart.shutil, "disk_usage", lambda path: SimpleNamespace(free=2000000))
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda args, **kwargs: "test-revision" if args[1] == "rev-parse" else b"",
    )
    args = SimpleNamespace(
        source=tmp_path / "source",
        snapshot=tmp_path / "snapshot",
        snapshot_sha256="fixture-digest",
        output=tmp_path / "fixture",
        port=5501,
        minimum_free_bytes=1000000,
        growth_allowance_bytes=1000,
    )
    if not cleanup:
        with pytest.raises(RuntimeError, match="teardown"):
            module.run_fixture(args)
        assert phases == ["first"] and not (args.output / "resumed").exists()
        return
    result = module.run_fixture(args)
    assert phases == ["first", "resumed"] and result["runtime_asset_copies"] == 1
    assert result["first_cleanup_verified"] and result["resumed_cleanup_verified"]
    assert (
        result["checkpoint_file_sha256"]
        == hashlib.sha256(
            (args.output / "first/checkpoint/checkpoint.json").read_bytes()
        ).hexdigest()
    )
    assert not (args.output / "resumed/runtime").exists()
    assert not (args.output / "resumed/checkpoint").exists()


def test_parent_rejects_dirty_source_before_output_creation(tmp_path, monkeypatch):
    from scripts import campaign_output_pause_smoke as module

    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda args, **kwargs: "test-revision" if args[1] == "rev-parse" else b"?? new.py\n",
    )
    output = tmp_path / "unused"
    with pytest.raises(ValueError, match="clean committed"):
        module.run_fixture(SimpleNamespace(output=output))
    assert not output.exists()


def test_published_native_fixture_preserves_operator_and_synthetic_proof_limits():
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads(
        (root / "experiments/evidence/native_output_pause_recovery_20260906.json").read_text()
    )
    assert evidence["native_output_pause_recovery_verified"] is True
    assert evidence["automatic_two_phase_cli_verified"] is False
    assert (
        evidence["autonomous_gameplay"] is False and evidence["year_two_gameplay_verified"] is False
    )
    assert evidence["first_phase_commands"] == 0 and evidence["resumed_phase_commands"] == 1
    assert evidence["provider_calls"] == 0 and evidence["usage_kind"] == "synthetic_fixture_only"
    assert evidence["initial_failure"]["second_phase_started"] is False
    assert evidence["initial_failure"]["time_wait_directly_observed"] is False
    assert evidence["restored_next_step"] == 0 and evidence["final_next_step"] == 1
    assert evidence["final_year_tick"] - evidence["initial_year_tick"] == 20
    assert hashlib.sha256((root / evidence["operator_driver_path"]).read_bytes()).hexdigest() == (
        evidence["operator_driver_sha256"]
    )
