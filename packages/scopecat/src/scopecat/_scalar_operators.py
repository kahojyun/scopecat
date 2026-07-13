"""Shared contracts for typed scalar operators and their local evaluator.

The authoring graph and the transient relation evaluator deliberately consume
the same operator matrix from this module.  Keeping the matrix here prevents a
typed expression from being accepted during authoring only to fail because the
local evaluator implements a different set of operand combinations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal, TypeGuard, cast

from scopecat._value_identity import quantity_comparison_values
from scopecat.models.entity import EntityRef, same_entity_identity
from scopecat.models.parameter import Quantity as QuantityValue
from scopecat.models.value import PayloadValue
from scopecat.units import UNIT_KINDS, compatible_units, to_base_value, unit_kind
from scopecat.value_types import (
    AtomType,
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Record,
    Scalar,
    String,
)

type ArithmeticOperator = Literal["+", "-", "*", "/"]
type EqualityOperator = Literal["==", "!="]
type OrderingOperator = Literal["<", "<=", ">", ">="]
type LogicalOperator = Literal["and", "or"]
type ScalarOperator = (
    ArithmeticOperator | EqualityOperator | OrderingOperator | LogicalOperator
)
SCALAR_OPERATORS: frozenset[ScalarOperator] = frozenset(
    {"+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">=", "and", "or"}
)
type ScalarCategory = Literal[
    "bool",
    "number",
    "string",
    "quantity",
    "entity",
    "record",
    "payload",
]


def is_scalar_operator(value: object) -> TypeGuard[ScalarOperator]:
    """Return whether an untrusted value names a supported scalar operator."""

    return isinstance(value, str) and value in SCALAR_OPERATORS


_ARITHMETIC_OPERANDS: dict[
    ArithmeticOperator,
    frozenset[tuple[ScalarCategory, ScalarCategory]],
] = {
    "+": frozenset({("number", "number"), ("quantity", "quantity")}),
    "-": frozenset({("number", "number"), ("quantity", "quantity")}),
    "*": frozenset(
        {
            ("number", "number"),
            ("quantity", "number"),
            ("number", "quantity"),
        }
    ),
    "/": frozenset({("number", "number"), ("quantity", "number")}),
}
_EQUALITY_CATEGORIES: frozenset[ScalarCategory] = frozenset(
    {"bool", "number", "string", "quantity", "entity", "record"}
)
_ORDERING_CATEGORIES: frozenset[ScalarCategory] = frozenset(
    {"number", "string", "quantity"}
)


def scalar_operator_result_type(
    left: Scalar,
    right: Scalar,
    operator: ScalarOperator,
    *,
    left_is_null_literal: bool = False,
    right_is_null_literal: bool = False,
) -> Scalar:
    """Validate one typed operator and return its semantic result type."""

    if left_is_null_literal or right_is_null_literal:
        if operator not in {"==", "!="}:
            raise _unsupported_type_operator(left, right, operator)
        selected = right.atom if left_is_null_literal else left.atom
        if isinstance(selected, Payload):
            raise _unsupported_type_operator(left, right, operator)
        return Scalar(Bool())

    if operator in {
        "+",
        "-",
        "*",
        "/",
        "<",
        "<=",
        ">",
        ">=",
        "and",
        "or",
    } and (left.nullable or right.nullable):
        msg = f"operator {operator!r} does not accept nullable operands"
        raise TypeError(msg)

    left_category = scalar_category(left)
    right_category = scalar_category(right)
    if operator in _ARITHMETIC_OPERANDS:
        if (left_category, right_category) not in _ARITHMETIC_OPERANDS[operator]:
            raise _unsupported_type_operator(left, right, operator)
        _require_type_specific_compatibility(
            left.atom,
            right.atom,
        )
        return _arithmetic_result_type(left.atom, right.atom, operator)
    if operator in {"==", "!="}:
        if left_category != right_category or left_category not in _EQUALITY_CATEGORIES:
            raise _unsupported_type_operator(left, right, operator)
        _require_type_specific_compatibility(
            left.atom,
            right.atom,
        )
        return Scalar(Bool())
    if operator in {"<", "<=", ">", ">="}:
        if left_category != right_category or left_category not in _ORDERING_CATEGORIES:
            raise _unsupported_type_operator(left, right, operator)
        _require_type_specific_compatibility(
            left.atom,
            right.atom,
        )
        _require_finite_ordering_type(left.atom)
        _require_finite_ordering_type(right.atom)
        return Scalar(Bool())
    if operator in {"and", "or"}:
        if left_category != "bool" or right_category != "bool":
            raise _unsupported_type_operator(left, right, operator)
        return Scalar(Bool())
    msg = f"unsupported scalar operator: {operator!r}"
    raise ValueError(msg)


def require_sortable_scalar(value_type: Scalar, *, column_id: str) -> None:
    """Require a scalar type that has a total local ordering."""

    if value_type.nullable:
        msg = f"sort column {column_id!r} must be non-nullable"
        raise TypeError(msg)
    category = scalar_category(value_type)
    if category not in _ORDERING_CATEGORIES:
        msg = f"sort column {column_id!r} is not orderable"
        raise TypeError(msg)
    try:
        _require_finite_ordering_type(value_type.atom)
    except TypeError as error:
        msg = f"sort column {column_id!r} must guarantee finite values"
        raise TypeError(msg) from error
    if isinstance(value_type.atom, Quantity) and not _quantity_type_is_orderable(
        value_type.atom
    ):
        msg = (
            f"sort column {column_id!r} quantity type does not guarantee "
            "compatible units"
        )
        raise TypeError(msg)


def require_runtime_operator(
    operator: ScalarOperator,
    left: object,
    right: object,
) -> None:
    """Validate runtime values against the shared operator matrix."""

    if left is None or right is None:
        if operator in {"==", "!="}:
            return
        raise _unsupported_runtime_operator(left, right, operator)

    left_category = runtime_scalar_category(left)
    right_category = runtime_scalar_category(right)
    if operator in _ARITHMETIC_OPERANDS:
        if (left_category, right_category) not in _ARITHMETIC_OPERANDS[operator]:
            raise _unsupported_runtime_operator(left, right, operator)
    elif operator in {"==", "!="}:
        if left_category != right_category or left_category not in _EQUALITY_CATEGORIES:
            raise _unsupported_runtime_operator(left, right, operator)
    elif operator in {"<", "<=", ">", ">="}:
        if left_category != right_category or left_category not in _ORDERING_CATEGORIES:
            raise _unsupported_runtime_operator(left, right, operator)
    elif operator in {"and", "or"}:
        if left_category != "bool" or right_category != "bool":
            raise _unsupported_runtime_operator(left, right, operator)
    else:
        msg = f"unsupported scalar operator: {operator!r}"
        raise ValueError(msg)
    _require_runtime_specific_compatibility(left, right, operator=operator)


def runtime_values_equal(left: object, right: object) -> bool:
    """Compare two already validated runtime scalar values."""

    require_runtime_operator("==", left, right)
    if left is None or right is None:
        return left is right
    if isinstance(left, QuantityValue) and isinstance(right, QuantityValue):
        left_value, right_value = _quantity_comparison_values(left, right)
        return left_value == right_value
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    if isinstance(left, dict) and isinstance(right, dict):
        return _nested_values_equal(
            cast("Mapping[object, object]", left),
            cast("Mapping[object, object]", right),
        )
    return left == right


def require_finite_arithmetic_result(
    operator: ArithmeticOperator,
    value: object,
) -> None:
    """Reject arithmetic results that violate finite typed-value contracts."""

    number = value.value if isinstance(value, QuantityValue) else value
    if isinstance(number, float) and not math.isfinite(number):
        msg = f"operator {operator!r} produced a non-finite result"
        raise ValueError(msg)


def compare_ordered_values(left: object, right: object) -> int:
    """Return a three-way comparison for orderable runtime scalar values."""

    require_runtime_operator("<", left, right)
    if isinstance(left, QuantityValue) and isinstance(right, QuantityValue):
        left_value, right_value = _quantity_comparison_values(left, right)
        return _three_way(left_value, right_value)
    if _is_number(left) and _is_number(right):
        return _three_way(left, right)
    if isinstance(left, str) and isinstance(right, str):
        return _three_way(left, right)
    raise _unsupported_runtime_operator(left, right, "<")


def scalar_category(value_type: Scalar) -> ScalarCategory:
    return _atom_category(value_type.atom)


def runtime_scalar_category(value: object) -> ScalarCategory:
    if isinstance(value, bool):
        return "bool"
    if _is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, QuantityValue):
        return "quantity"
    if isinstance(value, EntityRef):
        return "entity"
    if isinstance(value, dict):
        return "record"
    if isinstance(value, PayloadValue):
        return "payload"
    msg = f"unsupported scalar runtime value: {value!r}"
    raise TypeError(msg)


def _atom_category(atom: AtomType) -> ScalarCategory:
    if isinstance(atom, Bool):
        return "bool"
    if isinstance(atom, Int | Float):
        return "number"
    if isinstance(atom, String):
        return "string"
    if isinstance(atom, Quantity):
        return "quantity"
    if isinstance(atom, Entity):
        return "entity"
    if isinstance(atom, Record):
        return "record"
    return "payload"


def _require_type_specific_compatibility(
    left: AtomType,
    right: AtomType,
) -> None:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        if not _quantity_types_are_compatible(left, right):
            msg = "quantity operands do not guarantee compatible units"
            raise TypeError(msg)
        return
    if isinstance(left, Entity) and isinstance(right, Entity):
        # Entity equality is defined for every kind. Different concrete kinds
        # simply compare unequal; an unspecified kind is an unconstrained ref.
        return
    if isinstance(left, Payload) and isinstance(right, Payload):
        if left.schema_id != right.schema_id:
            msg = "payload operands have incompatible schemas"
            raise TypeError(msg)
        return
    if isinstance(left, Record) and isinstance(right, Record) and left != right:
        msg = "record operands have incompatible structures"
        raise TypeError(msg)
    if (
        isinstance(left, Record)
        and isinstance(right, Record)
        and (
            not _record_supports_equality(left) or not _record_supports_equality(right)
        )
    ):
        msg = (
            "record equality requires closed, recursively scalar fields "
            "without payloads"
        )
        raise TypeError(msg)


def _require_runtime_specific_compatibility(
    left: object,
    right: object,
    *,
    operator: ScalarOperator,
) -> None:
    if operator in {"<", "<=", ">", ">="}:
        _require_finite_ordering_value(left, operator=operator)
        _require_finite_ordering_value(right, operator=operator)
    if isinstance(left, QuantityValue) and isinstance(right, QuantityValue):
        _quantity_comparison_values(left, right)
        return
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return
    if (
        isinstance(left, PayloadValue)
        and isinstance(right, PayloadValue)
        and left.schema_id != right.schema_id
    ):
        raise _unsupported_runtime_operator(left, right, operator)


def _require_finite_ordering_type(atom: AtomType) -> None:
    if isinstance(atom, Float | Quantity) and not atom.finite:
        msg = "ordering requires types that guarantee finite numeric values"
        raise TypeError(msg)


def _require_finite_ordering_value(
    value: object,
    *,
    operator: ScalarOperator,
) -> None:
    number = value.value if isinstance(value, QuantityValue) else value
    if isinstance(number, float) and not math.isfinite(number):
        raise _unsupported_runtime_operator(value, value, operator)


def _nested_values_equal(left: object, right: object) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        left_mapping = cast("Mapping[object, object]", left)
        right_mapping = cast("Mapping[object, object]", right)
        if set(left_mapping) != set(right_mapping):
            return False
        return all(
            _nested_values_equal(left_mapping[key], right_mapping[key])
            for key in left_mapping
        )
    if (
        isinstance(left, Sequence)
        and not isinstance(left, str | bytes)
        and isinstance(right, Sequence)
        and not isinstance(right, str | bytes)
    ):
        left_sequence = cast("Sequence[object]", left)
        right_sequence = cast("Sequence[object]", right)
        return len(left_sequence) == len(right_sequence) and all(
            _nested_values_equal(left_item, right_item)
            for left_item, right_item in zip(
                left_sequence,
                right_sequence,
                strict=True,
            )
        )
    try:
        return runtime_values_equal(
            cast("object", left),
            cast("object", right),
        )
    except TypeError:
        return False


def _arithmetic_result_type(
    left: AtomType,
    right: AtomType,
    operator: ArithmeticOperator,
) -> Scalar:
    if isinstance(left, Int | Float) and isinstance(right, Int | Float):
        if operator == "/" or isinstance(left, Float) or isinstance(right, Float):
            return Scalar(Float())
        return Scalar(Int())
    quantity = left if isinstance(left, Quantity) else right
    if isinstance(quantity, Quantity):
        return Scalar(
            Quantity(
                dimension=quantity.dimension,
                unit=quantity.unit,
                finite=True,
            )
        )
    msg = f"unsupported arithmetic result for {left!r} and {right!r}"
    raise TypeError(msg)


def _quantity_types_are_compatible(left: Quantity, right: Quantity) -> bool:
    left_dimension = _quantity_dimension(left)
    right_dimension = _quantity_dimension(right)
    if (
        left_dimension is None
        or right_dimension is None
        or left_dimension != right_dimension
    ):
        return False
    if left.unit is not None and right.unit is not None:
        if left.unit == right.unit:
            return True
        return compatible_units(left.unit, right.unit) and _units_are_linear(
            left.unit,
            right.unit,
        )
    return _dimension_is_linear(left_dimension)


def _quantity_type_is_orderable(value_type: Quantity) -> bool:
    if value_type.unit is not None:
        return True
    dimension = _quantity_dimension(value_type)
    return dimension is not None and _dimension_is_linear(dimension)


def _quantity_dimension(value_type: Quantity) -> str | None:
    if value_type.dimension is not None:
        return value_type.dimension
    if value_type.unit is not None:
        return unit_kind(value_type.unit)
    return None


def _dimension_is_linear(dimension: str) -> bool:
    units = [unit for unit, kind in UNIT_KINDS.items() if kind == dimension]
    return bool(units) and _units_are_linear(*units)


def _units_are_linear(*units: str) -> bool:
    return all(to_base_value(1.0, unit) is not None for unit in units)


def _quantity_comparison_values(
    left: QuantityValue,
    right: QuantityValue,
) -> tuple[float, float]:
    try:
        return quantity_comparison_values(left, right)
    except ValueError as error:
        msg = f"cannot compare quantity units {left.unit!r} and {right.unit!r}"
        raise TypeError(msg) from error


def _record_supports_equality(value_type: Record) -> bool:
    if value_type.allow_extra_fields:
        return False
    for field in value_type.fields:
        if not isinstance(field.value_type, Scalar):
            return False
        atom = field.value_type.atom
        if isinstance(atom, Payload):
            return False
        if isinstance(atom, Record) and not _record_supports_equality(atom):
            return False
    return True


def _describe_scalar(value_type: Scalar) -> str:
    nullable = "?" if value_type.nullable else ""
    return f"Scalar[{type(value_type.atom).__name__}]{nullable}"


def _unsupported_type_operator(
    left: Scalar,
    right: Scalar,
    operator: ScalarOperator,
) -> TypeError:
    return TypeError(
        f"operator {operator!r} is not defined for "
        f"{_describe_scalar(left)} and {_describe_scalar(right)}"
    )


def _unsupported_runtime_operator(
    left: object,
    right: object,
    operator: ScalarOperator,
) -> TypeError:
    return TypeError(f"operator {operator!r} is not defined for {left!r} and {right!r}")


def _three_way(left: float | str, right: float | str) -> int:
    if left < right:  # pyright: ignore[reportOperatorIssue]
        return -1
    if left > right:  # pyright: ignore[reportOperatorIssue]
        return 1
    return 0


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


__all__ = [
    "SCALAR_OPERATORS",
    "ScalarOperator",
    "compare_ordered_values",
    "is_scalar_operator",
    "require_finite_arithmetic_result",
    "require_runtime_operator",
    "require_sortable_scalar",
    "runtime_values_equal",
    "scalar_operator_result_type",
]
