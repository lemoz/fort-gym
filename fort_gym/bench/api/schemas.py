"""Pydantic schemas for fort-gym API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


BackendType = Literal["mock", "dfhack"]
ModelType = Literal["random", "fake", "openai", "anthropic", "anthropic-keystroke"]


class RunInfo(BaseModel):
    """Metadata about a single run instance."""

    id: str
    status: Literal["pending", "running", "paused", "stopped", "completed", "failed"] = "pending"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    backend: BackendType = "mock"
    model: str = "unknown"
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


class JobInfo(BaseModel):
    """Metadata for batch execution jobs driving multiple runs."""

    id: str
    run_ids: List[str] = Field(default_factory=list)
    status: Literal["queued", "running", "completed", "failed"] = "queued"


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
    backend: BackendType
    status: str
    step: int
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    score: Optional[float] = None
    token: str
    scopes: List[str] = Field(default_factory=list)


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
