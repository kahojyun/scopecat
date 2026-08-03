"""Python-shaped product views returned from authored modules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields, is_dataclass, replace
from typing import cast

from scopecat.authoring.entity_parameters import PerEntity
from scopecat.kernel.product_identity import ProductId
from scopecat.program.products import ProductRef

type _ProductKey = tuple[ProductId, tuple[object, ...]]


def relocate_module_products[ProductsT](
    products: ProductsT,
    *,
    sources: Iterable[ProductRef],
    targets: Iterable[ProductRef],
) -> ProductsT:
    """Rebuild one typed product view against another module boundary."""

    if products is None:
        return products
    replacements = {
        _product_key(source): target
        for source, target in zip(sources, targets, strict=True)
    }
    relocated = _relocate_product_value(
        cast("object", products),
        replacements=replacements,
    )
    return cast("ProductsT", relocated)


def _relocate_product_value(
    value: object,
    *,
    replacements: dict[_ProductKey, ProductRef],
) -> object:
    if isinstance(value, ProductRef):
        try:
            return replacements[_product_key(value)]
        except KeyError:
            msg = f"module return exposes product {value.id!r} outside its body"
            raise ValueError(msg) from None
    if isinstance(value, PerEntity):
        return value.map(
            lambda item: _relocate_product_value(
                item,
                replacements=replacements,
            )
        )
    if is_dataclass(value) and not isinstance(value, type):
        members = fields(value)
        if not members:
            raise TypeError("module product dataclasses must not be empty")
        return replace(
            value,
            **{
                member.name: _relocate_product_value(
                    cast("object", getattr(value, member.name)),
                    replacements=replacements,
                )
                for member in members
            },
        )
    raise TypeError(
        "module functions must return None, ProductRef, or a dataclass/PerEntity "
        "tree of ProductRef values"
    )


def _product_key(product: ProductRef) -> _ProductKey:
    return product.product_id, product.origin
