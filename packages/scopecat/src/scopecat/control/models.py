"""Durable records owned by the project control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.records.config import ConfigContentHash
from scopecat.records.run import RunOutcome
from scopecat.records.run_request import RunRequest

type ExecutionMode = Literal["managed", "delegated"]
type ControlRunState = Literal[
    "accepted",
    "running",
    "terminal",
    "attention_required",
]
type ResourceKind = Literal["target", "instrument", "channel", "group"]
type ResourceLeaseStatus = Literal["active", "quarantined"]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class _ControlModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class ResourceKey(_ControlModel):
    """Canonical exclusive resource identity used by the scheduler."""

    kind: ResourceKind = "instrument"
    id: str = Field(min_length=1)


class RunAdmissionRecord(_ControlModel):
    """Inputs that must become durable before an executor can touch hardware."""

    submission_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_mode: ExecutionMode
    experiment_id: str = Field(min_length=1)
    config_content_hash: ConfigContentHash
    request: RunRequest | None = None
    plan_summary: dict[str, JsonValue] = Field(default_factory=dict)
    resource_claims: tuple[ResourceKey, ...] = ()
    admitted_at: datetime = Field(default_factory=utc_now)

    @field_validator("resource_claims")
    @classmethod
    def validate_resource_claims(
        cls,
        value: tuple[ResourceKey, ...],
    ) -> tuple[ResourceKey, ...]:
        identities = {(resource.kind, resource.id) for resource in value}
        if len(identities) != len(value):
            msg = "run admission contains duplicate resource claims"
            raise ValueError(msg)
        return value


class ControlRun(_ControlModel):
    """Current scheduler state plus the immutable admission record."""

    sequence: int = Field(ge=1)
    admission: RunAdmissionRecord
    state: ControlRunState
    state_version: int = Field(ge=1)
    updated_at: datetime
    outcome: RunOutcome | None = None
    attention_reason: str | None = None

    @model_validator(mode="after")
    def validate_state_details(self) -> ControlRun:
        if self.state == "terminal":
            if self.outcome is None:
                msg = "a terminal control run requires an outcome"
                raise ValueError(msg)
            if self.outcome.run_id != self.admission.run_id:
                msg = "run outcome does not belong to its control run"
                raise ValueError(msg)
        elif self.outcome is not None:
            msg = "a non-terminal control run cannot have an outcome"
            raise ValueError(msg)
        if self.state == "attention_required":
            if not self.attention_reason:
                msg = "attention-required control run requires a reason"
                raise ValueError(msg)
        elif self.attention_reason is not None:
            msg = "attention reason is only valid for attention-required runs"
            raise ValueError(msg)
        return self

    @property
    def run_id(self) -> str:
        return self.admission.run_id


class RunPage(_ControlModel):
    items: tuple[ControlRun, ...]
    next_cursor: int | None = None
    previous_cursor: int | None = None


class DurableEventInput(_ControlModel):
    """One event to append to the globally ordered replay stream."""

    run_id: str | None = None
    kind: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class DurableEvent(DurableEventInput):
    event_id: int = Field(ge=1)


class EventPage(_ControlModel):
    items: tuple[DurableEvent, ...]
    next_cursor: int | None = None


class ExecutorLease(_ControlModel):
    """Renewable fencing token for the process executing one run."""

    run_id: str
    executor_id: str
    token: str
    generation: int = Field(ge=1)
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_lifetime(self) -> ExecutorLease:
        if self.expires_at <= self.renewed_at:
            msg = "executor lease must expire after its renewal time"
            raise ValueError(msg)
        return self


class ResourceLease(_ControlModel):
    resource: ResourceKey
    run_id: str
    executor_token: str | None
    status: ResourceLeaseStatus
    acquired_at: datetime
    expires_at: datetime | None

    @model_validator(mode="after")
    def validate_ownership(self) -> ResourceLease:
        if self.status == "active":
            if self.executor_token is None or self.expires_at is None:
                msg = "an active resource lease requires an executor and expiry"
                raise ValueError(msg)
        elif self.executor_token is not None or self.expires_at is not None:
            msg = "a quarantined resource lease cannot remain executor-owned"
            raise ValueError(msg)
        return self


class ResourceClaimConflict(_ControlModel):
    resource: ResourceKey
    owner_run_id: str
    status: ResourceLeaseStatus


class ResourceClaimResult(_ControlModel):
    acquired: bool
    leases: tuple[ResourceLease, ...] = ()
    conflicts: tuple[ResourceClaimConflict, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> ResourceClaimResult:
        if self.acquired and self.conflicts:
            msg = "an acquired resource claim cannot contain conflicts"
            raise ValueError(msg)
        if not self.acquired and self.leases:
            msg = "a rejected resource claim cannot contain leases"
            raise ValueError(msg)
        return self
