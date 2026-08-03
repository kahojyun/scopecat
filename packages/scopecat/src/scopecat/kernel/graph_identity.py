"""Nominal graph identities shared across program and measurement layers."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True, slots=True)
class ValueId:
    """Identity in the graph-value symbol space."""

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

    def prefixed(self, *scope: str) -> ValueId:
        return ValueId(self.symbol.prefixed(*scope))


__all__ = ["ValueId"]
