"""Canonical, side-effect-free runtime contracts for supervised Fort Gym runs.

The contract binds one registry run to its exact runtime, seed, code, port,
nonce, filesystem roots, co-tenancy cohort, and provider policy before any
process or container is started.  It intentionally does not provision Docker
or open a socket; :class:`ProcessSupervisor` remains the owner of the actual
host-wide port lease and child process group.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .process_supervisor import RunSpec

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_NONCE_RE = re.compile(r"^[a-f0-9]{32,64}$")
_SAVE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_MODEL_LENGTH = 200
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PREPARED_RUNTIME_ENVIRONMENT_FIELDS = (
    "FORT_GYM_RUNTIME_PREPARED",
    "FORT_GYM_RUN_ID",
    "FORT_GYM_RUN_NONCE",
    "FORT_GYM_RUN_CONTRACT_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256",
    "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256",
    "FORT_GYM_EXPECTED_SEED_TREE_SHA256",
    "FORT_GYM_EXPECTED_SEED_WORLD_SHA256",
    "FORT_GYM_SEED_SAVE",
    "FORT_GYM_RUNTIME_SAVE",
)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_sha256(name: str, value: str) -> str:
    normalized = str(value).strip().lower()
    normalized = normalized.removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be an exact SHA-256 digest")
    return normalized


def _absolute_path(name: str, value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    if "\x00" in str(path):
        raise ValueError(f"{name} contains NUL")
    return path


def _bounded_text(name: str, value: str, *, maximum: int) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{name} must be non-empty and at most {maximum} characters")
    return normalized


def _supervised_pythonpath() -> str:
    """Return the exact sitecustomize and package import roots for the child."""

    runtime_directory = Path(__file__).resolve().parent
    package_root = Path(__file__).resolve().parents[3]
    if not (runtime_directory / "sitecustomize.py").is_file():
        raise RuntimeError("supervised network guard sitecustomize.py is missing")
    return os.pathsep.join((str(runtime_directory), str(package_root)))


class PreparedRuntimeIdentityError(ValueError):
    """A child was given a partial or contradictory prepared-runtime identity."""


@dataclass(frozen=True)
class PreparedRuntimeIdentity:
    """Validated, non-secret identity for an already-prepared DFHack runtime."""

    run_id: str
    nonce: str = field(repr=False)
    contract_sha256: str
    image_manifest_sha256: str
    image_config_sha256: str
    image_archive_sha256: str
    seed_tree_sha256: str
    seed_world_sha256: str
    seed_save: str
    runtime_save: str

    def summary_identity(self) -> dict[str, Any]:
        """Return a bounded persisted identity without exposing the runtime nonce."""

        return {
            "schema": "fortgym.m1b-prepared-runtime/v1",
            "runtime_prepared": True,
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "nonce_validated": True,
            "image": {
                "manifest_sha256": self.image_manifest_sha256,
                "config_sha256": self.image_config_sha256,
                "archive_sha256": self.image_archive_sha256,
            },
            "seed": {
                "tree_sha256": self.seed_tree_sha256,
                "world_sha256": self.seed_world_sha256,
                "seed_save": self.seed_save,
                "runtime_save": self.runtime_save,
            },
        }


def _prepared_environment_value(
    environment: Mapping[str, str],
    name: str,
) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value:
        raise PreparedRuntimeIdentityError(
            f"prepared runtime identity is incomplete: missing {name}"
        )
    if value != value.strip() or "\x00" in value:
        raise PreparedRuntimeIdentityError(
            f"prepared runtime identity has malformed {name}"
        )
    return value


def _prepared_environment_sha256(
    environment: Mapping[str, str],
    name: str,
) -> str:
    value = _prepared_environment_value(environment, name)
    if not _SHA256_RE.fullmatch(value):
        raise PreparedRuntimeIdentityError(
            f"prepared runtime identity has malformed {name}"
        )
    return value


def validate_prepared_runtime_environment(
    environment: Mapping[str, str],
    *,
    backend: str,
    run_id: str,
    seed_save: str | None,
    runtime_save: str | None,
) -> PreparedRuntimeIdentity | None:
    """Validate the supervisor-to-child handoff before any runtime side effect.

    A legacy DFHack launch has none of the prepared-runtime fields and keeps its
    host-side reset behavior. Once any handoff field is present, the full exact
    identity and the explicit ``FORT_GYM_RUNTIME_PREPARED=1`` marker are
    mandatory. Mock runs intentionally ignore this DFHack-only contract.
    """

    if backend != "dfhack":
        return None
    present = {
        name for name in _PREPARED_RUNTIME_ENVIRONMENT_FIELDS if name in environment
    }
    if not present:
        return None
    if environment.get("FORT_GYM_RUNTIME_PREPARED") != "1":
        raise PreparedRuntimeIdentityError(
            "prepared runtime identity requires FORT_GYM_RUNTIME_PREPARED=1"
        )
    missing = sorted(set(_PREPARED_RUNTIME_ENVIRONMENT_FIELDS) - present)
    if missing:
        raise PreparedRuntimeIdentityError(
            "prepared runtime identity is incomplete: missing " + ", ".join(missing)
        )

    declared_run_id = _prepared_environment_value(environment, "FORT_GYM_RUN_ID")
    if not _RUN_ID_RE.fullmatch(declared_run_id) or declared_run_id != run_id:
        raise PreparedRuntimeIdentityError(
            "prepared runtime identity run ID does not match the assigned run"
        )
    nonce = _prepared_environment_value(environment, "FORT_GYM_RUN_NONCE")
    if not _NONCE_RE.fullmatch(nonce):
        raise PreparedRuntimeIdentityError(
            "prepared runtime identity has malformed FORT_GYM_RUN_NONCE"
        )
    declared_seed_save = _prepared_environment_value(
        environment, "FORT_GYM_SEED_SAVE"
    )
    declared_runtime_save = _prepared_environment_value(
        environment, "FORT_GYM_RUNTIME_SAVE"
    )
    if declared_seed_save != seed_save or declared_runtime_save != runtime_save:
        raise PreparedRuntimeIdentityError(
            "prepared runtime seed/runtime save names do not match the run declaration"
        )

    return PreparedRuntimeIdentity(
        run_id=declared_run_id,
        nonce=nonce,
        contract_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_RUN_CONTRACT_SHA256"
        ),
        image_manifest_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256"
        ),
        image_config_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256"
        ),
        image_archive_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256"
        ),
        seed_tree_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_EXPECTED_SEED_TREE_SHA256"
        ),
        seed_world_sha256=_prepared_environment_sha256(
            environment, "FORT_GYM_EXPECTED_SEED_WORLD_SHA256"
        ),
        seed_save=declared_seed_save,
        runtime_save=declared_runtime_save,
    )


@dataclass(frozen=True)
class ProviderPolicy:
    """Explicit provider authority for one supervised child.

    The API key is deliberately excluded from the serializable identity.  Its
    presence is attested as a boolean; the secret itself is injected only into
    the child environment of a provider-enabled run.
    """

    enabled: bool = False
    route: str | None = None
    model: str | None = None
    provider_name: str | None = None
    base_url: str | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None
    api_key: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        configured = (
            self.route,
            self.model,
            self.provider_name,
            self.base_url,
            self.max_total_tokens,
            self.max_cost_usd,
            self.api_key,
        )
        if not self.enabled:
            if any(value is not None for value in configured):
                raise ValueError(
                    "disabled provider policy cannot carry provider material"
                )
            return

        if self.route != "openrouter":
            raise ValueError(
                "provider-enabled runs must use the explicit openrouter route"
            )
        model = _bounded_text("provider model", str(self.model or ""), maximum=200)
        provider_name = _bounded_text(
            "provider name", str(self.provider_name or ""), maximum=100
        )
        api_key = _bounded_text(
            "provider API key", str(self.api_key or ""), maximum=4096
        )
        base_url = _bounded_text(
            "provider base URL",
            str(self.base_url or _DEFAULT_OPENROUTER_BASE_URL),
            maximum=500,
        ).rstrip("/")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "provider base URL must be an explicit credential-free HTTPS URL"
            )
        if (
            isinstance(self.max_total_tokens, bool)
            or not isinstance(self.max_total_tokens, int)
            or self.max_total_tokens <= 0
        ):
            raise ValueError("provider token cap must be a positive integer")
        if isinstance(self.max_cost_usd, bool):
            raise TypeError("provider USD cap must be positive and finite")
        try:
            max_cost = float(self.max_cost_usd)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider USD cap must be positive and finite") from exc
        if not math.isfinite(max_cost) or max_cost <= 0:
            raise ValueError("provider USD cap must be positive and finite")

        object.__setattr__(self, "model", model)
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "max_cost_usd", max_cost)

    @classmethod
    def openrouter(
        cls,
        *,
        model: str,
        provider_name: str,
        api_key: str,
        max_total_tokens: int,
        max_cost_usd: float,
        base_url: str = _DEFAULT_OPENROUTER_BASE_URL,
    ) -> ProviderPolicy:
        return cls(
            enabled=True,
            route="openrouter",
            model=model,
            provider_name=provider_name,
            base_url=base_url,
            max_total_tokens=max_total_tokens,
            max_cost_usd=max_cost_usd,
            api_key=api_key,
        )

    def identity(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "route": self.route,
            "model": self.model,
            "provider_name": self.provider_name,
            "base_url": self.base_url,
            "max_total_tokens": self.max_total_tokens,
            "max_cost_usd": self.max_cost_usd,
            "credential_present": bool(self.api_key),
            "strict_supervised": self.enabled,
        }

    def environment(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        assert self.api_key is not None
        assert self.model is not None
        assert self.provider_name is not None
        assert self.base_url is not None
        assert self.max_total_tokens is not None
        assert self.max_cost_usd is not None
        return {
            "OPENROUTER_API_KEY": self.api_key,
            "OPENROUTER_BASE_URL": self.base_url,
            "OPENROUTER_MODEL": self.model,
            "OPENROUTER_PROVIDER_NAME": self.provider_name,
            "OPENROUTER_STRICT_SUPERVISED": "1",
            "OPENROUTER_MAX_TOTAL_TOKENS": str(self.max_total_tokens),
            "OPENROUTER_MAX_COST_USD": format(self.max_cost_usd, ".15g"),
        }


@dataclass(frozen=True)
class RuntimeContract:
    """Immutable pre-launch identity and environment for one supervised run."""

    run_id: str
    backend: str
    model: str
    port: int
    nonce: str
    image_manifest_sha256: str
    image_config_sha256: str
    image_archive_sha256: str
    seed_tree_sha256: str
    seed_world_sha256: str
    code_sha256: str
    db_path: Path
    artifacts_root: Path
    control_root: Path
    dfroot: Path
    seed_save: str
    runtime_save: str
    cohort_run_ids: Sequence[str]
    provider: ProviderPolicy = field(default_factory=ProviderPolicy)
    scripted: bool = True
    runtime_classification: str = "private_stock_archive_seeded"
    source_reproducible: bool = False

    def __post_init__(self) -> None:
        if not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        if self.backend not in {"mock", "dfhack"}:
            raise ValueError("backend must be 'mock' or 'dfhack'")
        object.__setattr__(
            self,
            "model",
            _bounded_text("model", self.model, maximum=_MAX_MODEL_LENGTH),
        )
        if not 1 <= int(self.port) <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        object.__setattr__(self, "port", int(self.port))
        nonce = str(self.nonce).strip().lower()
        if not _NONCE_RE.fullmatch(nonce):
            raise ValueError("nonce must be 128-256 bits encoded as lowercase hex")
        object.__setattr__(self, "nonce", nonce)

        for name in (
            "image_manifest_sha256",
            "image_config_sha256",
            "image_archive_sha256",
            "seed_tree_sha256",
            "seed_world_sha256",
            "code_sha256",
        ):
            object.__setattr__(self, name, _normalize_sha256(name, getattr(self, name)))

        for name in ("db_path", "artifacts_root", "control_root", "dfroot"):
            object.__setattr__(self, name, _absolute_path(name, getattr(self, name)))
        if self.control_root == self.artifacts_root:
            raise ValueError(
                "control_root must be separate from the run artifacts root"
            )

        seed_save = str(self.seed_save).strip()
        runtime_save = str(self.runtime_save).strip()
        if not _SAVE_NAME_RE.fullmatch(seed_save):
            raise ValueError("seed_save must be a bounded save name")
        if not _SAVE_NAME_RE.fullmatch(runtime_save):
            raise ValueError("runtime_save must be a bounded save name")
        object.__setattr__(self, "seed_save", seed_save)
        object.__setattr__(self, "runtime_save", runtime_save)

        cohort = tuple(sorted(str(item) for item in self.cohort_run_ids))
        if not cohort or len(set(cohort)) != len(cohort):
            raise ValueError("cohort_run_ids must be non-empty and unique")
        if any(not _RUN_ID_RE.fullmatch(item) for item in cohort):
            raise ValueError("cohort_run_ids contains an invalid run identifier")
        if self.run_id not in cohort:
            raise ValueError("cohort_run_ids must include run_id")
        object.__setattr__(self, "cohort_run_ids", cohort)

        if not isinstance(self.scripted, bool):
            raise TypeError("scripted must be a boolean")
        if self.scripted and self.provider.enabled:
            raise ValueError("scripted runs cannot enable a provider")
        if not isinstance(self.source_reproducible, bool):
            raise TypeError("source_reproducible must be a boolean")
        object.__setattr__(
            self,
            "runtime_classification",
            _bounded_text(
                "runtime_classification", self.runtime_classification, maximum=100
            ),
        )

    @staticmethod
    def new_nonce() -> str:
        return secrets.token_hex(16)

    @staticmethod
    def port_for_slot(*, base_port: int, slot: int, cohort_size: int) -> int:
        if isinstance(slot, bool) or isinstance(cohort_size, bool):
            raise TypeError("slot and cohort_size must be integers")
        if cohort_size <= 0 or slot < 0 or slot >= cohort_size:
            raise ValueError("slot must be within the non-empty cohort")
        port = int(base_port) + int(slot)
        if not 1 <= int(base_port) <= 65_535 or port > 65_535:
            raise ValueError("port cohort exceeds the TCP port range")
        return port

    @property
    def cohort_digest(self) -> str:
        return _sha256_payload(
            {"schema": "fortgym.m1b-cotenancy/v1", "run_ids": list(self.cohort_run_ids)}
        )

    def cotenancy(self) -> dict[str, Any]:
        peers = [item for item in self.cohort_run_ids if item != self.run_id]
        return {
            "schema": "fortgym.m1b-cotenancy/v1",
            "cohort_sha256": self.cohort_digest,
            "cohort_size": len(self.cohort_run_ids),
            "slot": self.cohort_run_ids.index(self.run_id),
            "peer_run_ids": peers,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-runtime-contract/v1",
            "run_id": self.run_id,
            "backend": self.backend,
            "model": self.model,
            "runtime": {
                "classification": self.runtime_classification,
                "source_reproducible": self.source_reproducible,
                "image_manifest_sha256": self.image_manifest_sha256,
                "image_config_sha256": self.image_config_sha256,
                "image_archive_sha256": self.image_archive_sha256,
            },
            "seed": {
                "tree_sha256": self.seed_tree_sha256,
                "world_sha256": self.seed_world_sha256,
                "seed_save": self.seed_save,
                "runtime_save": self.runtime_save,
            },
            "code_sha256": self.code_sha256,
            "rpc": {"host": "127.0.0.1", "port": self.port, "nonce": self.nonce},
            "paths": {
                "db": str(self.db_path),
                "artifacts_root": str(self.artifacts_root),
                "control_root": str(self.control_root),
                "dfroot": str(self.dfroot),
            },
            "scripted": self.scripted,
            "provider": self.provider.identity(),
            "cotenancy": self.cotenancy(),
        }

    @property
    def contract_sha256(self) -> str:
        return _sha256_payload(self.identity_payload())

    def environment_identity(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "contract_sha256": self.contract_sha256,
        }

    def _attempt_directory(self, attempt_dir: Path | str | None) -> Path:
        if attempt_dir is None:
            return self.control_root / self.run_id

        candidate = _absolute_path("attempt_dir", attempt_dir)
        if ".." in candidate.parts:
            raise ValueError("attempt_dir cannot contain path traversal")
        attempts_root = self.control_root / self.run_id / "attempts"
        try:
            relative = candidate.relative_to(attempts_root)
        except ValueError as exc:
            raise ValueError(
                "attempt_dir must be contained under the run attempts directory"
            ) from exc
        if not relative.parts:
            raise ValueError(
                "attempt_dir must identify a child of the run attempts directory"
            )
        try:
            candidate.resolve(strict=False).relative_to(
                attempts_root.resolve(strict=False)
            )
        except ValueError as exc:
            raise ValueError(
                "attempt_dir must resolve inside the run attempts directory"
            ) from exc
        return candidate

    def child_environment(
        self,
        *,
        attempt_dir: Path | str | None = None,
    ) -> dict[str, str]:
        attempt_directory = self._attempt_directory(attempt_dir)
        environment = {
            "ARTIFACTS_DIR": str(self.artifacts_root),
            "DFHACK_ENABLED": "1" if self.backend == "dfhack" else "0",
            "DFHACK_HOST": "127.0.0.1",
            "DFHACK_PORT": str(self.port),
            "DFROOT": str(self.dfroot),
            "DF_PROTO_ENABLED": "1" if self.backend == "dfhack" else "0",
            "FORT_GYM_CONTROL_DIR": str(attempt_directory),
            "FORT_GYM_DB_PATH": str(self.db_path),
            "FORT_GYM_RUN_CONTRACT_SHA256": self.contract_sha256,
            "FORT_GYM_RUN_ID": self.run_id,
            "FORT_GYM_RUN_NONCE": self.nonce,
            "FORT_GYM_SEED_SAVE": self.seed_save,
            "FORT_GYM_RUNTIME_SAVE": self.runtime_save,
            "FORT_GYM_TERMINAL_OWNER": "supervisor",
            "PYTHONPATH": _supervised_pythonpath(),
            "PYTHONUNBUFFERED": "1",
        }
        if not self.provider.enabled:
            environment["FORT_GYM_NETWORK_EVIDENCE_PATH"] = str(
                attempt_directory / "network-denials.jsonl"
            )
            if self.backend == "dfhack":
                environment.update(
                    {
                        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
                        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
                        "FORT_GYM_NETWORK_ALLOWED_PORT": str(self.port),
                    }
                )
            else:
                environment["FORT_GYM_NETWORK_POLICY"] = "deny-inet"
        if self.backend == "dfhack":
            environment.update(
                {
                    "FORT_GYM_DFHACK_TRANSPORT": "native-rpc",
                    "FORT_GYM_RUNTIME_PREPARED": "1",
                    "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256": (
                        self.image_manifest_sha256
                    ),
                    "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256": self.image_config_sha256,
                    "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256": (
                        self.image_archive_sha256
                    ),
                    "FORT_GYM_EXPECTED_SEED_TREE_SHA256": self.seed_tree_sha256,
                    "FORT_GYM_EXPECTED_SEED_WORLD_SHA256": self.seed_world_sha256,
                }
            )
        environment.update(self.provider.environment())
        return environment

    @staticmethod
    def worker_argv(
        *,
        python_executable: Path | str,
        config_path: Path | str,
        run_id: str,
    ) -> tuple[str, ...]:
        executable = _absolute_path("python_executable", python_executable)
        config = _absolute_path("config_path", config_path)
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        return (
            str(executable),
            "-m",
            "fort_gym.bench.cli",
            "experiment",
            str(config),
            "--external-run-id",
            run_id,
        )

    def to_run_spec(
        self,
        *,
        argv: Sequence[str],
        cwd: Path | str,
        attempt_dir: Path | str | None = None,
        timeout_seconds: float = 3_600.0,
        term_grace_seconds: float = 10.0,
        poll_interval_seconds: float = 0.1,
    ) -> RunSpec:
        normalized_argv = tuple(str(item) for item in argv)
        expected_pair = ("--external-run-id", self.run_id)
        if not any(
            normalized_argv[index : index + 2] == expected_pair
            for index in range(max(0, len(normalized_argv) - 1))
        ):
            raise ValueError("worker argv must bind the exact external run ID")
        attempt_directory = self._attempt_directory(attempt_dir)
        environment = self.child_environment(attempt_dir=attempt_dir)
        return RunSpec(
            run_id=self.run_id,
            argv=normalized_argv,
            artifact_dir=attempt_directory,
            cwd=_absolute_path("cwd", cwd),
            env=environment,
            env_allowlist=tuple(sorted(environment)),
            scripted=self.scripted,
            provider_enabled=self.provider.enabled,
            provider_route=self.provider.route,
            provider_model=self.provider.model,
            provider_name=self.provider.provider_name,
            max_total_tokens=(
                self.provider.max_total_tokens
                if self.provider.max_total_tokens is not None
                else 128_000
            ),
            max_cost_usd=(
                self.provider.max_cost_usd
                if self.provider.max_cost_usd is not None
                else 25.0
            ),
            timeout_seconds=timeout_seconds,
            term_grace_seconds=term_grace_seconds,
            poll_interval_seconds=poll_interval_seconds,
            trace_path=self.artifacts_root / self.run_id / "trace.jsonl",
            port=self.port if self.backend == "dfhack" else None,
            port_lock_dir=self.control_root / "port-leases",
            environment_identity=self.environment_identity(),
            cotenancy=self.cotenancy(),
            runtime_cleanup_required=True,
        )


__all__ = [
    "PreparedRuntimeIdentity",
    "PreparedRuntimeIdentityError",
    "ProviderPolicy",
    "RuntimeContract",
    "validate_prepared_runtime_environment",
]
