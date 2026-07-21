"""Durable operator intent for structured experiment runs.

These records are deliberately smaller than the compiler's linked program. They
capture what the operator requested and are safe to persist without treating
compiler or runtime internals as a stable wire format.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from scopecat.records._run_request_values import (
    normalize_json_value,
    normalize_run_request_value,
)
from scopecat.records.parameter import Quantity

RUN_REQUEST_SCHEMA_VERSION = "scopecat.run_request.v4"


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


class RunRequestAxisValue(_RunRequestModel):
    kind: Literal["axis"] = "axis"
    axis_id: str


class RunRequestInputValue(_RunRequestModel):
    kind: Literal["input"] = "input"
    input_id: str


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
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "and",
    "or",
]


class RunRequestBinaryValue(_RunRequestModel):
    kind: Literal["binary"] = "binary"
    operator: RunRequestBinaryOperator
    left: RunRequestScalarValue
    right: RunRequestScalarValue


type RunRequestExpressionValue = Annotated[
    RunRequestAxisValue
    | RunRequestInputValue
    | RunRequestParameterValue
    | RunRequestParameterLookupValue
    | RunRequestBinaryValue,
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
    target_id: str
    axis_id: str
    values: list[RunRequestScalarValue]
    unit: str | None = None


class AroundScanRecord(_RunRequestModel):
    """Persisted center/span scan axis record."""

    kind: Literal["scan"] = "scan"
    target_id: str
    axis_id: str
    center: RunRequestScalarValue
    span: RunRequestScalarValue
    points: int


class ParameterScanRecord(_RunRequestModel):
    """Persisted parameter-table scan axis record."""

    kind: Literal["parameter"] = "parameter"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str
    axis_id: str
    values: list[RunRequestScalarValue]
    unit: str | None = None


class ParameterAroundScanRecord(_RunRequestModel):
    """Persisted locator and shape for a snapshot-centered parameter scan.

    The accepted snapshot supplies the center during specialization rather
    than persisting a copied value, preserving the request's parameter intent
    while each run still records the exact snapshot it accepted.
    """

    kind: Literal["parameter_around"] = "parameter_around"
    table_id: str
    key: dict[str, RunRequestScalarValue]
    column: str
    axis_id: str
    span: RunRequestScalarValue
    points: int


class ScanGroupRecord(_RunRequestModel):
    """Persisted explicit scan composition record."""

    kind: Literal["cartesian", "zip"]
    scans: list[ScanRecord]


type ParameterScanLeafRecord = ParameterScanRecord | ParameterAroundScanRecord
type ScanLeafRecord = PointScanRecord | AroundScanRecord | ParameterScanLeafRecord
type ScanRecord = Annotated[
    PointScanRecord
    | AroundScanRecord
    | ParameterScanRecord
    | ParameterAroundScanRecord
    | ScanGroupRecord,
    Field(discriminator="kind"),
]

ScanGroupRecord.model_rebuild()


class RunRequest(_RunRequestModel):
    """Operator request for one structured run segment."""

    schema_version: Literal["scopecat.run_request.v4"] = RUN_REQUEST_SCHEMA_VERSION
    id: str
    template_id: str | None = None
    template_inputs: dict[str, RunRequestValue] = Field(default_factory=dict)
    config_source: str | None = None
    operator: str | None = None
    scans: list[ScanRecord] = Field(default_factory=list)
    segment_lineage: dict[str, RunRequestJsonValue] = Field(default_factory=dict)
    metadata: dict[str, RunRequestJsonValue] = Field(default_factory=dict)


def scan_axis_index(
    scans: Sequence[ScanRecord],
) -> dict[str, ScanLeafRecord]:
    """Return a flat ``axis_id`` index derived from canonical scan records."""

    axes: dict[str, ScanLeafRecord] = {}
    for scan in scans:
        for leaf in _scan_record_leaves(scan):
            axes[leaf.axis_id] = leaf
    return axes


def parameter_scan_records(
    scans: Sequence[ScanRecord],
) -> list[ParameterScanLeafRecord]:
    """Return parameter-scan leaves derived from canonical scan records."""

    return [
        leaf
        for scan in scans
        for leaf in _scan_record_leaves(scan)
        if isinstance(leaf, ParameterScanRecord | ParameterAroundScanRecord)
    ]


def _scan_record_leaves(scan: ScanRecord) -> tuple[ScanLeafRecord, ...]:
    if not isinstance(scan, ScanGroupRecord):
        return (scan,)
    return tuple(leaf for child in scan.scans for leaf in _scan_record_leaves(child))
