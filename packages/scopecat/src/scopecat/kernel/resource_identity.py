"""Shared logical-port and runtime resource-claim identities."""

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
class ResourceClaim:
    """Exclusive physical identity with lifetime defined by its container.

    A claim may protect a whole run or one coverage block. The enclosing
    execution object, rather than the identity itself, owns that lease duration.
    """

    id: str
    kind: Literal["target", "instrument", "channel", "group"] = "instrument"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "resource claim id must be non-empty"
            raise ValueError(msg)


def logical_resource_port_id(
    value: str | SymbolId,
) -> LogicalResourcePortId:
    """Create an unscoped port id or wrap an existing structural symbol."""

    symbol = value if isinstance(value, SymbolId) else SymbolId(local_id=value)
    return LogicalResourcePortId(symbol)
