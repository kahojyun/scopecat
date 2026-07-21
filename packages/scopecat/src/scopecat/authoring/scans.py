"""Typed, opaque scan composition for the public authoring DSL.

Scans are transient authoring intent. Public code creates them through the
factories in this module; private lowering projects them independently into the
compiler relation graph and the durable ``RunRequest`` value domain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal, cast, overload

from scopecat.authoring._frozen_values import freeze_runtime_input
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterValueContract,
)
from scopecat.authoring._scan_intents import (
    ParameterRow as ParameterRow,
)
from scopecat.authoring._scan_intents import (
    ParameterRowIntent as _ParameterRowIntent,
)
from scopecat.authoring._scan_intents import (
    ParameterScanIntent as _ParameterScanIntent,
)
from scopecat.authoring._scan_intents import (
    PointScanIntent as _PointScanIntent,
)
from scopecat.authoring._scan_intents import (
    Scan as Scan,
)
from scopecat.authoring._scan_intents import (
    ScanCenter as ScanCenter,
)
from scopecat.authoring._scan_intents import (
    ScanGroupIntent as _ScanGroupIntent,
)
from scopecat.authoring._scan_intents import (
    ScanValue as ScanValue,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_id,
)
from scopecat.authoring.values import ParameterKeyInput
from scopecat.compiler.relations.model import ParameterLookupUse
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_type_compatibility import literal_scalar_type
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import validate_literal
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


def axis(
    target: ValueRef,
    values: Sequence[ScanValue] = (),
    *,
    unit: str | None = None,
    center: ScanCenter | None = None,
    span: Quantity | str | None = None,
    points: int | None = None,
) -> Scan:
    """Scan one typed point value over explicit values or around a center."""

    point_id = _point_target_id(target)
    selected_values = tuple(values)
    if selected_values and any(item is not None for item in (center, span, points)):
        msg = "scan axis accepts either values or center/span/points, not both"
        raise ValueError(msg)
    if selected_values:
        _validate_scan_values(target, selected_values, unit=unit)
    elif any(item is not None for item in (center, span, points)):
        if center is None or span is None or points is None:
            msg = "scan axis around form requires center, span, and points"
            raise ValueError(msg)
        _validate_around_scan(target, center=center, span=span, points=points)
    else:
        msg = "scan axis requires values or center/span/points"
        raise ValueError(msg)
    captured_values = tuple(
        cast("ScanValue", freeze_runtime_input(value)) for value in selected_values
    )
    captured_center = (
        center
        if center is None or isinstance(center, ValueRef)
        else cast("Quantity", freeze_runtime_input(center))
    )
    captured_span = (
        cast("Quantity", freeze_runtime_input(span))
        if isinstance(span, Quantity)
        else span
    )
    return _PointScanIntent(
        target=target,
        point_id=point_id,
        point_values=captured_values,
        unit=unit,
        center=captured_center,
        span=captured_span,
        point_count=points,
        parameter_contracts=(
            _value_parameter_contracts(captured_center)
            if captured_center is not None
            else ()
        ),
    )


def build_scan(
    target: ValueRef | Scan,
    values: Sequence[ScanValue] = (),
    *,
    unit: str | None = None,
    center: ScanCenter | None = None,
    span: Quantity | str | None = None,
    points: int | None = None,
) -> Scan:
    """Normalize the shared fluent ``scan(...)`` call surface."""

    if isinstance(target, Scan):
        if values or any(item is not None for item in (unit, center, span, points)):
            msg = "scan handle cannot be combined with scan construction arguments"
            raise ValueError(msg)
        return target
    if values:
        return axis(target, values, unit=unit)
    if span is None or points is None:
        msg = "scan requires values or span and points"
        raise ValueError(msg)
    if center is not None:
        return axis(target, center=center, span=span, points=points)
    return _implicit_around_axis(target, span=span, points=points)


@overload
def param_axis(
    target: ValueRef,
    row: ParameterRow,
    column: str,
    values: Sequence[ScanValue],
    *,
    unit: str | None = None,
) -> Scan: ...


@overload
def param_axis(
    target: ValueRef,
    row: ParameterRow,
    column: str,
    *,
    span: Quantity | str,
    points: int,
) -> Scan: ...


def param_axis(
    target: ValueRef,
    row: ParameterRow,
    column: str,
    values: Sequence[ScanValue] = (),
    *,
    unit: str | None = None,
    span: Quantity | str | None = None,
    points: int | None = None,
) -> Scan:
    """Scan a parameter-table cell over values or around its accepted value.

    The around form records the cell locator, span, and point count; its center
    is resolved later from the accepted parameter snapshot. Each materialized
    point overlays that cell only for its own specialization, so every host or
    domain ``parameter_lookup`` of that cell sees the same scanned value without
    mutating accepted parameter state.
    """

    point_id = _point_target_id(target)
    if not isinstance(row, _ParameterRowIntent):
        msg = "parameter scan row must be created with scopecat.param_row"
        raise TypeError(msg)
    if not column:
        msg = "parameter scan column must be non-empty"
        raise ValueError(msg)
    selected_values = tuple(values)
    if selected_values and any(item is not None for item in (span, points)):
        msg = "parameter scan accepts either values or span/points, not both"
        raise ValueError(msg)
    if selected_values:
        _validate_scan_values(target, selected_values, unit=unit)
    elif any(item is not None for item in (span, points)):
        if span is None or points is None:
            msg = "parameter scan around form requires span and points"
            raise ValueError(msg)
        if unit is not None:
            msg = "parameter scan unit is only valid with explicit values"
            raise ValueError(msg)
        _validate_around_target(target, points=points)
        _validate_scan_span(target, span)
    else:
        msg = "parameter scan requires values or span and points"
        raise ValueError(msg)
    captured_values = tuple(
        cast("ScanValue", freeze_runtime_input(value)) for value in selected_values
    )
    captured_span = (
        cast("Quantity", freeze_runtime_input(span))
        if isinstance(span, Quantity)
        else span
    )
    return _ParameterScanIntent(
        target=target,
        point_id=point_id,
        table_id=row.table_id,
        key=row.key,
        column=column,
        values=captured_values,
        unit=unit,
        span=captured_span,
        point_count=points,
        parameter_contracts=(
            ParameterLookupUse(
                table_id=row.table_id,
                key_input_types=tuple(
                    (name, _parameter_key_value_type(value)) for name, value in row.key
                ),
                literal_key_columns=frozenset(
                    name for name, value in row.key if not isinstance(value, ValueRef)
                ),
                column_id=column,
                result_type=cast("Scalar", target.value_type),
            ),
        ),
    )


def cartesian(*scans: Scan) -> Scan:
    """Compose scans by Cartesian product."""

    return _scan_group("cartesian", scans)


def zip(*scans: Scan) -> Scan:  # noqa: A001
    """Compose scans point-wise, requiring equal materialized lengths."""

    return _scan_group("zip", scans)


def param_row(table_id: str, **key: ParameterKeyInput) -> ParameterRow:
    """Select one parameter-table row for a parameter scan."""

    if not table_id:
        msg = "parameter row table id must be non-empty"
        raise ValueError(msg)
    selected = cast("Mapping[object, object]", key)
    invalid = [
        name
        for name, value in selected.items()
        if not isinstance(name, str) or not name or not _is_parameter_key(value)
    ]
    if invalid:
        msg = "parameter row keys require non-empty names and typed scalar values"
        raise TypeError(msg)
    captured_key = tuple(
        (
            name,
            value
            if isinstance(value, ValueRef)
            else cast("ParameterKeyInput", freeze_runtime_input(value)),
        )
        for name, value in key.items()
    )
    return _ParameterRowIntent(table_id=table_id, key=captured_key)


def _implicit_around_axis(
    target: ValueRef,
    *,
    span: Quantity | str,
    points: int,
) -> Scan:
    point_id = _point_target_id(target)
    _validate_around_target(target, points=points)
    _validate_scan_span(target, span)
    captured_span = (
        cast("Quantity", freeze_runtime_input(span))
        if isinstance(span, Quantity)
        else span
    )
    return _PointScanIntent(
        target=target,
        point_id=point_id,
        span=captured_span,
        point_count=points,
        implicit_center=True,
        parameter_contracts=(
            ParameterValueContract(
                parameter_id=point_id,
                value_type=cast("Scalar", target.value_type),
            ),
        ),
    )


def _scan_group(kind: Literal["cartesian", "zip"], scans: Sequence[Scan]) -> Scan:
    minimum = 2 if kind == "zip" else 1
    if len(scans) < minimum:
        count = "two" if minimum == 2 else "one"
        msg = f"{kind} scan group requires at least {count} scans"
        raise ValueError(msg)
    return _ScanGroupIntent(kind=kind, scans=tuple(scans))


def _point_target_id(target: ValueRef) -> str:
    point_id = internal_value_ref_point_id(target)
    if point_id is None:
        msg = "scan target must be created with scopecat.point"
        raise TypeError(msg)
    if not isinstance(target.value_type, Scalar):
        msg = "scan target must carry a scalar value type"
        raise TypeError(msg)
    return point_id


def _validate_scan_values(
    target: ValueRef,
    values: Sequence[ScanValue],
    *,
    unit: str | None,
) -> None:
    for index, value in enumerate(values):
        selected: object = value
        if unit is not None:
            if not isinstance(value, int | float) or isinstance(value, bool):
                msg = "unit-qualified scan values must be numeric"
                raise TypeError(msg)
            selected = Quantity(value=float(value), unit=unit)
        validate_literal(
            target.value_type,
            selected,
            path=("scan", "values", index),
        )


def _validate_around_scan(
    target: ValueRef,
    *,
    center: ScanCenter,
    span: Quantity | str,
    points: int,
) -> None:
    _validate_around_target(target, points=points)
    _validate_scan_span(target, span)
    if isinstance(center, ValueRef):
        if not isinstance(center.value_type, Scalar) or not isinstance(
            center.value_type.atom, QuantityType
        ):
            msg = "scan center must be a typed quantity scalar"
            raise TypeError(msg)
        _require_compatible_quantity_types(
            center.value_type.atom,
            cast("QuantityType", cast("Scalar", target.value_type).atom),
            path="scan.center",
        )
        return
    validate_literal(target.value_type, center, path=("scan", "center"))


def _validate_around_target(target: ValueRef, *, points: int) -> None:
    target_type = target.value_type
    if not isinstance(target_type, Scalar) or not isinstance(
        target_type.atom, QuantityType
    ):
        msg = "around scan target must be a typed quantity point"
        raise TypeError(msg)
    if points < 2:
        msg = "scan axis points must be at least 2"
        raise ValueError(msg)


def _validate_scan_span(target: ValueRef, span: Quantity | str) -> None:
    selected = _parse_scan_quantity(span, path="scan.span")
    target_type = target.value_type
    if not isinstance(target_type, Scalar) or not isinstance(
        target_type.atom, QuantityType
    ):
        msg = "around scan target must be a typed quantity point"
        raise TypeError(msg)
    expected_dimension = target_type.atom.dimension or (
        unit_kind(target_type.atom.unit) if target_type.atom.unit is not None else None
    )
    if (
        expected_dimension is not None
        and unit_kind(selected.unit) != expected_dimension
    ):
        msg = (
            f"scan.span uses {selected.unit!r}, which is incompatible with "
            f"point dimension {expected_dimension!r}"
        )
        raise TypeError(msg)


def _require_compatible_quantity_types(
    source: QuantityType,
    target: QuantityType,
    *,
    path: str,
) -> None:
    source_dimension = source.dimension or (
        unit_kind(source.unit) if source.unit is not None else None
    )
    target_dimension = target.dimension or (
        unit_kind(target.unit) if target.unit is not None else None
    )
    if (
        source_dimension is not None
        and target_dimension is not None
        and source_dimension != target_dimension
    ) or (
        source.unit is not None
        and target.unit is not None
        and not compatible_units(source.unit, target.unit)
    ):
        msg = f"{path} must be compatible with the scan point quantity type"
        raise TypeError(msg)


def _parse_scan_quantity(value: Quantity | str, *, path: str) -> Quantity:
    if isinstance(value, Quantity):
        return value
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([A-Za-z][A-Za-z0-9_]*)\s*",
        value,
    )
    if match is not None:
        return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = f"{path} must be a Quantity or '<number> <unit>' string"
    raise TypeError(msg)


def _is_parameter_key(value: object) -> bool:
    return (
        value is None
        or isinstance(value, Quantity | EntityRef | str | int | float | bool)
        or (isinstance(value, ValueRef) and isinstance(value.value_type, Scalar))
    )


def _parameter_key_value_type(value: ParameterKeyInput) -> Scalar:
    if isinstance(value, ValueRef):
        return cast("Scalar", value.value_type)
    return literal_scalar_type(value)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )


__all__ = [
    "ParameterRow",
    "Scan",
    "ScanCenter",
    "ScanValue",
    "axis",
    "cartesian",
    "param_axis",
    "param_row",
    "zip",
]
