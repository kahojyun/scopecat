"""Lower public scan intent into point-domain and durable request values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from scopecat.authoring._point_domain_intents import PointDomainIntent
from scopecat.authoring._scan_intents import (
    CenteredParameterScanIntent,
    CenteredPointScanIntent,
    ExplicitParameterScanIntent,
    ExplicitPointScanIntent,
    ImplicitScanCenter,
    ScanLeafIntent,
    parameter_scan_lookup,
    scan_parameter_contracts,
    scan_point_id,
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


def lower_scan_points(
    scan: ScanLeafIntent,
    *,
    inputs: Mapping[str, object] | None = None,
) -> PointAxis[ValueRef]:
    """Build one structural point-domain axis from a scalar scan intent."""

    match scan:
        case ExplicitPointScanIntent() | ExplicitParameterScanIntent():
            return point_axis_values(
                scan_point_id(scan),
                _scan_point_value_type(scan),
                _scan_axis_values(scan.values, unit=scan.unit),
            )
        case CenteredPointScanIntent():
            return point_axis_linear(
                scan_point_id(scan),
                _scan_point_value_type(scan),
                _lower_scan_center_value_ref(scan, inputs=inputs),
                scan.span,
                scan.points,
            )
        case CenteredParameterScanIntent():
            return point_axis_linear(
                scan_point_id(scan),
                _scan_point_value_type(scan),
                _lower_parameter_scan_center_value_ref(scan, inputs=inputs),
                scan.span,
                scan.points,
            )


def lower_scans_point_domain(
    scans: Sequence[ScanLeafIntent],
    *,
    inputs: Mapping[str, object] | None = None,
) -> PointDomainIntent:
    """Lower flat scan axes as one declaration-ordered Cartesian product."""

    domain: PointDomainIntent = POINT_UNIT
    for scan in scans:
        domain = point_product(
            domain,
            lower_scan_points(scan, inputs=inputs),
        )
    return domain


def project_scan_record(
    scan: ScanLeafIntent,
    *,
    inputs: Mapping[str, object] | None = None,
) -> ScanRecord:
    """Project scan intent into the closed durable request value domain."""

    match scan:
        case ExplicitPointScanIntent():
            return PointScanRecord.model_validate(
                {
                    "target_id": scan_point_id(scan),
                    "axis_id": scan_point_id(scan),
                    "values": [
                        _request_scalar_value(value, inputs=inputs)
                        for value in scan.values
                    ],
                    "unit": scan.unit,
                }
            )
        case CenteredPointScanIntent():
            return AroundScanRecord.model_validate(
                {
                    "target_id": scan_point_id(scan),
                    "axis_id": scan_point_id(scan),
                    "center": project_run_request_scalar(
                        _lower_scan_center(scan, inputs=inputs)
                    ),
                    "span": _request_scalar_value(scan.span, inputs=inputs),
                    "points": scan.points,
                }
            )
        case ExplicitParameterScanIntent():
            common = _parameter_scan_record_fields(scan, inputs=inputs)
            return ParameterScanRecord.model_validate(
                {
                    **common,
                    "values": [
                        _request_scalar_value(value, inputs=inputs)
                        for value in scan.values
                    ],
                    "unit": scan.unit,
                }
            )
        case CenteredParameterScanIntent():
            common = _parameter_scan_record_fields(scan, inputs=inputs)
            return ParameterAroundScanRecord.model_validate(
                {
                    **common,
                    "span": _request_scalar_value(scan.span, inputs=inputs),
                    "points": scan.points,
                }
            )


def _parameter_scan_record_fields(
    scan: ExplicitParameterScanIntent | CenteredParameterScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> dict[str, object]:
    lookup, key = parameter_scan_lookup(scan)
    return {
        "table_id": lookup.table_id,
        "key": {
            name: _request_scalar_value(value, inputs=inputs) for name, value in key
        },
        "column": lookup.column_id,
        "axis_id": scan_point_id(scan),
    }


def _scan_point_value_type(scan: ScanLeafIntent) -> Scalar:
    value_type = cast("Scalar", scan.target.value_type)
    unit = (
        scan.unit
        if isinstance(
            scan,
            ExplicitPointScanIntent | ExplicitParameterScanIntent,
        )
        else None
    )
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
    scan: CenteredPointScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> ScalarExpr:
    if isinstance(scan.center, ValueRef):
        expression = internal_lower_scalar_value_ref(scan.center)
    elif isinstance(scan.center, ImplicitScanCenter):
        expression = param(scan_point_id(scan))
    else:
        expression = as_scalar_expr(scan.center)
    if inputs is None:
        return expression
    return bind_scalar_input_refs(expression, inputs)


def _lower_scan_center_value_ref(
    scan: CenteredPointScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> ValueRef:
    center = scan.center if isinstance(scan.center, ValueRef) else None
    center_type = (
        cast("Scalar", center.value_type)
        if center is not None
        else cast("Scalar", scan.target.value_type)
    )
    return internal_value_ref_from_expression(
        _lower_scan_center(scan, inputs=inputs),
        center_type,
        parameter_contracts=scan_parameter_contracts(scan),
    )


def _lower_parameter_scan_center_value_ref(
    scan: CenteredParameterScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> ValueRef:
    """Lower an around-axis center through the ordinary parameter lookup path.

    Reusing the same lookup contract as authored program inputs keeps cell
    identity, input binding, and specialization semantics aligned; a parameter
    scan does not introduce a second configuration access mechanism.
    """

    center = scan.lookup
    expression = internal_lower_scalar_value_ref(center)
    if inputs is not None:
        expression = bind_scalar_input_refs(expression, inputs)
    return internal_value_ref_from_expression(
        expression,
        cast("Scalar", scan.target.value_type),
        parameter_contracts=scan_parameter_contracts(scan),
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
