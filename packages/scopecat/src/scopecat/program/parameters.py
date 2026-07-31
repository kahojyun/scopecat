"""Typed contracts for symbolic parameter dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.graph.relations.model import ParameterLookupUse
from scopecat.kernel.value_types import ValueType


@dataclass(frozen=True, slots=True)
class ParameterValueContract:
    """Declared shape and type of one parameter dependency."""

    parameter_id: str
    value_type: ValueType


type ParameterContract = ParameterValueContract | ParameterLookupUse


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
