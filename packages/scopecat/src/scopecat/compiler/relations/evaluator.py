"""Deterministic implementation of relation evaluation semantics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import cmp_to_key
from itertools import product
from typing import cast

from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CaseScalarExpr,
    CellValue,
    ColumnScalarExpr,
    CrossRelationExpr,
    FilterRelationExpr,
    GridColumn,
    GridRelationExpr,
    InputRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    JoinRelationExpr,
    LateralCrossRelationExpr,
    LimitRelationExpr,
    LinspaceSeriesExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    OuterColumnScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    PointCrossRelationExpr,
    RangeSeriesExpr,
    RelationColumnSeriesExpr,
    RelationEntitiesSeriesExpr,
    RelationExpr,
    RelationExpression,
    RelationGridColumn,
    Row,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    ScalarGridColumn,
    SelectRelationExpr,
    SeriesExpr,
    SeriesExpression,
    SeriesGridColumn,
    SortRelationExpr,
    TableRelationExpr,
    ValuesGridColumn,
    ValuesSeriesExpr,
    WithColumnsRelationExpr,
    ZipRelationExpr,
)
from scopecat.compiler.relations.operators import (
    compare_ordered_values,
    runtime_values_equal,
)
from scopecat.compiler.relations.point_domain import decompose_product_ordinal
from scopecat.compiler.relations.scalar_eval import (
    cell_matches,
    eval_binary,
    is_cell_value,
    read_path,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


def evaluate_scalar_expression(expression: ScalarExpr, ctx: EvalContext) -> CellValue:
    scalar = cast("ScalarExpression", expression)
    match scalar:
        case LiteralScalarExpr():
            return scalar.value
        case ColumnScalarExpr():
            row_scope_id = scalar.row_scope_id
            row = (
                ctx.row_scopes.get(row_scope_id)
                if row_scope_id is not None
                else ctx.row
            )
            if row is None:
                scope_name = (
                    row_scope_id.qualified_name
                    if row_scope_id is not None
                    else "<implicit-current-row>"
                )
                msg = f"row column references an inactive scope: {scope_name!r}"
                raise ValueError(msg)
            return read_path(row, scalar.name)
        case OuterColumnScalarExpr():
            if ctx.outer_row is None:
                msg = f"outer column {scalar.name!r} used outside scope"
                raise ValueError(msg)
            return read_path(ctx.outer_row, scalar.name)
        case PointColumnScalarExpr():
            return read_path(ctx.point_row, scalar.name)
        case InputScalarExpr():
            return read_path(ctx.inputs, scalar.name)
        case ParameterScalarExpr():
            return ctx.params.scalar(scalar.name)
        case ParameterLookupScalarExpr():
            resolved_key = {
                name: evaluate_scalar_expression(value, ctx)
                for name, value in scalar.key.items()
            }
            row = ctx.params.lookup_row(scalar.table_id, resolved_key)
            return read_path(row, scalar.column)
        case BinaryScalarExpr():
            return eval_binary(
                scalar.op,
                evaluate_scalar_expression(scalar.left, ctx),
                evaluate_scalar_expression(scalar.right, ctx),
            )
        case CaseScalarExpr():
            for branch in scalar.cases:
                if evaluate_scalar_expression(branch.condition, ctx) is True:
                    return evaluate_scalar_expression(branch.value, ctx)
            return evaluate_scalar_expression(scalar.fallback, ctx)


def evaluate_series_expression(
    expression: SeriesExpr, ctx: EvalContext
) -> list[CellValue]:
    series = cast("SeriesExpression", expression)
    match series:
        case ValuesSeriesExpr():
            return list(series.items)
        case LinspaceSeriesExpr():
            count = series.count
            start_value = evaluate_scalar_expression(series.start, ctx)
            stop_value = evaluate_scalar_expression(series.stop, ctx)
            unit = series.unit or _quantity_unit(start_value)
            start = _series_float(start_value, unit=unit)
            stop = _series_float(stop_value, unit=unit)
            if count == 1:
                return _series_values([start], unit=unit)
            step_value = (stop - start) / (count - 1)
            return _series_values(
                [start + index * step_value for index in range(count)],
                unit=unit,
            )
        case RangeSeriesExpr():
            start_value = evaluate_scalar_expression(series.start, ctx)
            stop_value = evaluate_scalar_expression(series.stop, ctx)
            step_value = evaluate_scalar_expression(series.step, ctx)
            unit = series.unit or _quantity_unit(start_value)
            start = _series_float(start_value, unit=unit)
            stop = _series_float(stop_value, unit=unit)
            step = _series_float(step_value, unit=unit)
            if step == 0:
                msg = "range step must not be zero"
                raise ValueError(msg)
            selected: list[float] = []
            current = start
            if step > 0:
                while current < stop or (
                    series.include_stop and _float_almost_equal(current, stop)
                ):
                    selected.append(current)
                    next_current = current + step
                    if next_current == current:
                        msg = "range step is too small to advance the current value"
                        raise ValueError(msg)
                    current = next_current
            else:
                while current > stop or (
                    series.include_stop and _float_almost_equal(current, stop)
                ):
                    selected.append(current)
                    next_current = current + step
                    if next_current == current:
                        msg = "range step is too small to advance the current value"
                        raise ValueError(msg)
                    current = next_current
            return _series_values(selected, unit=unit)
        case InputSeriesExpr():
            return _input_series(ctx.inputs, series.name)
        case ParameterSeriesExpr():
            return ctx.params.series_values(series.name)
        case RelationColumnSeriesExpr():
            return [
                read_path(row, series.column)
                for row in evaluate_relation_expression(series.source, ctx)
            ]
        case RelationEntitiesSeriesExpr():
            entities: list[CellValue] = []
            for row in evaluate_relation_expression(series.source, ctx):
                for column in series.columns:
                    value = read_path(row, column)
                    if not any(cell_matches(existing, value) for existing in entities):
                        entities.append(value)
            return entities


def _evaluate_grid_column(column: GridColumn, ctx: EvalContext) -> list[CellValue]:
    match column:
        case ScalarGridColumn():
            return [evaluate_scalar_expression(column.scalar, ctx)]
        case SeriesGridColumn():
            return evaluate_series_expression(column.series, ctx)
        case RelationGridColumn():
            return cast(
                "list[CellValue]",
                evaluate_relation_expression(column.relation, ctx),
            )
        case ValuesGridColumn():
            return list(column.values)


def evaluate_relation_expression(
    expression: RelationExpr, ctx: EvalContext
) -> list[Row]:
    relation = cast("RelationExpression", expression)
    match relation:
        case LiteralRowsRelationExpr():
            return [dict(row) for row in relation.rows]
        case TableRelationExpr():
            return ctx.params.table_rows(relation.table_id)
        case InputRelationExpr():
            return _input_table(ctx.inputs, relation.name)
        case GridRelationExpr():
            names = tuple(relation.columns)
            choices = [
                _evaluate_grid_column(relation.columns[name], ctx) for name in names
            ]
            return [
                dict(zip(names, values, strict=True)) for values in product(*choices)
            ]
        case SelectRelationExpr():
            return [
                {
                    column: read_path(source_row, column)
                    for column in relation.select_columns
                }
                for source_row in evaluate_relation_expression(relation.source, ctx)
            ]
        case FilterRelationExpr():
            selected: list[Row] = []
            for source_row in evaluate_relation_expression(relation.source, ctx):
                child_ctx = _child_context(
                    ctx,
                    row=source_row,
                    row_scope_id=relation.row_scope_id,
                )
                if evaluate_scalar_expression(relation.condition, child_ctx) is True:
                    selected.append(source_row)
            return selected
        case JoinRelationExpr():
            left_rows = evaluate_relation_expression(relation.left, ctx)
            right_rows = evaluate_relation_expression(relation.right, ctx)
            on = relation.on
            allowed_shared = {
                left_column
                for left_column, right_column in on.items()
                if left_column == right_column
            }
            _require_disjoint_row_columns(
                left_rows,
                right_rows,
                operation="join",
                allowed_shared=allowed_shared,
            )
            return [
                _merge_rows(
                    left_row,
                    right_row,
                    operation="join",
                    allowed_shared=allowed_shared,
                )
                for left_row in left_rows
                for right_row in right_rows
                if _join_keys_match(left_row, right_row, on)
            ]
        case CrossRelationExpr():
            left_rows = evaluate_relation_expression(relation.left, ctx)
            right_rows = evaluate_relation_expression(relation.right, ctx)
            _require_disjoint_row_columns(left_rows, right_rows, operation="cross")
            return [
                _merge_rows(left_row, right_row, operation="cross")
                for left_row in left_rows
                for right_row in right_rows
            ]
        case LateralCrossRelationExpr():
            crossed: list[Row] = []
            for left_row in evaluate_relation_expression(relation.left, ctx):
                right_rows = evaluate_relation_expression(
                    relation.right,
                    EvalContext(
                        params=ctx.params,
                        row=left_row,
                        outer_row=left_row,
                        point_row=ctx.point_row,
                        row_scopes=ctx.row_scopes,
                        inputs=ctx.inputs,
                    ),
                )
                _require_disjoint_row_columns(
                    [left_row],
                    right_rows,
                    operation="lateral_cross",
                )
                crossed.extend(
                    _merge_rows(left_row, right_row, operation="lateral_cross")
                    for right_row in right_rows
                )
            return crossed
        case PointCrossRelationExpr():
            crossed = []
            for left_row in evaluate_relation_expression(relation.left, ctx):
                point_row = (
                    _merge_rows(ctx.point_row, left_row, operation="point_cross")
                    if ctx.point_row
                    else left_row
                )
                right_rows = evaluate_relation_expression(
                    relation.right,
                    EvalContext(
                        params=ctx.params,
                        row=ctx.row,
                        outer_row=ctx.outer_row,
                        point_row=point_row,
                        row_scopes=ctx.row_scopes,
                        inputs=ctx.inputs,
                    ),
                )
                _require_disjoint_row_columns(
                    [left_row],
                    right_rows,
                    operation="point_cross",
                )
                crossed.extend(
                    _merge_rows(left_row, right_row, operation="point_cross")
                    for right_row in right_rows
                )
            return crossed
        case ZipRelationExpr():
            rows_by_source = [
                evaluate_relation_expression(source, ctx) for source in relation.sources
            ]
            lengths = {len(rows) for rows in rows_by_source}
            if len(lengths) != 1:
                msg = "zip relation requires sources with equal length"
                raise ValueError(msg)
            zipped: list[Row] = []
            for row_index in range(next(iter(lengths), 0)):
                merged: Row = {}
                for rows in rows_by_source:
                    row = rows[row_index]
                    overlap = set(merged).intersection(row)
                    if overlap:
                        msg = "zip relation contains duplicate columns: " + ", ".join(
                            sorted(overlap)
                        )
                        raise ValueError(msg)
                    merged.update(row)
                zipped.append(merged)
            return zipped
        case WithColumnsRelationExpr():
            derived: list[Row] = []
            for source_row in evaluate_relation_expression(relation.source, ctx):
                next_row = dict(source_row)
                child_ctx = _child_context(
                    ctx,
                    row=next_row,
                    row_scope_id=relation.row_scope_id,
                )
                for name, scalar in relation.new_columns.items():
                    next_row[name] = evaluate_scalar_expression(scalar, child_ctx)
                derived.append(next_row)
            return derived
        case SortRelationExpr():
            rows = evaluate_relation_expression(relation.source, ctx)
            columns = tuple(relation.sort_columns)
            return sorted(
                rows,
                key=cmp_to_key(
                    lambda left, right: _compare_rows(left, right, columns=columns)
                ),
            )
        case LimitRelationExpr():
            return evaluate_relation_expression(relation.source, ctx)[
                : relation.limit_count
            ]


def evaluate_relation_expression_ordinals(
    expression: RelationExpr,
    ctx: EvalContext,
    ordinals: tuple[int, ...],
) -> list[Row]:
    """Evaluate selected stable ordinals, falling back for order-changing nodes."""

    relation = cast("RelationExpression", expression)
    match relation:
        case LiteralRowsRelationExpr():
            return _select_relation_rows(relation.rows, ordinals)
        case TableRelationExpr():
            return _select_relation_rows(
                ctx.params.table_rows(relation.table_id),
                ordinals,
            )
        case InputRelationExpr():
            return _select_relation_rows(
                _input_table(ctx.inputs, relation.name),
                ordinals,
            )
        case GridRelationExpr():
            names = tuple(relation.columns)
            choices = tuple(
                _evaluate_grid_column(relation.columns[name], ctx) for name in names
            )
            counts = tuple(len(values) for values in choices)
            total = math.prod(counts)
            if any(ordinal >= total for ordinal in ordinals):
                raise ValueError("relation ordinal is outside the evaluated grid")
            return [
                dict(
                    zip(
                        names,
                        (
                            choices[index][child_ordinal]
                            for index, child_ordinal in enumerate(
                                decompose_product_ordinal(ordinal, counts)
                            )
                        ),
                        strict=True,
                    )
                )
                for ordinal in ordinals
            ]
        case SelectRelationExpr():
            return [
                {
                    column: read_path(source_row, column)
                    for column in relation.select_columns
                }
                for source_row in evaluate_relation_expression_ordinals(
                    relation.source,
                    ctx,
                    ordinals,
                )
            ]
        case WithColumnsRelationExpr():
            derived: list[Row] = []
            for source_row in evaluate_relation_expression_ordinals(
                relation.source,
                ctx,
                ordinals,
            ):
                next_row = dict(source_row)
                child_ctx = _child_context(
                    ctx,
                    row=next_row,
                    row_scope_id=relation.row_scope_id,
                )
                for name, scalar in relation.new_columns.items():
                    next_row[name] = evaluate_scalar_expression(scalar, child_ctx)
                derived.append(next_row)
            return derived
        case LimitRelationExpr():
            if any(ordinal >= relation.limit_count for ordinal in ordinals):
                raise ValueError("relation ordinal is outside the limit")
            return evaluate_relation_expression_ordinals(
                relation.source,
                ctx,
                ordinals,
            )
        case _:
            return _select_relation_rows(
                evaluate_relation_expression(relation, ctx),
                ordinals,
            )


def _select_relation_rows(rows: Sequence[Row], ordinals: tuple[int, ...]) -> list[Row]:
    if ordinals and ordinals[-1] >= len(rows):
        raise ValueError("relation ordinal is outside the evaluated rows")
    return [dict(rows[ordinal]) for ordinal in ordinals]


def _child_context(
    ctx: EvalContext,
    *,
    row: Row,
    point_row: Row | None = None,
    row_scope_id: RowScopeId | None = None,
) -> EvalContext:
    row_scopes = dict(ctx.row_scopes)
    if row_scope_id is not None:
        row_scopes[row_scope_id] = row
    return EvalContext(
        params=ctx.params,
        row=row,
        outer_row=ctx.outer_row,
        point_row=ctx.point_row if point_row is None else point_row,
        row_scopes=row_scopes,
        inputs=ctx.inputs,
    )


def _quantity_unit(value: CellValue) -> str | None:
    return value.unit if isinstance(value, Quantity) else None


def _series_float(value: CellValue, *, unit: str | None) -> float:
    if isinstance(value, Quantity):
        return value.value if unit is None else value.to(unit).value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = f"series bound must be numeric or quantity, got {value!r}"
    raise TypeError(msg)


def _series_values(raw_values: Sequence[float], *, unit: str | None) -> list[CellValue]:
    if any(not math.isfinite(value) for value in raw_values):
        msg = "series materialization produced a non-finite value"
        raise ValueError(msg)
    values = [round(value, 12) for value in raw_values]
    if unit is None:
        return [cast("CellValue", value) for value in values]
    return [Quantity(value=value, unit=unit) for value in values]


def _float_almost_equal(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12


def _join_keys_match(left: Row, right: Row, on: Mapping[str, str]) -> bool:
    for left_column, right_column in on.items():
        left_value = read_path(left, left_column)
        right_value = read_path(right, right_column)
        if left_value is None or right_value is None:
            msg = "join key values must be non-null"
            raise TypeError(msg)
        if not runtime_values_equal(left_value, right_value):
            return False
    return True


def _compare_rows(left: Row, right: Row, *, columns: tuple[str, ...]) -> int:
    for column in columns:
        result = compare_ordered_values(
            read_path(left, column),
            read_path(right, column),
        )
        if result:
            return result
    return 0


def _require_disjoint_row_columns(
    left_rows: Sequence[Row],
    right_rows: Sequence[Row],
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> None:
    left_columns = {column for row in left_rows for column in row}
    right_columns = {column for row in right_rows for column in row}
    conflicts = sorted((left_columns & right_columns) - (allowed_shared or set()))
    if conflicts:
        msg = f"{operation} column collision: {', '.join(conflicts)}"
        raise ValueError(msg)


def _merge_rows(
    left: Row,
    right: Row,
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> Row:
    merged = dict(left)
    for key, value in right.items():
        if key in merged:
            if key not in (allowed_shared or set()):
                msg = f"{operation} column collision for {key!r}"
                raise ValueError(msg)
            if not runtime_values_equal(merged[key], value):
                msg = (
                    f"{operation} shared key {key!r} differs: "
                    f"{merged[key]!r} != {value!r}"
                )
                raise ValueError(msg)
            continue
        merged[key] = value
    return merged


def _input_series(inputs: Mapping[str, object], name: str) -> list[CellValue]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown series input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"series input {name!r} must be a sequence"
        raise TypeError(msg)
    items: list[CellValue] = []
    for item in value:
        if not is_cell_value(item):
            msg = f"series input {name!r} contains unsupported value {item!r}"
            raise TypeError(msg)
        items.append(item)
    return items


def _input_table(inputs: Mapping[str, object], name: str) -> list[Row]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown table input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {name!r} must be a sequence of rows"
        raise TypeError(msg)
    rows: list[Row] = []
    for row in value:
        if not isinstance(row, Mapping):
            msg = f"table input {name!r} contains non-row value {row!r}"
            raise TypeError(msg)
        mapping = cast("Mapping[object, object]", row)
        if not all(isinstance(key, str) for key in mapping):
            msg = f"table input {name!r} row keys must be strings"
            raise TypeError(msg)
        rows.append(
            {
                cast("str", key): _normalize_input_cell(item)
                for key, item in mapping.items()
            }
        )
    return rows


def _normalize_input_cell(value: object) -> CellValue:
    if not isinstance(value, Mapping):
        if is_cell_value(value):
            return value
        msg = f"input table cell contains unsupported value {value!r}"
        raise TypeError(msg)
    mapping = cast("Mapping[object, object]", value)
    if set(mapping) == {"value", "unit"}:
        return Quantity.model_validate(mapping)
    if "id" in mapping and set(mapping) <= {"id", "kind", "metadata"}:
        return EntityRef.model_validate(mapping)
    if not all(isinstance(key, str) for key in mapping):
        msg = "input table mapping cells must use string keys"
        raise TypeError(msg)
    return dict(cast("Mapping[str, object]", mapping))
