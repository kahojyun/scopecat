"""Structured, machine-readable findings reported at Scopecat boundaries.

A ``Problem`` describes an expected domain finding; it is not Python control
flow, a run outcome, a live event, or a log record. Codes are stable
domain-owned strings, while messages are presentation text and must not be
parsed. Machine-readable context belongs in details and structural locations,
never in delimiter-packed path strings. Advisory problems inform callers;
blocking problems prevent the owning phase from completing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping, thaw_json_value

type LocationPathItem = str | int


class ProblemImpact(StrEnum):
    """Whether a problem only informs the caller or prevents an operation."""

    ADVISORY = "advisory"
    BLOCKING = "blocking"


class ProblemCategory(StrEnum):
    """Stable machine-oriented classification independent of presentation."""

    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    DATA_INTEGRITY = "data_integrity"
    STORAGE = "storage"
    PROVIDER_CONTRACT = "provider_contract"
    UNAVAILABLE = "unavailable"
    OPERATION = "operation"
    EXTERNAL_FAILURE = "external_failure"
    INTERRUPTED = "interrupted"


class ProblemPhase(StrEnum):
    """Pipeline boundary at which a problem was established."""

    DEFINITION = "definition"
    AUTHORING = "authoring"
    CONFIGURATION = "configuration"
    PLANNING = "planning"
    PROVIDER_PREFLIGHT = "provider_preflight"
    EXECUTION = "execution"
    PERSISTENCE = "persistence"
    ANALYSIS = "analysis"
    IMPORTING = "importing"


class _LocationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class ModelLocation(_LocationModel):
    """A path within a public model or transient compiler structure."""

    kind: Literal["model"] = "model"
    root: str
    path: tuple[LocationPathItem, ...] = ()

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: str) -> str:
        selected = _non_empty(value, field="model location root")
        if "." in selected or "[" in selected or "]" in selected:
            msg = "model location root must not contain path delimiters"
            raise ValueError(msg)
        return selected

    @field_validator("path")
    @classmethod
    def validate_path(
        cls,
        value: tuple[LocationPathItem, ...],
    ) -> tuple[LocationPathItem, ...]:
        return _validate_path(value)


class StorageLocation(_LocationModel):
    """A location in project storage or one durable run namespace."""

    kind: Literal["storage"] = "storage"
    run_id: str | None = None
    ref: str | None = None
    path: tuple[LocationPathItem, ...] = ()

    @field_validator("run_id", "ref")
    @classmethod
    def validate_optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _non_empty(value, field="storage identity")

    @field_validator("path")
    @classmethod
    def validate_path(
        cls,
        value: tuple[LocationPathItem, ...],
    ) -> tuple[LocationPathItem, ...]:
        return _validate_path(value)

    @model_validator(mode="after")
    def validate_identity(self) -> StorageLocation:
        if self.run_id is None and self.ref is None and not self.path:
            msg = "storage location requires run_id, ref, or path"
            raise ValueError(msg)
        return self


class ExternalLocation(_LocationModel):
    """A location in an imported document or other external source."""

    kind: Literal["external"] = "external"
    uri: str
    sheet: str | None = None
    row: int | None = None
    column: int | str | None = None
    path: tuple[LocationPathItem, ...] = ()

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        return _non_empty(value, field="external location URI")

    @field_validator("sheet")
    @classmethod
    def validate_sheet(cls, value: str | None) -> str | None:
        return None if value is None else _non_empty(value, field="sheet")

    @field_validator("row")
    @classmethod
    def validate_row(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            msg = "external location row must be positive"
            raise ValueError(msg)
        return value

    @field_validator("column")
    @classmethod
    def validate_column(cls, value: int | str | None) -> int | str | None:
        if isinstance(value, int) and value <= 0:
            msg = "external location column must be positive"
            raise ValueError(msg)
        if isinstance(value, str):
            return _non_empty(value, field="external location column")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(
        cls,
        value: tuple[LocationPathItem, ...],
    ) -> tuple[LocationPathItem, ...]:
        return _validate_path(value)


class RuntimeLocation(_LocationModel):
    """A location in a live or durably recorded run operation."""

    kind: Literal["runtime"] = "runtime"
    run_id: str | None = None
    operation_id: str | None = None
    point_index: int | None = None
    instrument_id: str | None = None

    @field_validator("run_id", "operation_id", "instrument_id")
    @classmethod
    def validate_optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _non_empty(value, field="runtime identity")

    @field_validator("point_index")
    @classmethod
    def validate_point_index(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            msg = "runtime point_index must be non-negative"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> RuntimeLocation:
        if (
            self.run_id is None
            and self.operation_id is None
            and self.point_index is None
            and self.instrument_id is None
        ):
            msg = "runtime location requires at least one identity field"
            raise ValueError(msg)
        return self


type ProblemLocation = Annotated[
    ModelLocation | StorageLocation | ExternalLocation | RuntimeLocation,
    Field(discriminator="kind"),
]


def _empty_details() -> Mapping[str, object]:
    return FrozenMapping()


class Problem(BaseModel):
    """One expected, structured finding without presentation policy."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.problem.v1"] = "scopecat.problem.v1"
    code: str
    impact: ProblemImpact
    category: ProblemCategory
    phase: ProblemPhase
    message: str
    location: ProblemLocation | None = None
    related_locations: tuple[ProblemLocation, ...] = ()
    details: Mapping[str, object] = Field(default_factory=_empty_details)
    occurrence_id: str | None = None

    @field_validator("code", "message")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _non_empty(value, field="problem text")

    @field_validator("occurrence_id")
    @classmethod
    def validate_occurrence_id(cls, value: str | None) -> str | None:
        return None if value is None else _non_empty(value, field="occurrence_id")

    @field_validator("details", mode="after")
    @classmethod
    def validate_details(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        return freeze_json_mapping(value, path="problem details")

    @field_serializer("details")
    def serialize_details(self, value: Mapping[str, object]) -> object:
        return thaw_json_value(value)


def model_location(root: str, *path: LocationPathItem) -> ModelLocation:
    """Build a structured model location without delimiter-packed paths."""

    return ModelLocation(root=root, path=path)


def blocking_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory,
    phase: ProblemPhase,
    location: ProblemLocation | None = None,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
    occurrence_id: str | None = None,
) -> Problem:
    """Build a blocking problem while keeping classification explicit."""

    return Problem(
        code=code,
        impact=ProblemImpact.BLOCKING,
        category=category,
        phase=phase,
        message=message,
        location=location,
        related_locations=tuple(related_locations),
        details={} if details is None else details,
        occurrence_id=occurrence_id,
    )


def has_blocking_problems(problems: Sequence[Problem]) -> bool:
    """Return whether a problem collection prevents its operation."""

    return any(problem.impact is ProblemImpact.BLOCKING for problem in problems)


def _non_empty(value: str, *, field: str) -> str:
    if not value:
        msg = f"{field} must be non-empty"
        raise ValueError(msg)
    return value


def _validate_path(
    path: tuple[LocationPathItem, ...],
) -> tuple[LocationPathItem, ...]:
    for item in path:
        if isinstance(item, int):
            if item < 0:
                msg = "location path indexes must be non-negative"
                raise ValueError(msg)
        elif not item:
            msg = "location path segments must be non-empty"
            raise ValueError(msg)
    return path
