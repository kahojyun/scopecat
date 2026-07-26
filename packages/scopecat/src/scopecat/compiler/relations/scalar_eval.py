"""Local scalar helpers used by relation evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeGuard, cast

from scopecat.graph.relations.model import CellValue, is_cell_value
from scopecat.graph.relations.operators import (
    ScalarOperator,
    compare_ordered_values,
    require_finite_arithmetic_result,
    require_runtime_operator,
    runtime_values_equal,
)
from scopecat.kernel.entity import (
    EntityRef,
    same_entity_identity,
)
from scopecat.kernel.quantity import Quantity


def read_path(row: Mapping[str, object], path: str) -> CellValue:
    if path in row:
        selected = row[path]
        if not is_cell_value(selected):
            msg = f"path {path!r} resolved to unsupported value {selected!r}"
            raise TypeError(msg)
        return selected
    current: object = row
    for part in path.split("."):
        if not _is_string_key_mapping(current) or part not in current:
            msg = f"cannot read path {path!r} from row {row!r}"
            raise KeyError(msg)
        current = current[part]
    if not is_cell_value(current):
        msg = f"path {path!r} resolved to unsupported value {current!r}"
        raise TypeError(msg)
    return current


def eval_binary(op: ScalarOperator, left: CellValue, right: CellValue) -> CellValue:
    require_runtime_operator(op, left, right)
    if op == "+":
        result = _add(left, right)
        require_finite_arithmetic_result(op, result)
        return result
    if op == "-":
        result = _sub(left, right)
        require_finite_arithmetic_result(op, result)
        return result
    if op == "*":
        result = _mul(left, right)
        require_finite_arithmetic_result(op, result)
        return result
    if op == "/":
        result = _div(left, right)
        require_finite_arithmetic_result(op, result)
        return result
    if op == "==":
        return runtime_values_equal(left, right)
    if op == "!=":
        return not runtime_values_equal(left, right)
    if op in {"<", "<=", ">", ">="}:
        return _compare(op, left, right)
    if op == "and":
        return _bool(left) and _bool(right)
    if op == "or":
        return _bool(left) or _bool(right)
    msg = f"unsupported binary operator: {op}"
    raise ValueError(msg)


def cell_matches(left: CellValue | None, right: CellValue) -> bool:
    """Compare lookup cells using the relation runtime's scalar semantics."""

    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    if isinstance(left, EntityRef) and isinstance(right, str):
        return left.id == right
    if isinstance(left, str) and isinstance(right, EntityRef):
        return left == right.id
    try:
        return runtime_values_equal(left, right)
    except TypeError:
        return False


def _add(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        if left.unit == right.unit:
            return Quantity(value=left.value + right.value, unit=left.unit)
        return left + right
    if _is_number(left) and _is_number(right):
        return left + right
    msg = f"cannot add {left!r} and {right!r}"
    raise TypeError(msg)


def _sub(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        if left.unit == right.unit:
            return Quantity(value=left.value - right.value, unit=left.unit)
        return left - right
    if _is_number(left) and _is_number(right):
        return left - right
    msg = f"cannot subtract {right!r} from {left!r}"
    raise TypeError(msg)


def _mul(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and _is_number(right):
        return left * right
    if _is_number(left) and isinstance(right, Quantity):
        return right * left
    if _is_number(left) and _is_number(right):
        return left * right
    msg = f"cannot multiply {left!r} and {right!r}"
    raise TypeError(msg)


def _div(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and _is_number(right):
        return left / right
    if _is_number(left) and _is_number(right):
        return left / right
    msg = f"cannot divide {left!r} by {right!r}"
    raise TypeError(msg)


def _compare(op: ScalarOperator, left: CellValue, right: CellValue) -> bool:
    ordering = compare_ordered_values(left, right)
    if op == "<":
        return ordering < 0
    if op == "<=":
        return ordering <= 0
    if op == ">":
        return ordering > 0
    if op == ">=":
        return ordering >= 0
    msg = f"unsupported comparison operator: {op}"
    raise ValueError(msg)


def _bool(value: CellValue) -> bool:
    if isinstance(value, bool):
        return value
    msg = f"boolean operator requires bool values, got {value!r}"
    raise TypeError(msg)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_string_key_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return False
    mapping = cast("Mapping[object, object]", value)
    return all(isinstance(key, str) for key in mapping)
