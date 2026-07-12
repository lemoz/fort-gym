"""Pydantic schemas for fort-gym API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..eval.protocol import EVALUATION_PROTOCOL_PATTERN


BackendType = Literal["mock", "dfhack"]
ModelType = Literal[
    "random",
    "fake",
    "dfhack-governed-scripted",
    "dfhack-governed-llm",
    "dfhack-governed-llm-glm52",
    "dfhack-governed-llm-deepseek-v4",
    "dfhack-governed-llm-gpt55",
    "dfhack-governed-llm-fable5",
    "dfhack-governed-llm-gpt56-sol",
    "dfhack-governed-llm-glm5v",
    "dfhack-governed-llm-gpt55-vision",
    "dfhack-governed-llm-kimi-vision",
    "dfhack-governed-llm-minimax-vision",
    "openai",
    "openai-keystroke-perception-review",
    "openrouter-keystroke",
    "openrouter-keystroke-perception-review",
    "openrouter-glm-5.2",
    "anthropic",
    "anthropic-dig-first",
    "anthropic-fortress-plan",
    "anthropic-keystroke",
    "anthropic-keystroke-poi-review",
    "anthropic-keystroke-plan-review",
    "anthropic-keystroke-perception-review",
    "anthropic-keystroke-perception-review-opus",
    "anthropic-research",
]


class RunInfo(BaseModel):
    """Metadata about a single run instance."""

    id: str
    status: Literal["pending", "running", "paused", "stopped", "completed", "failed"] = "pending"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    backend: BackendType = "mock"
    model: str = "unknown"
    git_sha: Optional[str] = None
    seed_save: Optional[str] = None
    runtime_save: Optional[str] = None
    preserve_save: bool = False
    evaluation_protocol: Optional[str] = None
    max_steps: int = 0
    ticks_per_step: int = 0
    step: int = 0
    score: Optional[float] = None


class RunCreateRequest(BaseModel):
    """Request payload for launching a benchmark run."""

    backend: BackendType = "mock"
    max_steps: int = Field(default=5, ge=1)
    ticks_per_step: int = Field(default=100, ge=1)
    model: ModelType = "random"
    safe: Optional[bool] = True
    preserve_save: bool = False
    evaluation_protocol: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=EVALUATION_PROTOCOL_PATTERN,
    )
    # Per-run seed selection (G6 generalization): a bare save-folder name
    # under data/seed_saves to reset from, and the runtime save name to reset
    # into. None keeps the deployment defaults
    # (FORT_GYM_SEED_SAVE / FORT_GYM_RUNTIME_SAVE).
    seed_save: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    runtime_save: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")


class ActionRecord(BaseModel):
    """Single action entry in a run trace."""

    step: int
    action: Dict[str, Any]
    timestamp: datetime
    validation: Optional[Dict[str, Any]] = None


class StateSnapshot(BaseModel):
    """State payload surfaced to observers."""

    run_id: str
    step: int
    state: Dict[str, Any]
    encoded_text: str
    model_config = {"populate_by_name": True}


class ScoreUpdate(BaseModel):
    """Scoring updates emitted after evaluation."""

    run_id: str
    score: float
    detail: Dict[str, Any] = Field(default_factory=dict)


class RunInfoPublic(BaseModel):
    """Publicly consumable run metadata."""

    run_id: str
    model: str
    git_sha: Optional[str] = None
    backend: BackendType
    status: str
    step: int
    max_steps: int = 0
    ticks_per_step: int = 0
    seed_save: Optional[str] = None
    runtime_save: Optional[str] = None
    preserve_save: bool = False
    evaluation_protocol: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    score: Optional[float] = None
    token: str
    scopes: List[str] = Field(default_factory=list)


class PublicRunsPage(BaseModel):
    """A page of publicly shared runs for the runs library."""

    items: List[RunInfoPublic] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class PublicModelResult(BaseModel):
    """One model's scores inside a complete comparison scope."""

    model: str
    model_digest: Optional[str] = None
    public_label: Optional[str] = None
    task_verdict: Optional[str] = None
    g7_outcomes: Optional[Dict[str, int]] = None
    run_count: int
    mean_score: float
    best_score: float
    best_token: Optional[str] = None


