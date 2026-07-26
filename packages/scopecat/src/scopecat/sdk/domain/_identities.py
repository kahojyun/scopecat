"""Native identities carried by opaque domain SDK references."""

from __future__ import annotations

from typing import cast

from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.sdk.domain.view import DomainPointRef, DomainProductUseRef


def point_id(ref: DomainPointRef) -> LogicalPointId:
    return cast("LogicalPointId", ref.native)


def product_use_id(ref: DomainProductUseRef) -> ProductUseId:
    return cast("ProductUseId", ref.native)


__all__ = ["point_id", "product_use_id"]
