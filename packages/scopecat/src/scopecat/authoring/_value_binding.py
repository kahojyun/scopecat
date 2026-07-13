"""Private binding of typed authoring values to module inputs.

This module owns the relation-tree rewrite boundary shared by module assembly,
scan lowering, and resource routing.  Keeping it independent from
``authoring.assembly`` makes those layers depend in one direction only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from scopecat._compute_result import ComputeResultRef
from scopecat._relation_analysis import plan_input_refs
from scopecat._relations import (
    CellValue,
    GridColumn,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    literal_rows,
    point_col,
    values,
)
from scopecat.authoring._value_refs import ValueRef, internal_lower_value_ref
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

_EMPTY_INPUT_RESOLUTION: frozenset[str] = frozenset()
type _DataExpr = ScalarExpr | SeriesExpr | RelationExpr


@dataclass(frozen=True, slots=True)
class _LexicalReplacement:
    """One parent expression closed against the current child environment."""

    value: object


def bind_scalar_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> ScalarExpr:
    """Bind scalar input nodes without exposing relation syntax to users."""

    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            if preserve_unbound_inputs:
                return expression
            return point_col(input_name)
        selected = inputs[input_name]
        substitute_once = isinstance(selected, _LexicalReplacement)
        value = selected.value if substitute_once else selected
        if isinstance(value, ValueRef):
            value = internal_lower_value_ref(value)
        if isinstance(value, ComputeResultRef):
            msg = (
                f"compute result {value.value_id!r} cannot be embedded in a scalar "
                "expression; connect it as a standalone value"
            )
            raise TypeError(msg)
        next_resolving = _descend_input_resolution(input_name, resolving)
        if isinstance(value, ScalarExpr):
            if substitute_once:
                return value
            if value.kind == "input" and value.name == input_name:
                if preserve_unbound_inputs:
                    return value
                return point_col(input_name)
            bound = bind_scalar_input_refs(
                value,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=next_resolving,
            )
            return bound
        return literal_scalar(input_cell(value))
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: bind_scalar_input_refs(
                        value,
                        inputs,
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
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                ),
                "right": bind_scalar_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
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
                                preserve_unbound_inputs=preserve_unbound_inputs,
                                resolving=resolving,
                            ),
                            "value": bind_scalar_input_refs(
                                branch.value,
                                inputs,
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
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> _DataExpr:
    if isinstance(expression, ScalarExpr):
        return bind_scalar_input_refs(
            expression,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    if isinstance(expression, SeriesExpr):
        return bind_series_input_refs(
            expression,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    return bind_relation_input_refs(
        expression,
        inputs,
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
        {input_id: _LexicalReplacement(value) for input_id, value in inputs.items()},
        preserve_unbound_inputs=True,
    )


def bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> SeriesExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        value = inputs[input_name]
        substitute_once = isinstance(value, _LexicalReplacement)
        selected = series_input_value(
            input_name,
            value.value if substitute_once else value,
        )
        if substitute_once:
            return selected
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return bind_series_input_refs(
            selected,
            inputs,
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
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
    if expression.source is not None:
        update["source"] = bind_relation_input_refs(
            expression.source,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    return expression.model_copy(update=update) if update else expression


def bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> RelationExpr:
    if expression.kind == "input":
        input_name = _required_name(expression.name, "input.name")
        if input_name not in inputs:
            return expression
        value = inputs[input_name]
        substitute_once = isinstance(value, _LexicalReplacement)
        selected = table_input_value(
            input_name,
            value.value if substitute_once else value,
        )
        if substitute_once:
            return selected
        if selected.kind == "input" and selected.name == input_name:
            return selected
        return bind_relation_input_refs(
            selected,
            inputs,
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
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
    if expression.sources is not None:
        update["sources"] = [
            bind_relation_input_refs(
                source,
                inputs,
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
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
            for name, column in expression.columns.items()
        }
    if expression.condition is not None:
        update["condition"] = bind_scalar_input_refs(
            expression.condition,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )
    if expression.new_columns is not None:
        update["new_columns"] = {
            name: bind_scalar_input_refs(
                value,
                inputs,
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
    preserve_unbound_inputs: bool,
    resolving: frozenset[str],
) -> GridColumn:
    if column.scalar is not None:
        return column.model_copy(
            update={
                "scalar": bind_scalar_input_refs(
                    column.scalar,
                    inputs,
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


def value_input_refs(expression: _DataExpr) -> tuple[str, ...]:
    return plan_input_refs(expression)


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
    "series_input_value",
    "substitute_value_input_refs",
    "table_input_value",
    "value_input_refs",
]
