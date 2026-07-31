"""Shared identities and references for logical program values."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Scalar


@dataclass(frozen=True, slots=True)
class OperationId:
    """Nominal identity in the graph-operation symbol space."""

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

    def prefixed(self, *scope: str) -> OperationId:
        return OperationId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class ValueId:
    """Nominal identity in the graph-value symbol space."""

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


def operation_result_id(operation_id: OperationId) -> ValueId:
    """Return the canonical result identity for one operation."""

    return ValueId(
        SymbolId(
            scope=(*operation_id.scope, operation_id.local_id, "outputs"),
            local_id="result",
        )
    )


@dataclass(frozen=True, slots=True)
class ComputeOutput:
    """One explicitly typed value produced by a compute operation."""

    id: ValueId
    value_type: Scalar
