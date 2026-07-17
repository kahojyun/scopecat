"""Rewrite relation input references against already-lowered compiler values.

This module is independent of authoring value handles. Frontends adapt their
source values into relation expressions before crossing this boundary.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast, override

from scopecat.compiler.relations.analysis import plan_input_refs
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CaseScalarExpr,
    CellValue,
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
    ParameterLookupScalarExpr,
    PointCrossRelationExpr,
    RangeSeriesExpr,
    RelationColumnSeriesExpr,
    RelationEntitiesSeriesExpr,
    RelationExpr,
    RelationExpression,
    RelationGridColumn,
    ScalarExpr,
    ScalarExpression,
    ScalarGridColumn,
    SelectRelationExpr,
    SeriesExpr,
    SeriesExpression,
    SeriesGridColumn,
    SortRelationExpr,
    TableRelationExpr,
    ZipRelationExpr,
    lit,
    literal_rows,
    point_col,
    values,
)
from scopecat.kernel.payloads import PayloadValue
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

_EMPTY_INPUT_RESOLUTION: frozenset[str] = frozenset()
type _DataExpr = ScalarExpr | SeriesExpr | RelationExpr


@dataclass(frozen=True, slots=True)
class _LexicalReplacement:
    """One parent expression closed against the current child environment."""

    value: object


class _LexicalReplacements(Mapping[str, object]):
    """Lazily mark one composition layer as single-substitution values."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values

    @override
    def __getitem__(self, key: str) -> object:
        return _LexicalReplacement(self._values[key])

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)


