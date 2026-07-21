"""Lower public scan intent into point-domain and durable request values."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import replace
from typing import cast

from scopecat.authoring._point_domain_intents import PointDomainIntent
from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    Scan,
    ScanGroupIntent,
    iter_scan_leaves,
    scan_parameter_contracts,
    scan_point_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_value_ref_from_expression,
    internal_value_ref_point_dependencies,
)
from scopecat.compiler.frontend.request_values import (
    project_run_request_scalar,
    project_run_request_value,
)
from scopecat.compiler.frontend.value_binding import bind_scalar_input_refs
from scopecat.compiler.relations.model import (
    CellValue,
    ScalarExpr,
    as_scalar_expr,
    param,
)
from scopecat.compiler.relations.point_domain import (
    PointAxis,
    point_axis_linear,
    point_axis_values,
    point_dependent_product,
    point_product,
    point_zip,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.records.parameter import Quantity
from scopecat.records.run_request import (
    AroundScanRecord,
    ParameterScanRecord,
    PointScanRecord,
    ScanGroupRecord,
    ScanRecord,
)


def lower_scan_points(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
) -> PointAxis[ValueRef]:
    """Build one structural point-domain axis from a scalar scan intent."""

    if isinstance(scan, ScanGroupIntent):
        msg = "scan groups must lower through the point-domain algebra"
        raise TypeError(msg)
    if isinstance(scan, PointScanIntent):
        value_type = _scan_point_value_type(scan)
        if scan.point_values:
            return point_axis_values(
                scan.point_id,
                value_type,
                _scan_axis_values(scan.point_values, unit=scan.unit),
            )
        if (
            (scan.center is None and not scan.implicit_center)
            or scan.span is None
            or scan.point_count is None
        ):
            msg = f"scan axis {scan.point_id!r} requires values or center/span/points"
            raise ValueError(msg)
        if scan.point_count < 2:
            msg = "scan axis points must be at least 2"
            raise ValueError(msg)
        return point_axis_linear(
            scan.point_id,
            value_type,
            _lower_scan_center_value_ref(scan, inputs=inputs),
            _scan_quantity(scan.span),
            scan.point_count,
        )
    if isinstance(scan, ParameterScanIntent):
        value_type = _scan_point_value_type(scan)
        return point_axis_values(
            scan.point_id,
            value_type,
            _scan_axis_values(scan.values, unit=scan.unit),
        )
    msg = "scan axis must be a point or parameter scan"
    raise TypeError(msg)


def lower_scan_point_domain(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
    dependency_edges: Collection[tuple[str, str]] = (),
) -> PointDomainIntent:
    """Preserve Cartesian, dependent, and positional scan composition."""

    if not isinstance(scan, ScanGroupIntent):
        return lower_scan_points(scan, inputs=inputs)
    children = tuple(
        lower_scan_point_domain(
            child,
            inputs=inputs,
            dependency_edges=dependency_edges,
        )
        for child in scan.scans
    )
    if scan.kind == "zip":
        return point_zip(*children)

    combined = children[0]
    produced = {scan_point_id(leaf) for leaf in iter_scan_leaves(scan.scans[0])}
    for child_scan, child_domain in zip(scan.scans[1:], children[1:], strict=True):
        child_ids = {scan_point_id(leaf) for leaf in iter_scan_leaves(child_scan)}
        dependent = any(
            producer_id in produced and consumer_id in child_ids
            for producer_id, consumer_id in dependency_edges
        )
        combined = (
            point_dependent_product(combined, child_domain)
            if dependent
            else point_product(combined, child_domain)
        )
        produced.update(child_ids)
    return combined


def project_scan_record(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
) -> ScanRecord:
    """Project scan intent into the closed durable request value domain."""

    if isinstance(scan, PointScanIntent):
        if scan.point_values:
            return PointScanRecord.model_validate(
                {
                    "target_id": scan.point_id,
                    "axis_id": scan.point_id,
                    "values": [
                        _request_scalar_value(value, inputs=inputs)
                        for value in scan.point_values
                    ],
                    "unit": scan.unit,
                }
            )
        if (
            (scan.center is None and not scan.implicit_center)
            or scan.span is None
            or scan.point_count is None
        ):
            msg = f"scan axis {scan.point_id!r} requires values or center/span/points"
            raise ValueError(msg)
        return AroundScanRecord.model_validate(
            {
                "target_id": scan.point_id,
                "axis_id": scan.point_id,
                "center": project_run_request_scalar(
                    _lower_scan_center(scan, inputs=inputs)
                ),
                "span": _request_scalar_value(scan.span, inputs=inputs),
                "points": scan.point_count,
            }
        )
    if isinstance(scan, ParameterScanIntent):
        return ParameterScanRecord.model_validate(
            {
                "table_id": scan.table_id,
                "key": {
                    name: _request_scalar_value(value, inputs=inputs)
                    for name, value in scan.key
                },
                "column": scan.column,
                "axis_id": scan.point_id,
                "values": [
                    _request_scalar_value(value, inputs=inputs) for value in scan.values
                ],
                "unit": scan.unit,
            }
        )
    if not isinstance(scan, ScanGroupIntent):
        msg = "invalid scan handle"
        raise TypeError(msg)
    return ScanGroupRecord(
        kind=scan.kind,
        scans=[project_scan_record(child, inputs=inputs) for child in scan.scans],
    )


def _scan_point_value_type(scan: PointScanIntent | ParameterScanIntent) -> Scalar:
    value_type = scan.target.value_type
    if not isinstance(value_type, Scalar):
        msg = "scan target must carry a scalar value type"
        raise TypeError(msg)
    if (
        scan.unit is not None
        and isinstance(value_type.atom, QuantityType)
        and value_type.atom.unit is None
    ):
        return Scalar(
            replace(value_type.atom, unit=scan.unit),
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


def _scan_quantity(value: object) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if isinstance(value, str):
        match = re.match(
            r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([A-Za-z][A-Za-z0-9_]*)\s*$",
            value,
        )
        if match is not None:
            return Quantity(value=float(match.group(1)), unit=match.group(2))
    msg = "scan span must be a Quantity or '<number> <unit>' string"
    raise TypeError(msg)


def _lower_scan_center(
    scan: PointScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> ScalarExpr:
    if isinstance(scan.center, ValueRef):
        expression = internal_lower_scalar_value_ref(scan.center)
    elif scan.center is not None:
        expression = as_scalar_expr(scan.center)
    elif scan.implicit_center:
        expression = param(scan.point_id)
    else:
        msg = f"scan axis {scan.point_id!r} requires a center"
        raise ValueError(msg)
    if inputs is None:
        return expression
    return bind_scalar_input_refs(expression, inputs)


def _lower_scan_center_value_ref(
    scan: PointScanIntent,
    *,
    inputs: Mapping[str, object] | None,
) -> ValueRef:
    center = scan.center if isinstance(scan.center, ValueRef) else None
    center_type = center.value_type if center is not None else scan.target.value_type
    if not isinstance(center_type, Scalar):
        msg = "scan center must carry a scalar value type"
        raise TypeError(msg)
    return internal_value_ref_from_expression(
        _lower_scan_center(scan, inputs=inputs),
        center_type,
        parameter_contracts=scan_parameter_contracts(scan),
        point_dependencies=(
            internal_value_ref_point_dependencies(center) if center is not None else ()
        ),
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
