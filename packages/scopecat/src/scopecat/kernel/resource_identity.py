"""Shared logical, physical, and leasing resource identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override

from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True, slots=True)
class LogicalResourcePortId:
    """Hygienic identity of one logical resource requirement."""

    symbol: SymbolId

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

    @override
    def __str__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True, slots=True)
class PhysicalResourceId:
    """Nominal physical-resource reference, closed against config when linked."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "physical resource id must be non-empty"
            raise ValueError(msg)

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """Run-level exclusive claim closed while specializing resources."""

    id: str
    kind: Literal["target", "instrument", "channel", "group"] = "instrument"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "resource claim id must be non-empty"
            raise ValueError(msg)


type ResourceTarget = LogicalResourcePortId | PhysicalResourceId


def logical_resource_port_id(
    value: str | SymbolId,
) -> LogicalResourcePortId:
    """Create an unscoped port id or wrap an existing structural symbol."""

    symbol = value if isinstance(value, SymbolId) else SymbolId(local_id=value)
    return LogicalResourcePortId(symbol)
