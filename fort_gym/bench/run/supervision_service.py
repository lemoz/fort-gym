"""API-agnostic orchestration for M1b process-supervised Fort Gym runs.

The service reserves a complete co-tenancy cohort before launch, persists a
provider-credential-free private control contract outside gameplay artifacts,
and delegates every worker to :class:`SupervisedRunManager`. It never calls
``run_once`` in the API process and never inherits an ambient provider
credential. Private control evidence contains the nonce needed for recovery and
must not be published.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..config import get_settings
from ..env.dfhack_client import DFHackClient
from ..eval.fort_eval_easy_p1 import p1_measurement_code_digest
from ..eval.protocol import validate_evaluation_protocol
from .fault_driver import (
    PRELAUNCH_ENOSPC_RECEIPT_SCHEMA,
    FaultGate,
    FaultTestAuthorization,
    OwnedRunEvidenceLoader,
    PrelaunchEnospcWorkspace,
    authorize_private_m1b_fault,
)
from .process_supervisor import (
    ProviderNetworkController,
    RunSpec,
    SupervisorError,
    validate_terminal_chain,
)
from .runtime_contract import ProviderPolicy, RuntimeContract
from .runtime_controller import (
    DockerRuntimeController,
    PreReadinessOomMonitor,
    RuntimeFaultProfile,
    RuntimeTestFault,
)
from .startup_replacement import (
    StartupReplacementDenied,
    StartupReplacementError,
    StartupReplacementLedger,
)
from .storage import RunInfo, RunRegistry
from .supervised_manager import ManagedRunResult, SupervisedRunManager

SUPERVISION_MODE = "m1b-process"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CPUSET_RE = re.compile(r"^[0-9]+(?:[-,][0-9]+)*$")
_MAX_STEPS = 20
_MAX_TICKS_PER_STEP = 200
_TERMINAL = frozenset({"completed", "failed", "stopped"})
_RUNTIME_FAULT_PROFILE_SCHEMA = "fortgym.m1b-runtime-fault-profile/v1"
_WORKSPACE_FAULT_PROFILE_SCHEMA = "fortgym.m1b-workspace-fault-profile/v1"
_ENOSPC_WORKSPACE_BYTES = 16 * 1024 * 1024
_NORMAL_RUNTIME_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
_OOM_RUNTIME_MEMORY_BYTES = 256 * 1024 * 1024
_IMAGE_MANIFEST_SHA256 = (
    "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
)
_IMAGE_CONFIG_SHA256 = (
    "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
)
_IMAGE_ARCHIVE_SHA256 = (
    "87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a"
)
_SEED_TREE_SHA256 = "49ba1de07b62e7afda93b42059b6c566598bb0f4c83d11ae1dfdb78b54cd9ec0"
_SEED_WORLD_SHA256 = "070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d"
_PINNED_MODELS = {
    "dfhack-governed-llm-glm52": "z-ai/glm-5.2",
    "dfhack-governed-llm-deepseek-v4": "deepseek/deepseek-v4-pro",
    "dfhack-governed-llm-gpt55": "openai/gpt-5.5",
    "dfhack-governed-llm-fable5": "anthropic/claude-fable-5",
    "dfhack-governed-llm-gpt56-sol": "openai/gpt-5.6-sol",
    "dfhack-governed-llm-glm5v": "z-ai/glm-5v-turbo",
    "dfhack-governed-llm-gpt55-vision": "openai/gpt-5.5",
    "dfhack-governed-llm-kimi-vision": "moonshotai/kimi-k2.7-code",
    "dfhack-governed-llm-minimax-vision": "minimax/minimax-m3",
    "dfhack-governed-llm-minimax-canary": "minimax/minimax-m3",
}


class SupervisionServiceError(RuntimeError):
    """Base error for the API-facing M1b supervision boundary."""


class SupervisionConfigurationError(SupervisionServiceError):
    """The local service lacks an exact, safe runtime configuration."""


class SupervisionRequestError(SupervisionServiceError):
    """A requested run cannot be represented by the M1b contract."""


class LaunchEvidenceError(SupervisionServiceError):
    """Persisted launch evidence is absent, malformed, or contradictory."""


class RunNotOwnedError(SupervisionServiceError):
    """A run is not owned by the M1b process supervisor."""


class ManagerLike(Protocol):
    def run(self, run_id: str) -> ManagedRunResult: ...

    def reconcile(self, run_id: str) -> ManagedRunResult: ...


class ScreenClientLike(Protocol):
    def connect(self) -> None: ...

    def get_screen(self) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ServiceConfig:
    """Immutable host and digest inputs for all service-owned contracts."""

    db_path: Path
    artifacts_root: Path
    control_root: Path
    repo_root: Path
    python_executable: Path
    entrypoint_path: Path
    dfroot: Path
    code_sha256: str
    default_seed_save: str = "seed_region3_fresh"
    runtime_save_prefix: str = "m1b"
    base_port: int = 58_000
    max_cohort: int = 8
    timeout_seconds: float = 3_600.0
    term_grace_seconds: float = 10.0
    poll_interval_seconds: float = 0.1
    image_manifest_sha256: str = _IMAGE_MANIFEST_SHA256
    image_config_sha256: str = _IMAGE_CONFIG_SHA256
    image_archive_sha256: str = _IMAGE_ARCHIVE_SHA256
    seed_tree_sha256: str = _SEED_TREE_SHA256
    seed_world_sha256: str = _SEED_WORLD_SHA256
    cpusets: Sequence[str | None] = field(default_factory=tuple)
    openrouter_api_key: str | None = field(default=None, repr=False, compare=False)
    allow_test_startup_faults: bool = False
    allow_test_runtime_fault_profiles: bool = False
    allow_test_workspace_fault_profiles: bool = False
    image_archive_path: Path | None = None
    zstd_executable: str = "zstd"

    def __post_init__(self) -> None:
        for name in (
            "db_path",
            "artifacts_root",
            "control_root",
            "repo_root",
            "entrypoint_path",
            "dfroot",
        ):
            path = Path(getattr(self, name))
            if not path.is_absolute() or "\x00" in str(path):
                raise SupervisionConfigurationError(f"{name} must be absolute")
            object.__setattr__(self, name, path.resolve(strict=False))
        python_executable = Path(self.python_executable)
        if not python_executable.is_absolute() or "\x00" in str(python_executable):
            raise SupervisionConfigurationError("python_executable must be absolute")
        # Preserve a virtualenv's interpreter symlink. Resolving it selects the
        # base interpreter and silently drops the environment's site-packages.
        object.__setattr__(self, "python_executable", python_executable.absolute())
        if _paths_overlap(self.control_root, self.artifacts_root):
            raise SupervisionConfigurationError(
                "control_root must remain separate from gameplay artifacts"
            )
        if not self.entrypoint_path.is_file():
            raise SupervisionConfigurationError(
                "entrypoint_path must name an existing regular file"
            )
        if not self.python_executable.is_file() or not os.access(
            self.python_executable, os.X_OK
        ):
            raise SupervisionConfigurationError(
                "python_executable must name an executable regular file"
            )
        if not self.repo_root.is_dir():
            raise SupervisionConfigurationError(
                "repo_root must name an existing directory"
            )
        for name in (
            "code_sha256",
            "image_manifest_sha256",
            "image_config_sha256",
            "image_archive_sha256",
            "seed_tree_sha256",
            "seed_world_sha256",
        ):
            value = str(getattr(self, name)).lower()
            if not _SHA256_RE.fullmatch(value):
                raise SupervisionConfigurationError(f"{name} must be SHA-256")
            object.__setattr__(self, name, value)
        if not _SAVE_RE.fullmatch(self.default_seed_save):
            raise SupervisionConfigurationError("default_seed_save is invalid")
        if not _SAVE_RE.fullmatch(self.runtime_save_prefix):
            raise SupervisionConfigurationError("runtime_save_prefix is invalid")
        if (
            isinstance(self.max_cohort, bool)
            or not isinstance(self.max_cohort, int)
            or not 1 <= self.max_cohort <= 64
        ):
            raise SupervisionConfigurationError("max_cohort must be 1-64")
        if isinstance(self.base_port, bool) or not isinstance(self.base_port, int):
            raise SupervisionConfigurationError("base_port must be an integer")
        if not 1 <= self.base_port <= 65_535:
            raise SupervisionConfigurationError("base_port is invalid")
        if self.base_port + self.max_cohort - 1 > 65_535:
            raise SupervisionConfigurationError("port cohort exceeds TCP range")
        for name in (
            "timeout_seconds",
            "term_grace_seconds",
            "poll_interval_seconds",
        ):
            raw_value = getattr(self, name)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise SupervisionConfigurationError(
                    f"{name} must be a finite positive number"
                )
            value = float(raw_value)
            if not math.isfinite(value) or value <= 0:
                raise SupervisionConfigurationError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        cpusets = tuple(self.cpusets)
        if len(cpusets) > self.max_cohort:
            raise SupervisionConfigurationError("cpusets exceeds max_cohort")
        if any(
            value is not None
            and (
                not isinstance(value, str)
                or not value.strip()
                or not _CPUSET_RE.fullmatch(value.strip())
            )
            for value in cpusets
        ):
            raise SupervisionConfigurationError("cpusets contains an invalid CPU set")
        cpusets = tuple(
            value.strip() if value is not None else None for value in cpusets
        )
        object.__setattr__(self, "cpusets", cpusets)
        if not isinstance(self.allow_test_startup_faults, bool):
            raise SupervisionConfigurationError(
                "allow_test_startup_faults must be a boolean"
            )
        if not isinstance(self.allow_test_runtime_fault_profiles, bool):
            raise SupervisionConfigurationError(
                "allow_test_runtime_fault_profiles must be a boolean"
            )
        if not isinstance(self.allow_test_workspace_fault_profiles, bool):
            raise SupervisionConfigurationError(
                "allow_test_workspace_fault_profiles must be a boolean"
            )
        if self.image_archive_path is not None:
            archive_path = Path(self.image_archive_path)
            if not archive_path.is_absolute() or "\x00" in str(archive_path):
                raise SupervisionConfigurationError(
                    "image_archive_path must be absolute"
                )
            archive_path = archive_path.resolve(strict=False)
            if not archive_path.is_file():
                raise SupervisionConfigurationError(
                    "image_archive_path must name an existing regular file"
                )
            object.__setattr__(self, "image_archive_path", archive_path)
        if (
            not isinstance(self.zstd_executable, str)
            or not self.zstd_executable
            or "\x00" in self.zstd_executable
        ):
            raise SupervisionConfigurationError(
                "zstd_executable must be non-empty and NUL-free"
            )
        if self.openrouter_api_key is not None and (
            not isinstance(self.openrouter_api_key, str)
            or not self.openrouter_api_key
            or self.openrouter_api_key != self.openrouter_api_key.strip()
            or "\x00" in self.openrouter_api_key
        ):
            raise SupervisionConfigurationError("dedicated OpenRouter key is malformed")

    @classmethod
    def from_environment(cls) -> ServiceConfig:
        """Build configuration without touching Docker, sockets, or providers."""

        if os.environ.get("FORT_GYM_M1B_SUPERVISION_ENABLED") != "1":
            raise SupervisionConfigurationError(
                "M1b supervision is disabled; set FORT_GYM_M1B_SUPERVISION_ENABLED=1"
            )
        settings = get_settings()
        repo_root = Path(__file__).resolve().parents[3]
        artifacts_root = Path(settings.ARTIFACTS_DIR).resolve()
        db_path = Path(
            os.environ.get(
                "FORT_GYM_DB_PATH",
                str(artifacts_root / "fort_gym.sqlite3"),
            )
        ).resolve()
        control_root = Path(
            os.environ.get(
                "FORT_GYM_M1B_CONTROL_ROOT",
                str(artifacts_root.parent / "fort-gym-m1b-control"),
            )
        ).resolve()
        cpusets_raw = os.environ.get("FORT_GYM_M1B_CPUSETS_JSON", "[]")
        try:
            cpusets_value = json.loads(cpusets_raw)
        except json.JSONDecodeError as exc:
            raise SupervisionConfigurationError(
                "FORT_GYM_M1B_CPUSETS_JSON must be JSON"
            ) from exc
        if not isinstance(cpusets_value, list) or any(
            value is not None and not isinstance(value, str) for value in cpusets_value
        ):
            raise SupervisionConfigurationError(
                "FORT_GYM_M1B_CPUSETS_JSON must be a list of strings or null"
            )
        return cls(
            db_path=db_path,
            artifacts_root=artifacts_root,
            control_root=control_root,
            repo_root=repo_root,
            python_executable=Path(sys.executable).absolute(),
            entrypoint_path=repo_root / "infra" / "m1b" / "runtime_entrypoint.sh",
            dfroot=Path(os.environ.get("DFROOT", "/opt/dwarf-fortress")),
            code_sha256=p1_measurement_code_digest(),
            default_seed_save=(
                os.environ.get("FORT_GYM_SEED_SAVE")
                or settings.FORT_GYM_SEED_SAVE
                or "seed_region3_fresh"
            ),
            runtime_save_prefix=os.environ.get(
                "FORT_GYM_M1B_RUNTIME_SAVE_PREFIX", "m1b"
            ),
            base_port=_environment_int("FORT_GYM_M1B_BASE_PORT", 58_000),
            max_cohort=_environment_int("FORT_GYM_M1B_MAX_COHORT", 8),
            cpusets=tuple(cpusets_value),
            openrouter_api_key=os.environ.get("FORT_GYM_M1B_OPENROUTER_API_KEY"),
            image_archive_path=(
                Path(os.environ["FORT_GYM_M1B_IMAGE_ARCHIVE_PATH"])
                if "FORT_GYM_M1B_IMAGE_ARCHIVE_PATH" in os.environ
                else None
            ),
            zstd_executable=os.environ.get("FORT_GYM_M1B_ZSTD_EXECUTABLE", "zstd"),
        )


@dataclass(frozen=True)
class SupervisedRunRequest:
    backend: str
    model: str
    max_steps: int
    ticks_per_step: int
    cohort_size: int = 1
    safe: bool = True
    evaluation_protocol: str | None = None
    preserve_save: bool = False
    memory_window: int = 0
    seed_save: str | None = None
    runtime_save_prefix: str | None = None
    provider_policy: ProviderPolicy | None = None


@dataclass(frozen=True)
class CohortLaunch:
    run_ids: tuple[str, ...]
    records: tuple[RunInfo, ...]


@dataclass(frozen=True)
class StartupSequenceResult:
    """One logical run and its bounded, separately owned startup attempts."""

    packet_id: str
    logical_run_id: str
    run_ids: tuple[str, ...]
    results: tuple[ManagedRunResult, ...]
    evidence_path: Path
    replacement_kind: str | None
    completed: bool


class _NoopRuntimeController:
    """Explicit lifecycle for isolated mock workers."""

    def prepare(self) -> Mapping[str, Any]:
        return {"ok": True, "backend": "mock", "runtime": "none"}

    def cleanup(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "backend": "mock",
            "runtime": "none",
            "container_absent": True,
            "listener_absent": True,
        }

    def reconcile(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "backend": "mock",
            "managed_candidates": 0,
            "removed_container_ids": [],
            "skipped_foreign_container_ids": [],
            "listener_absent": True,
            "noop": True,
            "errors": [],
        }


ManagerFactory = Callable[..., ManagerLike]
ClientFactory = Callable[..., ScreenClientLike]
ThreadFactory = Callable[..., threading.Thread]
OomMonitorFactory = Callable[[RuntimeContract, RuntimeContract], PreReadinessOomMonitor]
ProviderNetworkServiceFactory = Callable[
    [RuntimeContract, Path, Any, RunSpec], ProviderNetworkController
]


@dataclass(frozen=True)
class _EnospcPostCleanupController:
    loader: OwnedRunEvidenceLoader
    workspace: PrelaunchEnospcWorkspace
    run_id: str
    peer_run_id: str
    discard_authorization: Callable[[str], None]

    def cleanup(self) -> Mapping[str, Any]:
        self.discard_authorization(self.run_id)
        target = self.loader.load_enospc_cleanup_target(
            self.run_id,
            peer_run_id=self.peer_run_id,
        )
        return self.workspace.cleanup_workspace(target=target)

    def reconcile(self) -> Mapping[str, Any]:
        self.discard_authorization(self.run_id)
        target = self.loader.load_enospc_cleanup_target(
            self.run_id,
            peer_run_id=self.peer_run_id,
        )
        return self.workspace.reconcile_workspace(target=target)


class SupervisionService:
    """Reserve, launch, recover, and inspect process-supervised runs."""

    def __init__(
        self,
        *,
        registry: RunRegistry,
        config: ServiceConfig,
        manager_factory: ManagerFactory = SupervisedRunManager,
        client_factory: ClientFactory = DFHackClient,
        thread_factory: ThreadFactory = threading.Thread,
        pre_readiness_oom_monitor_factory: OomMonitorFactory | None = None,
        provider_network_controller_factory: ProviderNetworkServiceFactory
        | None = None,
        enospc_evidence_loader: OwnedRunEvidenceLoader | None = None,
        enospc_workspace: PrelaunchEnospcWorkspace | None = None,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        nonce_factory: Callable[[], str] = RuntimeContract.new_nonce,
    ) -> None:
        if registry.database_path != config.db_path:
            raise SupervisionConfigurationError(
                "registry database does not match the M1b service contract"
            )
        if registry.artifacts_root != config.artifacts_root:
            raise SupervisionConfigurationError(
                "registry artifact root does not match the M1b service contract"
            )
        self.registry = registry
        self.config = config
        self._manager_factory = manager_factory
        self._client_factory = client_factory
        self._thread_factory = thread_factory
        if pre_readiness_oom_monitor_factory is not None and not callable(
            pre_readiness_oom_monitor_factory
        ):
            raise TypeError("pre_readiness_oom_monitor_factory must be callable")
        self._pre_readiness_oom_monitor_factory = pre_readiness_oom_monitor_factory
        if provider_network_controller_factory is not None and not callable(
            provider_network_controller_factory
        ):
            raise TypeError("provider_network_controller_factory must be callable")
        self._provider_network_controller_factory = provider_network_controller_factory
        if (enospc_evidence_loader is None) != (enospc_workspace is None):
            raise TypeError(
                "ENOSPC evidence loader and workspace lifecycle must be supplied together"
            )
        if enospc_evidence_loader is not None:
            for name in (
                "load_prelaunch_enospc_target",
                "load_enospc_cleanup_target",
            ):
                if not callable(getattr(enospc_evidence_loader, name, None)):
                    raise TypeError(f"ENOSPC evidence loader must define {name}()")
        if enospc_workspace is not None:
            for name in (
                "prepare_workspace",
                "cleanup_workspace",
                "reconcile_workspace",
            ):
                if not callable(getattr(enospc_workspace, name, None)):
                    raise TypeError(f"ENOSPC workspace lifecycle must define {name}()")
        self._enospc_evidence_loader = enospc_evidence_loader
        self._enospc_workspace = enospc_workspace
        self._id_factory = id_factory
        self._nonce_factory = nonce_factory
        self._active: set[str] = set()
        self._active_lock = threading.Lock()
        self._enospc_authorizations: dict[str, FaultTestAuthorization] = {}
        self._enospc_preparing: set[str] = set()
        self._enospc_authorization_lock = threading.Lock()

    def reserve(self, request: SupervisedRunRequest) -> CohortLaunch:
        """Persist a complete symmetric cohort without starting a worker."""

        return self._reserve(request, test_fault=None)

    def reserve_oom_preflight_cohort(
        self, request: SupervisedRunRequest
    ) -> CohortLaunch:
        """Reserve one private two-run OOM target/normal peer test cohort.

        This capability is constructor-only: no API or ambient environment
        setting enables it.  The first returned run ID is the 256 MiB target;
        the second is the normal 4 GiB peer, and both roles are persisted in
        their private launch evidence for exact manager reconstruction.
        """

        if self.config.allow_test_runtime_fault_profiles is not True:
            raise SupervisionConfigurationError(
                "runtime fault profiles require explicit programmatic authorization"
            )
        if self._pre_readiness_oom_monitor_factory is None:
            raise SupervisionConfigurationError(
                "OOM preflight requires an explicit host monitor factory"
            )
        provider = self._validate_request(request)
        if (
            request.backend != "dfhack"
            or request.model != "dfhack-governed-scripted"
            or request.cohort_size != 2
            or provider.enabled
        ):
            raise SupervisionRequestError(
                "OOM preflight requires exactly two provider-free scripted DFHack runs"
            )
        return self._reserve(
            request,
            test_fault=None,
            runtime_fault_profiles=(RuntimeFaultProfile.OOM_256M, None),
        )

    def run_oom_preflight_cohort(
        self, request: SupervisedRunRequest
    ) -> dict[str, ManagedRunResult]:
        """Reserve and concurrently enter the OOM target and normal peer managers."""

        launch = self.reserve_oom_preflight_cohort(request)
        start_barrier = threading.Barrier(2)

        def run_one(run_id: str) -> ManagedRunResult:
            start_barrier.wait()
            return self.run_reserved(run_id)

        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="fortgym-m1b-oom-preflight",
        ) as executor:
            futures = {
                run_id: executor.submit(run_one, run_id) for run_id in launch.run_ids
            }
            return {run_id: futures[run_id].result() for run_id in launch.run_ids}

    def reserve_enospc_preflight_cohort(
        self, request: SupervisedRunRequest
    ) -> CohortLaunch:
        """Reserve one private 16 MiB target and one normal-workspace peer."""

        if self.config.allow_test_workspace_fault_profiles is not True:
            raise SupervisionConfigurationError(
                "workspace fault profiles require explicit programmatic authorization"
            )
        if self._enospc_evidence_loader is None or self._enospc_workspace is None:
            raise SupervisionConfigurationError(
                "ENOSPC preflight requires explicit evidence and workspace controls"
            )
        provider = self._validate_request(request)
        if (
            request.backend != "dfhack"
            or request.model != "dfhack-governed-scripted"
            or request.cohort_size != 2
            or provider.enabled
        ):
            raise SupervisionRequestError(
                "ENOSPC preflight requires exactly two provider-free scripted DFHack runs"
            )
        return self._reserve(
            request,
            test_fault=None,
            workspace_fault_roles=("target", "peer"),
        )

    def run_enospc_preflight_cohort(
        self, request: SupervisedRunRequest
    ) -> dict[str, ManagedRunResult]:
        """Reserve and enter the exact ENOSPC target/normal peer managers."""

        launch = self.reserve_enospc_preflight_cohort(request)
        self.prepare_enospc_preflight_target(launch.run_ids[0])
        start_barrier = threading.Barrier(2)

        def run_one(run_id: str) -> ManagedRunResult:
            start_barrier.wait()
            return self.run_reserved(run_id)

        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="fortgym-m1b-enospc-preflight",
        ) as executor:
            futures = {
                run_id: executor.submit(run_one, run_id) for run_id in launch.run_ids
            }
            return {run_id: futures[run_id].result() for run_id in launch.run_ids}

    def _reserve(
        self,
        request: SupervisedRunRequest,
        *,
        test_fault: RuntimeTestFault | None,
        run_ids: Sequence[str] | None = None,
        runtime_fault_profiles: Sequence[RuntimeFaultProfile | None] | None = None,
        workspace_fault_roles: Sequence[str] | None = None,
    ) -> CohortLaunch:
        """Internal reservation seam for explicitly authorized fault preflights."""

        provider = self._validate_request(request)
        if test_fault is not None:
            if self.config.allow_test_startup_faults is not True:
                raise SupervisionConfigurationError(
                    "test startup faults are disabled in this service"
                )
            if (
                request.backend != "dfhack"
                or request.model != "dfhack-governed-scripted"
                or provider.enabled
                or request.cohort_size != 1
            ):
                raise SupervisionRequestError(
                    "test startup faults require one provider-free scripted DFHack run"
                )
        profile_cohort = runtime_fault_profiles is not None
        if runtime_fault_profiles is None:
            selected_profiles: tuple[RuntimeFaultProfile | None, ...] = (
                None,
            ) * request.cohort_size
        else:
            selected_profiles = tuple(runtime_fault_profiles)
            if self.config.allow_test_runtime_fault_profiles is not True:
                raise SupervisionConfigurationError(
                    "runtime fault profiles require explicit programmatic authorization"
                )
            if (
                selected_profiles != (RuntimeFaultProfile.OOM_256M, None)
                or request.backend != "dfhack"
                or request.model != "dfhack-governed-scripted"
                or request.cohort_size != 2
                or provider.enabled
            ):
                raise SupervisionRequestError(
                    "runtime fault profile cohort must be one OOM target and one normal peer"
                )
        workspace_profile_cohort = workspace_fault_roles is not None
        if workspace_fault_roles is None:
            selected_workspace_roles: tuple[str | None, ...] = (
                None,
            ) * request.cohort_size
        else:
            selected_workspace_roles = tuple(workspace_fault_roles)
            if self.config.allow_test_workspace_fault_profiles is not True:
                raise SupervisionConfigurationError(
                    "workspace fault profiles require explicit programmatic authorization"
                )
            if (
                selected_workspace_roles != ("target", "peer")
                or runtime_fault_profiles is not None
                or test_fault is not None
                or request.backend != "dfhack"
                or request.model != "dfhack-governed-scripted"
                or request.cohort_size != 2
                or provider.enabled
            ):
                raise SupervisionRequestError(
                    "workspace fault cohort must be one ENOSPC target and one normal peer"
                )
        if run_ids is None:
            selected_run_ids = tuple(self._new_run_ids(request.cohort_size))
        else:
            selected_run_ids = tuple(run_ids)
            if (
                len(selected_run_ids) != request.cohort_size
                or len(set(selected_run_ids)) != len(selected_run_ids)
                or any(not _RUN_ID_RE.fullmatch(run_id) for run_id in selected_run_ids)
            ):
                raise SupervisionServiceError(
                    "preallocated run IDs do not match the request cohort"
                )
            for run_id in selected_run_ids:
                if (
                    self.registry.get(run_id) is not None
                    or self._run_dir(run_id).exists()
                ):
                    raise SupervisionServiceError(f"run ID already exists: {run_id}")
        cohort_ids = tuple(sorted(selected_run_ids))
        seed_save = request.seed_save or self.config.default_seed_save
        runtime_prefix = request.runtime_save_prefix or self.config.runtime_save_prefix
        if not _SAVE_RE.fullmatch(seed_save):
            raise SupervisionRequestError("seed_save is invalid")
        if not _SAVE_RE.fullmatch(runtime_prefix) or len(runtime_prefix) > 80:
            raise SupervisionRequestError("runtime_save_prefix is invalid")

        contracts: list[RuntimeContract] = []
        configs: list[dict[str, Any]] = []
        for run_id in selected_run_ids:
            slot = cohort_ids.index(run_id)
            runtime_save = f"{runtime_prefix}-{run_id}"
            if not _SAVE_RE.fullmatch(runtime_save):
                raise SupervisionRequestError("derived runtime save name is invalid")
            contract = RuntimeContract(
                run_id=run_id,
                backend=request.backend,
                model=request.model,
                port=RuntimeContract.port_for_slot(
                    base_port=self.config.base_port,
                    slot=slot,
                    cohort_size=len(cohort_ids),
                ),
                nonce=self._nonce_factory(),
                image_manifest_sha256=self.config.image_manifest_sha256,
                image_config_sha256=self.config.image_config_sha256,
                image_archive_sha256=self.config.image_archive_sha256,
                seed_tree_sha256=self.config.seed_tree_sha256,
                seed_world_sha256=self.config.seed_world_sha256,
                code_sha256=self.config.code_sha256,
                db_path=self.config.db_path,
                artifacts_root=self.config.artifacts_root,
                control_root=self.config.control_root,
                dfroot=self.config.dfroot,
                seed_save=seed_save,
                runtime_save=runtime_save,
                cohort_run_ids=cohort_ids,
                provider=provider,
                scripted=not provider.enabled,
            )
            contracts.append(contract)
            configs.append(self._experiment_config(request, contract))

        if len({contract.nonce for contract in contracts}) != len(contracts):
            raise SupervisionServiceError("nonce factory returned duplicate identities")

        for contract, experiment, fault_profile, workspace_role in zip(
            contracts,
            configs,
            selected_profiles,
            selected_workspace_roles,
            strict=True,
        ):
            self._persist_launch(
                contract,
                request,
                experiment,
                test_fault=test_fault,
                runtime_fault_profile=fault_profile,
                profile_cohort=profile_cohort,
                workspace_fault_role=workspace_role,
                workspace_profile_cohort=workspace_profile_cohort,
            )

        records: list[RunInfo] = []
        try:
            for contract in contracts:
                record = self.registry.create(
                    backend=contract.backend,
                    model=contract.model,
                    max_steps=request.max_steps,
                    ticks_per_step=request.ticks_per_step,
                    run_id=contract.run_id,
                    preserve_save=request.preserve_save,
                    seed_save=contract.seed_save,
                    runtime_save=contract.runtime_save,
                    evaluation_protocol=request.evaluation_protocol,
                    supervision_mode=SUPERVISION_MODE,
                )
                records.append(record)
        except Exception as exc:
            now = datetime.now(UTC)
            for record in records:
                self.registry.record_cleanup_completed(record.run_id, completed_at=now)
                self.registry.record_terminal_failure(
                    record.run_id,
                    terminal_reason={
                        "code": "cohort_reservation_failed",
                        "error": _safe_error(exc),
                    },
                    step=0,
                    ended_at=now,
                )
            raise SupervisionServiceError("cohort reservation failed") from exc
        return CohortLaunch(run_ids=selected_run_ids, records=tuple(records))

    def launch_async(self, request: SupervisedRunRequest) -> CohortLaunch:
        if request.cohort_size != 1:
            raise SupervisionRequestError(
                "launch_async is single-run only; reserve cohorts for the scheduler"
            )
        launch = self.reserve(request)
        threads: list[tuple[str, threading.Thread]] = []
        try:
            for run_id in launch.run_ids:
                threads.append(
                    (
                        run_id,
                        self._thread_factory(
                            target=self._run_reserved_in_thread,
                            args=(run_id, "manager_async_preclaim_failed"),
                            name=f"m1b-run-{run_id}",
                            daemon=True,
                        ),
                    )
                )
        except Exception as exc:
            for run_id in launch.run_ids:
                self._terminalize_unstarted(run_id, exc)
            raise SupervisionServiceError(
                "failed to construct supervised manager threads"
            ) from exc

        for index, (run_id, thread) in enumerate(threads):
            try:
                thread.start()
            except Exception as exc:
                for remaining_id, _remaining_thread in threads[index:]:
                    self._terminalize_unstarted(remaining_id, exc)
                raise SupervisionServiceError(
                    f"failed to start supervised manager thread for {run_id}"
                ) from exc
        return launch

    def run_blocking(
        self, request: SupervisedRunRequest
    ) -> dict[str, ManagedRunResult]:
        if request.cohort_size != 1:
            raise SupervisionRequestError(
                "run_blocking is single-run only; reserve cohorts for the scheduler"
            )
        launch = self.reserve(request)
        run_id = launch.run_ids[0]
        return {run_id: self.run_reserved(run_id)}

    def run_with_startup_replacement(
        self, request: SupervisedRunRequest
    ) -> StartupSequenceResult:
        """Run one opt-in logical run with at most one natural startup replacement."""

        return self._run_startup_sequence(request, inject_first_rpc_timeout=False)

    def run_cold_retry_preflight(
        self, request: SupervisedRunRequest
    ) -> StartupSequenceResult:
        """Exercise the explicit test-injector rerun without spending natural budget."""

        if self.config.allow_test_startup_faults is not True:
            raise SupervisionConfigurationError(
                "COLD-RETRY requires explicit test startup fault authorization"
            )
        outcome = self._run_startup_sequence(
            request,
            inject_first_rpc_timeout=True,
        )
        first_code = outcome.results[0].reason.get("code") if outcome.results else None
        if (
            len(outcome.results) != 2
            or outcome.replacement_kind != "test_injector_invalid_rerun"
            or first_code != "rpc_readiness_timeout"
            or outcome.completed is not True
        ):
            raise StartupReplacementError(
                "COLD-RETRY did not produce one injected timeout and one completion; "
                f"see {outcome.evidence_path}"
            )
        return outcome

    def _run_startup_sequence(
        self,
        request: SupervisedRunRequest,
        *,
        inject_first_rpc_timeout: bool,
    ) -> StartupSequenceResult:
        if request.cohort_size != 1:
            raise SupervisionRequestError("startup replacement is single-run only")
        if request.backend != "dfhack":
            raise SupervisionRequestError(
                "startup replacement requires a DFHack runtime"
            )
        test_fault = (
            RuntimeTestFault.SUPPRESS_RPC_READINESS
            if inject_first_rpc_timeout
            else None
        )
        launch = self._reserve(request, test_fault=test_fault)
        logical_run_id = launch.run_ids[0]
        evidence_path = (
            self.config.control_root
            / "_startup-replacements"
            / f"{logical_run_id}.jsonl"
        )
        ledger = StartupReplacementLedger(
            evidence_path,
            packet_id=logical_run_id,
            cohort_size=request.cohort_size,
        )
        ledger.append(
            "packet_started",
            logical_run_id=logical_run_id,
            injected_preflight=inject_first_rpc_timeout,
            maximum_natural_replacements_per_logical_run=1,
            maximum_test_injector_reruns=1,
        )

        try:
            first_result = self.run_reserved(logical_run_id)
            first_evidence = self._startup_attempt_evidence(
                logical_run_id,
                first_result,
            )
        except Exception as exc:
            ledger.append(
                "packet_failed",
                logical_run_id=logical_run_id,
                stage="first_attempt_execution_or_evidence",
                error_type=type(exc).__name__,
                maximum_additional_attempts=0,
            )
            raise
        ledger.append("attempt_terminal", attempt_index=1, **first_evidence)
        results = [first_result]
        run_ids = [logical_run_id]
        replacement_kind: str | None = None

        if first_result.status != "completed":
            requested_kind = (
                "test_injector_invalid_rerun"
                if inject_first_rpc_timeout
                else "natural_startup"
            )
            try:
                ledger.authorize(
                    kind=requested_kind,
                    logical_run_id=logical_run_id,
                    source_run_id=logical_run_id,
                    terminal_code=str(first_evidence["terminal_code"]),
                    injected=bool(first_evidence["injected"]),
                    harness_started=bool(first_evidence["harness_started"]),
                    cleanup_verified=bool(first_evidence["cleanup_verified"]),
                )
            except StartupReplacementDenied as exc:
                ledger.append(
                    "replacement_denied",
                    logical_run_id=logical_run_id,
                    source_run_id=logical_run_id,
                    requested_kind=requested_kind,
                    terminal_code=first_evidence["terminal_code"],
                    reason=str(exc),
                )
            else:
                replacement_kind = requested_kind
                replacement_run_id: str | None = None
                stage = "replacement_identity_allocation"
                try:
                    replacement_run_id = self._new_run_ids(1)[0]
                    stage = "replacement_reservation"
                    replacement = self._reserve(
                        request,
                        test_fault=None,
                        run_ids=(replacement_run_id,),
                    )
                    if replacement.run_ids != (replacement_run_id,):
                        raise StartupReplacementError(
                            "replacement reservation changed the preallocated run ID"
                        )
                    stage = "replacement_identity_validation"
                    replacement_contract = self._load_contract(replacement_run_id)
                    first_contract = self._load_contract(logical_run_id)
                    fresh_identity = self._fresh_replacement_identity(
                        first_contract,
                        replacement_contract,
                        first_evidence,
                    )
                    ledger.append(
                        "replacement_reserved",
                        logical_run_id=logical_run_id,
                        source_run_id=logical_run_id,
                        replacement_run_id=replacement_run_id,
                        kind=requested_kind,
                        fresh_identity=fresh_identity,
                    )
                    stage = "replacement_execution"
                    replacement_result = self.run_reserved(replacement_run_id)
                    stage = "replacement_evidence_validation"
                    replacement_evidence = self._startup_attempt_evidence(
                        replacement_run_id,
                        replacement_result,
                    )
                    self._assert_fresh_replacement_attempts(
                        first_evidence,
                        replacement_evidence,
                    )
                    ledger.append(
                        "attempt_terminal",
                        attempt_index=2,
                        logical_run_id=logical_run_id,
                        **replacement_evidence,
                    )
                except Exception as exc:
                    disposition = self._abort_pending_replacement(
                        replacement_run_id,
                        stage=stage,
                    )
                    ledger.append(
                        "replacement_failed",
                        logical_run_id=logical_run_id,
                        source_run_id=logical_run_id,
                        replacement_run_id=replacement_run_id,
                        kind=requested_kind,
                        stage=stage,
                        error_type=type(exc).__name__,
                        pending_row_disposition=disposition,
                        maximum_additional_attempts=0,
                    )
                    ledger.append(
                        "packet_failed",
                        logical_run_id=logical_run_id,
                        stage=stage,
                        error_type=type(exc).__name__,
                        maximum_additional_attempts=0,
                    )
                    raise
                if replacement_result.status != "completed":
                    ledger.append(
                        "replacement_cap_enforced",
                        logical_run_id=logical_run_id,
                        source_run_id=replacement_run_id,
                        maximum_additional_attempts=0,
                    )
                results.append(replacement_result)
                run_ids.append(replacement_run_id)

        completed = results[-1].status == "completed"
        ledger.append(
            "packet_completed",
            logical_run_id=logical_run_id,
            run_ids=run_ids,
            replacement_kind=replacement_kind,
            completed=completed,
        )
        return StartupSequenceResult(
            packet_id=logical_run_id,
            logical_run_id=logical_run_id,
            run_ids=tuple(run_ids),
            results=tuple(results),
            evidence_path=evidence_path,
            replacement_kind=replacement_kind,
            completed=completed,
        )

    def _abort_pending_replacement(
        self,
        run_id: str | None,
        *,
        stage: str,
    ) -> str:
        """Prevent an authorized-but-unstarted replacement row from stranding."""

        if run_id is None:
            return "identity_not_allocated"
        record = self.registry.get(run_id)
        if record is None:
            return "registry_row_not_created"
        if record.status in _TERMINAL:
            return f"already_terminal_{record.status}"
        if record.status == "pending" and not self._has_attempt(run_id):
            try:
                self._terminalize_unstarted(
                    run_id,
                    StartupReplacementError(f"replacement aborted at {stage}"),
                    code="startup_replacement_aborted",
                )
            except Exception as exc:  # noqa: BLE001 - preserve the triggering failure
                return f"pending_terminalization_failed_{type(exc).__name__}"
            terminal = self.registry.get(run_id)
            if terminal is not None and terminal.status == "failed":
                return "pending_terminalized_failed"
            return "pending_terminalization_unverified"
        return f"preserved_{record.status}_for_manager_recovery"

    def run_reserved(self, run_id: str) -> ManagedRunResult:
        self._require_owned(run_id)
        try:
            contract = self._load_contract(run_id)
        except LaunchEvidenceError as exc:
            with self._active_lock:
                active = run_id in self._active
            record = self.registry.get(run_id)
            if (
                not active
                and record is not None
                and record.status == "pending"
                and not self._has_attempt(run_id)
            ):
                self._terminalize_unstarted(
                    run_id,
                    exc,
                    code="manager_preflight_evidence_invalid",
                )
            raise
        with self._active_lock:
            if run_id in self._active:
                raise SupervisionServiceError(
                    f"run already has an active manager: {run_id}"
                )
            self._active.add(run_id)
        try:
            manager = self._manager()
            role = self._load_workspace_fault_profile(contract)
            if role == "target":
                receipt_path = self._run_dir(run_id) / "prelaunch-enospc-workspace.json"
                workspace_path = self.config.artifacts_root / run_id
                if receipt_path.exists():
                    if not self._retains_enospc_fault_authorization(contract):
                        self._reconcile_interrupted_enospc_prelaunch(contract)
                        return manager.reconcile(run_id)
                    if not workspace_path.is_dir():
                        raise LaunchEvidenceError(
                            "prepared ENOSPC target workspace is unavailable"
                        )
                if workspace_path.exists():
                    if not receipt_path.exists():
                        raise LaunchEvidenceError(
                            "ENOSPC target workspace exists without durable ownership receipt"
                        )
                else:
                    self._prepare_enospc_workspace(contract)
            return manager.run(run_id)
        finally:
            self._discard_enospc_fault_authorization(run_id)
            with self._active_lock:
                self._active.discard(run_id)

    def reconcile_all(self) -> dict[str, ManagedRunResult | str]:
        """Recover only persisted service-owned rows; restart untouched pending rows."""

        results: dict[str, ManagedRunResult | str] = {}
        for record in self.registry.list():
            if (
                record.supervision_mode != SUPERVISION_MODE
                or record.status in _TERMINAL
            ):
                continue
            # Recovery never resumes a prepared ENOSPC injection.  Invalidate
            # any same-process capability before inspecting durable state.
            self._discard_enospc_fault_authorization(record.run_id)
            try:
                contract = self._load_contract(record.run_id)
            except LaunchEvidenceError as exc:
                if record.status == "pending" and not self._has_attempt(record.run_id):
                    self._terminalize_unstarted(
                        record.run_id,
                        exc,
                        code="launch_evidence_invalid",
                    )
                    results[record.run_id] = "invalid_launch_terminalized"
                else:
                    results[record.run_id] = "launch_evidence_invalid"
                continue
            if record.status == "pending" and not self._has_attempt(record.run_id):
                role = self._load_workspace_fault_profile(contract)
                if role == "target":
                    receipt_path = (
                        self._run_dir(record.run_id) / "prelaunch-enospc-workspace.json"
                    )
                    workspace_path = self.config.artifacts_root / record.run_id
                    if receipt_path.exists():
                        self._reconcile_interrupted_enospc_prelaunch(contract)
                        results[record.run_id] = self._manager().reconcile(
                            record.run_id
                        )
                        continue
                    if workspace_path.exists():
                        results[record.run_id] = "enospc_workspace_unresolved"
                        continue
                try:
                    thread = self._thread_factory(
                        target=self._run_reserved_in_thread,
                        args=(record.run_id, "manager_recovery_preclaim_failed"),
                        name=f"m1b-recover-{record.run_id}",
                        daemon=True,
                    )
                    thread.start()
                    results[record.run_id] = "pending_restarted"
                except Exception as exc:
                    self._terminalize_unstarted(record.run_id, exc)
                    raise SupervisionServiceError(
                        f"failed to restart pending run {record.run_id}"
                    ) from exc
            else:
                results[record.run_id] = self._manager().reconcile(record.run_id)
        return results

    def prepare_enospc_preflight_target(self, run_id: str) -> None:
        """Prepare the ENOSPC target before any cohort manager can start.

        The root broker temporarily protects the shared artifacts parent while
        mounting the target workspace.  Keeping this transition serial prevents
        a peer manager from trying to create its workspace during that bounded
        protection window.  Only the same service instance retains the private
        one-shot authorization that lets ``run_reserved`` consume the receipt.
        """

        record = self._require_owned(run_id)
        contract = self._load_contract(run_id)
        if (
            record.status != "pending"
            or self._has_attempt(run_id)
            or self._load_workspace_fault_profile(contract) != "target"
        ):
            raise SupervisionServiceError(
                "ENOSPC target preparation requires an untouched pending target"
            )
        with self._active_lock:
            if run_id in self._active:
                raise SupervisionServiceError(
                    "ENOSPC target manager is already active"
                )
        receipt_path = self._run_dir(run_id) / "prelaunch-enospc-workspace.json"
        workspace_path = self.config.artifacts_root / run_id
        if receipt_path.exists() or workspace_path.exists():
            raise LaunchEvidenceError(
                "ENOSPC target preparation found pre-existing workspace evidence"
            )
        self._prepare_enospc_workspace(contract)

    def _retains_enospc_fault_authorization(
        self,
        contract: RuntimeContract,
    ) -> bool:
        peer_ids = tuple(
            run_id for run_id in contract.cohort_run_ids if run_id != contract.run_id
        )
        if len(peer_ids) != 1:
            raise LaunchEvidenceError("ENOSPC target must have one exact peer")
        with self._enospc_authorization_lock:
            authorization = self._enospc_authorizations.get(contract.run_id)
        if authorization is None:
            return False
        if (
            authorization.gate is not FaultGate.ENOSPC
            or authorization.target_run_id != contract.run_id
            or authorization.peer_run_id != peer_ids[0]
        ):
            raise LaunchEvidenceError("retained ENOSPC authorization binding differs")
        return True

    def _prepare_enospc_workspace(self, contract: RuntimeContract) -> None:
        loader = self._enospc_evidence_loader
        workspace = self._enospc_workspace
        if loader is None or workspace is None:
            raise SupervisionConfigurationError("ENOSPC host controls are unavailable")
        target = loader.load_prelaunch_enospc_target(contract.run_id)
        peer_ids = [
            run_id for run_id in contract.cohort_run_ids if run_id != contract.run_id
        ]
        if (
            len(peer_ids) != 1
            or target.run_id != contract.run_id
            or target.contract_sha256 != contract.contract_sha256
            or target.nonce != contract.nonce
            or target.cohort_sha256 != contract.cohort_digest
            or target.peer_run_id != peer_ids[0]
            or target.db_path != self.config.db_path
            or target.control_root != self.config.control_root
            or target.workspace != self.config.artifacts_root / contract.run_id
        ):
            raise LaunchEvidenceError("ENOSPC prelaunch target identity differs")
        with self._enospc_authorization_lock:
            if (
                contract.run_id in self._enospc_preparing
                or contract.run_id in self._enospc_authorizations
            ):
                raise SupervisionServiceError(
                    "ENOSPC authorization is already prepared or preparing"
                )
            self._enospc_preparing.add(contract.run_id)
        try:
            authorization = authorize_private_m1b_fault(
                test_mode=True,
                gate=FaultGate.ENOSPC,
                target_run_id=contract.run_id,
                peer_run_id=peer_ids[0],
            )
            raw_receipt = workspace.prepare_workspace(
                authorization=authorization,
                target=target,
            )
            if not isinstance(raw_receipt, Mapping):
                raise LaunchEvidenceError("ENOSPC prelaunch receipt must be a mapping")
            receipt = dict(raw_receipt)
            expected_keys = {
                "schema",
                "ok",
                "run_id",
                "contract_sha256",
                "nonce_sha256",
                "cohort_sha256",
                "peer_run_id",
                "workspace",
                "filesystem",
                "size_bytes",
                "source",
                "marker_sha256",
                "mount_argv",
                "shell",
                "prepared_before_manager",
            }
            source = f"fortgym-m1b-enospc-{contract.run_id}"
            expected_mount_argv = [
                "/bin/mount",
                "-t",
                "tmpfs",
                "-o",
                f"size={_ENOSPC_WORKSPACE_BYTES},nosuid,nodev,noexec,mode=0700",
                source,
                str(target.workspace),
            ]
            if (
                set(receipt) != expected_keys
                or receipt.get("schema") != PRELAUNCH_ENOSPC_RECEIPT_SCHEMA
                or receipt.get("ok") is not True
                or receipt.get("run_id") != contract.run_id
                or receipt.get("contract_sha256") != contract.contract_sha256
                or receipt.get("nonce_sha256")
                != hashlib.sha256(contract.nonce.encode("utf-8")).hexdigest()
                or receipt.get("cohort_sha256") != contract.cohort_digest
                or receipt.get("peer_run_id") != peer_ids[0]
                or receipt.get("workspace") != str(target.workspace)
                or receipt.get("filesystem") != "tmpfs"
                or receipt.get("size_bytes") != _ENOSPC_WORKSPACE_BYTES
                or receipt.get("source") != source
                or not isinstance(receipt.get("marker_sha256"), str)
                or not _SHA256_RE.fullmatch(str(receipt["marker_sha256"]))
                or receipt.get("mount_argv") != expected_mount_argv
                or receipt.get("shell") is not False
                or receipt.get("prepared_before_manager") is not True
            ):
                raise LaunchEvidenceError("ENOSPC prelaunch receipt is noncanonical")
            with self._enospc_authorization_lock:
                if contract.run_id not in self._enospc_preparing:
                    raise SupervisionServiceError(
                        "ENOSPC authorization was invalidated during preparation"
                    )
                if contract.run_id in self._enospc_authorizations:
                    raise SupervisionServiceError(
                        "ENOSPC authorization already exists after preparation"
                    )
                self._enospc_preparing.remove(contract.run_id)
                self._enospc_authorizations[contract.run_id] = authorization
        except BaseException:
            self._discard_enospc_fault_authorization(contract.run_id)
            raise

    def _take_enospc_fault_authorization(
        self,
        *,
        target_run_id: str,
        peer_run_id: str,
    ) -> FaultTestAuthorization:
        """Hand one prepared ENOSPC capability to a private runner exactly once.

        This deliberately private, in-memory-only seam is unavailable through
        the API, environment, launch evidence, or serialized service config.
        Popping precedes validation so a mismatched or tampered handoff cannot
        leave a reusable capability behind.
        """

        if (
            self.config.allow_test_workspace_fault_profiles is not True
            or self._enospc_evidence_loader is None
            or self._enospc_workspace is None
        ):
            raise SupervisionConfigurationError(
                "ENOSPC fault authorization is not programmatically enabled"
            )
        if (
            not isinstance(target_run_id, str)
            or not _RUN_ID_RE.fullmatch(target_run_id)
            or not isinstance(peer_run_id, str)
            or not _RUN_ID_RE.fullmatch(peer_run_id)
            or target_run_id == peer_run_id
        ):
            raise SupervisionRequestError("ENOSPC handoff run identities are invalid")
        with self._enospc_authorization_lock:
            authorization = self._enospc_authorizations.pop(target_run_id, None)
        if authorization is None:
            raise SupervisionServiceError(
                "ENOSPC fault authorization is unavailable or already handed off"
            )
        if (
            authorization.gate is not FaultGate.ENOSPC
            or authorization.target_run_id != target_run_id
            or authorization.peer_run_id != peer_run_id
        ):
            raise LaunchEvidenceError("ENOSPC fault authorization binding differs")
        contract = self._load_contract(target_run_id)
        peers = tuple(
            run_id for run_id in contract.cohort_run_ids if run_id != target_run_id
        )
        if self._load_workspace_fault_profile(contract) != "target" or peers != (
            peer_run_id,
        ):
            # The mapping entry was already removed.  Never restore a token
            # after contradictory durable evidence or a failed verification.
            raise LaunchEvidenceError(
                "ENOSPC handoff does not match the persisted target cohort"
            )
        return authorization

    def _discard_enospc_fault_authorization(self, run_id: str) -> None:
        """Forget any private setup capability without exposing its presence."""

        with self._enospc_authorization_lock:
            self._enospc_authorizations.pop(run_id, None)
            self._enospc_preparing.discard(run_id)

    def _reconcile_interrupted_enospc_prelaunch(
        self,
        contract: RuntimeContract,
    ) -> None:
        self._discard_enospc_fault_authorization(contract.run_id)
        controller = self._enospc_post_cleanup_controller(
            self._require_owned(contract.run_id),
            self._run_dir(contract.run_id),
        )
        if controller is None:
            raise LaunchEvidenceError("ENOSPC target cleanup controller is missing")
        result = controller.reconcile()
        if (
            not isinstance(result, Mapping)
            or result.get("run_id") != contract.run_id
            or result.get("residue_absent") is not True
        ):
            raise LaunchEvidenceError(
                "interrupted ENOSPC prelaunch cleanup did not prove residue absence"
            )
        self._terminalize_unstarted(
            contract.run_id,
            SupervisionServiceError(
                "interrupted ENOSPC prelaunch workspace was reconciled without resume"
            ),
            code="enospc_prelaunch_owner_lost",
        )

    def owns_run(self, run_id: str) -> bool:
        record = self.registry.get(run_id)
        return bool(record and record.supervision_mode == SUPERVISION_MODE)

    def _run_reserved_in_thread(self, run_id: str, failure_code: str) -> None:
        """Prevent an asynchronous pre-claim failure from stranding a row."""

        try:
            self.run_reserved(run_id)
        except BaseException as exc:  # noqa: BLE001 - terminalize async failures
            with self._active_lock:
                active = run_id in self._active
            record = self.registry.get(run_id)
            if (
                not active
                and record is not None
                and record.status == "pending"
                and not self._has_attempt(run_id)
            ):
                self._terminalize_unstarted(run_id, exc, code=failure_code)

    def terminalize_unstarted(
        self,
        run_id: str,
        exc: BaseException,
        *,
        code: str = "manager_thread_start_failed",
    ) -> None:
        """Finalize one reserved row whose manager process never started."""

        self._terminalize_unstarted(run_id, exc, code=code)

    def environment_identity(self, run_id: str) -> dict[str, Any]:
        self._require_owned(run_id)
        identity = self._load_contract(run_id).environment_identity()
        rpc = identity.get("rpc")
        if isinstance(rpc, dict):
            rpc.pop("nonce", None)
            rpc["nonce_attested"] = True
        return identity

    def capture_screen(self, run_id: str) -> dict[str, Any]:
        record = self._require_owned(run_id)
        if record.backend != "dfhack" or record.status not in {"running", "paused"}:
            raise SupervisionRequestError(
                "run-scoped screenshot requires an active DFHack run"
            )
        contract = self._load_contract(run_id)
        client = self._client_factory(
            host="127.0.0.1",
            port=contract.port,
            retries=1,
            expected_run_id=contract.run_id,
            expected_nonce=contract.nonce,
            expected_contract_sha256=contract.contract_sha256,
            expected_seed_tree_sha256=contract.seed_tree_sha256,
            expected_seed_world_sha256=contract.seed_world_sha256,
            expected_image_manifest_sha256=contract.image_manifest_sha256,
            expected_image_config_sha256=contract.image_config_sha256,
            expected_image_archive_sha256=contract.image_archive_sha256,
        )
        try:
            client.connect()
            screen = client.get_screen()
            if not isinstance(screen, Mapping):
                raise SupervisionServiceError("DFHack screenshot was not a mapping")
            return dict(screen)
        finally:
            client.close()

    def _manager(self) -> ManagerLike:
        kwargs: dict[str, Any] = {
            "registry": self.registry,
            "control_root": self.config.control_root,
            "runtime_controller_factory": self._runtime_controller,
            "contract_factory": self._run_spec,
        }
        if self._provider_network_controller_factory is not None:
            kwargs["provider_network_controller_factory"] = (
                self._provider_network_controller
            )
        if self._enospc_evidence_loader is not None:
            kwargs["post_cleanup_controller_factory"] = (
                self._enospc_post_cleanup_controller
            )
        return self._manager_factory(**kwargs)

    def _enospc_post_cleanup_controller(
        self,
        record: RunInfo,
        run_dir: Path,
    ) -> _EnospcPostCleanupController | None:
        loader = self._enospc_evidence_loader
        workspace = self._enospc_workspace
        if loader is None or workspace is None:
            raise SupervisionConfigurationError("ENOSPC host controls are unavailable")
        contract = self._load_contract(record.run_id)
        role = self._load_workspace_fault_profile(contract)
        if role != "target":
            return None
        if run_dir.resolve() != (self.config.control_root / record.run_id).resolve():
            raise SupervisionConfigurationError(
                "ENOSPC post-cleanup control directory differs"
            )
        peer_ids = [
            run_id for run_id in contract.cohort_run_ids if run_id != record.run_id
        ]
        if len(peer_ids) != 1:
            raise LaunchEvidenceError("ENOSPC target must have one exact peer")
        return _EnospcPostCleanupController(
            loader=loader,
            workspace=workspace,
            run_id=record.run_id,
            peer_run_id=peer_ids[0],
            discard_authorization=self._discard_enospc_fault_authorization,
        )

    def _provider_network_controller(
        self,
        record: RunInfo,
        run_dir: Path,
        runtime_controller: Any,
        spec: RunSpec,
    ) -> ProviderNetworkController:
        """Reconstruct the explicit host control for launch and recovery.

        This seam is constructor-only. ``ServiceConfig.from_environment`` and
        the API server cannot enable it, and the nonce remains inside the
        private ``RuntimeContract``/controller rather than public identity.
        """

        factory = self._provider_network_controller_factory
        if factory is None:
            raise SupervisionConfigurationError(
                "provider-network controller was not programmatically authorized"
            )
        contract = self._load_contract(record.run_id)
        if (
            record.supervision_mode != SUPERVISION_MODE
            or contract.backend != "dfhack"
            or contract.model != "dfhack-governed-scripted"
            or contract.provider.enabled
            or not contract.scripted
            or spec.run_id != contract.run_id
            or run_dir.resolve() != (self.config.control_root / record.run_id).resolve()
        ):
            raise SupervisionConfigurationError(
                "provider-network control requires an exact provider-free scripted DFHack run"
            )
        controller = factory(contract, run_dir, runtime_controller, spec)
        if controller is None:
            raise SupervisionConfigurationError(
                "provider-network controller factory returned no controller"
            )
        return controller

    def _runtime_controller(self, record: RunInfo, run_dir: Path) -> Any:
        contract = self._load_contract(record.run_id)
        if contract.backend == "mock":
            return _NoopRuntimeController()
        test_fault = self._load_test_fault(record.run_id)
        fault_profile = self._load_runtime_fault_profile(contract)
        if test_fault is not None and fault_profile is not None:
            raise LaunchEvidenceError(
                "startup fault and runtime fault profile cannot be combined"
            )
        slot = contract.cotenancy()["slot"]
        cpuset = self.config.cpusets[slot] if slot < len(self.config.cpusets) else None
        oom_monitor: PreReadinessOomMonitor | None = None
        if fault_profile is RuntimeFaultProfile.OOM_256M:
            if self._pre_readiness_oom_monitor_factory is None:
                raise SupervisionConfigurationError(
                    "OOM target recovery requires an explicit host monitor factory"
                )
            peer_ids = [
                run_id
                for run_id in contract.cohort_run_ids
                if run_id != contract.run_id
            ]
            if len(peer_ids) != 1:
                raise LaunchEvidenceError("OOM target must have one exact peer")
            peer_contract = self._load_contract(peer_ids[0])
            oom_monitor = self._pre_readiness_oom_monitor_factory(
                contract,
                peer_contract,
            )
            if oom_monitor is None:
                raise SupervisionConfigurationError(
                    "OOM host monitor factory returned no monitor"
                )
        return DockerRuntimeController(
            contract,
            entrypoint_path=self.config.entrypoint_path,
            evidence_dir=run_dir / "attempts" / "attempt-0001" / "runtime",
            cpuset_cpus=cpuset,
            image_archive_path=self.config.image_archive_path,
            zstd_executable=self.config.zstd_executable,
            allow_test_faults=self.config.allow_test_startup_faults,
            test_fault=test_fault,
            allow_test_fault_profile=self.config.allow_test_runtime_fault_profiles,
            fault_profile=fault_profile,
            pre_readiness_oom_monitor=oom_monitor,
        )

    def _run_spec(self, record: RunInfo, attempt_dir: Path, _controller: Any) -> Any:
        contract = self._load_contract(record.run_id)
        config_path = self._run_dir(record.run_id) / "experiment.json"
        argv = RuntimeContract.worker_argv(
            python_executable=self.config.python_executable,
            config_path=config_path,
            run_id=record.run_id,
        )
        return contract.to_run_spec(
            argv=argv,
            cwd=self.config.repo_root,
            attempt_dir=attempt_dir,
            timeout_seconds=self.config.timeout_seconds,
            term_grace_seconds=self.config.term_grace_seconds,
            poll_interval_seconds=self.config.poll_interval_seconds,
        )

    def _startup_attempt_evidence(
        self,
        run_id: str,
        result: ManagedRunResult,
    ) -> dict[str, Any]:
        """Validate one terminal attempt before it can authorize another."""

        run_dir = self._run_dir(run_id)
        attempt_dir = run_dir / "attempts" / "attempt-0001"
        if (
            result.run_id != run_id
            or result.control_dir.resolve() != run_dir.resolve()
            or result.finalized is not True
            or result.status not in _TERMINAL
        ):
            raise StartupReplacementError("manager result identity is not terminal")
        record = self._require_owned(run_id)
        if (
            record.status != result.status
            or record.ended_at is None
            or "cleanup_completed_at" not in record.metadata
        ):
            raise StartupReplacementError(
                "registry terminal or cleanup evidence is incomplete"
            )

        terminal = _read_mapping(attempt_dir / "terminal.json")
        manager_terminal = _read_mapping(run_dir / "manager-terminal.json")
        if (
            terminal.get("schema") != "fortgym.process-supervisor-terminal/v1"
            or terminal.get("run_id") != run_id
            or manager_terminal.get("schema")
            != "fortgym.supervised-manager-terminal/v1"
            or manager_terminal.get("run_id") != run_id
            or manager_terminal.get("status") != result.status
        ):
            raise StartupReplacementError("terminal evidence identity differs")
        manager_reason = manager_terminal.get("reason")
        terminal_reason = terminal.get("reason")
        if not isinstance(manager_reason, Mapping) or not isinstance(
            terminal_reason, Mapping
        ):
            raise StartupReplacementError("terminal reason evidence is missing")
        result_code = result.reason.get("code")
        if (
            not isinstance(result_code, str)
            or manager_reason.get("code") != result_code
        ):
            raise StartupReplacementError("manager terminal reason is contradictory")
        if result.status != "completed" and terminal_reason.get("code") != result_code:
            raise StartupReplacementError("supervisor terminal reason is contradictory")

        cleanup = terminal.get("cleanup")
        if not isinstance(cleanup, Mapping) or cleanup.get("ok") is not True:
            raise StartupReplacementError("replacement requires successful cleanup")
        try:
            validate_terminal_chain(
                attempt_dir,
                terminal,
                run_id=run_id,
                require_cleanup_success=True,
            )
        except (OSError, SupervisorError) as exc:
            raise StartupReplacementError(
                "replacement requires the exact terminal chain"
            ) from exc
        stages = cleanup.get("stages")
        if not isinstance(stages, list) or any(
            not isinstance(stage, Mapping) for stage in stages
        ):
            raise StartupReplacementError("cleanup stage evidence is malformed")
        port_stages = [stage for stage in stages if stage.get("stage") == "port_lease"]
        callback_stages = [
            stage for stage in stages if stage.get("stage") == "callback"
        ]
        if (
            len(port_stages) != 1
            or port_stages[0].get("ok") is not True
            or len(callback_stages) != 1
            or callback_stages[0].get("ok") is not True
        ):
            raise StartupReplacementError(
                "runtime cleanup or lease release is not verified"
            )
        callback_details = callback_stages[0].get("details")
        if (
            not isinstance(callback_details, Mapping)
            or callback_details.get("ok") is not True
            or callback_details.get("container_absent") is not True
            or callback_details.get("listener_absent") is not True
        ):
            raise StartupReplacementError(
                "runtime container/listener absence is not verified"
            )

        attempt_records = _read_jsonl(attempt_dir / "attempt-journal.jsonl")
        attempt_events = [row["event"] for row in attempt_records]
        manager_records = _read_jsonl(run_dir / "manager-journal.jsonl")
        manager_events = [row["event"] for row in manager_records]
        if (
            attempt_events.count("port_leased") != 1
            or attempt_events.count("cleanup_recorded") != 1
            or attempt_events.count("terminal_pending") != 1
            or attempt_events.index("cleanup_recorded")
            > attempt_events.index("terminal_pending")
            or manager_events.count("cleanup_completion_recorded") != 1
            or manager_events.count("registry_terminal_recorded") != 1
            or manager_events.index("cleanup_completion_recorded")
            > manager_events.index("registry_terminal_recorded")
        ):
            raise StartupReplacementError(
                "cleanup-to-terminal journal order is incomplete"
            )
        harness_started = "child_started" in attempt_events
        injected_fault = self._load_test_fault(run_id)
        injected = False
        contract = self._load_contract(run_id)
        if result_code in {
            "container_create_failure",
            "rpc_readiness_timeout",
            "map_readiness_timeout",
        }:
            startup_terminal = _read_mapping(
                attempt_dir / "runtime" / "startup-terminal.json"
            )
            marker_injected = startup_terminal.get("injected")
            if not isinstance(marker_injected, bool):
                raise StartupReplacementError(
                    "startup timeout injection evidence is malformed"
                )
            injected = marker_injected
            expected_startup = {
                "schema": "fortgym.m1b-startup-terminal/v1",
                "run_id": run_id,
                "contract_sha256": contract.contract_sha256,
                "terminal_code": result_code,
                "injected": marker_injected,
            }
            if startup_terminal != expected_startup:
                raise StartupReplacementError(
                    "startup timeout evidence is noncanonical"
                )
            if marker_injected and (
                injected_fault is not RuntimeTestFault.SUPPRESS_RPC_READINESS
                or result_code != "rpc_readiness_timeout"
            ):
                raise StartupReplacementError(
                    "startup injection evidence is not authorized"
                )
        if not harness_started and terminal.get("child_pid") is not None:
            raise StartupReplacementError(
                "pre-harness terminal unexpectedly records a child PID"
            )

        return {
            "run_id": run_id,
            "status": result.status,
            "terminal_code": result_code,
            "injected": injected,
            "harness_started": harness_started,
            "cleanup_verified": True,
            "lease_lifecycle": {
                "port": contract.port,
                "acquired": True,
                "released": True,
            },
            "identity": {
                "contract_sha256": contract.contract_sha256,
                "nonce_sha256": hashlib.sha256(contract.nonce.encode()).hexdigest(),
                "runtime_save": contract.runtime_save,
                "container_name": (
                    f"fortgym-m1b-{run_id}-{contract.contract_sha256[:12]}"
                ),
                "control_dir": str(run_dir),
                "artifact_dir": str(contract.artifacts_root / run_id),
            },
        }

    @staticmethod
    def _fresh_replacement_identity(
        first: RuntimeContract,
        replacement: RuntimeContract,
        first_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        first_identity = first_evidence.get("identity")
        if not isinstance(first_identity, Mapping):
            raise StartupReplacementError("first attempt identity evidence is missing")
        replacement_container = (
            f"fortgym-m1b-{replacement.run_id}-{replacement.contract_sha256[:12]}"
        )
        checks = {
            "run_id": first.run_id != replacement.run_id,
            "nonce": first.nonce != replacement.nonce,
            "contract_sha256": (first.contract_sha256 != replacement.contract_sha256),
            "runtime_save": first.runtime_save != replacement.runtime_save,
            "container_name": (
                first_identity.get("container_name") != replacement_container
            ),
            "control_dir": (
                first.control_root / first.run_id
                != replacement.control_root / replacement.run_id
            ),
            "artifact_dir": (
                first.artifacts_root / first.run_id
                != replacement.artifacts_root / replacement.run_id
            ),
        }
        if not all(checks.values()):
            failed = sorted(name for name, ok in checks.items() if not ok)
            raise StartupReplacementError(
                f"replacement identity is not fresh: {', '.join(failed)}"
            )
        return {
            "all_distinct": True,
            "fields": checks,
            "replacement_contract_sha256": replacement.contract_sha256,
            "replacement_nonce_sha256": hashlib.sha256(
                replacement.nonce.encode()
            ).hexdigest(),
            "replacement_runtime_save": replacement.runtime_save,
            "replacement_container_name": replacement_container,
            "replacement_control_dir": str(
                replacement.control_root / replacement.run_id
            ),
            "replacement_artifact_dir": str(
                replacement.artifacts_root / replacement.run_id
            ),
        }

    @staticmethod
    def _assert_fresh_replacement_attempts(
        first: Mapping[str, Any], replacement: Mapping[str, Any]
    ) -> None:
        first_identity = first.get("identity")
        replacement_identity = replacement.get("identity")
        if not isinstance(first_identity, Mapping) or not isinstance(
            replacement_identity, Mapping
        ):
            raise StartupReplacementError("replacement identity evidence is missing")
        for field_name in (
            "contract_sha256",
            "nonce_sha256",
            "runtime_save",
            "container_name",
            "control_dir",
            "artifact_dir",
        ):
            if first_identity.get(field_name) == replacement_identity.get(field_name):
                raise StartupReplacementError(
                    f"replacement attempt reused {field_name}"
                )
        first_lease = first.get("lease_lifecycle")
        replacement_lease = replacement.get("lease_lifecycle")
        for lease in (first_lease, replacement_lease):
            if (
                not isinstance(lease, Mapping)
                or lease.get("acquired") is not True
                or lease.get("released") is not True
            ):
                raise StartupReplacementError(
                    "replacement attempt lacks a fresh lease lifecycle"
                )

    def _validate_request(self, request: SupervisedRunRequest) -> ProviderPolicy:
        if request.safe is not True:
            raise SupervisionRequestError("M1b requires safe=True")
        if request.preserve_save is not False:
            raise SupervisionRequestError("M1b requires preserve_save=False")
        for name, value in (
            ("max_steps", request.max_steps),
            ("ticks_per_step", request.ticks_per_step),
            ("cohort_size", request.cohort_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SupervisionRequestError(f"{name} must be a positive integer")
        if request.max_steps > _MAX_STEPS:
            raise SupervisionRequestError(
                f"max_steps exceeds the frozen M1b limit of {_MAX_STEPS}"
            )
        if request.ticks_per_step > _MAX_TICKS_PER_STEP:
            raise SupervisionRequestError(
                f"ticks_per_step exceeds the frozen M1b limit of {_MAX_TICKS_PER_STEP}"
            )
        if request.cohort_size > self.config.max_cohort:
            raise SupervisionRequestError("cohort exceeds configured M1b capacity")
        if (
            isinstance(request.memory_window, bool)
            or not isinstance(request.memory_window, int)
            or request.memory_window != 0
        ):
            raise SupervisionRequestError("M1b requires memory_window=0")
        try:
            validate_evaluation_protocol(request.evaluation_protocol)
        except ValueError as exc:
            raise SupervisionRequestError(str(exc)) from exc
        if request.seed_save is not None and not isinstance(request.seed_save, str):
            raise SupervisionRequestError("seed_save must be a string")
        if request.runtime_save_prefix is not None and not isinstance(
            request.runtime_save_prefix, str
        ):
            raise SupervisionRequestError("runtime_save_prefix must be a string")
        if request.provider_policy is not None and not isinstance(
            request.provider_policy, ProviderPolicy
        ):
            raise SupervisionRequestError("provider_policy must be a ProviderPolicy")
        provider = request.provider_policy or ProviderPolicy()
        if self._provider_network_controller_factory is not None and (
            request.backend != "dfhack"
            or request.model != "dfhack-governed-scripted"
            or provider.enabled
        ):
            raise SupervisionRequestError(
                "provider-network service accepts only provider-free scripted DFHack runs"
            )
        if request.backend == "mock":
            if request.model not in {"random", "fake"} or provider.enabled:
                raise SupervisionRequestError(
                    "mock supervision supports only provider-free random/fake agents"
                )
            return provider
        if request.backend != "dfhack":
            raise SupervisionRequestError("unsupported backend")
        if request.model == "dfhack-governed-scripted":
            if provider.enabled:
                raise SupervisionRequestError(
                    "scripted DFHack runs cannot use a provider"
                )
            return provider
        if (
            request.model != "dfhack-governed-llm"
            and request.model not in _PINNED_MODELS
        ):
            raise SupervisionRequestError(
                "M1b DFHack supports only governed scripted or governed LLM agents"
            )
        if not provider.enabled:
            raise SupervisionRequestError(
                "governed LLM runs require an explicit provider policy"
            )
        if not self.config.openrouter_api_key:
            raise SupervisionConfigurationError(
                "dedicated FORT_GYM_M1B_OPENROUTER_API_KEY is unavailable"
            )
        if provider.api_key != self.config.openrouter_api_key:
            raise SupervisionRequestError(
                "provider policy must use the dedicated M1b credential"
            )
        pinned = _PINNED_MODELS.get(request.model)
        if pinned is not None and provider.model != pinned:
            raise SupervisionRequestError(
                f"{request.model} requires provider model {pinned}"
            )
        return provider

    def _new_run_ids(self, count: int) -> list[str]:
        run_ids = [str(self._id_factory()) for _ in range(count)]
        if len(set(run_ids)) != len(run_ids) or any(
            not _RUN_ID_RE.fullmatch(run_id) for run_id in run_ids
        ):
            raise SupervisionServiceError("run ID factory returned invalid IDs")
        for run_id in run_ids:
            if self.registry.get(run_id) is not None or self._run_dir(run_id).exists():
                raise SupervisionServiceError(f"run ID already exists: {run_id}")
        return run_ids

    def _persist_launch(
        self,
        contract: RuntimeContract,
        request: SupervisedRunRequest,
        experiment: Mapping[str, Any],
        *,
        test_fault: RuntimeTestFault | None,
        runtime_fault_profile: RuntimeFaultProfile | None,
        profile_cohort: bool,
        workspace_fault_role: str | None,
        workspace_profile_cohort: bool,
    ) -> None:
        run_dir = self._run_dir(contract.run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        launch = {
            "schema": "fortgym.m1b-service-launch/v1",
            "run_id": contract.run_id,
            "created_at": _utc_now(),
            "contract": contract.environment_identity(),
            "request": {
                "max_steps": request.max_steps,
                "ticks_per_step": request.ticks_per_step,
                "evaluation_protocol": request.evaluation_protocol,
                "preserve_save": request.preserve_save,
                "memory_window": request.memory_window,
                "safe": request.safe,
            },
        }
        if test_fault is not None:
            launch["test_fault"] = {
                "schema": "fortgym.m1b-test-startup-fault/v1",
                "name": test_fault.value,
                "injected": True,
                "attempt_index": 1,
            }
        if profile_cohort:
            launch["runtime_fault_profile"] = self._runtime_fault_profile_identity(
                runtime_fault_profile
            )
        if workspace_profile_cohort:
            if workspace_fault_role is None:
                raise SupervisionConfigurationError(
                    "workspace fault cohort role is missing"
                )
            launch["workspace_fault_profile"] = self._workspace_fault_profile_identity(
                workspace_fault_role
            )
        _write_once_json(run_dir / "launch.json", launch)
        _write_once_json(run_dir / "experiment.json", experiment)

    @staticmethod
    def _runtime_fault_profile_identity(
        profile: RuntimeFaultProfile | None,
    ) -> dict[str, Any]:
        if profile is RuntimeFaultProfile.OOM_256M:
            return {
                "schema": _RUNTIME_FAULT_PROFILE_SCHEMA,
                "cohort_kind": "oom_256m_target_peer",
                "role": "target",
                "name": RuntimeFaultProfile.OOM_256M.value,
                "memory_bytes": _OOM_RUNTIME_MEMORY_BYTES,
                "memory_swap_bytes": _OOM_RUNTIME_MEMORY_BYTES,
                "test_only": True,
            }
        if profile is None:
            return {
                "schema": _RUNTIME_FAULT_PROFILE_SCHEMA,
                "cohort_kind": "oom_256m_target_peer",
                "role": "peer",
                "name": "normal_4g",
                "memory_bytes": _NORMAL_RUNTIME_MEMORY_BYTES,
                "memory_swap_bytes": _NORMAL_RUNTIME_MEMORY_BYTES,
                "test_only": True,
            }
        raise SupervisionConfigurationError("unsupported runtime fault profile")

    @staticmethod
    def _workspace_fault_profile_identity(role: str) -> dict[str, Any]:
        if role == "target":
            return {
                "schema": _WORKSPACE_FAULT_PROFILE_SCHEMA,
                "cohort_kind": "enospc_16m_target_peer",
                "role": "target",
                "name": "enospc_16m",
                "filesystem": "tmpfs",
                "size_bytes": _ENOSPC_WORKSPACE_BYTES,
                "test_only": True,
            }
        if role == "peer":
            return {
                "schema": _WORKSPACE_FAULT_PROFILE_SCHEMA,
                "cohort_kind": "enospc_16m_target_peer",
                "role": "peer",
                "name": "normal_workspace",
                "filesystem": "host",
                "size_bytes": None,
                "test_only": True,
            }
        raise SupervisionConfigurationError("unsupported workspace fault profile")

    @staticmethod
    def _experiment_config(
        request: SupervisedRunRequest, contract: RuntimeContract
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "backend": request.backend,
            "model": request.model,
            "max_steps": request.max_steps,
            "ticks_per_step": request.ticks_per_step,
            "preserve_save": request.preserve_save,
            "seed_save": contract.seed_save,
            "runtime_save": contract.runtime_save,
        }
        if request.evaluation_protocol is not None:
            base["evaluation_protocol"] = request.evaluation_protocol
        return {
            "name": f"m1b-{contract.run_id}",
            "description": "M1b externally supervised single-run worker",
            "base_config": base,
            "variants": [
                {
                    "name": "supervised",
                    "memory_window": request.memory_window,
                }
            ],
            "runs_per_variant": 1,
        }

    def _load_contract(
        self, run_id: str, *, validate_cohort: bool = True
    ) -> RuntimeContract:
        payload = _read_mapping(self._run_dir(run_id) / "launch.json")
        if payload.get("schema") != "fortgym.m1b-service-launch/v1":
            raise LaunchEvidenceError("launch schema is invalid")
        if payload.get("run_id") != run_id:
            raise LaunchEvidenceError("launch run ID mismatch")
        request_identity = _mapping(payload.get("request"), "request")
        identity = payload.get("contract")
        if not isinstance(identity, Mapping):
            raise LaunchEvidenceError("launch contract is missing")
        try:
            runtime = _mapping(identity.get("runtime"), "runtime")
            seed = _mapping(identity.get("seed"), "seed")
            rpc = _mapping(identity.get("rpc"), "rpc")
            paths = _mapping(identity.get("paths"), "paths")
            provider_identity = _mapping(identity.get("provider"), "provider")
            cotenancy = _mapping(identity.get("cotenancy"), "cotenancy")
            provider = self._provider_from_identity(provider_identity)
            contract = RuntimeContract(
                run_id=str(identity["run_id"]),
                backend=str(identity["backend"]),
                model=str(identity["model"]),
                port=_exact_json_int(rpc["port"], "rpc.port"),
                nonce=str(rpc["nonce"]),
                image_manifest_sha256=str(runtime["image_manifest_sha256"]),
                image_config_sha256=str(runtime["image_config_sha256"]),
                image_archive_sha256=str(runtime["image_archive_sha256"]),
                seed_tree_sha256=str(seed["tree_sha256"]),
                seed_world_sha256=str(seed["world_sha256"]),
                code_sha256=str(identity["code_sha256"]),
                db_path=Path(str(paths["db"])),
                artifacts_root=Path(str(paths["artifacts_root"])),
                control_root=Path(str(paths["control_root"])),
                dfroot=Path(str(paths["dfroot"])),
                seed_save=str(seed["seed_save"]),
                runtime_save=str(seed["runtime_save"]),
                cohort_run_ids=(str(identity["run_id"]),)
                if _exact_json_int(cotenancy["cohort_size"], "cotenancy.cohort_size")
                == 1
                else tuple(
                    sorted(
                        [str(identity["run_id"])]
                        + [str(value) for value in cotenancy["peer_run_ids"]]
                    )
                ),
                provider=provider,
                scripted=_exact_json_bool(identity["scripted"], "scripted"),
                runtime_classification=str(runtime["classification"]),
                source_reproducible=_exact_json_bool(
                    runtime["source_reproducible"], "runtime.source_reproducible"
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LaunchEvidenceError(
                "launch contract cannot be reconstructed"
            ) from exc
        expected_paths = {
            "db_path": self.config.db_path,
            "artifacts_root": self.config.artifacts_root,
            "control_root": self.config.control_root,
            "repo_code": self.config.code_sha256,
        }
        if contract.run_id != run_id:
            raise LaunchEvidenceError("inner launch contract run ID mismatch")
        if (
            contract.db_path != expected_paths["db_path"]
            or contract.artifacts_root != expected_paths["artifacts_root"]
            or contract.control_root != expected_paths["control_root"]
            or contract.dfroot != self.config.dfroot
            or contract.code_sha256 != expected_paths["repo_code"]
            or contract.image_manifest_sha256 != self.config.image_manifest_sha256
            or contract.image_config_sha256 != self.config.image_config_sha256
            or contract.image_archive_sha256 != self.config.image_archive_sha256
            or contract.seed_tree_sha256 != self.config.seed_tree_sha256
            or contract.seed_world_sha256 != self.config.seed_world_sha256
            or contract.runtime_classification != "private_stock_archive_seeded"
            or contract.source_reproducible is not False
        ):
            raise LaunchEvidenceError(
                "launch contract no longer matches service config"
            )
        if contract.contract_sha256 != identity.get("contract_sha256"):
            raise LaunchEvidenceError("launch contract digest mismatch")
        if dict(identity) != contract.environment_identity():
            raise LaunchEvidenceError("launch contract identity is noncanonical")
        cotenancy_identity = contract.cotenancy()
        if len(contract.cohort_run_ids) > self.config.max_cohort:
            raise LaunchEvidenceError("launch cohort exceeds service capacity")
        expected_port = RuntimeContract.port_for_slot(
            base_port=self.config.base_port,
            slot=int(cotenancy_identity["slot"]),
            cohort_size=int(cotenancy_identity["cohort_size"]),
        )
        if contract.port != expected_port:
            raise LaunchEvidenceError("launch port no longer matches cohort slot")
        record = self.registry.get(run_id)
        if record is None:
            raise LaunchEvidenceError("launch contract has no registry row")
        if record is not None:
            expected_request = {
                "max_steps": record.max_steps,
                "ticks_per_step": record.ticks_per_step,
                "evaluation_protocol": record.evaluation_protocol,
                "preserve_save": record.preserve_save,
                "memory_window": 0,
                "safe": True,
            }
            if dict(request_identity) != expected_request:
                raise LaunchEvidenceError("launch request contradicts registry row")
            if (
                record.supervision_mode != SUPERVISION_MODE
                or record.backend != contract.backend
                or record.model != contract.model
                or record.seed_save != contract.seed_save
                or record.runtime_save != contract.runtime_save
            ):
                raise LaunchEvidenceError("launch contract contradicts registry row")
            expected_experiment = self._experiment_config(
                SupervisedRunRequest(
                    backend=record.backend,
                    model=record.model,
                    max_steps=record.max_steps,
                    ticks_per_step=record.ticks_per_step,
                    safe=True,
                    evaluation_protocol=record.evaluation_protocol,
                    preserve_save=record.preserve_save,
                    memory_window=0,
                ),
                contract,
            )
            experiment = _read_mapping(self._run_dir(run_id) / "experiment.json")
            if experiment != expected_experiment:
                raise LaunchEvidenceError(
                    "experiment config contradicts launch and registry"
                )
        if validate_cohort:
            for peer_run_id in contract.cohort_run_ids:
                if peer_run_id == run_id:
                    continue
                peer = self._load_contract(peer_run_id, validate_cohort=False)
                if (
                    peer.cohort_run_ids != contract.cohort_run_ids
                    or peer.cohort_digest != contract.cohort_digest
                ):
                    raise LaunchEvidenceError(
                        "launch cohort is not symmetric across service-owned peers"
                    )
        self._load_runtime_fault_profile(contract)
        self._load_workspace_fault_profile(contract)
        return contract

    def _load_test_fault(self, run_id: str) -> RuntimeTestFault | None:
        payload = _read_mapping(self._run_dir(run_id) / "launch.json")
        raw = payload.get("test_fault")
        if raw is None:
            return None
        if self.config.allow_test_startup_faults is not True:
            raise LaunchEvidenceError(
                "persisted test startup fault is forbidden by service config"
            )
        if not isinstance(raw, Mapping):
            raise LaunchEvidenceError("test startup fault evidence must be an object")
        expected = {
            "schema": "fortgym.m1b-test-startup-fault/v1",
            "name": RuntimeTestFault.SUPPRESS_RPC_READINESS.value,
            "injected": True,
            "attempt_index": 1,
        }
        if dict(raw) != expected:
            raise LaunchEvidenceError("test startup fault evidence is noncanonical")
        return RuntimeTestFault.SUPPRESS_RPC_READINESS

    def _load_runtime_fault_profile(
        self, contract: RuntimeContract
    ) -> RuntimeFaultProfile | None:
        """Recover one exact private OOM target/normal peer launch profile."""

        profile_rows: dict[str, Mapping[str, Any] | None] = {}
        for cohort_run_id in contract.cohort_run_ids:
            launch = _read_mapping(self._run_dir(cohort_run_id) / "launch.json")
            if (
                launch.get("schema") != "fortgym.m1b-service-launch/v1"
                or launch.get("run_id") != cohort_run_id
            ):
                raise LaunchEvidenceError(
                    "runtime fault profile launch identity differs"
                )
            if (
                "runtime_fault_profile" in launch
                and "workspace_fault_profile" in launch
            ):
                raise LaunchEvidenceError("fault profile families cannot be combined")
            raw = launch.get("runtime_fault_profile")
            if raw is not None and not isinstance(raw, Mapping):
                raise LaunchEvidenceError(
                    "runtime fault profile evidence must be an object"
                )
            profile_rows[cohort_run_id] = raw

        present = {
            run_id: raw for run_id, raw in profile_rows.items() if raw is not None
        }
        if not present:
            return None
        if self.config.allow_test_runtime_fault_profiles is not True:
            raise LaunchEvidenceError(
                "persisted runtime fault profile is forbidden by service config"
            )
        if (
            len(contract.cohort_run_ids) != 2
            or len(present) != 2
            or contract.backend != "dfhack"
            or contract.model != "dfhack-governed-scripted"
            or contract.scripted is not True
            or contract.provider.enabled
        ):
            raise LaunchEvidenceError(
                "runtime fault profile cohort identity is invalid"
            )

        target_ids: list[str] = []
        peer_ids: list[str] = []
        for run_id, raw in present.items():
            if not isinstance(raw, Mapping):
                raise LaunchEvidenceError(
                    "runtime fault profile evidence must be an object"
                )
            if dict(raw) == self._runtime_fault_profile_identity(
                RuntimeFaultProfile.OOM_256M
            ):
                target_ids.append(run_id)
            elif dict(raw) == self._runtime_fault_profile_identity(None):
                peer_ids.append(run_id)
            else:
                raise LaunchEvidenceError(
                    "runtime fault profile evidence is noncanonical"
                )
        if len(target_ids) != 1 or len(peer_ids) != 1:
            raise LaunchEvidenceError(
                "runtime fault profile cohort must have one target and one peer"
            )
        if contract.run_id == target_ids[0]:
            return RuntimeFaultProfile.OOM_256M
        if contract.run_id == peer_ids[0]:
            return None
        raise LaunchEvidenceError("runtime fault profile omits the current run")

    def _load_workspace_fault_profile(self, contract: RuntimeContract) -> str | None:
        """Recover one exact private ENOSPC target/normal peer launch profile."""

        profile_rows: dict[str, Mapping[str, Any] | None] = {}
        for cohort_run_id in contract.cohort_run_ids:
            launch = _read_mapping(self._run_dir(cohort_run_id) / "launch.json")
            if (
                launch.get("schema") != "fortgym.m1b-service-launch/v1"
                or launch.get("run_id") != cohort_run_id
            ):
                raise LaunchEvidenceError(
                    "workspace fault profile launch identity differs"
                )
            if (
                "runtime_fault_profile" in launch
                and "workspace_fault_profile" in launch
            ):
                raise LaunchEvidenceError("fault profile families cannot be combined")
            if "workspace_fault_profile" in launch and "test_fault" in launch:
                raise LaunchEvidenceError(
                    "workspace and startup fault profiles cannot be combined"
                )
            raw = launch.get("workspace_fault_profile")
            if raw is not None and not isinstance(raw, Mapping):
                raise LaunchEvidenceError(
                    "workspace fault profile evidence must be an object"
                )
            profile_rows[cohort_run_id] = raw

        present = {
            run_id: raw for run_id, raw in profile_rows.items() if raw is not None
        }
        if not present:
            return None
        if self.config.allow_test_workspace_fault_profiles is not True:
            raise LaunchEvidenceError(
                "persisted workspace fault profile is forbidden by service config"
            )
        if self._enospc_evidence_loader is None or self._enospc_workspace is None:
            raise LaunchEvidenceError(
                "persisted workspace fault profile lacks explicit host controls"
            )
        if (
            len(contract.cohort_run_ids) != 2
            or len(present) != 2
            or contract.backend != "dfhack"
            or contract.model != "dfhack-governed-scripted"
            or contract.scripted is not True
            or contract.provider.enabled
        ):
            raise LaunchEvidenceError(
                "workspace fault profile cohort identity is invalid"
            )

        target_ids: list[str] = []
        peer_ids: list[str] = []
        for run_id, raw in present.items():
            if not isinstance(raw, Mapping):
                raise LaunchEvidenceError(
                    "workspace fault profile evidence must be an object"
                )
            if dict(raw) == self._workspace_fault_profile_identity("target"):
                target_ids.append(run_id)
            elif dict(raw) == self._workspace_fault_profile_identity("peer"):
                peer_ids.append(run_id)
            else:
                raise LaunchEvidenceError(
                    "workspace fault profile evidence is noncanonical"
                )
        if len(target_ids) != 1 or len(peer_ids) != 1:
            raise LaunchEvidenceError(
                "workspace fault profile cohort must have one target and one peer"
            )
        if contract.run_id == target_ids[0]:
            return "target"
        if contract.run_id == peer_ids[0]:
            return "peer"
        raise LaunchEvidenceError("workspace fault profile omits the current run")

    def _provider_from_identity(self, identity: Mapping[str, Any]) -> ProviderPolicy:
        enabled = identity.get("enabled")
        if enabled is False:
            if dict(identity) != ProviderPolicy().identity():
                raise LaunchEvidenceError("disabled provider identity is noncanonical")
            return ProviderPolicy()
        if enabled is not True:
            raise LaunchEvidenceError("provider enabled flag must be a boolean")
        if identity.get("credential_present") is not True:
            raise LaunchEvidenceError("provider credential attestation is missing")
        if identity.get("strict_supervised") is not True:
            raise LaunchEvidenceError("strict provider attestation is missing")
        if not self.config.openrouter_api_key:
            raise LaunchEvidenceError("provider launch cannot recover without M1b key")
        return ProviderPolicy.openrouter(
            model=str(identity["model"]),
            provider_name=str(identity["provider_name"]),
            api_key=self.config.openrouter_api_key,
            max_total_tokens=_exact_json_int(
                identity["max_total_tokens"], "provider.max_total_tokens"
            ),
            max_cost_usd=_exact_json_number(
                identity["max_cost_usd"], "provider.max_cost_usd"
            ),
            base_url=str(identity["base_url"]),
        )

    def _require_owned(self, run_id: str) -> RunInfo:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise RunNotOwnedError("invalid run ID")
        record = self.registry.get(run_id)
        if record is None or record.supervision_mode != SUPERVISION_MODE:
            raise RunNotOwnedError(f"run is not M1b-supervised: {run_id}")
        return record

    def _run_dir(self, run_id: str) -> Path:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise SupervisionServiceError("invalid run ID")
        return self.config.control_root / run_id

    def _has_attempt(self, run_id: str) -> bool:
        run_dir = self._run_dir(run_id)
        return any(
            path.exists()
            for path in (
                run_dir / "owner.json",
                run_dir / "attempts" / "attempt-0001",
                run_dir / "supervision-observed.json",
            )
        )

    def _terminalize_unstarted(
        self,
        run_id: str,
        exc: BaseException,
        *,
        code: str = "manager_thread_start_failed",
    ) -> None:
        self._discard_enospc_fault_authorization(run_id)
        record = self._require_owned(run_id)
        if record.status in _TERMINAL:
            return
        if record.status != "pending":
            raise SupervisionServiceError(
                f"cannot classify non-pending run as unstarted: {run_id}"
            )
        now = datetime.now(UTC)
        self.registry.record_cleanup_completed(run_id, completed_at=now)
        self.registry.record_terminal_failure(
            run_id,
            terminal_reason={
                "code": code,
                "error": _safe_error(exc),
            },
            step=record.step,
            ended_at=now,
        )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _environment_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SupervisionConfigurationError(f"{name} must be an integer") from exc


def _exact_json_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise LaunchEvidenceError(f"launch {name} must be a boolean")
    return value


def _exact_json_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LaunchEvidenceError(f"launch {name} must be an integer")
    return value


def _exact_json_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LaunchEvidenceError(f"launch {name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise LaunchEvidenceError(f"launch {name} must be finite")
    return normalized


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LaunchEvidenceError(f"launch {name} must be a mapping")
    return value


def _safe_error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": " ".join(str(exc).split())[:400],
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise LaunchEvidenceError(f"launch evidence already exists: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise LaunchEvidenceError(f"invalid launch evidence: {path}") from exc
    if not isinstance(value, dict):
        raise LaunchEvidenceError(f"launch evidence must be an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise StartupReplacementError(f"missing append-only evidence: {path}") from exc
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StartupReplacementError(
                f"invalid append-only evidence: {path}"
            ) from exc
        if not isinstance(record, dict) or not isinstance(record.get("event"), str):
            raise StartupReplacementError(
                f"append-only evidence row is malformed: {path}"
            )
        records.append(record)
    return records


__all__ = [
    "SUPERVISION_MODE",
    "CohortLaunch",
    "LaunchEvidenceError",
    "ProviderNetworkServiceFactory",
    "RunNotOwnedError",
    "ServiceConfig",
    "StartupSequenceResult",
    "SupervisedRunRequest",
    "SupervisionConfigurationError",
    "SupervisionRequestError",
    "SupervisionService",
    "SupervisionServiceError",
]
