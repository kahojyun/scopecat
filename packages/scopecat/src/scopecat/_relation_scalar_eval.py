from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeGuard, cast

from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

type ScalarValue = str | int | float | bool | None | Quantity | EntityRef | PayloadValue
type CellValue = ScalarValue | dict[str, Any]
type ScalarOperator = Literal[
    "+",
    "-",
    "*",
    "/",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "and",
    "or",
]


def read_path(row: Mapping[str, object], path: str) -> CellValue:
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
    if op == "+":
        return _add(left, right)
    if op == "-":
        return _sub(left, right)
    if op == "*":
        return _mul(left, right)
    if op == "/":
        return _div(left, right)
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op in {"<", "<=", ">", ">="}:
        return _compare(op, left, right)
    if op == "and":
        return _bool(left) and _bool(right)
    if op == "or":
        return _bool(left) or _bool(right)
    msg = f"unsupported binary operator: {op}"
    raise ValueError(msg)


def is_cell_value(value: object) -> TypeGuard[CellValue]:
    return value is None or isinstance(
        value,
        str | int | float | bool | Quantity | EntityRef | PayloadValue | dict,
    )


def _add(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        return left + right
    if _is_number(left) and _is_number(right):
        return left + right
    msg = f"cannot add {left!r} and {right!r}"
    raise TypeError(msg)


def _sub(left: CellValue, right: CellValue) -> CellValue:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
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
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        right = right.to(left.unit)
        return _compare_number_values(op, left.value, right.value)
    if _is_number(left) and _is_number(right):
        return _compare_number_values(op, float(left), float(right))
    if isinstance(left, str) and isinstance(right, str):
        return _compare_string_values(op, left, right)
    msg = f"cannot compare {left!r} and {right!r}"
    raise TypeError(msg)


def _compare_number_values(op: ScalarOperator, left: float, right: float) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    msg = f"unsupported comparison operator: {op}"
    raise ValueError(msg)


def _compare_string_values(op: ScalarOperator, left: str, right: str) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
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
    mapping = cast(Mapping[object, object], value)
    return all(isinstance(key, str) for key in mapping)
