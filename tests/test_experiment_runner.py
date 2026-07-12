from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from fort_gym.bench.config import get_settings
from fort_gym.bench.experiment.config import VariantConfig
from fort_gym.bench.experiment.runner import ExperimentRunner


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
        run["run_id"]
        for variant in metadata["variants"]
        for run in variant["runs"]
    ]
    assert len(run_ids) == 2

    for run_id in run_ids:
        trace_path = artifacts_root / run_id / "trace.jsonl"
        assert trace_path.is_file()
        summary = json.loads((artifacts_root / run_id / "summary.json").read_text(encoding="utf-8"))
        assert summary["evaluation_protocol"] == "fort-eval-v1"

    assert os.environ.get("FORT_GYM_MEMORY_WINDOW") == original_memory
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_p1_experiment_runner_registers_and_shares_public_runs(
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

    run_id = ExperimentRunner(artifacts_root=tmp_path)._run_variant(
        {
            "backend": "dfhack",
            "model": "dfhack-governed-llm-fable5",
            "max_steps": 200,
            "ticks_per_step": 2500,
            "evaluation_protocol": "fort-eval-easy-p1-g7-v3",
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

    assert run_id == "p1-public-run"
    assert create_calls[0]["runtime_save"] == "region1"
    assert share_calls == [
        (
            "p1-public-run",
            {"scope": ["live", "replay", "export"], "ttl_seconds": None},
        )
    ]
    assert run_calls[0]["run_id"] == "p1-public-run"
    assert run_calls[0]["registry"] is fake_registry
