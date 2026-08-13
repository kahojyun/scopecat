"""Exact backend-neutral model for ordered logical point domains."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from math import isfinite, prod
from typing import Generic, Never, TypeVar

from scopecat.kernel.point_identity import PointDomainLayout
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.program.scans import ScanRangeValue

type PointDomainPath = tuple[str | int, ...]

CenterT_co = TypeVar("CenterT_co", covariant=True)


def is_point_coordinate_type(value_type: Scalar) -> bool:
    """Return whether a scalar belongs to the dataset coordinate domain."""

    return isinstance(
        value_type.atom,
        Bool | Int | Float | String | QuantityType | Entity,
    )


def point_axis_linear_value(
    center: Quantity,
    span: Quantity,
    count: int,
    index: int,
) -> Quantity:
    """Return one exact value from a fixed-count linear point axis."""

    converted_span = span.to(center.unit)
    last_index = count - 1
    half_span = converted_span.value / 2
    if index == 0:
        value = center.value - half_span
    elif index == last_index:
        value = center.value + half_span
    else:
        centered_index = 2 * index - last_index
        value = center.value + (
            converted_span.value * centered_index / (2 * last_index)
        )
    return Quantity(
        value=value,
        unit=center.unit,
    )


def point_axis_range_values(
    start: ScanRangeValue,
    stop: ScanRangeValue,
    count: int,
) -> tuple[ScanRangeValue, ...]:
    """Generate one inclusive coordinate range with NumPy linspace semantics."""

    return tuple(
        point_axis_range_value(start, stop, count, index) for index in range(count)
    )


def point_axis_range_value(
    start: ScanRangeValue,
    stop: ScanRangeValue,
    count: int,
    index: int,
) -> ScanRangeValue:
    """Generate one random-access value from an inclusive coordinate range."""

    if not 0 <= index < count:
        raise IndexError(index)

    if isinstance(start, Quantity):
        if not isinstance(stop, Quantity):
            msg = "range endpoints must both be quantities or both be numeric"
            raise TypeError(msg)
        converted_stop = stop.to(start.unit)
        return Quantity(
            value=_float_linspace_value(
                start.value,
                converted_stop.value,
                count,
                index,
            ),
            unit=start.unit,
        )
    if isinstance(stop, Quantity):
        msg = "range endpoints must both be quantities or both be numeric"
        raise TypeError(msg)
    if isinstance(start, bool) or isinstance(stop, bool):
        msg = "range endpoints must be numeric, not bool"
        raise TypeError(msg)
    if isinstance(start, int) and isinstance(stop, int):
        last_index = count - 1
        difference = stop - start
        if difference % last_index != 0:
            msg = "integer point axis range must have an integral step"
            raise ValueError(msg)
        step = difference // last_index
        return start + step * index
    return _float_linspace_value(float(start), float(stop), count, index)


def _float_linspace_value(
    start: float,
    stop: float,
    count: int,
    index: int,
) -> float:
    """Interpolate one finite endpoint pair without overflowing its difference."""

    if index == 0:
        return start
    if index == count - 1:
        return stop
    difference = stop - start
    if isfinite(difference):
        return start + index * (difference / (count - 1))
    weight = index / (count - 1)
    return start * (1.0 - weight) + stop * weight


@dataclass(frozen=True, slots=True)
class PointAxisValues:
    """One finite axis whose values are known literally."""

    values: tuple[CellValue, ...]


@dataclass(frozen=True, slots=True)
class PointAxisLinear(Generic[CenterT_co]):
    """One fixed-count linear axis around a possibly dynamic center."""

    center: CenterT_co
    span: Quantity
    count: int

    def __post_init__(self) -> None:
        if self.count < 2:
            msg = "linear point axis count must be at least 2"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PointAxisRange:
    """One fixed-count linear axis between literal coordinate endpoints."""

    start: ScanRangeValue
    stop: ScanRangeValue
    count: int

    def __post_init__(self) -> None:
        if self.count < 2:
            msg = "range point axis count must be at least 2"
            raise ValueError(msg)


type PointAxisSource[CenterT] = (
    PointAxisValues | PointAxisLinear[CenterT] | PointAxisRange
)


@dataclass(frozen=True, slots=True)
class PointAxis(Generic[CenterT_co]):
    """One named scalar coordinate generated by an exact axis source."""

    id: str
    value_type: Scalar
    source: PointAxisSource[CenterT_co]

    def __post_init__(self) -> None:
        TableColumn(self.id, self.value_type)


type PointAxes[CenterT] = tuple[PointAxis[CenterT], ...]


def point_axis_values(
    axis_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointAxis[Never]:
    """Build one exact literal axis."""

    return PointAxis[Never](axis_id, value_type, PointAxisValues(values))


def point_axis_linear[CenterT](
    axis_id: str,
    value_type: Scalar,
    center: CenterT,
    span: Quantity,
    count: int,
) -> PointAxis[CenterT]:
    """Build one exact fixed-count linear axis."""

    return PointAxis(
        axis_id,
        value_type,
        PointAxisLinear(center=center, span=span, count=count),
    )


def point_axis_range(
    axis_id: str,
    value_type: Scalar,
    start: ScanRangeValue,
    stop: ScanRangeValue,
    count: int,
) -> PointAxis[Never]:
    """Build one fixed-count linear coordinate range."""

    return PointAxis[Never](
        axis_id,
        value_type,
        PointAxisRange(start=start, stop=stop, count=count),
    )


def point_axis_size[CenterT](source: PointAxisSource[CenterT]) -> int:
    """Return the exact number of values generated by one point axis source."""

    return len(source.values) if isinstance(source, PointAxisValues) else source.count


def iter_point_axis_linear[CenterT](
    axes: PointAxes[CenterT],
) -> Iterator[tuple[PointDomainPath, PointAxisLinear[CenterT]]]:
    """Yield linear sources and their stable axis paths."""

    for index, axis in enumerate(axes):
        if isinstance(axis.source, PointAxisLinear):
            yield ("axes", index), axis.source


def map_point_axis_centers[CenterT, MappedCenterT](
    axes: PointAxes[CenterT],
    transform: Callable[[CenterT, PointDomainPath], MappedCenterT],
) -> PointAxes[MappedCenterT]:
    """Map linear centers while preserving the flat domain structure."""

    def map_axis(
        axis: PointAxis[CenterT],
        path: PointDomainPath,
    ) -> PointAxis[MappedCenterT]:
        source = axis.source
        mapped_source: PointAxisSource[MappedCenterT]
        if isinstance(source, PointAxisLinear):
            mapped_source = PointAxisLinear(
                center=transform(source.center, path),
                span=source.span,
                count=source.count,
            )
        else:
            mapped_source = source
        return PointAxis(axis.id, axis.value_type, mapped_source)

    return tuple(map_axis(axis, ("axes", index)) for index, axis in enumerate(axes))


class PointDomainShapeError(ValueError):
    """A domain has incompatible output columns."""

    def __init__(self, code: str, path: PointDomainPath, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PointDomainShape:
    """The ordered columns and exact cardinality of one point domain."""

    columns: tuple[TableColumn, ...]
    cardinality: int

    def __post_init__(self) -> None:
        if self.cardinality < 0:
            msg = "point-domain cardinality must be nonnegative"
            raise ValueError(msg)

    @property
    def value_type(self) -> Table:
        """Project the columns to the compiler's table type."""

        return Table(columns=self.columns)