class PublicComparisonGroup(BaseModel):
    """A protocol-scoped comparison with separate model result rows."""

    comparability: Dict[str, Any]
    model_results: List[PublicModelResult] = Field(default_factory=list)


class PublicOverview(BaseModel):
    """Compact public snapshot of shared run activity and safe score groups."""

    generated_at: datetime
    active_runs: List[RunInfoPublic] = Field(default_factory=list)
    recent_runs: List[RunInfoPublic] = Field(default_factory=list)
    comparability_fields: List[str]
    comparison_groups: List[PublicComparisonGroup] = Field(default_factory=list)


class PublicResults(BaseModel):
    """Experimental comparison groups for one declared evaluation protocol."""

    generated_at: datetime
    protocol: str
    publication_stage: Optional[str] = None
    status: Literal["experimental"] = "experimental"
    comparability_fields: List[str]
    candidate_run_count: int = Field(ge=0)
    eligible_run_count: int = Field(ge=0)
    excluded_run_count: int = Field(ge=0)
    comparison_groups: List[PublicComparisonGroup] = Field(default_factory=list)


class PublicProtocol(BaseModel):
    """Public-safe definition of one allowlisted Fort-Eval protocol."""

    slug: str
    name: str
    profile: str
    profile_version: str
    status: str
    result_status: str
    summary: str
    interface: Dict[str, str]
    actions: List[str] = Field(default_factory=list)
    observation_bounds: Dict[str, str]
    knowledge: Dict[str, str]
    observer_firewall: str
    comparability_fields: List[str] = Field(default_factory=list)
    ranking: str
    pilot_state: str


class PublicRunSummary(BaseModel):
    """Persisted public summary data for one shared run."""

    run: RunInfoPublic
    summary: Dict[str, Any] = Field(default_factory=dict)
    usage: Optional[Any] = None
    cost: Optional[Any] = None
    cost_status: Literal["reported", "not_reported"]


class PublicRunPreview(BaseModel):
    """Bounded latest-frame preview for a public saved run."""

    step: Optional[int] = None
    screen_text: Optional[str] = None
    screen_status: Literal["recorded", "not_reported"]
    inspected_records: int = 0


class ShareCreate(BaseModel):
    """Request payload for minting share tokens."""

    scope: Optional[List[str]] = None
    ttl_seconds: Optional[int] = Field(default=86400, ge=60)


class StepRequest(BaseModel):
    """Interactive step request payload."""

    run_id: str
    action: Dict[str, Any] = Field(default_factory=dict)
    min_step_period_ms: Optional[int] = Field(default=1000, ge=0)
    max_ticks: Optional[int] = Field(default=500, ge=0)


class StepResponse(BaseModel):
    """Interactive step response schema."""

    observation: Dict[str, Any]
    reward: float
    done: bool
    info: Dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
    """Request payload for launching batched runs."""

    model: ModelType = "random"
    backend: BackendType = "mock"
    n: int = Field(default=10, ge=1)
    parallelism: int = Field(default=2, ge=1)
    max_steps: int = Field(default=200, ge=1)
    ticks_per_step: int = Field(default=100, ge=1)
    safe: Optional[bool] = True


class JobInfo(BaseModel):
    """Public job information returned by the API."""

    job_id: str
    model: str
    backend: BackendType
    n: int
    parallelism: int
    run_ids: List[str]
    status: str
    created_at: datetime
    finished_at: Optional[datetime] = None


class AdminKeysRequest(BaseModel):
    """Admin keystroke payload for manual DF control."""

    keys: List[str] = Field(..., min_length=1, max_length=100)
