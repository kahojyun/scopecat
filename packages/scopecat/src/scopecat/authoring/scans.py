"""Typed, opaque scan composition for the public authoring DSL.

Scans are transient authoring intent. Public code creates them through the
factories in this module; private lowering projects them independently into the
compiler relation graph and the durable ``RunRequest`` value domain.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import cast, overload

from scopecat.authoring._scan_intents import (
    CartesianScanIntent as _CartesianScanIntent,
)
from scopecat.authoring._scan_intents import (
    CenteredParameterScanIntent as _CenteredParameterScanIntent,
)
from scopecat.authoring._scan_intents import (
    CenteredPointScanIntent as _CenteredPointScanIntent,
)
from scopecat.authoring._scan_intents import (
    ExplicitParameterScanIntent as _ExplicitParameterScanIntent,
)
from scopecat.authoring._scan_intents import (
    ExplicitPointScanIntent as _ExplicitPointScanIntent,
)
from scopecat.authoring._scan_intents import (
    ImplicitScanCenter as _ImplicitScanCenter,
)
from scopecat.authoring._scan_intents import (
    Scan as Scan,
)
from scopecat.authoring._scan_intents import (
    ScanCenter as ScanCenter,
)
from scopecat.authoring._scan_intents import (
    ScanValue as ScanValue,
)
from scopecat.authoring._scan_intents import iter_scan_leaves
from scopecat.authoring._value_refs import (
    ValueRef,
    capture_runtime_input,
    internal_value_ref_parameter_lookup,
    internal_value_ref_point_id,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import validate_literal


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

    _point_target_id(target)
    selected_values = tuple(values)
    if selected_values and any(item is not None for item in (center, span, points)):
        msg = "scan axis accepts either values or center/span/points, not both"
        raise ValueError(msg)
    if selected_values:
        _validate_scan_values(target, selected_values, unit=unit)
        return _ExplicitPointScanIntent(
            target=target,
            values=tuple(
                cast("ScanValue", capture_runtime_input(value))
                for value in selected_values
            ),
            unit=unit,
        )
    if center is None or span is None or points is None:
        if any(item is not None for item in (center, span, points)):
            msg = "scan axis around form requires center, span, and points"
        else:
            msg = "scan axis requires values or center/span/points"
        raise ValueError(msg)
    captured_span = _validate_around_scan(
        target,
        center=center,
        span=span,
        points=points,
    )
    captured_center = (
        center
        if isinstance(center, ValueRef)
        else cast("Quantity", capture_runtime_input(center))
    )
    return _CenteredPointScanIntent(
        target=target,
        center=captured_center,
        span=captured_span,
        points=points,
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
    lookup: ValueRef,
    values: Sequence[ScanValue],
    *,
    unit: str | None = None,
) -> Scan: ...


@overload
def param_axis(
    target: ValueRef,
    lookup: ValueRef,
    *,
    span: Quantity | str,
    points: int,
) -> Scan: ...


def param_axis(
    target: ValueRef,
    lookup: ValueRef,
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

    _point_target_id(target)
    if internal_value_ref_parameter_lookup(lookup) is None:
        msg = "parameter scan requires a direct scopecat.parameter_lookup"
        raise TypeError(msg)
    if lookup.value_type != target.value_type:
        msg = "parameter scan lookup and point must use the same value type"
        raise TypeError(msg)
    selected_values = tuple(values)
    if selected_values and any(item is not None for item in (span, points)):
        msg = "parameter scan accepts either values or span/points, not both"
        raise ValueError(msg)
    if selected_values:
        _validate_scan_values(target, selected_values, unit=unit)
        return _ExplicitParameterScanIntent(
            target=target,
            lookup=lookup,
            values=tuple(
                cast("ScanValue", capture_runtime_input(value))
                for value in selected_values
            ),
            unit=unit,
        )
    if span is None or points is None:
        if any(item is not None for item in (span, points)):
            msg = "parameter scan around form requires span and points"
        else:
            msg = "parameter scan requires values or span and points"
        raise ValueError(msg)
    if unit is not None:
        msg = "parameter scan unit is only valid with explicit values"
        raise ValueError(msg)
    target_type = _validate_around_target(target, points=points)
    captured_span = _validate_scan_span(target_type, span)
    return _CenteredParameterScanIntent(
        target=target,
        lookup=lookup,
        span=captured_span,
        points=points,
    )


def cartesian(*scans: Scan) -> Scan:
    """Compose scans by a flat Cartesian product."""

    if not scans:
        msg = "cartesian scan group requires at least one scan"
        raise ValueError(msg)
    return _CartesianScanIntent(
        scans=tuple(leaf for scan in scans for leaf in iter_scan_leaves(scan))
    )


def _implicit_around_axis(
    target: ValueRef,
    *,
    span: Quantity | str,
    points: int,
) -> Scan:
    _point_target_id(target)
    target_type = _validate_around_target(target, points=points)
    captured_span = _validate_scan_span(target_type, span)
    return _CenteredPointScanIntent(
        target=target,
        center=_ImplicitScanCenter(),
        span=captured_span,
        points=points,
    )


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
) -> Quantity:
    target_type = _validate_around_target(target, points=points)
    captured_span = _validate_scan_span(target_type, span)
    if isinstance(center, ValueRef):
        if not isinstance(center.value_type, Scalar) or not isinstance(
            center.value_type.atom, QuantityType
        ):
            msg = "scan center must be a typed quantity scalar"
            raise TypeError(msg)
        _require_compatible_quantity_types(
            center.value_type.atom,
            target_type,
            path="scan.center",
        )
        return captured_span
    validate_literal(target.value_type, center, path=("scan", "center"))
    return captured_span


def _validate_around_target(target: ValueRef, *, points: int) -> QuantityType:
    target_type = target.value_type
    if not isinstance(target_type, Scalar) or not isinstance(
        target_type.atom, QuantityType
    ):
        msg = "around scan target must be a typed quantity point"
        raise TypeError(msg)
    if points < 2:
        msg = "scan axis points must be at least 2"
        raise ValueError(msg)
    return target_type.atom


def _validate_scan_span(
    target_type: QuantityType,
    span: Quantity | str,
) -> Quantity:
    selected = cast(
        "Quantity",
        capture_runtime_input(_parse_scan_quantity(span, path="scan.span")),
    )
    expected_dimension = target_type.dimension or (
        unit_kind(target_type.unit) if target_type.unit is not None else None
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
    return selected


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


__all__ = [
    "Scan",
    "ScanCenter",
    "ScanValue",
    "axis",
    "cartesian",
    "param_axis",
]
