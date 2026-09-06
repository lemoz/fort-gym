"""Experiment execution utilities."""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from ..agent.base import AGENT_FACTORIES, Agent
from ..config import get_settings
from ..eval.fort_eval_easy_p1 import P1_PROTOCOL, validate_p1_declaration
from ..run.fault_session import step_observer_from_environment
from ..run.runner import RunExecutionOutcome, run_once
from ..run.storage import RUN_REGISTRY, RunRegistry
from .config import (
    BaseRunConfig,
    ExperimentConfig,
    VariantConfig,
    load_experiment_config,
)

_EXTERNAL_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class VariantRun:
    run_id: str
    run_index: int
    summary: Mapping[str, object] | None
    worker_outcome: str | None = None
    terminal_reason: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "run_id": self.run_id,
            "run_index": self.run_index,
            "summary": self.summary,
        }
        if self.worker_outcome is not None:
            payload["worker_outcome"] = self.worker_outcome
            payload["terminal_reason"] = self.terminal_reason
        return payload


@dataclass(frozen=True)
class VariantResult:
    name: str
    memory_window: int
    backend: str
    max_steps: int
    model: str
    ticks_per_step: int
    evaluation_protocol: str | None
    runs: list[VariantRun]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "memory_window": self.memory_window,
            "backend": self.backend,
            "max_steps": self.max_steps,
            "model": self.model,
            "ticks_per_step": self.ticks_per_step,
            "evaluation_protocol": self.evaluation_protocol,
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
                "evaluation_protocol": self.base_config.evaluation_protocol,
                "preserve_save": self.base_config.preserve_save,
                "seed_save": self.base_config.seed_save,
                "runtime_save": self.base_config.runtime_save,
            },
            "variants": [variant.to_dict() for variant in self.variants],
        }


