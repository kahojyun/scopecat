"""Private typed contracts for parameter dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.kernel.value_types import Scalar, ValueType


@dataclass(frozen=True, slots=True)
class ParameterValueContract:
    """Declared shape and type of one parameter dependency."""

    kind: Literal["parameter"]
    parameter_id: str
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class ParameterLookupContract:
    """Declared scalar column lookup on one table-shaped parameter."""

    kind: Literal["lookup"]
    parameter_id: str
    key_columns: tuple[str, ...]
    key_types: tuple[tuple[str, Scalar], ...]
    literal_key_columns: frozenset[str]
    column_id: str
    value_type: Scalar


type ParameterContract = ParameterValueContract | ParameterLookupContract


def merge_parameter_contracts(
    *groups: tuple[ParameterContract, ...],
) -> tuple[ParameterContract, ...]:
    """Merge contracts without duplicating identical declarations."""

    result: list[ParameterContract] = []
    seen: set[ParameterContract] = set()
    for group in groups:
        for contract in group:
            if contract in seen:
                continue
            seen.add(contract)
            result.append(contract)
    return tuple(result)
