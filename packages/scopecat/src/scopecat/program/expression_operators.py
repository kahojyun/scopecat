"""Shared contracts for canonical expression operators and evaluation.

The authoring graph and transient relation evaluators deliberately consume
the same operator matrix from this module.  Keeping the matrix here prevents a
typed expression from being accepted during authoring only to fail because the
local evaluator implements a different set of operand combinations.
"""

from __future__ import annotations

import math
from typing import Literal, TypeGuard

from scopecat.kernel.entity import (
    EntityRef,
    same_entity_identity,
)
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_identity import (
    quantity_comparison_values,
    scalar_values_equal,
)
from scopecat.kernel.value_types import (
    AtomType,
    Float,
    Int,
    Quantity,
    Scalar,
)

type ArithmeticOperator = Literal["+", "-", "*", "/"]
type ScalarOperator = ArithmeticOperator
SCALAR_OPERATORS: frozenset[ScalarOperator] = frozenset({"+", "-", "*", "/"})
type ArithmeticCategory = Literal["number", "quantity"]


def is_scalar_operator(value: object) -> TypeGuard[ScalarOperator]:
    """Return whether an untrusted value names a supported scalar operator."""

    return isinstance(value, str) and value in SCALAR_OPERATORS


_ARITHMETIC_OPERANDS: dict[
    ArithmeticOperator,
    frozenset[tuple[ArithmeticCategory, ArithmeticCategory]],
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


def scalar_operator_result_type(
    left: Scalar,
    right: Scalar,
    operator: ScalarOperator,
) -> Scalar:
    """Validate one typed operator and return its semantic result type."""

    left_category = _atom_arithmetic_category(left.atom)
    right_category = _atom_arithmetic_category(right.atom)
    if (left_category, right_category) not in _ARITHMETIC_OPERANDS[operator]:
        raise _unsupported_type_operator(left, right, operator)
    _require_type_specific_compatibility(
        left.atom,
        right.atom,
    )
    return _arithmetic_result_type(left.atom, right.atom, operator)


def require_runtime_operator(
    operator: ScalarOperator,
    left: object,
    right: object,
) -> None:
    """Validate runtime values against the shared operator matrix."""

    if left is None or right is None:
        raise _unsupported_runtime_operator(left, right, operator)

    left_category = _runtime_arithmetic_category(left)
    right_category = _runtime_arithmetic_category(right)
    if (left_category, right_category) not in _ARITHMETIC_OPERANDS[operator]:
        raise _unsupported_runtime_operator(left, right, operator)
    _require_runtime_specific_compatibility(left, right)


def runtime_values_equal(left: object, right: object) -> bool:
    """Compare normalized scalars without a public equality expression."""

    if left is None or right is None:
        return left is right
    if isinstance(left, QuantityValue) or isinstance(right, QuantityValue):
        if not isinstance(left, QuantityValue) or not isinstance(right, QuantityValue):
            raise _unsupported_runtime_equality(left, right)
        try:
            return scalar_values_equal(left, right)
        except ValueError as error:
            msg = f"cannot compare quantity units {left.unit!r} and {right.unit!r}"
            raise TypeError(msg) from error
    if isinstance(left, EntityRef) or isinstance(right, EntityRef):
        if not isinstance(left, EntityRef) or not isinstance(right, EntityRef):
            raise _unsupported_runtime_equality(left, right)
        return same_entity_identity(left, right)
    if isinstance(left, bool) or isinstance(right, bool):
        if not isinstance(left, bool) or not isinstance(right, bool):
            raise _unsupported_runtime_equality(left, right)
        return left == right
    if _is_number(left) or _is_number(right):
        if not _is_number(left) or not _is_number(right):
            raise _unsupported_runtime_equality(left, right)
        return left == right
    if isinstance(left, str) or isinstance(right, str):
        if not isinstance(left, str) or not isinstance(right, str):
            raise _unsupported_runtime_equality(left, right)
        return left == right
    raise _unsupported_runtime_equality(left, right)


def require_finite_arithmetic_result(
    operator: ArithmeticOperator,
    value: object,
) -> None:
    """Reject arithmetic results that violate finite typed-value contracts."""

    number = value.value if isinstance(value, QuantityValue) else value
    if isinstance(number, float) and not math.isfinite(number):
        msg = f"operator {operator!r} produced a non-finite result"
        raise ValueError(msg)


def _atom_arithmetic_category(atom: AtomType) -> ArithmeticCategory | None:
    if isinstance(atom, Int | Float):
        return "number"
    if isinstance(atom, Quantity):
        return "quantity"
    return None


def _runtime_arithmetic_category(value: object) -> ArithmeticCategory | None:
    if _is_number(value):
        return "number"
    if isinstance(value, QuantityValue):
        return "quantity"
    return None


def _require_type_specific_compatibility(
    left: AtomType,
    right: AtomType,
) -> None:
    if (
        isinstance(left, Quantity)
        and isinstance(right, Quantity)
        and not _quantity_types_are_compatible(left, right)
    ):
        msg = "quantity operands do not guarantee compatible units"
        raise TypeError(msg)


def _require_runtime_specific_compatibility(
    left: object,
    right: object,
) -> None:
    if isinstance(left, QuantityValue) and isinstance(right, QuantityValue):
        _quantity_comparison_values(left, right)


def _arithmetic_result_type(
    left: AtomType,
    right: AtomType,
    operator: ArithmeticOperator,
) -> Scalar:
    if isinstance(left, Int) and isinstance(right, Int) and operator != "/":
        return Scalar(_integer_arithmetic_result_type(left, right, operator))
    if isinstance(left, Int | Float) and isinstance(right, Int | Float):
        return Scalar(Float())
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


def _integer_arithmetic_result_type(
    left: Int,
    right: Int,
    operator: Literal["+", "-", "*"],
) -> Int:
    """Preserve bounds for affine integer expressions."""

    if operator == "+":
        return Int(
            minimum=_combine_known_bounds(left.minimum, right.minimum, operator="+"),
            maximum=_combine_known_bounds(left.maximum, right.maximum, operator="+"),
        )
    if operator == "-":
        return Int(
            minimum=_combine_known_bounds(left.minimum, right.maximum, operator="-"),
            maximum=_combine_known_bounds(left.maximum, right.minimum, operator="-"),
        )

    left_constant = _exact_integer(left)
    if left_constant is not None:
        return _scale_integer_bounds(right, left_constant)
    right_constant = _exact_integer(right)
    if right_constant is not None:
        return _scale_integer_bounds(left, right_constant)
    return Int()


def _combine_known_bounds(
    left: int | None,
    right: int | None,
    *,
    operator: Literal["+", "-"],
) -> int | None:
    if left is None or right is None:
        return None
    return left + right if operator == "+" else left - right


def _exact_integer(value_type: Int) -> int | None:
    if value_type.minimum is not None and value_type.minimum == value_type.maximum:
        return value_type.minimum
    return None


def _scale_integer_bounds(value_type: Int, factor: int) -> Int:
    if factor == 0:
        return Int(minimum=0, maximum=0)
    if factor > 0:
        minimum = value_type.minimum
        maximum = value_type.maximum
    else:
        minimum = value_type.maximum
        maximum = value_type.minimum
    return Int(
        minimum=None if minimum is None else factor * minimum,
        maximum=None if maximum is None else factor * maximum,
    )


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
        return compatible_units(left.unit, right.unit)
    return True


def _quantity_dimension(value_type: Quantity) -> str | None:
    if value_type.dimension is not None:
        return value_type.dimension
    if value_type.unit is not None:
        return unit_kind(value_type.unit)
    return None


def _quantity_comparison_values(
    left: QuantityValue,
    right: QuantityValue,
) -> tuple[float, float]:
    try:
        return quantity_comparison_values(left, right)
    except ValueError as error:
        msg = f"cannot compare quantity units {left.unit!r} and {right.unit!r}"
        raise TypeError(msg) from error


def _describe_scalar(value_type: Scalar) -> str:
    return f"Scalar[{type(value_type.atom).__name__}]"


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


def _unsupported_runtime_equality(left: object, right: object) -> TypeError:
    return TypeError(
        "runtime equality requires matching bool, number, string, quantity, "
        f"or entity values; got {left!r} and {right!r}"
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)
