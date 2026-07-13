"""Adapt authored value handles to the generic relation input rewriter."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from scopecat.authoring._value_refs import ValueRef, internal_lower_value_ref
from scopecat.compiler.relations import input_binding as relation_input_binding
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
)

type _DataExpr = ScalarExpr | SeriesExpr | RelationExpr


class _ResolvedInputs(Mapping[str, object]):
    """Lazily lower only authored inputs reached by an expression."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return _lower_authoring_value(self._values[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def bind_scalar_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
) -> ScalarExpr:
    return relation_input_binding.bind_scalar_input_refs(
        expression,
        _ResolvedInputs(inputs),
        preserve_unbound_inputs=preserve_unbound_inputs,
    )


def bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
) -> SeriesExpr:
    return relation_input_binding.bind_series_input_refs(
        expression,
        _ResolvedInputs(inputs),
        preserve_unbound_inputs=preserve_unbound_inputs,
    )


def bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
) -> RelationExpr:
    return relation_input_binding.bind_relation_input_refs(
        expression,
        _ResolvedInputs(inputs),
        preserve_unbound_inputs=preserve_unbound_inputs,
    )


def bind_value_input_refs(
    expression: _DataExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
) -> _DataExpr:
    return relation_input_binding.bind_value_input_refs(
        expression,
        _ResolvedInputs(inputs),
        preserve_unbound_inputs=preserve_unbound_inputs,
    )


def substitute_value_input_refs(
    expression: _DataExpr,
    inputs: Mapping[str, object],
) -> _DataExpr:
    return relation_input_binding.substitute_value_input_refs(
        expression,
        _ResolvedInputs(inputs),
    )


def series_input_value(input_name: str, value: object) -> SeriesExpr:
    return relation_input_binding.series_input_value(
        input_name,
        _lower_authoring_value(value),
    )


def table_input_value(input_name: str, value: object) -> RelationExpr:
    return relation_input_binding.table_input_value(
        input_name,
        _lower_authoring_value(value),
    )


def literal_data_expr(value: object) -> _DataExpr:
    return relation_input_binding.literal_data_expr(_lower_authoring_value(value))


def input_cell(value: object) -> CellValue:
    return relation_input_binding.input_cell(value)


def literal_scalar(value: CellValue) -> ScalarExpr:
    return relation_input_binding.literal_scalar(value)


def value_input_refs(expression: _DataExpr) -> tuple[str, ...]:
    return relation_input_binding.value_input_refs(expression)


def _lower_authoring_value(value: object) -> object:
    if isinstance(value, ValueRef):
        return internal_lower_value_ref(value)
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
