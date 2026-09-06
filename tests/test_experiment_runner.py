from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.experiment.config import (
    BaseRunConfig,
    ExperimentConfig,
    VariantConfig,
)
from fort_gym.bench.experiment.runner import ExperimentRunner
from fort_gym.bench.run.runner import RunExecutionOutcome
from fort_gym.bench.run.storage import RunRegistry


def _experiment_config(
    *,
    variant_count: int = 1,
    runs_per_variant: int = 1,
) -> ExperimentConfig:
    return ExperimentConfig(
        name="external-run-contract",
        description=None,
        base_config=BaseRunConfig(
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
        ),
        variants=[
            VariantConfig(name=f"variant-{index}", memory_window=0)
            for index in range(variant_count)
        ],
        runs_per_variant=runs_per_variant,
    )


def test_external_scripted_worker_receives_declared_tick_budget(tmp_path, monkeypatch) -> None:
    from fort_gym.bench.experiment import runner as runner_module
    from fort_gym.bench.env.mock_env import MockEnvironment

    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(tmp_path / "runs.sqlite"))
    get_settings.cache_clear()
    registry = RunRegistry(recover_interrupted=False)
    registry.create(run_id="scripted-bound", backend="mock", model="dfhack-governed-scripted",
                    max_steps=2, ticks_per_step=200)
    config = _experiment_config()
    config = replace(config, base_config=replace(
        config.base_config, model="dfhack-governed-scripted", ticks_per_step=200
    ))
    captured = []

    def run(agent, **kwargs):
        captured.append(agent.decide("", MockEnvironment().observe())["advance_ticks"])
        assert kwargs["ticks_per_step"] == 200
        assert kwargs["supervisor_owns_terminal"] is True
        return RunExecutionOutcome(run_id=kwargs["run_id"], outcome="completed")

    monkeypatch.setattr(runner_module, "run_once", run)
    try:
        ExperimentRunner(artifacts_root=artifacts).run(config, external_run_id="scripted-bound")
        assert captured == [200]
    finally:
        get_settings.cache_clear()


def test_real_external_scripted_cli_commits_only_declared_tick_requests(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    db_path = tmp_path / "runs.sqlite"
    registry = RunRegistry(db_path=db_path, recover_interrupted=False)
    run_id = "scripted-cli-bound"
    registry.create(run_id=run_id, backend="mock", model="dfhack-governed-scripted",
                    max_steps=3, ticks_per_step=200)
    config = _experiment_config()
    config = replace(config, base_config=replace(
        config.base_config, model="dfhack-governed-scripted", ticks_per_step=200, max_steps=3
    ))
    config_path = tmp_path / "experiment.json"
    config_path.write_text(json.dumps(asdict(config)))
    repo = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, "-m", "fort_gym.bench.cli", "experiment", str(config_path),
         "--external-run-id", run_id],
        cwd=repo,
        env={"PATH": os.defpath, "PYTHONPATH": str(repo),
             "FORT_GYM_DISABLE_DOTENV": "1", "ARTIFACTS_DIR": str(artifacts),
             "FORT_GYM_DB_PATH": str(db_path)},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert process.returncode == 0, process.stderr
    rows = [json.loads(line) for line in
            (artifacts / run_id / "trace.jsonl").read_text().splitlines()]
    assert [row["step"] for row in rows] == [0, 1, 2]
    assert all(row["action"]["advance_ticks"] == 200 for row in rows)
    assert all(row["tick_advance"]["ticks_advanced"] == 200 for row in rows)
    assert [row["state_after_advance"]["time"] for row in rows] == [200, 400, 600]
    # CLI success does not usurp the supervisor's terminal/cleanup ownership.
    record = registry.get(run_id)
    assert record is not None and record.status == "running"
    assert record.ended_at is None


