from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from fort_gym.bench.agent.base import Agent, RandomAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import RunExecutionOutcome, run_once
from fort_gym.bench.run.storage import RunRegistry


class DecisionFailureAgent(Agent):
    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("deterministic decision failure")


class UnexpectedExecutionAgent(Agent):
    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a pre-stopped run must not execute the agent")


class InvalidResultAgent(Agent):
    def decide(self, obs_text: str, obs_json: dict[str, Any]) -> dict[str, Any]:
        return "not-an-action"  # type: ignore[return-value]


def _registry_with_pending_run(tmp_path, monkeypatch) -> tuple[RunRegistry, str]:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    return registry, record.run_id


def _external_run(
    agent: Agent,
    *,
    registry: RunRegistry,
    run_id: str,
) -> RunExecutionOutcome:
    outcome = run_once(
        agent,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
        run_id=run_id,
        registry=registry,
        supervisor_owns_terminal=True,
    )
    assert isinstance(outcome, RunExecutionOutcome)
    return outcome


def test_external_worker_success_defers_registry_terminal_to_parent(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    outcome = _external_run(
        RandomAgent(seed=0, safe=True),
        registry=registry,
        run_id=run_id,
    )

    assert outcome == RunExecutionOutcome(run_id=run_id, outcome="completed")
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
    assert "cleanup_completed_at" not in loaded.metadata
    assert loaded.latest_summary is not None


def test_external_worker_failure_is_explicit_but_not_registry_terminal(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    outcome = _external_run(
        DecisionFailureAgent(),
        registry=registry,
        run_id=run_id,
    )

    assert outcome.outcome == "failed"
    assert outcome.terminal_reason is not None
    assert outcome.terminal_reason["code"] == "agent_decide_error"
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
    assert loaded.metadata["terminal_reason"]["code"] == "agent_decide_error"
    assert "cleanup_completed_at" not in loaded.metadata


def test_external_worker_stop_is_explicit_and_stop_request_remains_for_parent(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)
    assert registry.request_stop(run_id) is True

    outcome = _external_run(
        UnexpectedExecutionAgent(),
        registry=registry,
        run_id=run_id,
    )

    assert outcome == RunExecutionOutcome(run_id=run_id, outcome="stopped")
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
    assert "stop_requested_at" in loaded.metadata
    assert "cleanup_completed_at" not in loaded.metadata


def test_external_worker_exception_stages_reason_without_terminalizing(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    with pytest.raises(TypeError, match="dictionary action"):
        _external_run(
            InvalidResultAgent(),
            registry=registry,
            run_id=run_id,
        )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
    assert loaded.metadata["terminal_reason"]["code"] == "worker_exception"
    assert loaded.metadata["terminal_reason"]["type"] == "TypeError"
    assert "cleanup_completed_at" not in loaded.metadata


def test_external_worker_after_claim_setup_exception_leaves_terminal_to_parent(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.run import runner as runner_module

    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    def fail_artifacts_root():
        raise OSError("deterministic artifact setup failure")

    monkeypatch.setattr(runner_module, "_artifacts_root", fail_artifacts_root)

    with pytest.raises(OSError, match="artifact setup failure"):
        _external_run(
            RandomAgent(seed=0, safe=True),
            registry=registry,
            run_id=run_id,
        )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
    assert "cleanup_completed_at" not in loaded.metadata


def test_legacy_run_once_still_returns_id_and_owns_terminal_status(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    result = run_once(
        RandomAgent(seed=0, safe=True),
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
        run_id=run_id,
        registry=registry,
    )

    assert result == run_id
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.ended_at is not None
    assert "cleanup_completed_at" in loaded.metadata


def test_legacy_failure_still_returns_id_and_finalizes_failed(
    tmp_path, monkeypatch
) -> None:
    registry, run_id = _registry_with_pending_run(tmp_path, monkeypatch)

    result = run_once(
        DecisionFailureAgent(),
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
        run_id=run_id,
        registry=registry,
    )

    assert result == run_id
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.ended_at is not None
    assert loaded.metadata["terminal_reason"]["code"] == "agent_decide_error"
    assert "cleanup_completed_at" in loaded.metadata


@pytest.mark.parametrize(
    ("outcome", "expected_exit"),
    [("completed", 0), ("failed", 20), ("stopped", 21)],
)
def test_external_worker_cli_has_stable_outcome_exit_contract(
    monkeypatch,
    outcome: str,
    expected_exit: int,
) -> None:
    from fort_gym.bench import cli
    from fort_gym.bench.experiment import runner as runner_module

    class FakeRunner:
        def run_from_path(self, config, *, external_run_id=None):
            return SimpleNamespace(
                experiment_id="experiment-id",
                artifacts_dir="/tmp/experiment-artifacts",
                variants=[
                    SimpleNamespace(
                        runs=[
                            SimpleNamespace(
                                run_id=external_run_id,
                                worker_outcome=outcome,
                                terminal_reason=(
                                    {"code": "deterministic_failure"}
                                    if outcome == "failed"
                                    else None
                                ),
                            )
                        ]
                    )
                ],
            )

    monkeypatch.setattr(runner_module, "ExperimentRunner", FakeRunner)
    result = CliRunner().invoke(
        cli.app,
        [
            "experiment",
            "config.yaml",
            "--external-run-id",
            "preassigned-run",
        ],
    )

    assert result.exit_code == expected_exit, result.output
    payload = json.loads(
        next(line for line in result.output.splitlines() if line.startswith("{"))
    )
    assert payload["schema"] == "fortgym.external-worker-outcome/v1"
    assert payload["run_id"] == "preassigned-run"
    assert payload["outcome"] == outcome


def test_external_worker_cli_maps_exception_to_nonzero_outcome(
    monkeypatch,
) -> None:
    from fort_gym.bench import cli
    from fort_gym.bench.experiment import runner as runner_module

    class FakeRunner:
        def run_from_path(self, config, *, external_run_id=None):
            raise RuntimeError("deterministic worker exception")

    monkeypatch.setattr(runner_module, "ExperimentRunner", FakeRunner)
    result = CliRunner().invoke(
        cli.app,
        [
            "experiment",
            "config.yaml",
            "--external-run-id",
            "preassigned-run",
        ],
    )

    assert result.exit_code == 22, result.output
    payload = json.loads(
        next(line for line in result.output.splitlines() if line.startswith("{"))
    )
    assert payload["outcome"] == "exception"
    assert payload["error"]["type"] == "RuntimeError"


def test_legacy_cli_exception_is_not_reclassified_as_external_worker_outcome(
    monkeypatch,
) -> None:
    from fort_gym.bench import cli
    from fort_gym.bench.experiment import runner as runner_module

    class FakeRunner:
        def run_from_path(self, config, *, external_run_id=None):
            raise RuntimeError("legacy exception")

    monkeypatch.setattr(runner_module, "ExperimentRunner", FakeRunner)
    result = CliRunner().invoke(cli.app, ["experiment", "config.yaml"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert "fortgym.external-worker-outcome/v1" not in result.output