class ExperimentRunner:
    def __init__(self, artifacts_root: Path | None = None) -> None:
        self._artifacts_root = artifacts_root or _artifacts_root()

    def run_from_path(
        self,
        config_path: str | Path,
        *,
        external_run_id: str | None = None,
    ) -> ExperimentResult:
        resolved_path = resolve_experiment_path(config_path)
        config = load_experiment_config(resolved_path)
        return self.run(
            config,
            config_path=resolved_path,
            external_run_id=external_run_id,
        )

    def run(
        self,
        config: ExperimentConfig,
        *,
        config_path: Path | None = None,
        external_run_id: str | None = None,
    ) -> ExperimentResult:
        worker_registry: RunRegistry | None = None
        external_resolved: dict[str, int | str | bool | None] | None = None
        if external_run_id is not None:
            _validate_external_run_shape(config, external_run_id)
            external_resolved = _resolve_variant(
                config.base_config,
                config.variants[0],
            )
            worker_registry = RunRegistry(recover_interrupted=False)
            _require_pending_external_run(
                worker_registry,
                external_run_id,
                external_resolved,
            )

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
            resolved = external_resolved or _resolve_variant(
                config.base_config,
                variant,
            )
            runs: list[VariantRun] = []
            for index in range(config.runs_per_variant):
                execution = self._run_variant(
                    resolved,
                    variant,
                    external_run_id=external_run_id,
                    registry=worker_registry,
                )
                if isinstance(execution, RunExecutionOutcome):
                    run_id = execution.run_id
                    worker_outcome = execution.outcome
                    terminal_reason = execution.terminal_reason
                else:
                    run_id = execution
                    worker_outcome = None
                    terminal_reason = None
                summary = _load_summary(self._artifacts_root, run_id)
                runs.append(
                    VariantRun(
                        run_id=run_id,
                        run_index=index + 1,
                        summary=summary,
                        worker_outcome=worker_outcome,
                        terminal_reason=terminal_reason,
                    )
                )
            variants_results.append(
                VariantResult(
                    name=variant.name,
                    memory_window=variant.memory_window,
                    backend=resolved["backend"],
                    max_steps=resolved["max_steps"],
                    model=resolved["model"],
                    ticks_per_step=resolved["ticks_per_step"],
                    evaluation_protocol=resolved["evaluation_protocol"],
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

    def _run_variant(
        self,
        resolved: dict[str, int | str | bool | None],
        variant: VariantConfig,
        *,
        external_run_id: str | None = None,
        registry: RunRegistry | None = None,
    ) -> str | RunExecutionOutcome:
        agent_name = str(resolved["model"])
        ticks_per_step = int(resolved["ticks_per_step"])
        with _memory_window_context(variant.memory_window):
            if external_run_id is not None and agent_name == "dfhack-governed-scripted":
                from ..agent.governed import DFHackGovernedScriptedAgent

                agent = DFHackGovernedScriptedAgent(ticks_per_step=ticks_per_step)
            else:
                agent = _make_agent(agent_name)
            run_kwargs = {
                "backend": str(resolved["backend"]),
                "model": str(resolved["model"]),
                "max_steps": int(resolved["max_steps"]),
                "ticks_per_step": ticks_per_step,
                "evaluation_protocol": resolved["evaluation_protocol"],
                "preserve_save": bool(resolved["preserve_save"]),
                "seed_save": (
                    str(resolved["seed_save"]) if resolved["seed_save"] else None
                ),
                "runtime_save": (
                    str(resolved["runtime_save"]) if resolved["runtime_save"] else None
                ),
            }
            validate_p1_declaration(
                protocol=resolved["evaluation_protocol"],
                backend=str(resolved["backend"]),
                model=str(resolved["model"]),
                seed_save=(
                    str(resolved["seed_save"]) if resolved["seed_save"] else None
                ),
                runtime_save=(
                    str(resolved["runtime_save"]) if resolved["runtime_save"] else None
                ),
                preserve_save=bool(resolved["preserve_save"]),
                max_steps=int(resolved["max_steps"]),
                ticks_per_step=ticks_per_step,
            )
            if external_run_id is not None:
                if registry is None:  # pragma: no cover - guarded by run()
                    raise RuntimeError(
                        "External run execution requires a worker registry"
                    )
                step_commit_observer = step_observer_from_environment(os.environ)
                if step_commit_observer is not None:
                    run_kwargs["step_commit_observer"] = step_commit_observer
                outcome = run_once(
                    agent,
                    run_id=external_run_id,
                    registry=registry,
                    supervisor_owns_terminal=True,
                    **run_kwargs,
                )
                if not isinstance(outcome, RunExecutionOutcome):
                    raise RuntimeError(
                        "External worker run did not return an explicit outcome"
                    )
                return outcome
            if resolved["evaluation_protocol"] == P1_PROTOCOL:
                record = RUN_REGISTRY.create(**run_kwargs)
                RUN_REGISTRY.create_share(
                    record.run_id,
                    scope=["live", "replay", "export"],
                    ttl_seconds=None,
                )
                return run_once(
                    agent,
                    run_id=record.run_id,
                    registry=RUN_REGISTRY,
                    **run_kwargs,
                )
            return run_once(agent, **run_kwargs)


def _validate_external_run_shape(
    config: ExperimentConfig,
    external_run_id: str,
) -> None:
    if not _EXTERNAL_RUN_ID_RE.fullmatch(external_run_id):
        raise ValueError(
            "external_run_id must be 1-128 characters using only letters, "
            "numbers, '.', '_', or '-', and must start with a letter or number"
        )
    if len(config.variants) != 1 or config.runs_per_variant != 1:
        raise ValueError(
            "external_run_id requires exactly one variant and runs_per_variant=1"
        )


def _require_pending_external_run(
    registry: RunRegistry,
    run_id: str,
    resolved: Mapping[str, int | str | bool | None],
) -> None:
    record = registry.get(run_id)
    if record is None:
        raise ValueError(f"Externally preassigned run '{run_id}' is not registered")
    if record.status != "pending":
        raise ValueError(
            f"Externally preassigned run '{run_id}' must be pending; "
            f"found '{record.status}'"
        )

    settings = get_settings()
    expected: dict[str, object] = {
        "backend": str(resolved["backend"]),
        "model": str(resolved["model"]),
        "max_steps": int(resolved["max_steps"]),
        "ticks_per_step": int(resolved["ticks_per_step"]),
        "evaluation_protocol": resolved["evaluation_protocol"],
        "preserve_save": bool(resolved["preserve_save"]),
        "seed_save": (
            str(resolved["seed_save"])
            if resolved["seed_save"]
            else settings.FORT_GYM_SEED_SAVE
        ),
        "runtime_save": (
            str(resolved["runtime_save"])
            if resolved["runtime_save"]
            else getattr(settings, "FORT_GYM_RUNTIME_SAVE", None)
        ),
    }
    actual = {
        "backend": record.backend,
        "model": record.model,
        "max_steps": record.max_steps,
        "ticks_per_step": record.ticks_per_step,
        "evaluation_protocol": record.evaluation_protocol,
        "preserve_save": record.preserve_save,
        "seed_save": record.seed_save,
        "runtime_save": record.runtime_save,
    }
    mismatched = [field for field in expected if actual[field] != expected[field]]
    if mismatched:
        detail = ", ".join(
            f"{field} (registered={actual[field]!r}, resolved={expected[field]!r})"
            for field in mismatched
        )
        raise ValueError(
            f"Externally preassigned run '{run_id}' does not match the resolved "
            f"experiment config: {detail}"
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


def _resolve_variant(
    base: BaseRunConfig, variant: VariantConfig
) -> dict[str, int | str | bool | None]:
    settings = get_settings()
    ticks = (
        base.ticks_per_step
        if base.ticks_per_step is not None
        else settings.TICKS_PER_STEP
    )
    return {
        "backend": base.backend,
        "max_steps": base.max_steps,
        "model": variant.model or base.model,
        "ticks_per_step": ticks,
        "evaluation_protocol": base.evaluation_protocol,
        "preserve_save": base.preserve_save,
        "seed_save": base.seed_save,
        "runtime_save": base.runtime_save,
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
    from ..agent import (
        fake_llm,
        governed,
        governed_llm,
        llm_anthropic,
        llm_anthropic_research,
        llm_openai,
        llm_openrouter,
    )

    _ = (
        fake_llm,
        governed,
        governed_llm,
        llm_anthropic,
        llm_anthropic_research,
        llm_openai,
        llm_openrouter,
    )


__all__ = [
    "ExperimentResult",
    "ExperimentRunner",
    "resolve_experiment_path",
]
