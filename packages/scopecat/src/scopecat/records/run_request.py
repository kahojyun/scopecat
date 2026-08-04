"""Durable operator intent for structured experiment runs.

These records are deliberately smaller than the compiler's bound plan. They
capture what the operator requested and are safe to persist without treating
compiler or runtime internals as a stable wire format.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
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


class _RunRequestModel(BaseModel):
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


class PointScanRecord(_RunRequestModel):
    """Persisted point-value scan axis record."""

    kind: Literal["point"] = "point"
    axis_id: str
    values: list[RunRequestScalarValue]


class AroundScanRecord(_RunRequestModel):
    """Persisted center/span scan axis record."""

    kind: Literal["scan"] = "scan"
    axis_id: str
    center: RunRequestScalarValue
    span: RunRequestQuantity
    points: int = Field(ge=2)


class RangeScanRecord(_RunRequestModel):
    """Persisted fixed-count linear coordinate range."""

    kind: Literal["range"] = "range"
    axis_id: str
    start: RunRequestRangeValue
    stop: RunRequestRangeValue
    points: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_endpoints(self) -> RangeScanRecord:
        _validate_range_endpoints(self.start, self.stop)
        return self


class ParameterScanRecord(_RunRequestModel):
    """Persisted parameter-table scan axis record."""

    kind: Literal["parameter"] = "parameter"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str
    axis_id: str
    values: list[RunRequestScalarValue]


class ParameterAroundScanRecord(_RunRequestModel):
    """Persisted locator and shape for a snapshot-centered parameter overlay.

    The accepted snapshot supplies the center during specialization rather
    than persisting a copied value, preserving the request's parameter intent
    while each run still records the exact snapshot it accepted.
    """

    kind: Literal["parameter_around"] = "parameter_around"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str
    axis_id: str
    span: RunRequestQuantity
    points: int = Field(ge=2)


class ParameterRangeScanRecord(_RunRequestModel):
    """Persisted parameter-table range scan axis record."""

    kind: Literal["parameter_range"] = "parameter_range"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str
    axis_id: str
    start: RunRequestRangeValue
    stop: RunRequestRangeValue
    points: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_endpoints(self) -> ParameterRangeScanRecord:
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


type ScanRecord = Annotated[
    PointScanRecord
    | AroundScanRecord
    | RangeScanRecord
    | ParameterScanRecord
    | ParameterAroundScanRecord
    | ParameterRangeScanRecord,
    Field(discriminator="kind"),
]


class GridDomainRecord(_RunRequestModel):
    """Persisted Cartesian point domain with declaration-ordered axes.

    An empty axis list denotes the unit point rather than an empty domain.
    """

    kind: Literal["grid"] = "grid"
    axes: list[ScanRecord] = Field(default_factory=list)


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


class RunRequest(_RunRequestModel):
    """Operator request for one structured run."""

    experiment_id: str | None = None
    inputs: dict[str, RunRequestValue] = Field(default_factory=dict)
    operator: str | None = None
    point_domain: PointDomainRecord = Field(default_factory=GridDomainRecord)
    stage: RunStageLineage | None = None
    metadata: dict[str, RunRequestJsonValue] = Field(default_factory=dict)
