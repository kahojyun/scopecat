"""Bind authored scalar expressions and direct table sources."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import cast, override

from scopecat.kernel.value_data import CellValue
from scopecat.program import expression_binding
from scopecat.program.expressions import (
    ScalarExpr,
    lit,
)
from scopecat.program.table_values import (
    InputTableSource,
    LiteralTableSource,
    ParameterTableSource,
    TableSource,
    literal_table_source,
)
from scopecat.program.value_refs import ValueRef, internal_lower_value_ref


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
    return expression_binding.bind_scalar_input_refs(
        expression,
        _ResolvedInputs(inputs),
    )


def bind_table_source(
    source: TableSource,
    inputs: Mapping[str, object],
) -> TableSource:
    """Resolve the only indirection supported by a whole-table value."""

    if not isinstance(source, InputTableSource):
        return source
    if source.input_id not in inputs:
        return source
    value = _lower_authoring_value(inputs[source.input_id])
    if isinstance(
        value,
        LiteralTableSource | ParameterTableSource | InputTableSource,
    ):
        return value
    return literal_table_source(
        cast("Sequence[Mapping[str, CellValue]]", value),
    )


def literal_scalar_expr(value: object) -> ScalarExpr:
    return lit(input_cell(_lower_authoring_value(value)))


def input_cell(value: object) -> CellValue:
    return expression_binding.input_cell(value)


def scalar_input_refs(expression: ScalarExpr) -> tuple[str, ...]:
    return expression_binding.scalar_input_refs(expression)


def _lower_authoring_value(value: object) -> object:
    if isinstance(value, ValueRef):
        return internal_lower_value_ref(value)
    return value