def test_experiment_runner_creates_metadata(tmp_path, monkeypatch) -> None:
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(
        """
name: test-experiment
description: Test experiment config
base_config:
  backend: mock
  max_steps: 2
  model: fake
  evaluation_protocol: fort-eval-v1
variants:
  - name: short
    memory_window: 0
  - name: long
    memory_window: 3
runs_per_variant: 1
""".lstrip(),
        encoding="utf-8",
    )

    original_memory = os.environ.get("FORT_GYM_MEMORY_WINDOW")
    runner = ExperimentRunner()
    result = runner.run_from_path(config_path)

    experiment_dir = Path(result.artifacts_dir)
    metadata_path = experiment_dir / "experiment.json"
    config_copy_path = experiment_dir / "config.yaml"

    assert metadata_path.is_file()
    assert config_copy_path.is_file()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["name"] == "test-experiment"
    assert metadata["runs_per_variant"] == 1
    assert metadata["base_config"]["evaluation_protocol"] == "fort-eval-v1"

    run_ids = [
        run["run_id"] for variant in metadata["variants"] for run in variant["runs"]
    ]
    assert len(run_ids) == 2

    for run_id in run_ids:
        trace_path = artifacts_root / run_id / "trace.jsonl"
        assert trace_path.is_file()
        summary = json.loads(
            (artifacts_root / run_id / "summary.json").read_text(encoding="utf-8")
        )
        assert summary["evaluation_protocol"] == "fort-eval-v1"

    assert os.environ.get("FORT_GYM_MEMORY_WINDOW") == original_memory
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_p1_experiment_runner_rejects_frozen_protocol_before_registering_run(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    create_calls: list[dict] = []
    share_calls: list[tuple[str, dict]] = []
    run_calls: list[dict] = []

    class FakeRegistry:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            return SimpleNamespace(run_id="p1-public-run")

        def create_share(self, run_id, **kwargs):
            share_calls.append((run_id, kwargs))

    fake_registry = FakeRegistry()
    monkeypatch.setattr(runner_module, "RUN_REGISTRY", fake_registry)
    monkeypatch.setattr(runner_module, "_make_agent", lambda _name: object())

    def fake_run_once(_agent, **kwargs):
        run_calls.append(kwargs)
        return kwargs["run_id"]

    monkeypatch.setattr(runner_module, "run_once", fake_run_once)

    with pytest.raises(ValueError, match="G7-v4 is frozen"):
        ExperimentRunner(artifacts_root=tmp_path)._run_variant(
            {
                "backend": "dfhack",
                "model": "dfhack-governed-llm-fable5",
                "max_steps": 200,
                "ticks_per_step": 2500,
                "evaluation_protocol": "fort-eval-easy-p1-g7-v4",
                "preserve_save": False,
                "seed_save": "seed_region3_fresh",
                "runtime_save": "region1",
            },
            VariantConfig(
                name="fable5-memory-off",
                memory_window=0,
                model="dfhack-governed-llm-fable5",
            ),
        )

    assert create_calls == []
    assert share_calls == []
    assert run_calls == []


def test_external_run_id_uses_worker_registry_and_exact_preassigned_id(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    db_path = tmp_path / "runs.sqlite3"
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    api_registry = RunRegistry(db_path=db_path)
    target = api_registry.create(
        run_id="api-preassigned-run",
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    sibling = api_registry.create(
        run_id="sibling-run",
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    assert api_registry.claim_pending_run(
        sibling.run_id,
        started_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    class ForbiddenGlobalRegistry:
        def create(self, **_kwargs):
            raise AssertionError("external worker must not create a run")

        def create_share(self, *_args, **_kwargs):
            raise AssertionError("external worker must not create a share")

    captured: dict[str, object] = {}
    agent = object()
    monkeypatch.setattr(runner_module, "RUN_REGISTRY", ForbiddenGlobalRegistry())
    monkeypatch.setattr(runner_module, "_ensure_agent_factories", lambda: None)
    monkeypatch.setattr(runner_module, "_make_agent", lambda _name: agent)

    def fake_run_once(actual_agent, **kwargs):
        captured.update(kwargs)
        assert actual_agent is agent
        worker_registry = kwargs["registry"]
        assert isinstance(worker_registry, RunRegistry)
        loaded_sibling = worker_registry.get(sibling.run_id)
        assert loaded_sibling is not None and loaded_sibling.status == "running"
        return RunExecutionOutcome(
            run_id=kwargs["run_id"],
            outcome="completed",
        )

    monkeypatch.setattr(runner_module, "run_once", fake_run_once)

    result = ExperimentRunner(artifacts_root=artifacts_root).run(
        _experiment_config(),
        external_run_id=target.run_id,
    )

    assert captured["run_id"] == target.run_id
    assert captured["supervisor_owns_terminal"] is True
    assert result.variants[0].runs[0].run_id == target.run_id
    assert result.variants[0].runs[0].worker_outcome == "completed"
    assert sorted(run.run_id for run in api_registry.list()) == [
        "api-preassigned-run",
        "sibling-run",
    ]
    assert api_registry.list_public() == []
    loaded_sibling = api_registry.get(sibling.run_id)
    assert loaded_sibling is not None and loaded_sibling.status == "running"
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("variant_count", "runs_per_variant"),
    [(2, 1), (1, 2)],
)
def test_external_run_id_rejects_multi_run_config_before_registry_or_execution(
    tmp_path,
    monkeypatch,
    variant_count: int,
    runs_per_variant: int,
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    def unexpected_registry(**_kwargs):
        raise AssertionError("invalid shape must fail before opening the registry")

    monkeypatch.setattr(runner_module, "RunRegistry", unexpected_registry)
    monkeypatch.setattr(
        runner_module,
        "_ensure_agent_factories",
        lambda: (_ for _ in ()).throw(AssertionError("agent loading must not start")),
    )

    with pytest.raises(ValueError, match="exactly one variant"):
        ExperimentRunner(artifacts_root=tmp_path).run(
            _experiment_config(
                variant_count=variant_count,
                runs_per_variant=runs_per_variant,
            ),
            external_run_id="api-preassigned-run",
        )

    assert not (tmp_path / "experiments").exists()


def test_external_run_id_rejects_invalid_identifier_before_registry(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    def unexpected_registry(**_kwargs):
        raise AssertionError("invalid ID must fail before opening the registry")

    monkeypatch.setattr(runner_module, "RunRegistry", unexpected_registry)

    with pytest.raises(ValueError, match="external_run_id must be 1-128"):
        ExperimentRunner(artifacts_root=tmp_path).run(
            _experiment_config(),
            external_run_id="../escape",
        )

    assert not (tmp_path / "experiments").exists()


def test_external_run_id_rejects_missing_registry_row_before_execution(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    db_path = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    api_registry = RunRegistry(db_path=db_path)
    api_registry.create(
        run_id="known-run",
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    monkeypatch.setattr(
        runner_module,
        "_ensure_agent_factories",
        lambda: (_ for _ in ()).throw(AssertionError("execution must not start")),
    )

    with pytest.raises(ValueError, match="is not registered"):
        ExperimentRunner(artifacts_root=tmp_path / "artifacts").run(
            _experiment_config(),
            external_run_id="missing-run",
        )

    assert [run.run_id for run in api_registry.list()] == ["known-run"]
    assert api_registry.list_public() == []


def test_external_run_id_rejects_non_pending_row_without_recovering_it(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    db_path = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    api_registry = RunRegistry(db_path=db_path)
    record = api_registry.create(
        run_id="already-running",
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    assert api_registry.claim_pending_run(
        record.run_id,
        started_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    monkeypatch.setattr(
        runner_module,
        "_ensure_agent_factories",
        lambda: (_ for _ in ()).throw(AssertionError("execution must not start")),
    )

    with pytest.raises(ValueError, match="must be pending; found 'running'"):
        ExperimentRunner(artifacts_root=tmp_path / "artifacts").run(
            _experiment_config(),
            external_run_id=record.run_id,
        )

    loaded = api_registry.get(record.run_id)
    assert loaded is not None and loaded.status == "running"
    assert api_registry.list_public() == []


@pytest.mark.parametrize(
    ("field", "registered_value"),
    [
        ("backend", "dfhack"),
        ("model", "random"),
        ("max_steps", 3),
        ("ticks_per_step", 11),
        ("evaluation_protocol", "fort-eval-v1"),
        ("preserve_save", True),
        ("seed_save", "different-seed"),
        ("runtime_save", "different-runtime"),
    ],
)
def test_external_run_id_rejects_registry_config_mismatch_without_mutation(
    tmp_path,
    monkeypatch,
    field: str,
    registered_value: object,
) -> None:
    from fort_gym.bench.experiment import runner as runner_module

    db_path = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    api_registry = RunRegistry(db_path=db_path)
    create_kwargs: dict[str, object] = {
        "run_id": f"mismatch-{field.replace('_', '-')}",
        "backend": "mock",
        "model": "fake",
        "max_steps": 2,
        "ticks_per_step": 10,
    }
    create_kwargs[field] = registered_value
    record = api_registry.create(**create_kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(
        runner_module,
        "_ensure_agent_factories",
        lambda: (_ for _ in ()).throw(AssertionError("execution must not start")),
    )
    monkeypatch.setattr(
        runner_module,
        "_make_agent",
        lambda _name: (_ for _ in ()).throw(
            AssertionError("agent must not be created")
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "run_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("run_once must not execute")
        ),
    )

    with pytest.raises(ValueError, match=field):
        ExperimentRunner(artifacts_root=tmp_path / "artifacts").run(
            _experiment_config(),
            external_run_id=record.run_id,
        )

    loaded = api_registry.get(record.run_id)
    assert loaded is not None and loaded.status == "pending"
    assert getattr(loaded, field) == registered_value
    assert api_registry.list_public() == []
    assert not (tmp_path / "artifacts" / "experiments").exists()


def test_experiment_cli_forwards_optional_external_run_id(monkeypatch) -> None:
    from typer.testing import CliRunner

    from fort_gym.bench import cli
    from fort_gym.bench.experiment import runner as runner_module

    calls: list[tuple[str, str | None]] = []

    class FakeRunner:
        def run_from_path(self, config, *, external_run_id=None):
            calls.append((config, external_run_id))
            variants = (
                [
                    SimpleNamespace(
                        runs=[
                            SimpleNamespace(
                                run_id=external_run_id,
                                worker_outcome="completed",
                                terminal_reason=None,
                            )
                        ]
                    )
                ]
                if external_run_id is not None
                else []
            )
            return SimpleNamespace(
                experiment_id="experiment-id",
                artifacts_dir="/tmp/experiment-artifacts",
                variants=variants,
            )

    monkeypatch.setattr(runner_module, "ExperimentRunner", FakeRunner)
    cli_runner = CliRunner()

    external = cli_runner.invoke(
        cli.app,
        [
            "experiment",
            "config.yaml",
            "--external-run-id",
            "api-preassigned-run",
        ],
    )
    legacy = cli_runner.invoke(cli.app, ["experiment", "config.yaml"])

    assert external.exit_code == 0, external.output
    assert legacy.exit_code == 0, legacy.output
    assert calls == [
        ("config.yaml", "api-preassigned-run"),
        ("config.yaml", None),
    ]
