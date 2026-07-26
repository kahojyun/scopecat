"""Adapt authored value handles to the generic relation input rewriter."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import override

from scopecat.authoring._value_refs import ValueRef, internal_lower_value_ref
from scopecat.graph.relations import input_binding as relation_input_binding
from scopecat.graph.relations.model import (
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

    @override
    def __getitem__(self, key: str) -> object:
        return _lower_authoring_value(self._values[key])

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)


def bind_scalar_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    return relation_input_binding.bind_scalar_input_refs(
        expression,
        _ResolvedInputs(inputs),
    )


def bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
) -> SeriesExpr:
    return relation_input_binding.bind_series_input_refs(
        expression,
        _ResolvedInputs(inputs),
    )


def bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
) -> RelationExpr:
    return relation_input_binding.bind_relation_input_refs(
        expression,
        _ResolvedInputs(inputs),
    )


def bind_value_input_refs(
    expression: _DataExpr,
    inputs: Mapping[str, object],
) -> _DataExpr:
    return relation_input_binding.bind_value_input_refs(
        expression,
        _ResolvedInputs(inputs),
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


def value_input_refs(expression: _DataExpr) -> tuple[str, ...]:
    return relation_input_binding.value_input_refs(expression)


def _lower_authoring_value(value: object) -> object:
    if isinstance(value, ValueRef):
        return internal_lower_value_ref(value)
    return value