def analyze_point_domain[CenterT](
    axes: PointAxes[CenterT],
    *,
    layout: PointDomainLayout = "product_grid",
) -> PointDomainShape:
    """Compute exact schema and cardinality from ordered point axes."""

    columns = tuple(TableColumn(axis.id, axis.value_type) for axis in axes)
    column_ids = tuple(column.id for column in columns)
    duplicates = tuple(
        sorted(
            {column_id for column_id in column_ids if column_ids.count(column_id) > 1}
        )
    )
    if duplicates:
        raise PointDomainShapeError(
            "point_domain_duplicate_columns",
            (),
            "point-domain composition produces duplicate columns: "
            + ", ".join(duplicates),
        )
    axis_sizes = tuple(point_axis_size(axis.source) for axis in axes)
    if layout == "point_cloud":
        linear_index = next(
            (
                index
                for index, axis in enumerate(axes)
                if not isinstance(axis.source, PointAxisValues)
            ),
            None,
        )
        if linear_index is not None:
            raise PointDomainShapeError(
                "point_domain_point_cloud_linear_axis",
                ("axes", linear_index, "source"),
                "point-cloud domains require explicit row values",
            )
        if len(set(axis_sizes)) > 1:
            raise PointDomainShapeError(
                "point_domain_point_cloud_length_mismatch",
                (),
                "point-cloud coordinate columns must contain the same number of rows",
            )
        cardinality = axis_sizes[0] if axis_sizes else 0
    else:
        cardinality = prod(axis_sizes)
    return PointDomainShape(columns, cardinality)
