"""Partial evaluation for pure scalar expressions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.scalar_eval import cell_matches, eval_binary, read_path
from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    CellValue,
    InputScalarExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
    lit,
)

_KNOWN_EVALUATION_ERRORS = (ArithmeticError, KeyError, TypeError, ValueError)


@dataclass(frozen=True, slots=True)
class KnownScalar:
    """A scalar value completely determined by the supplied bindings."""

    value: CellValue


@dataclass(frozen=True, slots=True)
class ResidualScalar:
    """A pure scalar expression retained with its remaining dependencies."""

    expression: ScalarExpression


type ScalarSpecialization = KnownScalar | ResidualScalar


@dataclass(frozen=True, slots=True)
class ParameterCellBinding:
    """One statically identified config cell replaced by a residual expression."""

    table_id: str
    key: tuple[tuple[str, CellValue], ...]
    column_id: str
    replacement: ScalarExpression

    def __post_init__(self) -> None:
        if not self.table_id or not self.column_id or not self.key:
            msg = "parameter cell binding ids and key must be non-empty"
            raise ValueError(msg)
        key_ids = tuple(column_id for column_id, _value in self.key)
        if key_ids != tuple(sorted(set(key_ids))):
            msg = "parameter cell binding keys must be unique and ordered"
            raise ValueError(msg)


def specialize_scalar(
    expression: ScalarExpr,
    *,
    known: EvalContext,
    parameter_cells: Sequence[ParameterCellBinding] = (),
) -> ScalarSpecialization:
    """Partially evaluate one pure scalar expression.

    Missing bindings and operations that fail for known operands remain
    residual. No external effect can be represented or executed here.
    """

    scalar = cast("ScalarExpression", expression)
    match scalar:
        case LiteralScalarExpr():
            return KnownScalar(deepcopy(scalar.value))
        case PointColumnScalarExpr():
            return _known_leaf(
                scalar,
                lambda: read_path(known.point_row, scalar.name),
            )
        case InputScalarExpr():
            return _known_leaf(
                scalar,
                lambda: read_path(known.inputs, scalar.name),
            )
        case ParameterScalarExpr():
            return _known_leaf(scalar, lambda: known.params.scalar(scalar.name))
        case ParameterLookupScalarExpr():
            return _specialize_parameter_lookup(
                scalar,
                known=known,
                parameter_cells=parameter_cells,
            )
        case BinaryScalarExpr():
            return _specialize_binary(
                scalar,
                known=known,
                parameter_cells=parameter_cells,
            )


def _known_leaf(
    expression: ScalarExpression,
    resolve: Callable[[], object],
) -> ScalarSpecialization:
    try:
        value = resolve()
    except _KNOWN_EVALUATION_ERRORS:
        return _residual(deepcopy(expression))
    return KnownScalar(deepcopy(cast("CellValue", value)))


def _specialize_parameter_lookup(
    expression: ParameterLookupScalarExpr,
    *,
    known: EvalContext,
    parameter_cells: Sequence[ParameterCellBinding],
) -> ScalarSpecialization:
    key_results = {
        name: specialize_scalar(
            value,
            known=known,
            parameter_cells=parameter_cells,
        )
        for name, value in expression.key.items()
    }
    if all(isinstance(result, KnownScalar) for result in key_results.values()):
        key = {
            name: cast("KnownScalar", result).value
            for name, result in key_results.items()
        }
        matched = _matching_parameter_cell(
            parameter_cells,
            table_id=expression.use.table_id,
            key=key,
            column_id=expression.use.column_id,
        )
        if matched is not None:
            return specialize_scalar(matched.replacement, known=known)
        try:
            row = known.params.lookup_row(expression.use.table_id, key)
            value = read_path(row, expression.use.column_id)
        except _KNOWN_EVALUATION_ERRORS:
            pass
        else:
            return KnownScalar(deepcopy(value))
    return _residual(
        ParameterLookupScalarExpr(
            use=expression.use,
            key={name: _expression(result) for name, result in key_results.items()},
        )
    )


def _specialize_binary(
    expression: BinaryScalarExpr,
    *,
    known: EvalContext,
    parameter_cells: Sequence[ParameterCellBinding],
) -> ScalarSpecialization:
    left = specialize_scalar(
        expression.left,
        known=known,
        parameter_cells=parameter_cells,
    )
    right = specialize_scalar(
        expression.right,
        known=known,
        parameter_cells=parameter_cells,
    )
    if isinstance(left, KnownScalar) and isinstance(right, KnownScalar):
        try:
            value = eval_binary(expression.op, left.value, right.value)
        except _KNOWN_EVALUATION_ERRORS:
            pass
        else:
            return KnownScalar(deepcopy(value))
    return _residual(
        BinaryScalarExpr(
            op=expression.op,
            left=_expression(left),
            right=_expression(right),
        )
    )


def residual_scalar_expression(result: ScalarSpecialization) -> ScalarExpression:
    """Return one specialization result as a pure scalar expression."""

    if isinstance(result, KnownScalar):
        return lit(deepcopy(result.value))
    return deepcopy(result.expression)


_expression = residual_scalar_expression


def _residual(expression: ScalarExpression) -> ResidualScalar:
    return ResidualScalar(expression)


def _matching_parameter_cell(
    bindings: Sequence[ParameterCellBinding],
    *,
    table_id: str,
    key: dict[str, CellValue],
    column_id: str,
) -> ParameterCellBinding | None:
    for binding in reversed(tuple(bindings)):
        if (
            binding.table_id == table_id
            and binding.column_id == column_id
            and _keys_equal(binding.key, key)
        ):
            return binding
    return None


def _keys_equal(
    expected: tuple[tuple[str, CellValue], ...],
    actual: dict[str, CellValue],
) -> bool:
    if {column_id for column_id, _value in expected} != set(actual):
        return False
    return all(cell_matches(value, actual[column_id]) for column_id, value in expected)


__all__ = [
    "KnownScalar",
    "ParameterCellBinding",
    "ResidualScalar",
    "ScalarSpecialization",
    "residual_scalar_expression",
    "specialize_scalar",
]
