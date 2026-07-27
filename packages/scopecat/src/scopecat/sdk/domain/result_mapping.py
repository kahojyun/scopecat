"""Carrier contracts for a closed domain-result ownership mapping."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field

from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.products import ProductDef
from scopecat.sdk.domain._identities import point_id, product_use_id
from scopecat.sdk.domain.batch import DomainBatchRequest
from scopecat.sdk.domain.view import DomainPointRef, DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainResultBinding[ResultAddressT: Hashable]:
    """Opaque target result location bound to one logical product occurrence."""

    result_address: ResultAddressT
    point: DomainPointRef
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainMappedResult[ResultAddressT: Hashable]:
    """One opaque result location and its exact logical output ownership."""

    result_address: ResultAddressT
    point: DomainPointRef
    product_uses: tuple[DomainProductUseRef, ...]
    product: ProductDef = field(repr=False)

    @property
    def logical_point_id(self) -> LogicalPointId:
        return point_id(self.point)

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return tuple(product_use_id(use) for use in self.product_uses)

    @property
    def product_id(self) -> ProductId:
        return self.product.id


@dataclass(frozen=True, slots=True)
class DomainResultMapping[ResultAddressT: Hashable]:
    """Exact inventory from opaque result locations to SDK-owned references."""

    context: DomainBatchRequest
    selected_product_uses: tuple[ProductUse, ...] = field(repr=False)
    results: tuple[DomainMappedResult[ResultAddressT], ...]
    product_by_use_id: Mapping[ProductUseId, ProductDef] = field(
        repr=False, compare=False
    )
    _contract_fingerprint: str = field(repr=False, compare=False)

    @property
    def contract_fingerprint(self) -> str:
        return self._contract_fingerprint

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        try:
            return self.product_by_use_id[product_use_id]
        except KeyError as error:
            raise KeyError(product_use_id.value) from error
