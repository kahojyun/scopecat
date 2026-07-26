"""Lower public scan intent into point-domain and durable request values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from scopecat.authoring._scan_intents import (
    AroundScanSource,
    AxisSpec,
    ValuesScanSource,
    parameter_cell_lookup,
    scan_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_value_ref_from_expression,
)
from scopecat.compiler.frontend.request_values import (
    project_run_request_scalar,
    project_run_request_value,
)
from scopecat.compiler.frontend.value_binding import bind_scalar_input_refs
from scopecat.graph.relations.model import (
    CellValue,
    ScalarExpr,
    as_scalar_expr,
    param,
)
from scopecat.graph.relations.point_domain import (
    POINT_UNIT,
    PointAxis,
    PointDomainExpr,
    point_axis_linear,
    point_axis_values,
    point_product,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.records.run_request import (
    AroundScanRecord,
    ParameterAroundScanRecord,
    ParameterScanRecord,
    PointScanRecord,
    ScanRecord,
)


def _lower_scan_axis(
    axis: AxisSpec,
    *,
    inputs: Mapping[str, object] | None = None,
) -> PointAxis[ValueRef]:
    """Build one structural point-domain axis from a scalar scan intent."""

    source = axis.source
    if isinstance(source, ValuesScanSource):
        return point_axis_values(
            axis.id,
            _scan_point_value_type(axis),
            _scan_axis_values(source.values, unit=source.unit),
        )
    return point_axis_linear(
        axis.id,
        _scan_point_value_type(axis),
        _lower_scan_center_value_ref(axis, inputs=inputs),
        source.span,
        source.points,
    )


def lower_scans_point_domain(
    scans: Sequence[AxisSpec],
    *,
    inputs: Mapping[str, object] | None = None,
) -> PointDomainExpr[ValueRef]:
    """Lower flat scan axes as one declaration-ordered Cartesian product."""

    domain: PointDomainExpr[ValueRef] = POINT_UNIT
    for scan in scans:
        domain = point_product(
            domain,
            _lower_scan_axis(scan, inputs=inputs),
        )
    return domain


def project_scan_record(
    axis: AxisSpec,
    *,
    inputs: Mapping[str, object] | None = None,
) -> ScanRecord:
    """Project scan intent into the closed durable request value domain."""

    source = axis.source
    if axis.overlay is None:
        if isinstance(source, ValuesScanSource):
            return PointScanRecord.model_validate(
                {
                    "target_id": axis.id,
                    "axis_id": axis.id,
                    "values": [
                        _request_scalar_value(value, inputs=inputs)
                        for value in source.values
                    ],
                    "unit": source.unit,
                }
            )
        return AroundScanRecord.model_validate(
            {
                "target_id": axis.id,
                "axis_id": axis.id,
                "center": project_run_request_scalar(
                    _lower_scan_center(axis, inputs=inputs)
                ),
                "span": _request_scalar_value(source.span, inputs=inputs),
                "points": source.points,
            }
        )
    common = _parameter_scan_record_fields(axis, inputs=inputs)
    if isinstance(source, ValuesScanSource):
        return ParameterScanRecord.model_validate(
            {
                **common,
                "values": [
                    _request_scalar_value(value, inputs=inputs)
                    for value in source.values
                ],
                "unit": source.unit,
            }
        )
    return ParameterAroundScanRecord.model_validate(
        {
            **common,
            "span": _request_scalar_value(source.span, inputs=inputs),
            "points": source.points,
        }
    )


def _parameter_scan_record_fields(
    axis: AxisSpec,
    *,
    inputs: Mapping[str, object] | None,
) -> dict[str, object]:
    lookup, key = parameter_cell_lookup(axis)
    return {
        "table_id": lookup.table_id,
        "key": {
            name: _request_scalar_value(value, inputs=inputs) for name, value in key
        },
        "column": lookup.column_id,
        "axis_id": axis.id,
    }


def _scan_point_value_type(axis: AxisSpec) -> Scalar:
    value_type = axis.value_type
    source = axis.source
    unit = source.unit if isinstance(source, ValuesScanSource) else None
    if (
        unit is not None
        and isinstance(value_type.atom, QuantityType)
        and value_type.atom.unit is None
    ):
        return Scalar(
            replace(value_type.atom, unit=unit),
            nullable=value_type.nullable,
        )
    return value_type


def _scan_axis_values(
    values: tuple[CellValue, ...],
    *,
    unit: str | None,
) -> tuple[CellValue, ...]:
    if unit is None:
        return values
    return tuple(
        Quantity(value=float(cast("int | float", value)), unit=unit) for value in values
    )


def _lower_scan_center(
    axis: AxisSpec,
    *,
    inputs: Mapping[str, object] | None,
) -> ScalarExpr:
    source = axis.source
    assert isinstance(source, AroundScanSource)
    if isinstance(source.center, ValueRef):
        expression = internal_lower_scalar_value_ref(source.center)
    elif source.center is None:
        expression = param(axis.id)
    else:
        expression = as_scalar_expr(source.center)
    if inputs is None:
        return expression
    return bind_scalar_input_refs(expression, inputs)


def _lower_scan_center_value_ref(
    axis: AxisSpec,
    *,
    inputs: Mapping[str, object] | None,
) -> ValueRef:
    source = axis.source
    assert isinstance(source, AroundScanSource)
    center = source.center if isinstance(source.center, ValueRef) else None
    center_type = (
        cast("Scalar", center.value_type) if center is not None else axis.value_type
    )
    return internal_value_ref_from_expression(
        _lower_scan_center(axis, inputs=inputs),
        center_type,
        parameter_contracts=scan_parameter_contracts(axis),
    )


def _request_scalar_value(
    value: object,
    *,
    inputs: Mapping[str, object] | None,
) -> object:
    if isinstance(value, ValueRef):
        expression = internal_lower_scalar_value_ref(value)
        if inputs is not None:
            expression = bind_scalar_input_refs(expression, inputs)
        return project_run_request_scalar(expression)
    if isinstance(value, ScalarExpr):
        expression = value
        if inputs is not None:
            expression = bind_scalar_input_refs(expression, inputs)
        return project_run_request_scalar(expression)
    return project_run_request_value(value, path="scan.value")
