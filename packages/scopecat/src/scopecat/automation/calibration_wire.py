"""Typed wire contracts for immutable calibration cohorts."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.automation.calibrations import (
    MAX_CALIBRATION_COHORT_MEMBERS,
    MAX_CALIBRATION_STATUS_KEYS,
    CalibrationCohort,
    CalibrationCohortMember,
    CalibrationCohortSpec,
    CalibrationCohortSummary,
    CalibrationStatusSnapshot,
    calibration_cohort_spec_hash,
)
from scopecat.records.content import Sha256ContentHash

type _NonEmptyText = Annotated[str, Field(min_length=1)]


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


__all__ = [
    "CalibrationCohortCreateCommand",
    "CalibrationCohortCreateReceipt",
    "CalibrationCohortGetQuery",
    "CalibrationCohortGetReceipt",
    "CalibrationCohortListQuery",
    "CalibrationCohortMemberListQuery",
    "CalibrationCohortMemberPage",
    "CalibrationCohortPage",
    "CalibrationStatusQuery",
    "CalibrationStatusReceipt",
]
