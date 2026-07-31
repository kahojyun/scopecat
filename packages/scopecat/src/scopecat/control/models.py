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
type ResourceClaimStatus = Literal["active", "quarantined"]
type ResourceOwnerKind = Literal["run", "instrument_session"]
type InventoryMigrationBlockerState = Literal[
    "queued",
    "leased",
    "attention_required",
    "active",
    "quarantined",
]
type InstrumentSessionState = Literal["active", "attention_required", "closed"]
type InstrumentOperationKind = Literal["apply", "invoke", "collect"]
type InstrumentSessionEndStatus = Literal["closed", "aborted"]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class _ControlModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class ResourceKey(_ControlModel):
    """Canonical exclusive resource identity used by the scheduler."""

    kind: ResourceKind = "instrument"
    id: str = Field(min_length=1)

    @classmethod
    def instrument(cls, exclusivity_key: str) -> ResourceKey:
        return cls(kind="instrument", id=exclusivity_key)


class RunResourceRequirement(_ControlModel):
    """Logical resource identity requested by a run plan."""

    kind: ResourceKind = "instrument"
    id: str = Field(min_length=1)


class RunDomainTargetRequirement(_ControlModel):
    """Domain target identity and its complete logical instrument footprint."""

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    instrument_ids: tuple[str, ...] = ()

    @field_validator("instrument_ids")
    @classmethod
    def validate_instrument_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not instrument_id for instrument_id in value):
            raise ValueError("domain target instrument ids must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("domain target instrument ids must be unique")
        return tuple(sorted(value))


class RunPlanSummary(_ControlModel):
    """Bounded scheduling and presentation facts for an in-process plan."""

    experiment_id: str = Field(min_length=1)
    experiment_kind: str = Field(min_length=1)
    point_count: int = Field(ge=0)
    coordinate_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    run_resource_requirements: tuple[RunResourceRequirement, ...] = ()
    domain_target_requirement: RunDomainTargetRequirement | None = None
    host_instrument_order: tuple[str, ...] = ()
    host_provider_id: str | None = Field(default=None, min_length=1)
    host_contract_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator(
        "coordinate_ids",
        "record_ids",
        "host_instrument_order",
    )
    @classmethod
    def validate_unique_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("run plan ids must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("run plan summary ids must be unique")
        return value

    @field_validator("run_resource_requirements")
    @classmethod
    def validate_unique_requirements(
        cls,
        value: tuple[RunResourceRequirement, ...],
    ) -> tuple[RunResourceRequirement, ...]:
        identities = tuple((requirement.kind, requirement.id) for requirement in value)
        if len(identities) != len(set(identities)):
            raise ValueError("run plan resource requirements must be unique")
        return value

    @model_validator(mode="after")
    def validate_resource_alignment(self) -> RunPlanSummary:
        target_ids = tuple(
            requirement.id
            for requirement in self.run_resource_requirements
            if requirement.kind == "target"
        )
        domain = self.domain_target_requirement
        if domain is None:
            if target_ids:
                raise ValueError(
                    "target requirements require a domain target requirement"
                )
        elif target_ids != (domain.id,):
            raise ValueError(
                "domain target requirement must match exactly one target requirement"
            )
        if domain is not None:
            instrument_ids = {
                requirement.id
                for requirement in self.run_resource_requirements
                if requirement.kind == "instrument"
            }
            missing = sorted(set(domain.instrument_ids) - instrument_ids)
            if missing:
                raise ValueError(
                    "run plan omits domain target instruments: " + ", ".join(missing)
                )

        required = {
            requirement.id
            for requirement in self.run_resource_requirements
            if requirement.kind == "instrument"
        }
        # Domain-owned instruments are required without a daemon-hosted driver.
        if not set(self.host_instrument_order).issubset(required):
            raise ValueError(
                "run plan host instrument order must reference instrument requirements"
            )
        has_host = bool(self.host_instrument_order)
        if has_host != (self.host_provider_id is not None):
            raise ValueError("host provider identity must match hosted instruments")
        if has_host != (self.host_contract_fingerprint is not None):
            raise ValueError("host contract fingerprint must match hosted instruments")
        return self


class RunAdmissionRecord(_ControlModel):
    """Scheduler facts committed with an accepted run skeleton."""

    submission_id: str = Field(min_length=1)
    submission_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    plan: RunPlanSummary
    resource_claims: tuple[ResourceKey, ...]
    admitted_at: datetime = Field(default_factory=utc_now)

    @field_validator("resource_claims")
    @classmethod
    def validate_unique_claims(
        cls,
        value: tuple[ResourceKey, ...],
    ) -> tuple[ResourceKey, ...]:
        identities = tuple((claim.kind, claim.id) for claim in value)
        if len(identities) != len(set(identities)):
            raise ValueError("run admission resource claims must be unique")
        return value

    @model_validator(mode="after")
    def validate_resource_claim_alignment(self) -> RunAdmissionRecord:
        logical = self.plan.run_resource_requirements
        if len(logical) != len(self.resource_claims):
            raise ValueError(
                "run admission claims must align with logical plan requirements"
            )
        for logical_requirement, canonical_claim in zip(
            logical,
            self.resource_claims,
            strict=True,
        ):
            if logical_requirement.kind != canonical_claim.kind:
                raise ValueError(
                    "run admission claims must align with logical plan requirements"
                )
        return self

    def is_retry_of(self, other: RunAdmissionRecord) -> bool:
        return (
            self.submission_id == other.submission_id
            and self.submission_content_hash == other.submission_content_hash
        )

    @property
    def experiment_id(self) -> str:
        return self.plan.experiment_id


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


class ResourceClaim(_ControlModel):
    resource: ResourceKey
    owner_kind: ResourceOwnerKind
    owner_id: str = Field(min_length=1)
    status: ResourceClaimStatus
    acquired_at: datetime


class InventoryMigrationBlocker(_ControlModel):
    """A durable owner that prevents changing one resource identity."""

    key: ResourceKey
    owner_kind: ResourceOwnerKind
    owner_id: str = Field(min_length=1)
    state: InventoryMigrationBlockerState


class InstrumentSession(_ControlModel):
    """Durable daemon state for one explicit direct-control session."""

    session_id: str = Field(min_length=1)
    open_operation_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    config_entry_id: str = Field(min_length=1)
    config_content_hash: str = Field(min_length=1)
    instrument_ids: tuple[str, ...] = Field(min_length=1)
    exclusivity_keys: tuple[str, ...] = Field(min_length=1)
    state: InstrumentSessionState
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime
    attention_reason: str | None = None
    active_operation_id: str | None = None
    active_operation_kind: InstrumentOperationKind | None = None
    end_status: InstrumentSessionEndStatus | None = None

    @field_validator("instrument_ids")
    @classmethod
    def validate_instrument_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not instrument_id for instrument_id in value):
            raise ValueError("instrument session ids must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("instrument session ids must be unique")
        return value

    @field_validator("exclusivity_keys")
    @classmethod
    def validate_exclusivity_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not exclusivity_key for exclusivity_key in value):
            raise ValueError("instrument session exclusivity keys must be non-empty")
        if len(value) != len(set(value)):
            raise ValueError("instrument session exclusivity keys must be unique")
        return value

    @model_validator(mode="after")
    def validate_lifetime(self) -> InstrumentSession:
        if self.expires_at <= self.renewed_at:
            raise ValueError("instrument session must expire after its renewal time")
        return self

    @model_validator(mode="after")
    def validate_state(self) -> InstrumentSession:
        if len(self.instrument_ids) != len(self.exclusivity_keys):
            raise ValueError(
                "instrument session ids and exclusivity keys must have equal length"
            )
        if self.state == "active":
            if self.attention_reason is not None:
                raise ValueError("active instrument session cannot require attention")
            if self.end_status is not None:
                raise ValueError("active instrument session cannot have an end status")
        elif self.state == "attention_required":
            if not self.attention_reason:
                raise ValueError("attention-required session requires a reason")
            if self.end_status is not None:
                raise ValueError(
                    "attention-required instrument session cannot have an end status"
                )
        else:
            if self.attention_reason is not None:
                raise ValueError("closed instrument session cannot require attention")
            if self.end_status is None:
                raise ValueError("closed instrument session requires an end status")
            if (
                self.active_operation_id is not None
                or self.active_operation_kind is not None
            ):
                raise ValueError("closed instrument session cannot retain an operation")
        if (self.active_operation_id is None) != (self.active_operation_kind is None):
            raise ValueError(
                "instrument session operation id and kind must be present together"
            )
        return self
