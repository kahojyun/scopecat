"""Typed axis construction for experiment point domains."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import cast

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_types import Bool, Entity, Float, Int, Scalar, String
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
    CoordinateRef,
    ValueRef,
    internal_coordinate_ref_id,
    internal_value_ref_parameter_lookup,
)
from scopecat.program.values import coordinate

type ScanCoordinate = Quantity | str | int | float
type ScanCenterInput = ValueRef | ScanCoordinate
type ScanValueType = Scalar | Bool | Entity | Float | Int | QuantityType | String


def axis(
    target: CoordinateRef,
    values: Iterable[ScanValue] | None = None,
    *,
    overlay: ValueRef | None = None,
    unit: str | None = None,
    start: ScanCoordinate | None = None,
    stop: ScanCoordinate | None = None,
    center: ScanCenterInput | None = None,
    span: ScanCoordinate | None = None,
    points: int | None = None,
) -> Axis:
    """Build one coordinate axis, optionally overlaying a parameter cell.

    Generated forms interpolate evenly in one coordinate unit. ``span`` is
    the total coordinate width, including for same-unit dBm coordinates. When
    ``overlay`` is present, each point temporarily supplies that parameter cell;
    the span form is centered on the accepted parameter value.
    """

    axis_id, value_type = _point_target(target)
    return _axis(
        axis_id,
        value_type,
        values,
        overlay=overlay,
        unit=unit,
        start=start,
        stop=stop,
        center=center,
        span=span,
        points=points,
    )


def _axis(
    axis_id: str,
    value_type: Scalar,
    values: Iterable[ScanValue] | None = None,
    *,
    overlay: ValueRef | None = None,
    unit: str | None = None,
    start: ScanCoordinate | None = None,
    stop: ScanCoordinate | None = None,
    center: ScanCenterInput | None = None,
    span: ScanCoordinate | None = None,
    points: int | None = None,
) -> Axis:
    """Build an axis from an already resolved coordinate identity and type."""

    _validate_overlay(value_type, overlay)
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
                values=_capture_scan_values(value_type, selected_values, unit=unit),
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
            value_type,
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
        value_type,
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


def scan_axis(
    id: str,
    values: Iterable[ScanValue] | None = None,
    *,
    value_type: ScanValueType | None = None,
    overlay: ValueRef | None = None,
    unit: str | None = None,
    start: ScanCoordinate | None = None,
    stop: ScanCoordinate | None = None,
    center: ScanCenterInput | None = None,
    span: ScanCoordinate | None = None,
    points: int | None = None,
) -> tuple[CoordinateRef, Axis]:
    """Build one inferred coordinate and its matching axis declaration."""

    selected_values = None if values is None else tuple(values)
    selected_type = (
        _normalize_scan_value_type(value_type)
        if value_type is not None
        else _infer_scan_value_type(
            selected_values,
            overlay=overlay,
            unit=unit,
            start=start,
            stop=stop,
            center=center,
            span=span,
        )
    )
    selected_axis = _axis(
        id,
        selected_type,
        selected_values,
        overlay=overlay,
        unit=unit,
        start=start,
        stop=stop,
        center=center,
        span=span,
        points=points,
    )
    return coordinate(id, selected_axis.value_type), selected_axis


def _normalize_scan_value_type(value_type: ScanValueType) -> Scalar:
    return value_type if isinstance(value_type, Scalar) else Scalar(value_type)


def _infer_scan_value_type(
    values: tuple[ScanValue, ...] | None,
    *,
    overlay: ValueRef | None,
    unit: str | None,
    start: ScanCoordinate | None,
    stop: ScanCoordinate | None,
    center: ScanCenterInput | None,
    span: ScanCoordinate | None,
) -> Scalar:
    if overlay is not None:
        return _scalar_value_ref_type(overlay, source="overlay")
    if isinstance(center, ValueRef):
        return _scalar_value_ref_type(center, source="center")
    if values is not None:
        return _infer_values_type(values, unit=unit)
    if start is not None or stop is not None:
        return _infer_range_type(start, stop, unit=unit)
    if center is not None or span is not None:
        return _infer_around_type(center, span, unit=unit)
    raise TypeError(
        "scan value type cannot be inferred; provide values, endpoints, "
        "an overlay, or value_type"
    )


def _scalar_value_ref_type(value: ValueRef, *, source: str) -> Scalar:
    if not isinstance(value.value_type, Scalar):
        raise TypeError(f"scan {source} must carry a scalar value type")
    return value.value_type


def _infer_values_type(
    values: tuple[ScanValue, ...],
    *,
    unit: str | None,
) -> Scalar:
    if not values:
        raise TypeError("empty scan values require value_type or an overlay")
    if unit is not None:
        for value in values:
            _numeric_scan_coordinate(value, path="scan.values")
        return Scalar(QuantityType(unit=unit))
    if all(isinstance(value, bool) for value in values):
        return Scalar(Bool())
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return Scalar(Int())
    if all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in values
    ):
        return Scalar(Float())
    if all(isinstance(value, str) for value in values):
        return Scalar(String())
    if all(isinstance(value, Quantity) for value in values):
        return _quantity_values_type(cast("tuple[Quantity, ...]", values))
    if all(isinstance(value, EntityRef) for value in values):
        entities = cast("tuple[EntityRef, ...]", values)
        kinds = {entity.kind for entity in entities}
        if len(kinds) != 1:
            raise TypeError("entity scan values require one common entity kind")
        [kind] = kinds
        return Scalar(Entity(entity_kind=kind))
    raise TypeError("scan values require one inferable scalar type")


def _quantity_values_type(values: tuple[Quantity, ...]) -> Scalar:
    unit = values[0].unit
    try:
        for value in values:
            value.to(unit)
    except ValueError as error:
        raise TypeError("quantity scan values require compatible units") from error
    return Scalar(QuantityType(unit=unit))


def _infer_range_type(
    start: ScanCoordinate | None,
    stop: ScanCoordinate | None,
    *,
    unit: str | None,
) -> Scalar:
    if start is None or stop is None:
        raise TypeError("scan range type inference requires start and stop")
    quantities = _inferred_quantities((start, stop), unit=unit)
    if quantities is not None:
        return _quantity_values_type(quantities)
    if (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(stop, int)
        and not isinstance(stop, bool)
    ):
        return Scalar(Int())
    if all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in (start, stop)
    ):
        return Scalar(Float())
    raise TypeError("scan range endpoints require one inferable numeric type")


def _infer_around_type(
    center: ScanCenterInput | None,
    span: ScanCoordinate | None,
    *,
    unit: str | None,
) -> Scalar:
    selected = tuple(
        value
        for value in (center, span)
        if value is not None and not isinstance(value, ValueRef)
    )
    quantities = _inferred_quantities(selected, unit=unit)
    if quantities is not None:
        return Scalar(QuantityType(unit=quantities[0].unit))
    raise TypeError(
        "around scan type inference requires a typed center, quantity coordinates, "
        "or unit"
    )


def _inferred_quantities(
    values: Sequence[ScanCoordinate],
    *,
    unit: str | None,
) -> tuple[Quantity, ...] | None:
    inferred_unit = unit
    for value in values:
        if isinstance(value, Quantity):
            inferred_unit = inferred_unit or value.unit
            break
        if isinstance(value, str):
            parsed = _parse_scan_quantity(value, path="scan")
            inferred_unit = inferred_unit or parsed.unit
            break
    if inferred_unit is None:
        return None
    quantities: list[Quantity] = []
    for value in values:
        if isinstance(value, Quantity):
            selected = value
        elif isinstance(value, str):
            selected = _parse_scan_quantity(value, path="scan")
        else:
            selected = Quantity(
                float(_numeric_scan_coordinate(value, path="scan")),
                inferred_unit,
            )
        try:
            quantities.append(selected.to(inferred_unit))
        except ValueError as error:
            raise TypeError("scan coordinates require compatible units") from error
    if not quantities:
        quantities.append(Quantity(0.0, inferred_unit))
    return tuple(quantities)


def _validate_overlay(value_type: Scalar, overlay: ValueRef | None) -> None:
    if overlay is None:
        return
    if internal_value_ref_parameter_lookup(overlay) is None:
        raise TypeError("axis overlay requires a direct scopecat.parameter_lookup")
    if overlay.value_type != value_type:
        raise TypeError("axis overlay and coordinate must use the same value type")


def _point_target(target: CoordinateRef) -> tuple[str, Scalar]:
    return internal_coordinate_ref_id(target), target.value_type


def _explicit_value_type(value_type: Scalar, *, unit: str | None) -> Scalar:
    atom = value_type.atom
    if unit is not None and isinstance(atom, QuantityType) and atom.unit is None:
        return Scalar(replace(atom, unit=unit))
    return value_type


def _capture_scan_values(
    value_type: Scalar,
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
            value_type,
            selected,
            path=("axis", "values", index),
        )
        captured.append(cast("ScanValue", capture_runtime_input(selected)))
    return tuple(captured)


def _capture_range_scan(
    value_type: Scalar,
    *,
    start: ScanCoordinate,
    stop: ScanCoordinate,
    points: int,
    unit: str | None,
) -> tuple[Scalar, ScanRangeValue, ScanRangeValue]:
    _validate_scan_points(points)
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
        validate_literal(value_type, captured_start, path=("axis", "start"))
        validate_literal(value_type, captured_stop, path=("axis", "stop"))
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
        validate_literal(value_type, start_value, path=("axis", "start"))
        validate_literal(value_type, stop_value, path=("axis", "stop"))
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
        validate_literal(value_type, start, path=("axis", "start"))
        validate_literal(value_type, stop, path=("axis", "stop"))
        if (stop - start) % (points - 1) != 0:
            msg = "integer axis range must have an integral step"
            raise ValueError(msg)
        return value_type, start, stop
    msg = "axis range target must be a float, int, or quantity point"
    raise TypeError(msg)


def _capture_around_scan(
    value_type: Scalar,
    *,
    center: ScanCenterInput,
    span: ScanCoordinate,
    points: int,
    unit: str | None,
) -> tuple[Scalar, ScanCenter, Quantity]:
    target_type = _validate_around_target(value_type, points=points)
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
    axis_type = _explicit_value_type(
        value_type,
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
        axis_type = value_type
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
            value_type,
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


def _validate_around_target(value_type: Scalar, *, points: int) -> QuantityType:
    if not isinstance(value_type.atom, QuantityType):
        msg = "around axis target must be a typed quantity point"
        raise TypeError(msg)
    _validate_scan_points(points)
    return value_type.atom


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
    value: ScanCoordinate,
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
    value: ScanCoordinate,
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
    value: ScanCoordinate,
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
    "ScanCenterInput",
    "ScanCoordinate",
    "ScanValue",
    "ScanValueType",
    "axis",
]
