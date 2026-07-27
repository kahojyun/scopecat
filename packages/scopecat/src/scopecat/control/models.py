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

type ControlRunState = Literal[
    "queued",
    "leased",
    "attention_required",
    "closed",
]
type ResourceKind = Literal["target", "instrument"]
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


class RunPlanSummary(_ControlModel):
    """Bounded scheduling and presentation facts for an in-process plan."""

    experiment_id: str = Field(min_length=1)
    experiment_kind: str = Field(min_length=1)
    point_count: int = Field(ge=0)
    coordinate_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    run_resource_claims: tuple[ResourceKey, ...] = ()

    @field_validator("coordinate_ids", "record_ids")
    @classmethod
    def validate_unique_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("run plan summary ids must be unique")
        return value

    @field_validator("run_resource_claims")
    @classmethod
    def validate_unique_claims(
        cls,
        value: tuple[ResourceKey, ...],
    ) -> tuple[ResourceKey, ...]:
        identities = tuple((claim.kind, claim.id) for claim in value)
        if len(identities) != len(set(identities)):
            raise ValueError("run plan resource claims must be unique")
        return value


class RunAdmissionRecord(_ControlModel):
    """Scheduler facts committed with an accepted run skeleton."""

    submission_id: str = Field(min_length=1)
    submission_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    plan: RunPlanSummary
    admitted_at: datetime = Field(default_factory=utc_now)

    def is_retry_of(self, other: RunAdmissionRecord) -> bool:
        return (
            self.submission_id == other.submission_id
            and self.submission_content_hash == other.submission_content_hash
        )

    @property
    def experiment_id(self) -> str:
        return self.plan.experiment_id

    @property
    def resource_claims(self) -> tuple[ResourceKey, ...]:
        return self.plan.run_resource_claims


class ControlRun(_ControlModel):
    """Current scheduler state plus the immutable admission record."""

    sequence: int = Field(ge=1)
    admission: RunAdmissionRecord
    state: ControlRunState
    updated_at: datetime
    attention_reason: str | None = None

    @model_validator(mode="after")
    def validate_state_details(self) -> ControlRun:
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
