"""Experiment execution utilities."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .config import BaseRunConfig, ExperimentConfig, VariantConfig, load_experiment_config
from ..agent.base import AGENT_FACTORIES, Agent
from ..config import get_settings
from ..run.runner import run_once


@dataclass(frozen=True)
class VariantRun:
    run_id: str
    run_index: int
    summary: Mapping[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_index": self.run_index,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class VariantResult:
    name: str
    memory_window: int
    backend: str
    max_steps: int
    model: str
    ticks_per_step: int
    runs: list[VariantRun]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "memory_window": self.memory_window,
            "backend": self.backend,
            "max_steps": self.max_steps,
            "model": self.model,
            "ticks_per_step": self.ticks_per_step,
            "runs": [run.to_dict() for run in self.runs],
        }


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    name: str
    description: str | None
    config_path: str | None
    artifacts_dir: str
    started_at: str
    finished_at: str
    runs_per_variant: int
    base_config: BaseRunConfig
    variants: list[VariantResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "config_path": self.config_path,
            "artifacts_dir": self.artifacts_dir,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "runs_per_variant": self.runs_per_variant,
            "base_config": {
                "backend": self.base_config.backend,
                "max_steps": self.base_config.max_steps,
                "model": self.base_config.model,
                "ticks_per_step": self.base_config.ticks_per_step,
            },
            "variants": [variant.to_dict() for variant in self.variants],
        }


class ExperimentRunner:
    def __init__(self, artifacts_root: Path | None = None) -> None:
        self._artifacts_root = artifacts_root or _artifacts_root()

    def run_from_path(self, config_path: str | Path) -> ExperimentResult:
        resolved_path = resolve_experiment_path(config_path)
        config = load_experiment_config(resolved_path)
        return self.run(config, config_path=resolved_path)

    def run(self, config: ExperimentConfig, *, config_path: Path | None = None) -> ExperimentResult:
        _ensure_agent_factories()
        experiment_id = _new_experiment_id()
        started_at = datetime.utcnow()
        experiment_dir = self._experiment_dir(config.name, experiment_id)
        experiment_dir.mkdir(parents=True, exist_ok=True)
        if config_path is not None:
            (experiment_dir / "config.yaml").write_text(
                config_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        variants_results: list[VariantResult] = []
        for variant in config.variants:
            resolved = _resolve_variant(config.base_config)
            runs: list[VariantRun] = []
            for index in range(config.runs_per_variant):
                run_id = self._run_variant(resolved, variant)
                summary = _load_summary(self._artifacts_root, run_id)
                runs.append(VariantRun(run_id=run_id, run_index=index + 1, summary=summary))
            variants_results.append(
                VariantResult(
                    name=variant.name,
                    memory_window=variant.memory_window,
                    backend=resolved["backend"],
                    max_steps=resolved["max_steps"],
                    model=resolved["model"],
                    ticks_per_step=resolved["ticks_per_step"],
                    runs=runs,
                )
            )

        finished_at = datetime.utcnow()
        result = ExperimentResult(
            experiment_id=experiment_id,
            name=config.name,
            description=config.description,
            config_path=str(config_path) if config_path else None,
            artifacts_dir=str(experiment_dir),
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            runs_per_variant=config.runs_per_variant,
            base_config=config.base_config,
            variants=variants_results,
        )
        _write_result(experiment_dir, result)
        return result

    def _experiment_dir(self, name: str, experiment_id: str) -> Path:
        return self._artifacts_root / "experiments" / name / experiment_id

    def _run_variant(self, resolved: dict[str, int | str], variant: VariantConfig) -> str:
        agent_name = str(resolved["model"])
        ticks_per_step = int(resolved["ticks_per_step"])
        with _memory_window_context(variant.memory_window):
            agent = _make_agent(agent_name)
            return run_once(
                agent,
                backend=str(resolved["backend"]),
                model=str(resolved["model"]),
                max_steps=int(resolved["max_steps"]),
                ticks_per_step=ticks_per_step,
            )


def resolve_experiment_path(config_path: str | Path) -> Path:
    candidate = Path(config_path)
    if candidate.is_file():
        return candidate
    repo_root = Path(__file__).resolve().parents[3]
    direct = repo_root / candidate
    if direct.is_file():
        return direct
    fallback = repo_root / "experiments" / candidate
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(f"Experiment config not found: {config_path}")


def _resolve_variant(base: BaseRunConfig) -> dict[str, int | str]:
    settings = get_settings()
    ticks = base.ticks_per_step if base.ticks_per_step is not None else settings.TICKS_PER_STEP
    return {
        "backend": base.backend,
        "max_steps": base.max_steps,
        "model": base.model,
        "ticks_per_step": ticks,
    }


def _new_experiment_id() -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _artifacts_root() -> Path:
    return Path(get_settings().ARTIFACTS_DIR).resolve()


def _write_result(experiment_dir: Path, result: ExperimentResult) -> None:
    path = experiment_dir / "experiment.json"
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def _load_summary(artifacts_root: Path, run_id: str) -> Mapping[str, object] | None:
    summary_path = artifacts_root / run_id / "summary.json"
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@contextmanager
def _memory_window_context(value: int | None):
    if value is None:
        yield
        return
    previous = os.environ.get("FORT_GYM_MEMORY_WINDOW")
    os.environ["FORT_GYM_MEMORY_WINDOW"] = str(value)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FORT_GYM_MEMORY_WINDOW", None)
        else:
            os.environ["FORT_GYM_MEMORY_WINDOW"] = previous
        get_settings.cache_clear()  # type: ignore[attr-defined]


def _make_agent(name: str) -> Agent:
    factory = AGENT_FACTORIES.get(name)
    if factory is None:
        available = ", ".join(sorted(AGENT_FACTORIES.keys()))
        raise ValueError(f"Unknown agent '{name}'. Available: {available}")
    return factory()


def _ensure_agent_factories() -> None:
    from ..agent import fake_llm, llm_anthropic, llm_anthropic_research, llm_openai

    _ = (fake_llm, llm_anthropic, llm_anthropic_research, llm_openai)


__all__ = [
    "ExperimentResult",
    "ExperimentRunner",
    "resolve_experiment_path",
]
