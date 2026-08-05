"""Typed axis construction for experiment point domains."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import cast

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_types import Float, Int, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_validation import validate_literal
from scopecat.program.input_capture import capture_runtime_input
from scopecat.program.scans import (
    AroundScanSource as _AroundScanSource,
)
from scopecat.program.scans import (
    AxisSpec as Axis,
)
from scopecat.program.scans import (
    PointRow as PointRow,
)
from scopecat.program.scans import (
    RangeScanSource as _RangeScanSource,
)
from scopecat.program.scans import (
    ScanCenter as ScanCenter,
)
from scopecat.program.scans import (
    ScanRangeValue as ScanRangeValue,
)
from scopecat.program.scans import (
    ScanValue as ScanValue,
)
from scopecat.program.scans import (
    ValuesScanSource as _ValuesScanSource,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_parameter_lookup,
    internal_value_ref_point_id,
)

type _ScanCoordinate = Quantity | str | int | float
type _ScanCenterInput = ValueRef | _ScanCoordinate


def axis(
    target: ValueRef,
    values: Iterable[ScanValue] | None = None,
    *,
    overlay: ValueRef | None = None,
    unit: str | None = None,
    start: _ScanCoordinate | None = None,
    stop: _ScanCoordinate | None = None,
    center: _ScanCenterInput | None = None,
    span: _ScanCoordinate | None = None,
    points: int | None = None,
) -> Axis:
    """Build one coordinate axis, optionally overlaying a parameter cell.

    Generated forms interpolate evenly in one coordinate unit. ``span`` is
    the total coordinate width, including for same-unit dBm coordinates. When
    ``overlay`` is present, each point temporarily supplies that parameter cell;
    the span form is centered on the accepted parameter value.
    """

    axis_id, value_type = _point_target(target)
    _validate_overlay(target, overlay)
    if overlay is not None and center is not None:
        raise ValueError("axis overlay supplies the center; omit center")
    selected_center = overlay if overlay is not None else center
    selected_values = None if values is None else tuple(values)
    if selected_values is not None and any(
        item is not None for item in (start, stop, center, span, points)
    ):
        msg = (
            "axis accepts exactly one of values, start/stop/points, "
            "or center/span/points"
        )
        raise ValueError(msg)
    if selected_values is not None:
        return Axis(
            id=axis_id,
            value_type=_explicit_value_type(value_type, unit=unit),
            source=_ValuesScanSource(
                values=_capture_scan_values(target, selected_values, unit=unit),
            ),
            overlay=overlay,
        )
    if start is not None or stop is not None:
        if center is not None or span is not None:
            msg = "axis range and around forms are mutually exclusive"
            raise ValueError(msg)
        if start is None or stop is None or points is None:
            msg = "axis range form requires start, stop, and points"
            raise ValueError(msg)
        range_type, captured_start, captured_stop = _capture_range_scan(
            target,
            start=start,
            stop=stop,
            points=points,
            unit=unit,
        )
        return Axis(
            id=axis_id,
            value_type=range_type,
            source=_RangeScanSource(
                start=captured_start,
                stop=captured_stop,
                points=points,
            ),
            overlay=overlay,
        )
    if selected_center is None and span is None:
        if points is not None:
            msg = "axis points must accompany start/stop, center/span, or overlay/span"
        else:
            msg = (
                "axis requires values, start/stop/points, center/span/points, "
                "or overlay/span/points"
            )
        raise ValueError(msg)
    if selected_center is None or span is None or points is None:
        msg = "axis around form requires a center or overlay, plus span and points"
        raise ValueError(msg)
    around_type, captured_center, captured_span = _capture_around_scan(
        target,
        center=selected_center,
        span=span,
        points=points,
        unit=unit,
    )
    return Axis(
        id=axis_id,
        value_type=around_type,
        source=_AroundScanSource(
            center=captured_center,
            span=captured_span,
            points=points,
        ),
        overlay=overlay,
    )


def _validate_overlay(target: ValueRef, overlay: ValueRef | None) -> None:
    if overlay is None:
        return
    if internal_value_ref_parameter_lookup(overlay) is None:
        raise TypeError("axis overlay requires a direct scopecat.parameter_lookup")
    if overlay.value_type != target.value_type:
        raise TypeError("axis overlay and coordinate must use the same value type")


def _point_target(target: ValueRef) -> tuple[str, Scalar]:
    point_id = internal_value_ref_point_id(target)
    if point_id is None:
        msg = "axis target must be created with scopecat.coordinate"
        raise TypeError(msg)
    if not isinstance(target.value_type, Scalar):
        msg = "axis target must carry a scalar value type"
        raise TypeError(msg)
    return point_id, target.value_type


def _explicit_value_type(value_type: Scalar, *, unit: str | None) -> Scalar:
    atom = value_type.atom
    if unit is not None and isinstance(atom, QuantityType) and atom.unit is None:
        return Scalar(replace(atom, unit=unit))
    return value_type


def _capture_scan_values(
    target: ValueRef,
    values: Sequence[ScanValue],
    *,
    unit: str | None,
) -> tuple[ScanValue, ...]:
    captured: list[ScanValue] = []
    for index, value in enumerate(values):
        selected: object = value
        if unit is not None:
            if not isinstance(value, int | float) or isinstance(value, bool):
                msg = "unit-qualified axis values must be numeric"
                raise TypeError(msg)
            selected = Quantity(value=float(value), unit=unit)
        validate_literal(
            target.value_type,
            selected,
            path=("axis", "values", index),
        )
        captured.append(cast("ScanValue", capture_runtime_input(selected)))
    return tuple(captured)


def _capture_range_scan(
    target: ValueRef,
    *,
    start: _ScanCoordinate,
    stop: _ScanCoordinate,
    points: int,
    unit: str | None,
) -> tuple[Scalar, ScanRangeValue, ScanRangeValue]:
    _validate_scan_points(points)
    value_type = cast("Scalar", target.value_type)
    atom = value_type.atom
    if isinstance(atom, QuantityType):
        start_quantity = _optional_scan_quantity(start, path="axis.start")
        stop_quantity = _optional_scan_quantity(stop, path="axis.stop")
        coordinate_unit = _select_coordinate_unit(
            atom,
            unit=unit,
            inferred=(start_quantity, stop_quantity),
        )
        captured_start = _normalize_scan_quantity(
            start,
            unit=coordinate_unit,
            path="axis.start",
        )
        captured_stop = _normalize_scan_quantity(
            stop,
            unit=coordinate_unit,
            path="axis.stop",
        )
        validate_literal(target.value_type, captured_start, path=("axis", "start"))
        validate_literal(target.value_type, captured_stop, path=("axis", "stop"))
        return (
            _explicit_value_type(value_type, unit=coordinate_unit),
            cast("Quantity", capture_runtime_input(captured_start)),
            cast("Quantity", capture_runtime_input(captured_stop)),
        )
    if unit is not None:
        msg = "axis unit requires a quantity point"
        raise TypeError(msg)
    if isinstance(atom, Float):
        start_value = _numeric_scan_coordinate(start, path="axis.start")
        stop_value = _numeric_scan_coordinate(stop, path="axis.stop")
        validate_literal(target.value_type, start_value, path=("axis", "start"))
        validate_literal(target.value_type, stop_value, path=("axis", "stop"))
        return (
            value_type,
            cast("float", capture_runtime_input(float(start_value))),
            cast("float", capture_runtime_input(float(stop_value))),
        )
    if isinstance(atom, Int):
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(stop, int)
            or isinstance(stop, bool)
        ):
            msg = "integer axis range endpoints must be integers"
            raise TypeError(msg)
        validate_literal(target.value_type, start, path=("axis", "start"))
        validate_literal(target.value_type, stop, path=("axis", "stop"))
        if (stop - start) % (points - 1) != 0:
            msg = "integer axis range must have an integral step"
            raise ValueError(msg)
        return value_type, start, stop
    msg = "axis range target must be a float, int, or quantity point"
    raise TypeError(msg)


def _capture_around_scan(
    target: ValueRef,
    *,
    center: _ScanCenterInput,
    span: _ScanCoordinate,
    points: int,
    unit: str | None,
) -> tuple[Scalar, ScanCenter, Quantity]:
    target_type = _validate_around_target(target, points=points)
    literal_center = (
        None
        if isinstance(center, ValueRef)
        else _optional_scan_quantity(center, path="axis.center")
    )
    literal_span = _optional_scan_quantity(span, path="axis.span")
    center_type: QuantityType | None = None
    if isinstance(center, ValueRef):
        if not isinstance(center.value_type, Scalar) or not isinstance(
            center.value_type.atom, QuantityType
        ):
            msg = "axis center must be a typed quantity scalar"
            raise TypeError(msg)
        center_type = center.value_type.atom
        _require_compatible_quantity_types(
            center_type,
            target_type,
            path="axis.center",
        )
    coordinate_unit = _select_coordinate_unit(
        target_type,
        unit=unit,
        inferred=(
            literal_center,
            _quantity_type_unit(center_type),
            literal_span,
        ),
    )
    target_scalar = cast("Scalar", target.value_type)
    axis_type = _explicit_value_type(
        target_scalar,
        unit=coordinate_unit,
    )
    if (
        isinstance(center, ValueRef)
        and center_type is not None
        and center_type.unit is None
    ):
        if unit is not None:
            msg = "axis.center must declare a unit for a unit-specific axis"
            raise TypeError(msg)
        axis_type = target_scalar
    if isinstance(center, ValueRef):
        _require_quantity_unit(
            cast("QuantityType", center_type),
            coordinate_unit,
            path="axis.center",
        )
        captured_center: ScanCenter = center
    else:
        selected_center = _capture_around_quantity(
            center,
            unit=coordinate_unit,
            path="axis.center",
            normalize=unit is not None,
        )
        validate_literal(
            target.value_type,
            selected_center,
            path=("axis", "center"),
        )
        captured_center = cast(
            "Quantity",
            capture_runtime_input(selected_center),
        )
    captured_span = _capture_around_quantity(
        span,
        unit=coordinate_unit,
        path="axis.span",
        normalize=unit is not None,
    )
    _require_quantity_unit(target_type, captured_span.unit, path="axis.span")
    return (
        axis_type,
        captured_center,
        cast(
            "Quantity",
            capture_runtime_input(captured_span),
        ),
    )


def _validate_around_target(target: ValueRef, *, points: int) -> QuantityType:
    target_type = target.value_type
    if not isinstance(target_type, Scalar) or not isinstance(
        target_type.atom, QuantityType
    ):
        msg = "around axis target must be a typed quantity point"
        raise TypeError(msg)
    _validate_scan_points(points)
    return target_type.atom


def _validate_scan_points(points: int) -> None:
    if points < 2:
        msg = "axis points must be at least 2"
        raise ValueError(msg)


def _require_quantity_unit(
    target_type: QuantityType,
    unit: str,
    *,
    path: str,
) -> None:
    expected_dimension = target_type.dimension or (
        unit_kind(target_type.unit) if target_type.unit is not None else None
    )
    if (expected_dimension is not None and unit_kind(unit) != expected_dimension) or (
        target_type.unit is not None and not compatible_units(target_type.unit, unit)
    ):
        msg = (
            f"{path} uses {unit!r}, which is incompatible with "
            "the axis point quantity type"
        )
        raise TypeError(msg)


def _select_coordinate_unit(
    target_type: QuantityType,
    *,
    unit: str | None,
    inferred: Sequence[Quantity | str | None],
) -> str:
    inferred_unit = next(
        (
            value.unit if isinstance(value, Quantity) else value
            for value in inferred
            if value is not None
        ),
        None,
    )
    selected = unit if unit is not None else target_type.unit or inferred_unit
    if selected is None:
        msg = "numeric quantity axis coordinates require unit or typed endpoints"
        raise TypeError(msg)
    Quantity(0.0, selected)
    _require_quantity_unit(target_type, selected, path="axis.unit")
    return selected


def _quantity_type_unit(value_type: QuantityType | None) -> str | None:
    return None if value_type is None else value_type.unit


def _optional_scan_quantity(
    value: _ScanCoordinate,
    *,
    path: str,
) -> Quantity | None:
    if isinstance(value, Quantity | str):
        return _parse_scan_quantity(value, path=path)
    if isinstance(value, bool):
        msg = f"{path} must be numeric or a quantity"
        raise TypeError(msg)
    return None


def _normalize_scan_quantity(
    value: _ScanCoordinate,
    *,
    unit: str,
    path: str,
) -> Quantity:
    parsed = _optional_scan_quantity(value, path=path)
    if parsed is None:
        return Quantity(
            value=float(_numeric_scan_coordinate(value, path=path)),
            unit=unit,
        )
    try:
        return parsed.to(unit)
    except ValueError as error:
        msg = f"{path} uses a unit incompatible with {unit!r}"
        raise TypeError(msg) from error


def _capture_around_quantity(
    value: _ScanCoordinate,
    *,
    unit: str,
    path: str,
    normalize: bool,
) -> Quantity:
    parsed = _optional_scan_quantity(value, path=path)
    if parsed is None:
        return Quantity(
            value=float(_numeric_scan_coordinate(value, path=path)),
            unit=unit,
        )
    try:
        converted = parsed.to(unit)
    except ValueError as error:
        msg = f"{path} uses a unit incompatible with {unit!r}"
        raise TypeError(msg) from error
    return converted if normalize else parsed


def _numeric_scan_coordinate(value: object, *, path: str) -> int | float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        msg = f"{path} must be numeric"
        raise TypeError(msg)
    return value


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
        msg = f"{path} must be compatible with the axis point quantity type"
        raise TypeError(msg)


def _parse_scan_quantity(value: Quantity | str, *, path: str) -> Quantity:
    if isinstance(value, Quantity):
        return value
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
        r"\s+([A-Za-z][A-Za-z0-9_]*)\s*",
        value,
    )
    if match is not None:
        return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = f"{path} must be a Quantity or '<number> <unit>' string"
    raise TypeError(msg)


__all__ = [
    "Axis",
    "PointRow",
    "ScanCenter",
    "ScanValue",
    "axis",
]
