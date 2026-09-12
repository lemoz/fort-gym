"""Exercise the fresh-trial CLI orchestration with synthetic native/model boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.keyboard_trial_config import load_trial
from scripts import campaign_keyboard_trial as launcher, campaign_keyboard_native as native
from tests.test_campaign_load_smoke import sources as sources
from tests.test_campaign_codex_keyboard import decision, admission_denied
from tests.test_keyboard_fresh_trial import config, MODELS
from tests.test_keyboard_runtime import environment


@pytest.fixture
def prepared(tmp_path, sources):
    source, snapshot, receipt = sources
    condition_path, trial_path = tmp_path / "condition.json", tmp_path / "trial.json"
    condition = config()
    trial = {
        "schema_version": "fortgym.keyboard-fresh-trial/v1",
        "original_condition": condition_path.name,
        "source_snapshot_receipt_sha256": receipt,
        "steps_per_segment": 3,
        "initial_memory": "empty",
        "strategy_intervention": False,
        "snapshot_profile": "native_menu_preserving_save/v4",
        "runtime_rpc_transport": "native-rpc",
        "private_measurement_profile": "fortgym.campaign-food-measurement/v1",
        "private_measurement_timeout_seconds": 15,
        "resource_observation_profile": "fortgym.native-resource-observations/v1",
    }
    publish(condition_path, condition)
    publish(trial_path, trial)
    return SimpleNamespace(
        condition=condition_path,
        trial=trial_path,
        snapshot=snapshot,
        source=source,
        output=tmp_path / "new-trial",
        port=5540,
        campaign_id="fixture-new-fort",
        revision="fixture",
    )


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("outcome", ["complete", "admission", "tokens", "failed", "cleanup"])
def test_loader_worker_exchange_save_and_terminal_outcome(prepared, monkeypatch, model, outcome):
    selected = config(model)
    if outcome == "tokens":
        selected["max_total_tokens"] = 100
    prepared.condition.write_text(json.dumps(selected))
    env = environment()
    env.tick = 19309
    closed = []
    env.close = lambda: closed.append(True)
    native_calls, worker_calls, requests = [], [], []
    monkeypatch.setattr(native, "NativeCampaignEnvironment", lambda **kwargs: env)
    monkeypatch.setattr(native, "MenuPreservingSnapshotter", lambda **kwargs: env)
    monkeypatch.setattr(
        launcher, "capture_resources", lambda: {"schema_version": "fixture-resources"}
    )

    def exchange(path, screen, memory, feedback, **kwargs):
        requests.append((path, memory, feedback, kwargs))
        if outcome == "admission":
            return admission_denied()
        if outcome == "failed":
            return {}
        value = decision(screen, memory, feedback)
        value["transport_receipt"].update(
            model_requested=kwargs["model"], reasoning_effort_requested=kwargs["reasoning_effort"]
        )
        value["prompt_profile"] = kwargs["prompt_profile"]
        return value

    def run_worker(command, **kwargs):
        worker_calls.append((command, kwargs))
        values = dict(zip(command[4::2], command[5::2]))
        args = SimpleNamespace(
            **{
                key.removeprefix("--").replace("-", "_"): value
                if key in ("--campaign-id", "--revision")
                else Path(value)
                for key, value in values.items()
            }
        )
        result = native.worker(args)
        if result["status"] not in ("bounded_segment_complete", "budget_limited_pause"):
            raise subprocess.CalledProcessError(1, command)

    def isolated(**kwargs):
        native_calls.append(kwargs)
        result = kwargs["work"](
            prepared.output / "fixture-runtime",
            {"LANG": "C"},
            {"year": 30, "year_tick": 19309, "paused": True},
        )
        return {
            "native_load_verified": True,
            "cleanup_verified": outcome != "cleanup",
            "experiment": result,
        }

    monkeypatch.setattr(native, "exchange_decision", exchange)
    monkeypatch.setattr(launcher, "run_worker", run_worker)
    monkeypatch.setattr(launcher, "run_isolated", isolated)
    result = launcher.run_trial(prepared)
    assert result == read(prepared.output / "result.json")
    assert len(native_calls) == len(worker_calls) == len(closed) == 1
    assert native_calls[0]["source_kind"] == "native_snapshot"
    assert native_calls[0]["snapshot"] == prepared.snapshot
    assert native_calls[0]["screen_size"] == (120, 40)
    assert result["source_snapshot_unchanged"] is True
    assert requests[0][1:3] == ("", None)
    assert requests[0][3]["model"] == model
    assert requests[0][3]["prompt_profile"] == selected["prompt_profile"]
    worker_env = worker_calls[0][1]["env"]
    assert worker_env["FORT_GYM_DFHACK_TRANSPORT"] == "native-rpc"
    assert worker_env["FORT_GYM_DISABLE_DOTENV"] == "1"
    assert [row["stage"] for row in result["resource_observations"]] == [
        "before-runtime",
        "loaded-before-worker",
        "after-worker",
        "after-runtime-unwind",
    ]
    expected = {
        "complete": "completed",
        "admission": "budget_limited_pause",
        "tokens": "paused",
        "failed": "failed",
        "cleanup": "failed",
    }[outcome]
    assert result["status"] == expected
    if outcome in ("complete", "tokens"):
        assert result["new_checkpoint_verified"] is True
        assert result["segment"]["next_step"] == (3 if outcome == "complete" else 1)
    elif outcome == "admission":
        assert result["new_checkpoint_verified"] is False and not env.actions
        assert result["segment"]["usage"]["total_tokens"] == 0
    else:
        assert result["new_checkpoint_verified"] is False


@pytest.mark.parametrize(
    "key,value",
    [
        ("initial_memory", "copied from Astra"),
        ("strategy_intervention", True),
        ("budget_extension", {}),
        ("continuation_from_next_step", 903),
        ("restart", {}),
        ("original_condition", "other.json"),
        ("source_snapshot_receipt_sha256", "bad"),
        ("steps_per_segment", 9),
        ("steps_per_segment", True),
        ("snapshot_profile", "unknown"),
        ("snapshot_profile", []),
        ("runtime_rpc_transport", "unknown"),
        ("resource_observation_profile", "unknown"),
        ("private_measurement_timeout_seconds", 0),
        ("max_segments", 4),
    ],
)
def test_trial_contract_rejects_undeclared_or_incompatible_start(prepared, key, value):
    trial = read(prepared.trial)
    trial[key] = value
    prepared.trial.write_text(json.dumps(trial))
    with pytest.raises(ValueError):
        load_trial(prepared.condition, prepared.trial)


@pytest.mark.parametrize(
    "change", ["port", "identity", "digest", "snapshot-bytes", "source-output", "snapshot-output"]
)
def test_invalid_start_fails_before_runtime_or_output(prepared, monkeypatch, change):
    monkeypatch.setattr(
        launcher, "run_isolated", lambda **kwargs: pytest.fail("Invalid start launched game")
    )
    if change == "port":
        prepared.port = 5000
    elif change == "identity":
        prepared.campaign_id = "../old-fort"
    elif change in ("digest", "snapshot-bytes"):
        if change == "digest":
            prepared.snapshot.joinpath("result.json").write_text("{}")
        else:
            prepared.snapshot.joinpath("native-snapshot/world.sav").write_text("changed fixture")
    elif change == "source-output":
        prepared.output = prepared.source / "nested"
    else:
        prepared.output = prepared.snapshot / "nested"
    with pytest.raises((ValueError, RuntimeError)):
        launcher.run_trial(prepared)
    assert not prepared.output.exists()


def test_loading_failure_keeps_failed_record_not_a_completed_campaign(prepared, monkeypatch):
    def failed(**kwargs):
        raise RuntimeError("fixture load failure")

    monkeypatch.setattr(launcher, "run_isolated", failed)
    result = launcher.run_trial(prepared)
    assert result["status"] == "failed" and result["source_snapshot_unchanged"] is True
    assert result["runtime_cleanup_verified"] is False and result["native_load_verified"] is False
    assert not (prepared.output / "segment-0").exists()
    with pytest.raises(FileExistsError):
        launcher.run_trial(prepared)
