"""Point-domain scan intents shared by authoring and compilation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import validate_literal
from scopecat.program.expressions import ParameterLookupUse
from scopecat.program.input_capture import capture_runtime_input
from scopecat.program.parameters import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.program.value_refs import (
    ScalarOperand,
    ValueRef,
    internal_value_ref_parameter_contracts,
    internal_value_ref_parameter_lookup,
    internal_value_ref_point_id,
)

type ScanValue = Quantity | EntityRef | str | int | float | bool | None
type ScanCenter = ValueRef | Quantity
type ScanRangeValue = Quantity | int | float
type PointRow = Mapping[ValueRef, ScanValue]


@dataclass(frozen=True, slots=True)
class ValuesScanSource:
    values: tuple[ScanValue, ...]


@dataclass(frozen=True, slots=True)
class AroundScanSource:
    """A fixed-count linear axis around one explicit center."""

    center: ScanCenter
    span: Quantity
    points: int


@dataclass(frozen=True, slots=True)
class RangeScanSource:
    """A fixed-count linear axis between two literal coordinate endpoints."""

    start: ScanRangeValue
    stop: ScanRangeValue
    points: int


type ScanSource = ValuesScanSource | AroundScanSource | RangeScanSource


@dataclass(frozen=True, slots=True, repr=False)
class AxisSpec:
    id: str
    value_type: Scalar
    source: ScanSource
    parameter_lookup: ValueRef | None = None


@dataclass(frozen=True, slots=True, repr=False)
class GridSpec:
    """One declaration-ordered Cartesian point domain."""

    axes: tuple[AxisSpec, ...] = ()

    def __post_init__(self) -> None:
        _require_unique_axis_ids(self.axes, context="grid")


@dataclass(frozen=True, slots=True, repr=False)
class PointsSpec:
    """One ordered point cloud represented by equal-length coordinate columns."""

    axes: tuple[AxisSpec, ...] = ()

    def __post_init__(self) -> None:
        _require_unique_axis_ids(self.axes, context="points")
        sources = tuple(axis.source for axis in self.axes)
        if any(not isinstance(source, ValuesScanSource) for source in sources):
            raise TypeError("point-cloud columns require explicit values")
        lengths = {len(cast("ValuesScanSource", source).values) for source in sources}
        if len(lengths) > 1:
            raise ValueError("point-cloud columns must have equal lengths")


type PointDomainSpec = GridSpec | PointsSpec


@dataclass(frozen=True, slots=True)
class PointPlan:
    """One complete logical point plan for an experiment invocation."""

    domain: PointDomainSpec = field(default_factory=GridSpec)


def points_spec(
    rows: Sequence[PointRow],
    *,
    coordinates: Sequence[ValueRef] = (),
) -> PointsSpec:
    """Capture ordered point rows as equal-length typed coordinate columns."""

    selected_rows = tuple(rows)
    selected_coordinates = tuple(coordinates)
    if not selected_coordinates and selected_rows:
        selected_coordinates = tuple(selected_rows[0])
    if selected_rows and not selected_coordinates:
        raise ValueError("non-empty points require at least one coordinate column")
    coordinate_specs = tuple(
        _point_coordinate(coordinate) for coordinate in selected_coordinates
    )
    _require_unique_ids(
        tuple(axis_id for _coordinate, axis_id, _value_type in coordinate_specs),
        context="points",
    )
    expected = frozenset(selected_coordinates)
    for row in selected_rows:
        if frozenset(row) != expected:
            raise ValueError(
                "points rows must contain the same typed coordinate columns"
            )
    return PointsSpec(
        tuple(
            AxisSpec(
                id=axis_id,
                value_type=value_type,
                source=ValuesScanSource(
                    tuple(
                        _capture_point_value(
                            value_type,
                            axis_id,
                            row[coordinate],
                            row_index=row_index,
                        )
                        for row_index, row in enumerate(selected_rows)
                    )
                ),
            )
            for coordinate, axis_id, value_type in coordinate_specs
        )
    )


def _point_coordinate(coordinate: ValueRef) -> tuple[ValueRef, str, Scalar]:
    coordinate_id = internal_value_ref_point_id(coordinate)
    if coordinate_id is None:
        raise TypeError("points coordinates must be created with scopecat.coordinate")
    if not isinstance(coordinate.value_type, Scalar):
        raise TypeError("points coordinates must carry scalar value types")
    return coordinate, coordinate_id, coordinate.value_type


def _capture_point_value(
    value_type: Scalar,
    coordinate_id: str,
    value: ScanValue,
    *,
    row_index: int,
) -> ScanValue:
    validate_literal(
        value_type,
        value,
        path=("points", "rows", row_index, coordinate_id),
    )
    return cast("ScanValue", capture_runtime_input(value))


def _require_unique_axis_ids(
    axes: Sequence[AxisSpec],
    *,
    context: str,
) -> None:
    _require_unique_ids(tuple(axis.id for axis in axes), context=context)


def _require_unique_ids(ids: Sequence[str], *, context: str) -> None:
    if any(not axis_id for axis_id in ids):
        raise ValueError(f"{context} axis ids must be non-empty")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{context} axis ids must be unique")


def parameter_cell_lookup(
    axis: AxisSpec,
) -> tuple[
    ParameterLookupUse,
    tuple[tuple[str, ScalarOperand], ...],
]:
    if axis.parameter_lookup is None:
        raise TypeError("scan axis does not overlay a parameter cell")
    lookup = internal_value_ref_parameter_lookup(axis.parameter_lookup)
    assert lookup is not None
    return lookup


def scan_parameter_contracts(scan: AxisSpec) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        _value_parameter_contracts(scan.parameter_lookup),
        _source_parameter_contracts(scan),
    )


def _source_parameter_contracts(axis: AxisSpec) -> tuple[ParameterContract, ...]:
    source = axis.source
    if not isinstance(source, AroundScanSource):
        return ()
    return _value_parameter_contracts(source.center)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )
