"""Experiment configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class BaseRunConfig:
    backend: str
    max_steps: int
    model: str
    ticks_per_step: int | None = None


@dataclass(frozen=True)
class VariantConfig:
    name: str
    memory_window: int


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    description: str | None
    base_config: BaseRunConfig
    variants: list[VariantConfig]
    runs_per_variant: int = 1


class ExperimentConfigError(ValueError):
    pass


def load_experiment_config(path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ExperimentConfigError(f"Experiment config is empty: {path}")
    if not isinstance(raw, Mapping):
        raise ExperimentConfigError("Experiment config must be a mapping")

    name = _require_str(raw, "name")
    description = _optional_str(raw, "description")
    base_config = _parse_base_config(raw.get("base_config"))
    variants = _parse_variants(raw.get("variants"))
    runs_per_variant = _optional_int(raw, "runs_per_variant")
    if runs_per_variant is None:
        runs_per_variant = 1
    if runs_per_variant < 1:
        raise ExperimentConfigError("runs_per_variant must be >= 1")

    return ExperimentConfig(
        name=name,
        description=description,
        base_config=base_config,
        variants=variants,
        runs_per_variant=runs_per_variant,
    )


def _parse_base_config(value: object) -> BaseRunConfig:
    if not isinstance(value, Mapping):
        raise ExperimentConfigError("base_config must be a mapping")
    backend = _require_str(value, "backend")
    max_steps = _require_int(value, "max_steps")
    if max_steps < 1:
        raise ExperimentConfigError("base_config.max_steps must be >= 1")
    model = _require_str(value, "model")
    ticks_per_step = _optional_int(value, "ticks_per_step")
    if ticks_per_step is not None and ticks_per_step < 1:
        raise ExperimentConfigError("base_config.ticks_per_step must be >= 1")

    return BaseRunConfig(
        backend=backend,
        max_steps=max_steps,
        model=model,
        ticks_per_step=ticks_per_step,
    )


def _parse_variants(value: object) -> list[VariantConfig]:
    if not isinstance(value, list) or not value:
        raise ExperimentConfigError("variants must be a non-empty list")

    variants: list[VariantConfig] = []
    for raw_variant in value:
        if not isinstance(raw_variant, Mapping):
            raise ExperimentConfigError("variant entries must be mappings")
        name = _require_str(raw_variant, "name")
        memory_window = _require_int(raw_variant, "memory_window")
        if memory_window < 0:
            raise ExperimentConfigError("variants.memory_window must be >= 0")
        variants.append(VariantConfig(name=name, memory_window=memory_window))

    return variants


def _require_str(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ExperimentConfigError(f"{field} must be a non-empty string")
    return value


def _optional_str(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExperimentConfigError(f"{field} must be a string")
    return value


def _require_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExperimentConfigError(f"{field} must be an integer")
    return value


def _optional_int(data: Mapping[str, object], field: str) -> int | None:
    if field not in data:
        return None
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExperimentConfigError(f"{field} must be an integer")
    return value


__all__ = [
    "BaseRunConfig",
    "VariantConfig",
    "ExperimentConfig",
    "ExperimentConfigError",
    "load_experiment_config",
]
