"""Typed wire contracts for immutable calibration cohorts."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.automation.calibrations import (
    MAX_CALIBRATION_COHORT_MEMBERS,
    MAX_CALIBRATION_STATUS_KEYS,
    CalibrationCohort,
    CalibrationCohortFinalization,
    CalibrationCohortMember,
    CalibrationCohortSpec,
    CalibrationCohortSummary,
    CalibrationPublicationPolicyRef,
    CalibrationStatusSnapshot,
    calibration_cohort_spec_hash,
)
from scopecat.records.content import Sha256ContentHash

type _NonEmptyText = Annotated[str, Field(min_length=1)]

MAX_CALIBRATION_PUBLICATION_RETRY_AFTER_SECONDS = 3600


class _CalibrationWireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CalibrationStatusQuery(_CalibrationWireModel):
    """Read one server-clock status and fanout-capacity snapshot."""

    calibration_keys: tuple[_NonEmptyText, ...] = Field(
        min_length=1,
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )
    fanout_scope: _NonEmptyText

    @field_validator("calibration_keys")
    @classmethod
    def validate_calibration_keys(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        for item in value:
            _non_blank(item, field_name="calibration status query key")
        _require_unique(value, label="calibration status query key")
        return value

    @field_validator("fanout_scope")
    @classmethod
    def validate_fanout_scope(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration fanout scope")


class CalibrationStatusReceipt(_CalibrationWireModel):
    """Status response kept explicit for stable HTTP response envelopes."""

    snapshot: CalibrationStatusSnapshot


class CalibrationCohortCreateCommand(_CalibrationWireModel):
    """Atomically admit one exact immutable calibration cohort."""

    cohort_id: _NonEmptyText
    spec: CalibrationCohortSpec

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort id")

    @model_validator(mode="after")
    def validate_prior_dependencies(self) -> CalibrationCohortCreateCommand:
        if any(
            dependency.cohort_id == self.cohort_id
            for member in self.spec.members
            for dependency in member.dependencies
        ):
            raise ValueError(
                "calibration cohort cannot consume a same-cohort dependency"
            )
        return self

    @property
    def spec_hash(self) -> Sha256ContentHash:
        return calibration_cohort_spec_hash(self.spec)


class CalibrationCohortCreateReceipt(_CalibrationWireModel):
    """Canonical cohort and ProcedureRun associations after create/replay."""

    cohort: CalibrationCohort
    members: tuple[CalibrationCohortMember, ...] = Field(
        min_length=1,
        max_length=MAX_CALIBRATION_COHORT_MEMBERS,
    )

    @model_validator(mode="after")
    def validate_members(self) -> CalibrationCohortCreateReceipt:
        _validate_complete_members(self.cohort, self.members)
        return self


class CalibrationCohortGetQuery(_CalibrationWireModel):
    """Address one caller-owned cohort identity."""

    cohort_id: _NonEmptyText

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort id")


class CalibrationCohortGetReceipt(_CalibrationWireModel):
    """Complete immutable cohort spec returned for exact reconciliation."""

    cohort: CalibrationCohort


class CalibrationCohortListQuery(_CalibrationWireModel):
    """Bounded newest-first cohort inspection query."""

    cursor: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=200)
    fanout_scope: _NonEmptyText | None = None

    @field_validator("fanout_scope")
    @classmethod
    def validate_fanout_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_blank(value, field_name="calibration fanout scope")


class CalibrationCohortPage(_CalibrationWireModel):
    """One newest-first page of compact cohort summaries."""

    items: tuple[CalibrationCohortSummary, ...] = Field(
        default=(),
        max_length=200,
    )
    next_cursor: int | None = Field(default=None, ge=1)

    @field_validator("items")
    @classmethod
    def validate_items(
        cls,
        value: tuple[CalibrationCohortSummary, ...],
    ) -> tuple[CalibrationCohortSummary, ...]:
        _require_unique(
            (item.cohort_id for item in value),
            label="calibration cohort page id",
        )
        return value


class CalibrationCohortMemberListQuery(_CalibrationWireModel):
    """Bounded admission-order member traversal for one cohort."""

    cohort_id: _NonEmptyText
    cursor: int | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=MAX_CALIBRATION_COHORT_MEMBERS)

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort id")


class CalibrationCohortMemberPage(_CalibrationWireModel):
    """One admission-order page of ProcedureRun member associations."""

    cohort_id: _NonEmptyText
    items: tuple[CalibrationCohortMember, ...] = Field(
        default=(),
        max_length=MAX_CALIBRATION_COHORT_MEMBERS,
    )
    next_cursor: int | None = Field(default=None, ge=0)

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort id")

    @model_validator(mode="after")
    def validate_items(self) -> CalibrationCohortMemberPage:
        if any(item.cohort_id != self.cohort_id for item in self.items):
            raise ValueError("calibration member page items must match its cohort")
        _require_unique(
            (item.index for item in self.items),
            label="calibration member page index",
        )
        _require_unique(
            (item.spec.member_id for item in self.items),
            label="calibration member page member id",
        )
        _require_unique(
            (item.procedure_run_id for item in self.items),
            label="calibration member page procedure run id",
        )
        indexes = tuple(item.index for item in self.items)
        if indexes != tuple(sorted(indexes)):
            raise ValueError("calibration member page must use admission order")
        return self


class CalibrationPublicationReadyQuery(_CalibrationWireModel):
    """Bound one finite traversal of ready automatic-publication work."""

    capabilities: tuple[CalibrationPublicationPolicyRef, ...] = Field(
        default=(),
        max_length=200,
    )
    cursor: int | None = Field(default=None, ge=1)
    through_sequence: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        value: tuple[CalibrationPublicationPolicyRef, ...],
    ) -> tuple[CalibrationPublicationPolicyRef, ...]:
        _require_unique(
            (capability.model_dump_json() for capability in value),
            label="calibration publication capability",
        )
        return value

    @model_validator(mode="after")
    def validate_traversal(self) -> CalibrationPublicationReadyQuery:
        _require_traversal_pair(
            cursor=self.cursor,
            through_sequence=self.through_sequence,
            cursor_name="calibration publication ready cursor",
        )
        return self


class CalibrationPublicationReadyItem(_CalibrationWireModel):
    """One ready occurrence with every exact input needed for finalization."""

    sequence: int = Field(ge=1)
    cohort: CalibrationCohortSummary
    finalization: CalibrationCohortFinalization
    enqueued_at: datetime

    @field_validator("enqueued_at")
    @classmethod
    def canonicalize_enqueued_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="enqueued_at")

    @model_validator(mode="after")
    def validate_occurrence(self) -> CalibrationPublicationReadyItem:
        finalization = self.finalization
        if finalization.state != "ready":
            raise ValueError("publication ready item requires ready finalization")
        if (
            finalization.cohort_id != self.cohort.cohort_id
            or finalization.spec_hash != self.cohort.spec_hash
            or finalization.policy.calibration != self.cohort.planner
        ):
            raise ValueError(
                "publication ready item must match its exact cohort summary"
            )
        if self.enqueued_at != finalization.ready_at:
            raise ValueError(
                "publication ready occurrence must match its readiness time"
            )
        return self


class CalibrationPublicationReadyPage(_CalibrationWireModel):
    """One insertion-oldest page within a finite ready-work traversal."""

    items: tuple[CalibrationPublicationReadyItem, ...] = Field(
        default=(),
        max_length=200,
    )
    next_cursor: int | None = Field(default=None, ge=1)
    through_sequence: int | None = Field(default=None, ge=1)

    @field_validator("items")
    @classmethod
    def validate_items(
        cls,
        value: tuple[CalibrationPublicationReadyItem, ...],
    ) -> tuple[CalibrationPublicationReadyItem, ...]:
        sequences = tuple(item.sequence for item in value)
        if sequences != tuple(sorted(sequences)):
            raise ValueError(
                "calibration publication ready page must use insertion order"
            )
        _require_unique(sequences, label="calibration publication ready sequence")
        _require_unique(
            (item.finalization.cohort_id for item in value),
            label="calibration publication ready cohort id",
        )
        return value

    @model_validator(mode="after")
    def validate_traversal(self) -> CalibrationPublicationReadyPage:
        _require_traversal_pair(
            cursor=self.next_cursor,
            through_sequence=self.through_sequence,
            cursor_name="next calibration publication ready cursor",
        )
        if self.next_cursor is not None:
            if not self.items or self.next_cursor != self.items[-1].sequence:
                raise ValueError(
                    "next publication cursor must match the last ready sequence"
                )
            if any(
                item.sequence > self.through_sequence
                for item in self.items
                if self.through_sequence is not None
            ):
                raise ValueError(
                    "publication ready page cannot exceed its traversal high-water"
                )
        return self


class CalibrationPublicationGetQuery(_CalibrationWireModel):
    """Read exact finalization state for response-loss reconciliation."""

    cohort_id: _NonEmptyText

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration publication cohort id")


class CalibrationPublicationGetReceipt(_CalibrationWireModel):
    """Current canonical finalization for one cohort."""

    finalization: CalibrationCohortFinalization


class CalibrationPublicationAttentionCommand(_CalibrationWireModel):
    """Move one exact ready finalization to durable operator attention."""

    cohort_id: _NonEmptyText
    policy: CalibrationPublicationPolicyRef
    expected_finalization_revision: int = Field(ge=1)
    actor: _NonEmptyText
    reason: _NonEmptyText

    @field_validator("cohort_id", "actor", "reason")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration publication attention")


class CalibrationPublicationAttentionReceipt(_CalibrationWireModel):
    """Exact attention-required state after compare-and-swap."""

    finalization: CalibrationCohortFinalization

    @model_validator(mode="after")
    def validate_attention(self) -> CalibrationPublicationAttentionReceipt:
        if self.finalization.state != "attention_required":
            raise ValueError(
                "publication attention receipt requires attention-required state"
            )
        return self


class CalibrationPublicationRetryCommand(_CalibrationWireModel):
    """Return one exact attention-required finalization to ready work."""

    cohort_id: _NonEmptyText
    policy: CalibrationPublicationPolicyRef
    expected_finalization_revision: int = Field(ge=1)
    actor: _NonEmptyText
    reason: _NonEmptyText

    @field_validator("cohort_id", "actor", "reason")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration publication retry")


class CalibrationPublicationRetryReceipt(_CalibrationWireModel):
    """Exact ready state after retry compare-and-swap."""

    finalization: CalibrationCohortFinalization

    @model_validator(mode="after")
    def validate_ready(self) -> CalibrationPublicationRetryReceipt:
        finalization = self.finalization
        if finalization.state != "ready":
            raise ValueError("publication retry receipt requires ready state")
        if not (
            finalization.ready_at
            == finalization.updated_at
            == finalization.available_at
        ):
            raise ValueError(
                "publication retry receipt requires a newly ready occurrence"
            )
        return self


class CalibrationPublicationDeferCommand(_CalibrationWireModel):
    """Delay one transiently blocked ready finalization without attention."""

    cohort_id: _NonEmptyText
    policy: CalibrationPublicationPolicyRef
    expected_finalization_revision: int = Field(ge=1)
    retry_after_seconds: int = Field(
        ge=1,
        le=MAX_CALIBRATION_PUBLICATION_RETRY_AFTER_SECONDS,
    )
    reason: _NonEmptyText

    @field_validator("cohort_id", "reason")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration publication defer")


class CalibrationPublicationDeferReceipt(_CalibrationWireModel):
    """Exact still-ready state with server-clock availability after defer."""

    finalization: CalibrationCohortFinalization

    @model_validator(mode="after")
    def validate_ready(self) -> CalibrationPublicationDeferReceipt:
        finalization = self.finalization
        if finalization.state != "ready":
            raise ValueError("publication defer receipt requires ready state")
        if (
            finalization.available_at is None
            or finalization.available_at <= finalization.updated_at
        ):
            raise ValueError(
                "publication defer receipt requires future server availability"
            )
        return self


def _validate_complete_members(
    cohort: CalibrationCohort,
    members: tuple[CalibrationCohortMember, ...],
) -> None:
    if len(members) != len(cohort.spec.members):
        raise ValueError("calibration create receipt requires every cohort member")
    for index, (member, spec) in enumerate(
        zip(members, cohort.spec.members, strict=True)
    ):
        if member.cohort_id != cohort.cohort_id:
            raise ValueError("calibration receipt member must match its cohort")
        if member.index != index:
            raise ValueError("calibration receipt members must use admission order")
        if member.spec != spec:
            raise ValueError("calibration receipt member must match its exact spec")
        if member.admitted_at != cohort.created_at:
            raise ValueError(
                "calibration receipt member admission must match cohort creation"
            )
    _require_unique(
        (member.procedure_run_id for member in members),
        label="calibration receipt procedure run id",
    )


def _non_blank(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_unique(values: Iterable[Hashable], *, label: str) -> None:
    selected = tuple(values)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label}s must be unique")


def _require_traversal_pair(
    *,
    cursor: int | None,
    through_sequence: int | None,
    cursor_name: str,
) -> None:
    if (cursor is None) != (through_sequence is None):
        raise ValueError(
            f"{cursor_name} and through_sequence must be provided together"
        )
    if (
        cursor is not None
        and through_sequence is not None
        and cursor >= through_sequence
    ):
        raise ValueError(f"{cursor_name} must be below through_sequence")


def _canonical_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


__all__ = [
    "MAX_CALIBRATION_PUBLICATION_RETRY_AFTER_SECONDS",
    "CalibrationCohortCreateCommand",
    "CalibrationCohortCreateReceipt",
    "CalibrationCohortGetQuery",
    "CalibrationCohortGetReceipt",
    "CalibrationCohortListQuery",
    "CalibrationCohortMemberListQuery",
    "CalibrationCohortMemberPage",
    "CalibrationCohortPage",
    "CalibrationPublicationAttentionCommand",
    "CalibrationPublicationAttentionReceipt",
    "CalibrationPublicationDeferCommand",
    "CalibrationPublicationDeferReceipt",
    "CalibrationPublicationGetQuery",
    "CalibrationPublicationGetReceipt",
    "CalibrationPublicationReadyItem",
    "CalibrationPublicationReadyPage",
    "CalibrationPublicationReadyQuery",
    "CalibrationPublicationRetryCommand",
    "CalibrationPublicationRetryReceipt",
    "CalibrationStatusQuery",
    "CalibrationStatusReceipt",
]
