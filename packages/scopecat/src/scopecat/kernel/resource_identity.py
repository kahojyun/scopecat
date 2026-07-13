"""Nominal logical and physical resource identities in transient compiler IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True, slots=True)
class LogicalResourcePortId:
    """Hygienic identity of one logical resource requirement."""

    symbol: SymbolId

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.symbol), SymbolId):
            msg = "logical resource port ids require a structural symbol"
            raise TypeError(msg)

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> LogicalResourcePortId:
        return LogicalResourcePortId(self.symbol.prefixed(*scope))

    def __str__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True, slots=True)
class PhysicalResourceId:
    """Nominal physical-resource reference, closed against config when linked."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.value), str):
            msg = "physical resource ids must be strings"
            raise TypeError(msg)
        if not self.value:
            msg = "physical resource id must be non-empty"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value


type ResourceTarget = LogicalResourcePortId | PhysicalResourceId


def logical_resource_port_id(
    value: str | SymbolId,
) -> LogicalResourcePortId:
    """Create an unscoped port id or wrap an existing structural symbol."""

    symbol = value if isinstance(value, SymbolId) else SymbolId(local_id=value)
    return LogicalResourcePortId(symbol)


def physical_resource_id(value: str) -> PhysicalResourceId:
    return PhysicalResourceId(value)


__all__ = [
    "LogicalResourcePortId",
    "PhysicalResourceId",
    "ResourceTarget",
    "logical_resource_port_id",
    "physical_resource_id",
]
