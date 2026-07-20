"""Nominal logical-product identities and use occurrences in transient IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import override
from uuid import uuid4

from scopecat.kernel.qualified_name import parse_qualified_name
from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True, slots=True)
class ProductId:
    """Hygienic identity of one logical product definition."""

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

    def prefixed(self, *scope: str) -> ProductId:
        return ProductId(self.symbol.prefixed(*scope))

    @override
    def __str__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True, slots=True)
class ProductUseId:
    """Opaque identity of one logical-product use occurrence."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "product-use identity must be non-empty"
            raise ValueError(msg)

    @classmethod
    def fresh(cls) -> ProductUseId:
        return cls(uuid4().hex)

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProductUse:
    """One occurrence that references exactly one logical product definition."""

    product_id: ProductId
    id: ProductUseId = field(default_factory=ProductUseId.fresh)


def product_id(value: str | SymbolId) -> ProductId:
    """Create an unscoped product id or wrap an existing structural symbol."""

    symbol = value if isinstance(value, SymbolId) else SymbolId(local_id=value)
    return ProductId(symbol)


def parse_product_id(value: str) -> ProductId:
    """Decode a canonical qualified product display name at an entry boundary."""

    scope, local_id = parse_qualified_name(value)
    return ProductId(SymbolId(scope=scope, local_id=local_id))


def product_use(value: ProductId) -> ProductUse:
    """Create a fresh use occurrence for one product definition."""

    return ProductUse(product_id=value)
