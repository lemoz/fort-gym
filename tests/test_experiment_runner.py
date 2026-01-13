from __future__ import annotations

import json
import os
from pathlib import Path

from fort_gym.bench.config import get_settings
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

    run_ids = [
        run["run_id"]
        for variant in metadata["variants"]
        for run in variant["runs"]
    ]
    assert len(run_ids) == 2

    for run_id in run_ids:
        trace_path = artifacts_root / run_id / "trace.jsonl"
        assert trace_path.is_file()

    assert os.environ.get("FORT_GYM_MEMORY_WINDOW") == original_memory
    get_settings.cache_clear()  # type: ignore[attr-defined]
