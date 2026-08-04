"""Durable operator intent for structured experiment runs.

These records are deliberately smaller than the compiler's bound plan. They
capture what the operator requested and are safe to persist without treating
compiler or runtime internals as a stable wire format.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    model_validator,
)

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units
from scopecat.records._run_request_values import (
    DurableRunRequestModel,
    normalize_json_value,
    normalize_run_request_value,
)
from scopecat.records.run import RunStageLineage

type RunRequestJsonValue = Annotated[
    str
    | bool
    | int
    | float
    | None
    | list[RunRequestJsonValue]
    | dict[str, RunRequestJsonValue],
    BeforeValidator(normalize_json_value),
]


class _RunRequestModel(DurableRunRequestModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunRequestEntityRef(_RunRequestModel):
    """Closed durable projection of an authoring ``EntityRef``."""

    kind: Literal["entity"] = "entity"
    entity_id: str
    entity_kind: str | None = None
    metadata: dict[str, RunRequestJsonValue] = Field(default_factory=dict)


class RunRequestParameterValue(_RunRequestModel):
    kind: Literal["parameter"] = "parameter"
    parameter_id: str


class RunRequestParameterLookupValue(_RunRequestModel):
    kind: Literal["parameter_lookup"] = "parameter_lookup"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str


type RunRequestBinaryOperator = Literal[
    "+",
    "-",
    "*",
    "/",
]


class RunRequestBinaryValue(_RunRequestModel):
    kind: Literal["binary"] = "binary"
    operator: RunRequestBinaryOperator
    left: RunRequestScalarValue
    right: RunRequestScalarValue


type RunRequestExpressionValue = Annotated[
    RunRequestParameterValue | RunRequestParameterLookupValue | RunRequestBinaryValue,
    Field(discriminator="kind"),
]


type RunRequestScalarValue = Annotated[
    Quantity
    | RunRequestEntityRef
    | RunRequestExpressionValue
    | str
    | bool
    | int
    | float
    | None,
    BeforeValidator(normalize_run_request_value),
]
type RunRequestValue = Annotated[
    RunRequestScalarValue | list[RunRequestValue] | dict[str, RunRequestValue],
    Field(union_mode="left_to_right"),
    BeforeValidator(normalize_run_request_value),
]


type RunRequestQuantity = Annotated[
    Quantity,
    BeforeValidator(normalize_run_request_value),
]
type RunRequestRangeValue = Annotated[
    Quantity | StrictInt | StrictFloat,
    BeforeValidator(normalize_run_request_value),
]


_RECURSIVE_REQUEST_MODELS = (
    RunRequestParameterLookupValue,
    RunRequestBinaryValue,
)
for _model in _RECURSIVE_REQUEST_MODELS:
    _model.model_rebuild(
        _types_namespace={
            "RunRequestScalarValue": RunRequestScalarValue,
            "RunRequestExpressionValue": RunRequestExpressionValue,
        }
    )


class AxisValuesSourceRecord(_RunRequestModel):
    """Persisted explicit values for one axis."""

    kind: Literal["values"] = "values"
    values: list[RunRequestScalarValue]


class AxisAroundSourceRecord(_RunRequestModel):
    """Persisted fixed-count axis centered on a scalar expression."""

    kind: Literal["around"] = "around"
    center: RunRequestScalarValue
    span: RunRequestQuantity
    points: int = Field(ge=2)


class AxisRangeSourceRecord(_RunRequestModel):
    """Persisted fixed-count linear axis between two endpoints."""

    kind: Literal["range"] = "range"
    start: RunRequestRangeValue
    stop: RunRequestRangeValue
    points: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_endpoints(self) -> AxisRangeSourceRecord:
        _validate_range_endpoints(self.start, self.stop)
        return self


def _validate_range_endpoints(
    start: Quantity | float,
    stop: Quantity | float,
) -> None:
    if isinstance(start, Quantity) != isinstance(stop, Quantity):
        raise ValueError("range endpoints must both be quantities or both be numeric")
    if (
        isinstance(start, Quantity)
        and isinstance(stop, Quantity)
        and not compatible_units(start.unit, stop.unit)
    ):
        raise ValueError("range quantity endpoints must use compatible units")


type AxisSourceRecord = Annotated[
    AxisValuesSourceRecord | AxisAroundSourceRecord | AxisRangeSourceRecord,
    Field(discriminator="kind"),
]


class AxisRecord(_RunRequestModel):
    """Persisted axis source and its optional parameter-cell overlay."""

    axis_id: str = Field(min_length=1)
    source: AxisSourceRecord
    overlay: RunRequestParameterLookupValue | None = None

    @model_validator(mode="after")
    def validate_overlay(self) -> AxisRecord:
        if (
            isinstance(self.source, AxisAroundSourceRecord)
            and self.overlay is not None
            and self.source.center != self.overlay
        ):
            raise ValueError("an around-axis overlay must also be its center")
        return self


class GridDomainRecord(_RunRequestModel):
    """Persisted Cartesian point domain with declaration-ordered axes.

    An empty axis list denotes the unit point rather than an empty domain.
    """

    kind: Literal["grid"] = "grid"
    axes: list[AxisRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_axes(self) -> GridDomainRecord:
        axis_ids = [axis.axis_id for axis in self.axes]
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("grid axis ids must be unique")
        return self


class PointCloudDomainRecord(_RunRequestModel):
    """Persisted ordered point-cloud rows with declaration-ordered columns."""

    kind: Literal["points"] = "points"
    columns: list[str]
    rows: list[dict[str, RunRequestScalarValue]]

    @model_validator(mode="after")
    def validate_rows(self) -> PointCloudDomainRecord:
        if any(not column for column in self.columns):
            raise ValueError("point-cloud column ids must be non-empty")
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("point-cloud column ids must be unique")
        expected = set(self.columns)
        if self.rows and not expected:
            raise ValueError("non-empty point-cloud rows require coordinate columns")
        if any(set(row) != expected for row in self.rows):
            raise ValueError(
                "point-cloud rows must contain exactly the declared coordinate columns"
            )
        return self


type PointDomainRecord = Annotated[
    GridDomainRecord | PointCloudDomainRecord,
    Field(discriminator="kind"),
]


class PointPlanRecord(_RunRequestModel):
    """Persisted base point domain and its execution-independent expansion policy."""

    domain: PointDomainRecord = Field(default_factory=GridDomainRecord)
    repeat: StrictInt = Field(default=1, ge=1)
    repeat_mode: Literal["point", "sweep"] = "point"
    traversal: Literal["forward", "snake"] = "forward"

    @model_validator(mode="after")
    def validate_policy(self) -> PointPlanRecord:
        if (
            isinstance(self.domain, PointCloudDomainRecord)
            and self.traversal == "snake"
        ):
            raise ValueError("snake traversal requires a Cartesian grid point domain")
        if self.repeat > 1 and _point_domain_ids(self.domain).intersection({"repeat"}):
            raise ValueError(
                "repeated point plans reserve the base coordinate id 'repeat'"
            )
        return self


def _point_domain_ids(domain: PointDomainRecord) -> set[str]:
    if isinstance(domain, GridDomainRecord):
        return {axis.axis_id for axis in domain.axes}
    return set(domain.columns)


class RunRequest(_RunRequestModel):
    """Operator request for one structured run."""

    experiment_id: str | None = None
    inputs: dict[str, RunRequestValue] = Field(default_factory=dict)
    operator: str | None = None
    point_plan: PointPlanRecord = Field(default_factory=PointPlanRecord)
    stage: RunStageLineage | None = None
    metadata: dict[str, RunRequestJsonValue] = Field(default_factory=dict)


__all__ = [
    "AxisAroundSourceRecord",
    "AxisRangeSourceRecord",
    "AxisRecord",
    "AxisSourceRecord",
    "AxisValuesSourceRecord",
    "GridDomainRecord",
    "PointCloudDomainRecord",
    "PointDomainRecord",
    "PointPlanRecord",
    "RunRequest",
    "RunRequestBinaryOperator",
    "RunRequestBinaryValue",
    "RunRequestEntityRef",
    "RunRequestExpressionValue",
    "RunRequestJsonValue",
    "RunRequestParameterLookupValue",
    "RunRequestParameterValue",
    "RunRequestQuantity",
    "RunRequestRangeValue",
    "RunRequestScalarValue",
    "RunRequestValue",
]
