"""Strict test helpers for the verify -> select -> evaluate pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.relations.backend import (
    EvalContext,
    ParameterRelationData,
    RelationBackend,
    select_relation_plan,
)
from scopecat.compiler.relations.backend import (
    evaluate_relation as evaluate_selected_relation,
)
from scopecat.compiler.relations.backend import (
    evaluate_scalar as evaluate_selected_scalar,
)
from scopecat.compiler.relations.backend import (
    evaluate_series as evaluate_selected_series,
)
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    Row,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
    verify_scalar_value_expr,
    verify_series_value_expr,
    verify_table_value_expr,
    verify_value_expr,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import bind_each, set_state_field
from scopecat.compiler.typed.state import StateSpec
from scopecat.kernel.value_types import Scalar, Series, Table, ValueType


def scalar_value_expr(
    expression: object,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> ScalarValueExpr:
    return verify_scalar_value_expr(
        (
            expression
            if isinstance(expression, ScalarExpr)
            else as_scalar_expr(expression)
        ),
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def series_value_expr(
    expression: SeriesExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Series | None = None,
) -> SeriesValueExpr:
    return verify_series_value_expr(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def table_value_expr(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Table | None = None,
) -> TableValueExpr:
    return verify_table_value_expr(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def point_domain(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Table | None = None,
    entity_columns: tuple[str, ...] = (),
) -> PointDomain:
    return PointDomain(
        root=point_rows(
            table_value_expr(
                expression,
                bindings=bindings,
                expected_type=expected_type,
            )
        ),
        entity_columns=entity_columns,
    )


def state_field(
    resource: object,
    *,
    capability_id: str,
    field_path: str,
    value: object | ComputeResultRef,
    route_entities: Sequence[object | ScalarValueExpr | SeriesValueExpr] = (),
    bindings: RelationTypeBindings | None = None,
    resource_type: Scalar | None = None,
    value_type: Scalar | None = None,
) -> StateSpec:
    selected_bindings = bindings or RelationTypeBindings()
    return set_state_field(
        scalar_value_expr(
            resource,
            bindings=selected_bindings,
            expected_type=resource_type,
        ),
        capability_id=capability_id,
        field_path=field_path,
        value=(
            value
            if isinstance(value, ComputeResultRef)
            else scalar_value_expr(
                value,
                bindings=selected_bindings,
                expected_type=value_type,
            )
        ),
        route_entities=tuple(
            entity
            if isinstance(entity, ScalarValueExpr | SeriesValueExpr)
            else (
                series_value_expr(entity, bindings=selected_bindings)
                if isinstance(entity, SeriesExpr)
                else scalar_value_expr(entity, bindings=selected_bindings)
            )
            for entity in route_entities
        ),
    )


def each_state(
    relation: RelationExpr,
    *state: StateSpec,
    bindings: RelationTypeBindings | None = None,
    expected_type: Table | None = None,
    row_scope_id: RowScopeId | None = None,
) -> StateSpec:
    return bind_each(
        table_value_expr(
            relation,
            bindings=bindings,
            expected_type=expected_type,
        ),
        *state,
        row_scope_id=row_scope_id,
    )


def value_expr(
    expression: ScalarExpr | SeriesExpr | RelationExpr,
    *,
    expected_type: ValueType,
    bindings: RelationTypeBindings | None = None,
) -> ValueExpr:
    return verify_value_expr(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )


def evaluate_scalar(
    backend: RelationBackend,
    expression: ScalarExpr,
    ctx: EvalContext,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Scalar | None = None,
) -> CellValue:
    verified = verify_relation_plan(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )
    return evaluate_selected_scalar(
        backend,
        select_relation_plan(backend, verified),
        ctx,
    )


def evaluate_series(
    backend: RelationBackend,
    expression: SeriesExpr,
    ctx: EvalContext,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: Series | None = None,
) -> list[CellValue]:
    verified = verify_relation_plan(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )
    return evaluate_selected_series(
        backend,
        select_relation_plan(backend, verified),
        ctx,
    )


def evaluate_relation(
    backend: RelationBackend,
    expression: RelationExpr,
    params: ParameterRelationData | None = None,
    *,
    row: Row | None = None,
    outer_row: Row | None = None,
    point_row: Row | None = None,
    row_scopes: Mapping[RowScopeId, Row] | None = None,
    inputs: Mapping[str, object] | None = None,
    bindings: RelationTypeBindings | None = None,
    expected_type: Table | None = None,
) -> list[Row]:
    verified = verify_relation_plan(
        expression,
        bindings=bindings or RelationTypeBindings(),
        expected_type=expected_type,
    )
    return evaluate_selected_relation(
        backend,
        select_relation_plan(backend, verified),
        params,
        row=row,
        outer_row=outer_row,
        point_row=point_row,
        row_scopes=row_scopes,
        inputs=inputs,
    )


def materialize_scalar_value(
    backend: RelationBackend,
    value: ScalarValueExpr,
    ctx: EvalContext,
) -> CellValue:
    return evaluate_selected_scalar(
        backend,
        select_relation_plan(backend, value.plan),
        ctx,
    )


def materialize_series_value(
    backend: RelationBackend,
    value: SeriesValueExpr,
    ctx: EvalContext,
) -> list[CellValue]:
    return evaluate_selected_series(
        backend,
        select_relation_plan(backend, value.plan),
        ctx,
    )


def materialize_table_value(
    backend: RelationBackend,
    value: TableValueExpr,
    params: ParameterRelationData | None = None,
    *,
    row: Row | None = None,
    outer_row: Row | None = None,
    point_row: Row | None = None,
    row_scopes: Mapping[RowScopeId, Row] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> list[Row]:
    return evaluate_selected_relation(
        backend,
        select_relation_plan(backend, value.plan),
        params,
        row=row,
        outer_row=outer_row,
        point_row=point_row,
        row_scopes=row_scopes,
        inputs=inputs,
    )


__all__ = [
    "each_state",
    "evaluate_relation",
    "evaluate_scalar",
    "evaluate_series",
    "materialize_scalar_value",
    "materialize_series_value",
    "materialize_table_value",
    "point_domain",
    "scalar_value_expr",
    "series_value_expr",
    "state_field",
    "table_value_expr",
    "value_expr",
]
