"""Deterministic Python reference implementation of relation semantics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import cmp_to_key
from itertools import product
from typing import cast

from scopecat.compiler.relations.analysis import RelationOperation
from scopecat.compiler.relations.backend import (
    EvalContext,
    PreparedRelationEvaluation,
    RelationBackendCapabilityIssue,
    RelationPlanRequirements,
)
from scopecat.compiler.relations.model import (
    CellValue,
    GridColumn,
    RelationExpr,
    Row,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.operators import (
    compare_ordered_values,
    runtime_values_equal,
)
from scopecat.compiler.relations.scalar_eval import (
    cell_matches,
    eval_binary,
    is_cell_value,
    read_path,
)
from scopecat.compiler.relations.verification import RelationRuntimeObligationKind
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


class ReferenceRelationBackend:
    """Deterministic Python implementation defining observable semantics."""

    _DEFAULT_SUPPORTED_OPERATIONS = frozenset(RelationOperation)
    _DEFAULT_DISCHARGED_OBLIGATIONS = frozenset(
        {
            RelationRuntimeObligationKind.DIVISION_RIGHT_NONZERO,
            RelationRuntimeObligationKind.NO_EXTRA_COLUMN_COLLISION,
            RelationRuntimeObligationKind.PARAMETER_LOOKUP_EXACTLY_ONE,
            RelationRuntimeObligationKind.RANGE_PROGRESS,
            RelationRuntimeObligationKind.RANGE_STEP_NONZERO,
            RelationRuntimeObligationKind.SCALAR_RESULT_FINITE,
            RelationRuntimeObligationKind.SERIES_VALUES_FINITE,
            RelationRuntimeObligationKind.ZIP_EQUAL_LENGTH,
        }
    )

    backend_id: str
    supported_operations: frozenset[RelationOperation]
    discharged_obligations: frozenset[RelationRuntimeObligationKind]

    def __init__(
        self,
        *,
        backend_id: str = "reference.python",
        supported_operations: frozenset[
            RelationOperation
        ] = _DEFAULT_SUPPORTED_OPERATIONS,
        discharged_obligations: frozenset[
            RelationRuntimeObligationKind
        ] = _DEFAULT_DISCHARGED_OBLIGATIONS,
    ) -> None:
        self.backend_id = backend_id
        self.supported_operations = supported_operations
        self.discharged_obligations = discharged_obligations

    @property
    def capability_fingerprint(self) -> str:
        return stable_content_hash(
            {
                "schema": "scopecat.relation_backend_capability.v1",
                "backend_type": f"{type(self).__module__}.{type(self).__qualname__}",
                "backend_id": self.backend_id,
                "supported_operations": tuple(
                    sorted(operation.value for operation in self.supported_operations)
                ),
                "discharged_obligations": tuple(
                    sorted(
                        obligation.value for obligation in self.discharged_obligations
                    )
                ),
            }
        )

    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> Sequence[RelationBackendCapabilityIssue]:
        """Accept every verified value type supported by Python containers."""

        _ = requirements
        return ()

    def materialize_scalar(
        self,
        evaluation: PreparedRelationEvaluation[ScalarExpr],
    ) -> CellValue:
        _require_prepared_evaluation(evaluation)
        expression, ctx = evaluation.unwrap_for_backend(self)
        return _evaluate_scalar(expression, ctx)

    def materialize_series(
        self,
        evaluation: PreparedRelationEvaluation[SeriesExpr],
    ) -> list[CellValue]:
        _require_prepared_evaluation(evaluation)
        expression, ctx = evaluation.unwrap_for_backend(self)
        return _evaluate_series(expression, ctx)

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        _require_prepared_evaluation(evaluation)
        expression, ctx = evaluation.unwrap_for_backend(self)
        return _evaluate_relation(expression, ctx)


REFERENCE_RELATION_BACKEND = ReferenceRelationBackend()


def _require_prepared_evaluation(evaluation: object) -> None:
    if not isinstance(evaluation, PreparedRelationEvaluation):
        msg = "reference backend requires a PreparedRelationEvaluation"
        raise TypeError(msg)


def _evaluate_scalar(expression: ScalarExpr, ctx: EvalContext) -> CellValue:
    if expression.kind == "literal":
        return expression.value
    if expression.kind == "column":
        row_scope_id = expression.row_scope_id
        row = ctx.row_scopes.get(row_scope_id) if row_scope_id is not None else ctx.row
        if row is None:
            scope_name = (
                row_scope_id.qualified_name
                if row_scope_id is not None
                else "<implicit-current-row>"
            )
            msg = f"row column references an inactive scope: {scope_name!r}"
            raise ValueError(msg)
        return read_path(row, _required(expression.name))
    if expression.kind == "outer_column":
        if ctx.outer_row is None:
            msg = f"outer column {_required(expression.name)!r} used outside scope"
            raise ValueError(msg)
        return read_path(ctx.outer_row, _required(expression.name))
    if expression.kind == "point_column":
        return read_path(ctx.point_row, _required(expression.name))
    if expression.kind == "input":
        return read_path(ctx.inputs, _required(expression.name))
    if expression.kind == "param_scalar":
        return ctx.params.scalar(_required(expression.name))
    if expression.kind == "param_lookup":
        resolved_key = {
            name: _evaluate_scalar(value, ctx)
            for name, value in _required(expression.key).items()
        }
        row = ctx.params.lookup_row(_required(expression.table_id), resolved_key)
        return read_path(row, _required(expression.column))
    if expression.kind == "binary":
        return eval_binary(
            _required(expression.op),
            _evaluate_scalar(_required(expression.left), ctx),
            _evaluate_scalar(_required(expression.right), ctx),
        )
    if expression.kind == "case":
        for branch in _required(expression.cases):
            if _evaluate_scalar(branch.condition, ctx) is True:
                return _evaluate_scalar(branch.value, ctx)
        return _evaluate_scalar(_required(expression.fallback), ctx)
    msg = f"unsupported scalar expression kind: {expression.kind}"
    raise ValueError(msg)


def _evaluate_series(expression: SeriesExpr, ctx: EvalContext) -> list[CellValue]:
    if expression.kind == "values":
        return list(_required(expression.items))
    if expression.kind == "linspace":
        count = _required(expression.count)
        start_value = _evaluate_scalar(_required(expression.start), ctx)
        stop_value = _evaluate_scalar(_required(expression.stop), ctx)
        unit = expression.unit or _quantity_unit(start_value)
        start = _series_float(start_value, unit=unit)
        stop = _series_float(stop_value, unit=unit)
        if count == 1:
            return _series_values([start], unit=unit)
        step_value = (stop - start) / (count - 1)
        return _series_values(
            [start + index * step_value for index in range(count)],
            unit=unit,
        )
    if expression.kind == "range":
        start_value = _evaluate_scalar(_required(expression.start), ctx)
        stop_value = _evaluate_scalar(_required(expression.stop), ctx)
        step_value = _evaluate_scalar(_required(expression.step), ctx)
        unit = expression.unit or _quantity_unit(start_value)
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
                expression.include_stop and _float_almost_equal(current, stop)
            ):
                selected.append(current)
                next_current = current + step
                if next_current == current:
                    msg = "range step is too small to advance the current value"
                    raise ValueError(msg)
                current = next_current
        else:
            while current > stop or (
                expression.include_stop and _float_almost_equal(current, stop)
            ):
                selected.append(current)
                next_current = current + step
                if next_current == current:
                    msg = "range step is too small to advance the current value"
                    raise ValueError(msg)
                current = next_current
        return _series_values(selected, unit=unit)
    if expression.kind == "input":
        return _input_series(ctx.inputs, _required(expression.name))
    if expression.kind == "param_series":
        return ctx.params.series_values(_required(expression.name))
    if expression.kind == "relation_column":
        return [
            read_path(row, _required(expression.column))
            for row in _evaluate_relation(_required(expression.source), ctx)
        ]
    if expression.kind == "relation_entities":
        entities: list[CellValue] = []
        for row in _evaluate_relation(_required(expression.source), ctx):
            for column in _required(expression.columns):
                value = read_path(row, column)
                if not any(cell_matches(existing, value) for existing in entities):
                    entities.append(value)
        return entities
    msg = f"unsupported series kind: {expression.kind}"
    raise ValueError(msg)


def _evaluate_grid_column(column: GridColumn, ctx: EvalContext) -> list[CellValue]:
    if column.kind == "scalar":
        return [_evaluate_scalar(_required(column.scalar), ctx)]
    if column.kind == "series":
        return _evaluate_series(_required(column.series), ctx)
    if column.kind == "relation":
        return cast(
            "list[CellValue]",
            _evaluate_relation(_required(column.relation), ctx),
        )
    if column.kind == "values":
        return list(_required(column.values))
    msg = f"unsupported grid column kind: {column.kind}"
    raise ValueError(msg)


def _evaluate_relation(expression: RelationExpr, ctx: EvalContext) -> list[Row]:
    if expression.kind == "literal_rows":
        return [dict(row) for row in _required(expression.rows)]
    if expression.kind == "table":
        return ctx.params.table_rows(_required(expression.table_id))
    if expression.kind == "input":
        return _input_table(ctx.inputs, _required(expression.name))
    if expression.kind == "grid":
        names = tuple(_required(expression.columns))
        choices = [
            _evaluate_grid_column(_required(expression.columns)[name], ctx)
            for name in names
        ]
        return [dict(zip(names, values, strict=True)) for values in product(*choices)]
    if expression.kind == "select":
        return [
            {
                column: read_path(source_row, column)
                for column in _required(expression.select_columns)
            }
            for source_row in _evaluate_relation(_required(expression.source), ctx)
        ]
    if expression.kind == "filter":
        selected: list[Row] = []
        for source_row in _evaluate_relation(_required(expression.source), ctx):
            child_ctx = _child_context(
                ctx,
                row=source_row,
                row_scope_id=expression.row_scope_id,
            )
            if _evaluate_scalar(_required(expression.condition), child_ctx) is True:
                selected.append(source_row)
        return selected
    if expression.kind == "join":
        left_rows = _evaluate_relation(_required(expression.left), ctx)
        right_rows = _evaluate_relation(_required(expression.right), ctx)
        on = _required(expression.on)
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
    if expression.kind == "cross":
        left_rows = _evaluate_relation(_required(expression.left), ctx)
        right_rows = _evaluate_relation(_required(expression.right), ctx)
        _require_disjoint_row_columns(left_rows, right_rows, operation="cross")
        return [
            _merge_rows(left_row, right_row, operation="cross")
            for left_row in left_rows
            for right_row in right_rows
        ]
    if expression.kind == "lateral_cross":
        crossed: list[Row] = []
        for left_row in _evaluate_relation(_required(expression.left), ctx):
            right_rows = _evaluate_relation(
                _required(expression.right),
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
    if expression.kind == "point_cross":
        crossed = []
        for left_row in _evaluate_relation(_required(expression.left), ctx):
            point_row = (
                _merge_rows(ctx.point_row, left_row, operation="point_cross")
                if ctx.point_row
                else left_row
            )
            right_rows = _evaluate_relation(
                _required(expression.right),
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
    if expression.kind == "zip":
        rows_by_source = [
            _evaluate_relation(source, ctx) for source in _required(expression.sources)
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
    if expression.kind == "with_columns":
        derived: list[Row] = []
        for source_row in _evaluate_relation(_required(expression.source), ctx):
            next_row = dict(source_row)
            child_ctx = _child_context(
                ctx,
                row=next_row,
                row_scope_id=expression.row_scope_id,
            )
            for name, scalar in _required(expression.new_columns).items():
                next_row[name] = _evaluate_scalar(scalar, child_ctx)
            derived.append(next_row)
        return derived
    if expression.kind == "sort":
        rows = _evaluate_relation(_required(expression.source), ctx)
        columns = tuple(_required(expression.sort_columns))
        return sorted(
            rows,
            key=cmp_to_key(
                lambda left, right: _compare_rows(left, right, columns=columns)
            ),
        )
    if expression.kind == "limit":
        return _evaluate_relation(_required(expression.source), ctx)[
            : _required(expression.limit_count)
        ]
    msg = f"unsupported relation kind: {expression.kind}"
    raise ValueError(msg)


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


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


__all__ = [
    "REFERENCE_RELATION_BACKEND",
    "ReferenceRelationBackend",
]
