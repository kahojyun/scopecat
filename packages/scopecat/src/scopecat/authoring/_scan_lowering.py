"""Private lowering and durable projection for public scan intent."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import replace

from scopecat._point_domain_algebra import (
    point_dependent_product,
    point_product,
    point_rows,
    point_zip,
)
from scopecat._relations import (
    RelationExpr,
    ScalarExpr,
    as_scalar_expr,
    grid,
    param,
)
from scopecat._relations import linspace as relation_linspace
from scopecat._relations import values as relation_values
from scopecat.authoring._point_domain_intents import PointDomainIntent
from scopecat.authoring._request_values import (
    project_run_request_scalar,
    project_run_request_value,
)
from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    Scan,
    ScanGroupIntent,
    iter_scan_leaves,
    scan_parameter_contracts,
    scan_point_id,
)
from scopecat.authoring._value_binding import bind_scalar_input_refs
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_value_ref_bound_point_input_ids,
    internal_value_ref_free_point_dependencies,
    internal_value_ref_from_expression,
    internal_value_ref_point_dependencies,
)
from scopecat.models.parameter import Quantity
from scopecat.models.run_request import (
    AroundScanRecord,
    ParameterScanRecord,
    PointScanRecord,
    ScanGroupRecord,
    ScanRecord,
)
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, Table, TableColumn


def lower_scan_points(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
) -> ValueRef:
    """Build one typed relation leaf from a scalar scan axis."""

    if isinstance(scan, ScanGroupIntent):
        msg = "scan groups must lower through the point-domain algebra"
        raise TypeError(msg)
    center = (
        scan.center
        if isinstance(scan, PointScanIntent) and isinstance(scan.center, ValueRef)
        else None
    )
    return internal_value_ref_from_expression(
        _lower_scan_points_relation(scan, inputs=inputs),
        _scan_points_type(scan),
        parameter_contracts=scan_parameter_contracts(scan),
        point_dependencies=(
            internal_value_ref_point_dependencies(center) if center is not None else ()
        ),
        free_point_dependencies=(
            internal_value_ref_free_point_dependencies(center)
            if center is not None
            else ()
        ),
        bound_point_input_ids=(
            internal_value_ref_bound_point_input_ids(center)
            if center is not None
            else frozenset()
        ),
    )


def lower_scan_point_domain(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
    dependency_edges: Collection[tuple[str, str]] = (),
) -> PointDomainIntent:
    """Preserve Cartesian, dependent, and positional scan composition."""

    if not isinstance(scan, ScanGroupIntent):
        return point_rows(lower_scan_points(scan, inputs=inputs))
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


def _lower_scan_points_relation(
    scan: Scan,
    *,
    inputs: Mapping[str, object] | None = None,
) -> RelationExpr:
    """Lower a scan at the private typed-value implementation boundary."""

    if isinstance(scan, PointScanIntent):
        if scan.point_values:
            source = (
                relation_values(scan.point_values, unit=scan.unit)
                if scan.unit is not None
                else list(scan.point_values)
            )
            return grid(**{scan.point_id: source})
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
        span = _scan_quantity(scan.span)
        center = _lower_scan_center(scan, inputs=inputs)
        return grid(
            **{
                scan.point_id: relation_linspace(
                    center - span / 2,
                    center + span / 2,
                    scan.point_count,
                )
            }
        )
    if isinstance(scan, ParameterScanIntent):
        source = (
            relation_values(scan.values, unit=scan.unit)
            if scan.unit is not None
            else list(scan.values)
        )
        return grid(**{scan.point_id: source})
    msg = "scan relation leaf must be a point or parameter scan"
    raise TypeError(msg)


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


def _scan_points_type(scan: Scan) -> Table:
    if isinstance(scan, PointScanIntent | ParameterScanIntent):
        if not isinstance(scan.target.value_type, Scalar):
            msg = "scan target must carry a scalar value type"
            raise TypeError(msg)
        row_count = (
            len(scan.point_values)
            if isinstance(scan, PointScanIntent) and scan.point_values
            else scan.point_count
            if isinstance(scan, PointScanIntent)
            else len(scan.values)
        )
        if row_count is None:
            msg = f"scan axis {scan.point_id!r} has no statically known row count"
            raise ValueError(msg)
        return Table(
            columns=(TableColumn(scan.point_id, _scan_point_value_type(scan)),),
            min_rows=row_count,
            max_rows=row_count,
        )
    if not isinstance(scan, ScanGroupIntent):
        msg = "invalid scan handle"
        raise TypeError(msg)
    children = tuple(_scan_points_type(child) for child in scan.scans)
    columns = tuple(column for child in children for column in child.columns)
    row_counts = tuple(child.min_rows for child in children)
    if scan.kind == "zip":
        if len(set(row_counts)) != 1:
            msg = "zip scan group requires scans with equal length"
            raise ValueError(msg)
        row_count = row_counts[0]
    else:
        row_count = 1
        for count in row_counts:
            row_count *= count
    return Table(
        columns=columns,
        min_rows=row_count,
        max_rows=row_count,
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


__all__ = ["lower_scan_point_domain", "lower_scan_points", "project_scan_record"]