def bind_scalar_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> ScalarExpr:
    """Bind scalar input nodes without exposing relation syntax to users."""

    scalar = cast("ScalarExpression", expression)
    if isinstance(scalar, InputScalarExpr):
        input_name = scalar.name
        if input_name not in inputs:
            if preserve_unbound_inputs:
                return scalar
            return point_col(input_name)
        selected = inputs[input_name]
        substitute_once = isinstance(selected, _LexicalReplacement)
        value = selected.value if substitute_once else selected
        next_resolving = _descend_input_resolution(input_name, resolving)
        if isinstance(value, ScalarExpr):
            value_scalar = cast("ScalarExpression", value)
            if substitute_once:
                return value_scalar
            if (
                isinstance(value_scalar, InputScalarExpr)
                and value_scalar.name == input_name
            ):
                if preserve_unbound_inputs:
                    return value_scalar
                return point_col(input_name)
            bound = bind_scalar_input_refs(
                value_scalar,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=next_resolving,
            )
            return bound
        return lit(input_cell(value))
    if isinstance(scalar, ParameterLookupScalarExpr):
        return replace(
            scalar,
            key={
                name: bind_scalar_input_refs(
                    value,
                    inputs,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
                for name, value in scalar.key.items()
            },
        )
    if isinstance(scalar, BinaryScalarExpr):
        return replace(
            scalar,
            left=bind_scalar_input_refs(
                scalar.left,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
            right=bind_scalar_input_refs(
                scalar.right,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(scalar, CaseScalarExpr):
        return replace(
            scalar,
            cases=[
                replace(
                    branch,
                    condition=bind_scalar_input_refs(
                        branch.condition,
                        inputs,
                        preserve_unbound_inputs=preserve_unbound_inputs,
                        resolving=resolving,
                    ),
                    value=bind_scalar_input_refs(
                        branch.value,
                        inputs,
                        preserve_unbound_inputs=preserve_unbound_inputs,
                        resolving=resolving,
                    ),
                )
                for branch in scalar.cases
            ],
            fallback=bind_scalar_input_refs(
                scalar.fallback,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    return scalar


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
        _LexicalReplacements(inputs),
        preserve_unbound_inputs=True,
    )


def bind_series_input_refs(
    expression: SeriesExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> SeriesExpr:
    series = cast("SeriesExpression", expression)
    if isinstance(series, InputSeriesExpr):
        input_name = series.name
        if input_name not in inputs:
            return series
        value = inputs[input_name]
        substitute_once = isinstance(value, _LexicalReplacement)
        selected = series_input_value(
            input_name,
            value.value if substitute_once else value,
        )
        if substitute_once:
            return selected
        if isinstance(selected, InputRelationExpr) and selected.name == input_name:
            return selected
        return bind_series_input_refs(
            selected,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=_descend_input_resolution(input_name, resolving),
        )

    def bind_scalar(scalar: ScalarExpr) -> ScalarExpr:
        return bind_scalar_input_refs(
            scalar,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        )

    if isinstance(series, (LinspaceSeriesExpr, RangeSeriesExpr)):
        if isinstance(series, RangeSeriesExpr):
            return replace(
                series,
                start=bind_scalar(series.start),
                stop=bind_scalar(series.stop),
                step=bind_scalar(series.step),
            )
        return replace(
            series,
            start=bind_scalar(series.start),
            stop=bind_scalar(series.stop),
        )
    if isinstance(series, (RelationColumnSeriesExpr, RelationEntitiesSeriesExpr)):
        source = series.source
    else:
        return series
    return replace(
        series,
        source=bind_relation_input_refs(
            source,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        ),
    )


def bind_relation_input_refs(
    expression: RelationExpr,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool = False,
    resolving: frozenset[str] = _EMPTY_INPUT_RESOLUTION,
) -> RelationExpr:
    relation = cast("RelationExpression", expression)
    if isinstance(relation, InputRelationExpr):
        input_name = relation.name
        if input_name not in inputs:
            return relation
        value = inputs[input_name]
        substitute_once = isinstance(value, _LexicalReplacement)
        selected = table_input_value(
            input_name,
            value.value if substitute_once else value,
        )
        if substitute_once:
            return selected
        if isinstance(selected, InputSeriesExpr) and selected.name == input_name:
            return selected
        return bind_relation_input_refs(
            selected,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=_descend_input_resolution(input_name, resolving),
        )
    if isinstance(relation, (LiteralRowsRelationExpr, TableRelationExpr)):
        return relation
    if isinstance(relation, GridRelationExpr):
        return replace(
            relation,
            columns={
                name: _bind_grid_column_input_refs(
                    column,
                    inputs,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
                for name, column in relation.columns.items()
            },
        )
    if isinstance(relation, (SelectRelationExpr, SortRelationExpr, LimitRelationExpr)):
        return replace(
            relation,
            source=bind_relation_input_refs(
                relation.source,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(relation, FilterRelationExpr):
        return replace(
            relation,
            source=bind_relation_input_refs(
                relation.source,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
            condition=bind_scalar_input_refs(
                relation.condition,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(
        relation,
        (
            JoinRelationExpr,
            CrossRelationExpr,
            LateralCrossRelationExpr,
            PointCrossRelationExpr,
        ),
    ):
        return replace(
            relation,
            left=bind_relation_input_refs(
                relation.left,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
            right=bind_relation_input_refs(
                relation.right,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(relation, ZipRelationExpr):
        return replace(
            relation,
            sources=[
                bind_relation_input_refs(
                    source,
                    inputs,
                    preserve_unbound_inputs=preserve_unbound_inputs,
                    resolving=resolving,
                )
                for source in relation.sources
            ],
        )
    return replace(
        relation,
        source=bind_relation_input_refs(
            relation.source,
            inputs,
            preserve_unbound_inputs=preserve_unbound_inputs,
            resolving=resolving,
        ),
        new_columns={
            name: bind_scalar_input_refs(
                value,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            )
            for name, value in relation.new_columns.items()
        },
    )


def _bind_grid_column_input_refs(
    column: GridColumn,
    inputs: Mapping[str, object],
    *,
    preserve_unbound_inputs: bool,
    resolving: frozenset[str],
) -> GridColumn:
    if isinstance(column, ScalarGridColumn):
        return replace(
            column,
            scalar=bind_scalar_input_refs(
                column.scalar,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(column, SeriesGridColumn):
        return replace(
            column,
            series=bind_series_input_refs(
                column.series,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    if isinstance(column, RelationGridColumn):
        return replace(
            column,
            relation=bind_relation_input_refs(
                column.relation,
                inputs,
                preserve_unbound_inputs=preserve_unbound_inputs,
                resolving=resolving,
            ),
        )
    return column


def series_input_value(input_name: str, value: object) -> SeriesExpression:
    if isinstance(value, SeriesExpr):
        return cast("SeriesExpression", value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = value
        return values([input_cell(item) for item in sequence])
    msg = f"series input {input_name!r} must bind to a sequence"
    raise TypeError(msg)


def table_input_value(input_name: str, value: object) -> RelationExpression:
    if isinstance(value, RelationExpr):
        return cast("RelationExpression", value)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {input_name!r} must bind to a sequence of rows"
        raise TypeError(msg)
    rows: list[dict[str, CellValue]] = []
    sequence = value
    for index, item in enumerate(sequence):
        if not isinstance(item, Mapping):
            msg = f"table input {input_name!r} row {index} must be a mapping"
            raise TypeError(msg)
        row = cast("Mapping[object, object]", item)
        rows.append({str(name): input_cell(cell) for name, cell in row.items()})
    return literal_rows(rows)


def literal_data_expr(value: object) -> _DataExpr:
    if isinstance(value, ScalarExpr | SeriesExpr | RelationExpr):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        sequence = value
        if sequence and all(isinstance(item, Mapping) for item in sequence):
            return table_input_value("literal", sequence)
        return values([input_cell(item) for item in sequence])
    return lit(input_cell(value))


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
        return cast("dict[str, object]", dict(mapping))
    msg = f"input value is not available as a scalar expression value: {value!r}"
    raise TypeError(msg)


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
