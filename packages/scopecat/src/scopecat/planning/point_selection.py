"""Shared coordinate contracts and Exact/Snap/Free point resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import inf
from typing import Literal, cast

from scopecat.control.models import (
    PointCoordinateSpec,
    PointCoordinateValue,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_identity import (
    quantity_comparison_values,
    scalar_values_equal,
)
from scopecat.kernel.value_types import Bool, Entity, Float, Int, Scalar, String
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_validation import coerce_literal
from scopecat.measurements.points import RunPointCatalog
from scopecat.program.point_domain import point_axis_size, point_axis_value

type PointSelectionMode = Literal["exact", "snap", "free"]


@dataclass(frozen=True, slots=True)
class ResolvedPointSelection:
    """Canonical selection and an optional authored point identity."""

    mode: PointSelectionMode
    coordinates: Mapping[str, CellValue]
    sampled_point_index: int | None = None


def point_coordinate_contract(
    catalog: RunPointCatalog,
    *,
    sampled_point_limit: int = 256,
) -> tuple[
    tuple[PointCoordinateSpec, ...],
    tuple[dict[str, PointCoordinateValue], ...],
    bool,
]:
    """Project one run catalog into bounded admitted coordinate facts."""

    if sampled_point_limit <= 0:
        raise ValueError("sampled point limit must be positive")
    axes = {axis.id: axis for axis in catalog.contract.domain_axes}
    specs: list[PointCoordinateSpec] = []
    for column in catalog.contract.coordinate_columns:
        atom = column.value_type.atom
        axis = axes[column.id]
        size = point_axis_size(axis.source)
        sampled_values = tuple(
            cast("PointCoordinateValue", point_axis_value(axis.source, index))
            for index in range(min(size, sampled_point_limit))
        )
        if isinstance(atom, Bool):
            kind = "bool"
            minimum = maximum = dimension = unit = choices = entity_kind = None
            finite = True
        elif isinstance(atom, Int):
            kind = "int"
            minimum, maximum = atom.minimum, atom.maximum
            dimension = unit = choices = entity_kind = None
            finite = True
        elif isinstance(atom, Float):
            kind = "float"
            minimum, maximum = atom.minimum, atom.maximum
            dimension = unit = choices = entity_kind = None
            finite = atom.finite
        elif isinstance(atom, String):
            kind = "string"
            minimum = maximum = dimension = unit = entity_kind = None
            finite = True
            choices = atom.choices
        elif isinstance(atom, QuantityType):
            kind = "quantity"
            dimension = atom.dimension
            minimum, maximum, unit = atom.minimum, atom.maximum, atom.unit
            finite = atom.finite
            choices = entity_kind = None
        elif isinstance(atom, Entity):
            kind = "entity"
            minimum = maximum = dimension = unit = choices = None
            finite = True
            entity_kind = atom.entity_kind
        else:
            raise TypeError(f"unsupported point coordinate type {type(atom).__name__}")
        specs.append(
            PointCoordinateSpec(
                id=column.id,
                kind=kind,
                dimension=dimension,
                unit=unit,
                minimum=minimum,
                maximum=maximum,
                finite=finite,
                choices=choices,
                entity_kind=entity_kind,
                sampled_values=sampled_values,
                sampled_values_truncated=size > len(sampled_values),
            )
        )
    sampled_points = tuple(
        {
            coordinate_id: cast(
                "PointCoordinateValue", point.coordinates[coordinate_id]
            )
            for coordinate_id in catalog.coordinate_ids
        }
        for point in catalog.points[:sampled_point_limit]
    )
    return (
        tuple(specs),
        sampled_points,
        len(catalog.points) > len(sampled_points),
    )


def resolve_point_selection(
    specs: Sequence[PointCoordinateSpec],
    coordinates: Mapping[str, object],
    *,
    mode: PointSelectionMode,
    sampled_points: Sequence[Mapping[str, object]] = (),
    sampled_points_truncated: bool = False,
) -> ResolvedPointSelection:
    """Resolve raw coordinates against one admitted coordinate contract."""

    ids = tuple(spec.id for spec in specs)
    if set(coordinates) != set(ids):
        missing = sorted(set(ids) - set(coordinates))
        extra = sorted(set(coordinates) - set(ids))
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise ValueError(
            "point coordinates must identify every axis (" + "; ".join(details) + ")"
        )
    normalized = {
        spec.id: _coerce_coordinate(spec, coordinates[spec.id]) for spec in specs
    }
    if mode == "free":
        return ResolvedPointSelection(mode=mode, coordinates=normalized)
    if sampled_points_truncated:
        raise ValueError(
            f"{mode} selection requires the complete authored point sampling"
        )
    if not sampled_points:
        raise ValueError(f"{mode} selection requires at least one authored point")
    if mode == "exact":
        selected = next(
            (
                index
                for index, point in enumerate(sampled_points)
                if all(
                    scalar_values_equal(normalized[coordinate_id], point[coordinate_id])
                    for coordinate_id in ids
                )
            ),
            None,
        )
        if selected is None:
            raise ValueError("coordinates do not identify one authored point")
    else:
        selected = _nearest_point_index(normalized, sampled_points, ids)
    point = sampled_points[selected]
    return ResolvedPointSelection(
        mode=mode,
        coordinates={
            coordinate_id: cast("CellValue", point[coordinate_id])
            for coordinate_id in ids
        },
        sampled_point_index=selected,
    )


def _coerce_coordinate(spec: PointCoordinateSpec, value: object) -> CellValue:
    if spec.kind == "bool":
        atom = Bool()
    elif spec.kind == "int":
        atom = Int(
            minimum=cast("int | None", spec.minimum),
            maximum=cast("int | None", spec.maximum),
        )
    elif spec.kind == "float":
        atom = Float(
            minimum=spec.minimum,
            maximum=spec.maximum,
            finite=spec.finite,
        )
    elif spec.kind == "string":
        atom = String(choices=spec.choices)
    elif spec.kind == "quantity":
        atom = QuantityType(
            dimension=spec.dimension,
            unit=spec.unit,
            minimum=spec.minimum,
            maximum=spec.maximum,
            finite=spec.finite,
        )
    else:
        atom = Entity(entity_kind=spec.entity_kind)
    return cast(
        "CellValue",
        coerce_literal(Scalar(atom), value, path=("coordinates", spec.id)),
    )


def _nearest_point_index(
    requested: Mapping[str, object],
    sampled_points: Sequence[Mapping[str, object]],
    coordinate_ids: Sequence[str],
) -> int:
    axis_values = {
        coordinate_id: tuple(point[coordinate_id] for point in sampled_points)
        for coordinate_id in coordinate_ids
    }
    distances = tuple(
        _point_distance(requested, point, axis_values, coordinate_ids)
        for point in sampled_points
    )
    selected = min(range(len(sampled_points)), key=distances.__getitem__)
    if distances[selected] == inf:
        raise ValueError("no authored point matches the non-numeric coordinates")
    return selected


def _point_distance(
    requested: Mapping[str, object],
    point: Mapping[str, object],
    axis_values: Mapping[str, tuple[object, ...]],
    coordinate_ids: Sequence[str],
) -> float:
    try:
        return sum(
            _normalized_value_distance(
                requested[coordinate_id],
                point[coordinate_id],
                axis_values[coordinate_id],
            )
            for coordinate_id in coordinate_ids
        )
    except ValueError:
        return inf


def _normalized_value_distance(
    requested: object,
    value: object,
    axis_values: tuple[object, ...],
) -> float:
    if scalar_values_equal(requested, value):
        return 0.0
    requested_number, value_number = _comparison_numbers(requested, value)
    numeric_axis = tuple(
        _comparison_numbers(value, candidate)[1] for candidate in axis_values
    )
    span = max(numeric_axis) - min(numeric_axis)
    scale = span if span > 0 else 1.0
    return ((requested_number - value_number) / scale) ** 2


def _comparison_numbers(left: object, right: object) -> tuple[float, float]:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        return quantity_comparison_values(left, right)
    if (
        isinstance(left, int | float)
        and not isinstance(left, bool)
        and isinstance(right, int | float)
        and not isinstance(right, bool)
    ):
        return float(left), float(right)
    raise ValueError("non-numeric coordinates require an exact authored value")


__all__ = [
    "PointSelectionMode",
    "ResolvedPointSelection",
    "point_coordinate_contract",
    "resolve_point_selection",
]
