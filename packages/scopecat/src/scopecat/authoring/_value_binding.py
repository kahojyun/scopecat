"""Private binding of typed authoring values to module inputs.

This module owns the relation-tree rewrite boundary shared by module assembly,
scan lowering, and resource routing.  Keeping it independent from
``authoring.assembly`` makes those layers depend in one direction only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    CellValue,
    GridColumn,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    col,
    literal_rows,
    outer,
    values,
)
from scopecat.authoring._value_refs import ValueRef, internal_lower_value_ref
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

_EMPTY_INPUT_RESOLUTION: frozenset[str] = frozenset()
type _DataExpr = ScalarExpr | SeriesExpr | RelationExpr


def bind_scalar_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> ScalarExpr:
    """Bind scalar input nodes without exposing relation syntax to users."""

    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            if preserve_unbound_inputs:
                return expression
            return outer(input_name) if unbound_to_outer else col(input_name)
        value = inputs[input_name]
        if isinstance(value, ValueRef):
            value = internal_lower_value_ref(value)
        if isinstance(value, ComputeResultRef):
            msg = (
                f"compute result {value.node_id!r} cannot be embedded in a scalar "
                "expression; connect it as a standalone value"
            )
            raise TypeError(msg)
        next_resolving = _descend_input_resolution(input_name, resolving)
        if isinstance(value, ScalarExpr):
            if value.kind == "input" and value.name == input_name:
                if preserve_unbound_inputs:
                    return value
                return outer(input_name) if unbound_to_outer else col(input_name)
            bound = bind_scalar_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=next_resolving,
            )
            return scalar_columns_to_outer(bound) if unbound_to_outer else bound
        return literal_scalar(input_cell(value))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: bind_scalar_input_refs(
                        value,
                        inputs,
                        unbound_to_outer=unbound_to_outer,
                        preserve_unbound_inputs=preserve_unbound_inputs,
                        resolving=resolving,
                    )
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": bind_scalar_input_refs(
                    _required_scalar(expression.left, "expression.left"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                ),
                "right": bind_scalar_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": bind_scalar_input_refs(
                                branch.condition,
                                inputs,
                                unbound_to_outer=unbound_to_outer,
                                preserve_unbound_inputs=preserve_unbound_inputs,
                                resolving=resolving,
                            ),
                            "value": bind_scalar_input_refs(
                                branch.value,
                                inputs,
                                unbound_to_outer=unbound_to_outer,
                                preserve_unbound_inputs=preserve_unbound_inputs,
                                resolving=resolving,
                            ),
                        }
                    )
                    for branch in (expression.cases or ())
                ],
                "fallback": bind_scalar_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                ),
            }
        )
    return expression


def bind_value_input_refs(
    expression: _DataExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> _DataExpr:
    if isinstance(expression, ScalarExpr):
        return bind_scalar_input_refs(
            expression,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    if isinstance(expression, SeriesExpr):
        return bind_series_input_refs(
            expression,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    return bind_relation_input_refs(
        expression,
        inputs,
        unbound_to_outer=unbound_to_outer,
        preserve_unbound_inputs=preserve_unbound_inputs,
        resolving=resolving,
    )


def substitute_value_input_refs(
    expression: _DataExpr,
    inputs: Mapping[str, object],
) -> _DataExpr:
    """Substitute one composition layer while preserving unbound input nodes."""

    return bind_value_input_refs(
        expression,
        inputs,
        preserve_unbound_inputs=True,
    )


def bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> SeriesExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        selected = series_input_value(input_name, inputs[input_name])
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return bind_series_input_refs(
            selected,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=_descend_input_resolution(input_name, resolving),
        )
    update: dict[str, object] = {}
    for field_name in ("start", "stop", "step"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = bind_scalar_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
    if expression.source is not None:
        update["source"] = bind_relation_input_refs(
            expression.source,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    return expression.model_copy(update=update) if update else expression


def bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool = False,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> RelationExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        selected = table_input_value(input_name, inputs[input_name])
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return bind_relation_input_refs(
            selected,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=_descend_input_resolution(input_name, resolving),
        )
    update: dict[str, object] = {}
    for field_name in ("source", "left", "right"):
        value = getattr(expression, field_name)
        if value is not None:
            update[field_name] = bind_relation_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
    if expression.sources is not None:
        update["sources"] = [
            bind_relation_input_refs(
                source,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
            for source in expression.sources
        ]
    if expression.columns is not None:
        update["columns"] = {
            name: _bind_grid_column_input_refs(
                column,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
            for name, column in expression.columns.items()
        }
    if expression.condition is not None:
        update["condition"] = bind_scalar_input_refs(
            expression.condition,
            inputs,
            unbound_to_outer=unbound_to_outer,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    if expression.new_columns is not None:
        update["new_columns"] = {
            name: bind_scalar_input_refs(
                value,
                inputs,
                unbound_to_outer=unbound_to_outer,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
            for name, value in expression.new_columns.items()
        }
    return expression.model_copy(update=update) if update else expression


def _bind_grid_column_input_refs(
    column: GridColumn,
    inputs: Mapping[str, object],
    *,
    unbound_to_outer: bool,
    preserve_unbound_inputs: bool,
    resolving: frozenset[str],
) -> GridColumn:
    if column.scalar is not None:
        return column.model_copy(
            update={
                "scalar": bind_scalar_input_refs(
                    column.scalar,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
            }
        )
    if column.series is not None:
        return column.model_copy(
            update={
                "series": bind_series_input_refs(
                    column.series,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
            }
        )
    if column.relation is not None:
        return column.model_copy(
            update={
                "relation": bind_relation_input_refs(
                    column.relation,
                    inputs,
                    unbound_to_outer=unbound_to_outer,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
            }
        )
    return column


def series_input_value(input_name: str, value: object) -> SeriesExpr:
    if isinstance(value, ValueRef):
        value = internal_lower_value_ref(value)
    if isinstance(value, SeriesExpr):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = cast("Sequence[object]", value)
        return values([input_cell(item) for item in sequence])
    msg = f"series input {input_name!r} must bind to a sequence"
    raise TypeError(msg)


def table_input_value(input_name: str, value: object) -> RelationExpr:
    if isinstance(value, ValueRef):
        value = internal_lower_value_ref(value)
    if isinstance(value, RelationExpr):
        return value
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {input_name!r} must bind to a sequence of rows"
        raise TypeError(msg)
    rows: list[dict[str, CellValue]] = []
    sequence = cast("Sequence[object]", value)
    for index, item in enumerate(sequence):
        if not isinstance(item, Mapping):
            msg = f"table input {input_name!r} row {index} must be a mapping"
            raise TypeError(msg)
        row = cast("Mapping[object, object]", item)
        rows.append({str(name): input_cell(cell) for name, cell in row.items()})
    return literal_rows(rows)


def literal_data_expr(value: object) -> _DataExpr:
    if isinstance(value, ValueRef):
        value = internal_lower_value_ref(value)
        if isinstance(value, ComputeResultRef):
            msg = "compute result is not a literal expression"
            raise TypeError(msg)
    if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = cast("Sequence[object]", value)
        if sequence and all(isinstance(item, Mapping) for item in sequence):
            return table_input_value("literal", sequence)
        return values([input_cell(item) for item in sequence])
    return literal_scalar(input_cell(value))


def input_cell(value: object) -> CellValue:
    if (
        isinstance(
            value,
            Quantity | EntityRef | PayloadValue | str | int | float | bool,
        )
        or value is None
    ):
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if not all(isinstance(key, str) for key in mapping):
            msg = "record input keys must be strings"
            raise TypeError(msg)
        return cast("dict[str, Any]", dict(mapping))
    msg = f"input value is not available as a scalar expression value: {value!r}"
    raise TypeError(msg)


def literal_scalar(value: CellValue) -> ScalarExpr:
    return ScalarExpr(kind="literal", value=value)


def scalar_columns_to_outer(expression: ScalarExpr) -> ScalarExpr:
    if expression.kind == "column":
        return outer(_required_name(expression.name, "column.name"))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: scalar_columns_to_outer(value)
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": scalar_columns_to_outer(
                    _required_scalar(expression.left, "expression.left")
                ),
                "right": scalar_columns_to_outer(
                    _required_scalar(expression.right, "expression.right")
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": scalar_columns_to_outer(branch.condition),
                            "value": scalar_columns_to_outer(branch.value),
                        }
                    )
                    for branch in (expression.cases or ())
                ],
                "fallback": scalar_columns_to_outer(
                    _required_scalar(expression.fallback, "expression.fallback")
                ),
            }
        )
    return expression


def value_input_refs(expression: _DataExpr) -> tuple[str, ...]:
    refs: set[str] = set()
    _collect_value_input_refs(expression, refs)
    return tuple(sorted(refs))


def _collect_value_input_refs(expression: _DataExpr, refs: set[str]) -> None:
    if isinstance(expression, ScalarExpr):
        _collect_scalar_input_refs(expression, refs)
        return
    if isinstance(expression, SeriesExpr):
        if expression.kind == "input" and expression.name:
            refs.add(expression.name)
        for bound in (expression.start, expression.stop, expression.step):
            if bound is not None:
                _collect_scalar_input_refs(bound, refs)
        if expression.source is not None:
            _collect_relation_input_refs(expression.source, refs)
        return
    _collect_relation_input_refs(expression, refs)


def _collect_scalar_input_refs(expression: ScalarExpr, refs: set[str]) -> None:
    if expression.kind == "input" and expression.name:
        refs.add(expression.name)
        return
    if expression.kind == "param_lookup":
        for value in (expression.key or {}).values():
            _collect_scalar_input_refs(value, refs)
        return
    if expression.kind == "binary":
        for value in (expression.left, expression.right):
            if value is not None:
                _collect_scalar_input_refs(value, refs)
        return
    if expression.kind == "case":
        for branch in expression.cases or ():
            _collect_scalar_input_refs(branch.condition, refs)
            _collect_scalar_input_refs(branch.value, refs)
        if expression.fallback is not None:
            _collect_scalar_input_refs(expression.fallback, refs)


def _collect_relation_input_refs(expression: RelationExpr, refs: set[str]) -> None:
    if expression.kind == "input" and expression.name:
        refs.add(expression.name)
    for source in (expression.source, expression.left, expression.right):
        if source is not None:
            _collect_relation_input_refs(source, refs)
    for source in expression.sources or ():
        _collect_relation_input_refs(source, refs)
    for column in (expression.columns or {}).values():
        if column.scalar is not None:
            _collect_scalar_input_refs(column.scalar, refs)
        if column.series is not None:
            _collect_value_input_refs(column.series, refs)
        if column.relation is not None:
            _collect_relation_input_refs(column.relation, refs)
    if expression.condition is not None:
        _collect_scalar_input_refs(expression.condition, refs)
    for value in (expression.new_columns or {}).values():
        _collect_scalar_input_refs(value, refs)


def _descend_input_resolution(
    input_name: str,
    resolving: frozenset[str],
) -> frozenset[str]:
    if input_name in resolving:
        msg = f"cyclic module input reference: {input_name}"
        raise ValueError(msg)
    return resolving | {input_name}


def _required_scalar(value: ScalarExpr | None, path: str) -> ScalarExpr:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_name(value: str | None, path: str) -> str:
    if not value:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


__all__ = [
    "bind_relation_input_refs",
    "bind_scalar_input_refs",
    "bind_series_input_refs",
    "bind_value_input_refs",
    "input_cell",
    "literal_data_expr",
    "literal_scalar",
    "scalar_columns_to_outer",
    "series_input_value",
    "substitute_value_input_refs",
    "table_input_value",
    "value_input_refs",
]
