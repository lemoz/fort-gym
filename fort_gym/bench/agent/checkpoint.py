"""Portable agent state for continuing one campaign, never credentials or clients."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class CheckpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryStep(CheckpointModel):
    step: StrictInt = Field(ge=0)
    observation: StrictStr
    action: dict[str, Any]
    result: StrictStr


class MemoryCheckpoint(CheckpointModel):
    schema_version: Literal["fortgym.memory-checkpoint/v1"] = "fortgym.memory-checkpoint/v1"
    configuration: dict[str, Any]
    summary: StrictStr
    pois: list[dict[str, Any]]
    failed_attempts: list[dict[str, Any]]
    gameplay_plan: dict[str, Any]
    plan_reviews: list[dict[str, Any]]
    step_counter: StrictInt = Field(ge=0)
    recent_steps: list[MemoryStep]

    @model_validator(mode="after")
    def validate_history(self) -> MemoryCheckpoint:
        steps = [record.step for record in self.recent_steps]
        if steps != sorted(set(steps)) or any(step > self.step_counter for step in steps):
            raise ValueError("Checkpoint history must be ordered and within the step counter")
        return self


class AgentUsage(CheckpointModel):
    total_tokens: StrictInt = Field(ge=0)
    total_cost_usd: StrictStr
    returned_responses: StrictInt = Field(ge=0)
    accounted_responses: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_response_counts(self) -> AgentUsage:
        if self.accounted_responses > self.returned_responses:
            raise ValueError("Accounted responses cannot exceed returned responses")
        return self


class PendingOutcome(CheckpointModel):
    observation_digest: StrictStr
    action: dict[str, Any]


class GovernedAgentCheckpoint(CheckpointModel):
    schema_version: Literal[
        "fortgym.governed-agent-checkpoint/v1"
    ] = "fortgym.governed-agent-checkpoint/v1"
    campaign_id: StrictStr = Field(min_length=1, max_length=128)
    configuration: dict[str, Any]
    memory: MemoryCheckpoint
    pending_outcome: PendingOutcome | None
    usage: AgentUsage
