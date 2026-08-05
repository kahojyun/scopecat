"""Python-shaped values returned across authored module boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields, is_dataclass, replace
from typing import cast

from scopecat.authoring.entity_selection import PerEntity
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.product_identity import ProductId
from scopecat.program.module import ModuleValueExport
from scopecat.program.products import ProductRef
from scopecat.program.value_refs import ValueRef

type _ProductKey = tuple[ProductId, tuple[object, ...]]


class ProductBundle:
    """Marker base for a dataclass tree that can be recorded as one product group."""

    __slots__ = ()


def recording_products(products: ProductBundle) -> tuple[ProductRef, ...]:
    """Flatten one recordable dataclass bundle in declaration order."""

    selected: list[ProductRef] = []
    _append_recording_products(selected, products)
    return tuple(selected)


def module_result_value_exports(result: object) -> tuple[ModuleValueExport, ...]:
    """Derive private value ports from the ValueRef leaves of one return value."""

    values: list[ValueRef] = []
    _append_result_values(values, result)
    return tuple(
        ModuleValueExport(id=f"result_{index}", source=value)
        for index, value in enumerate(values)
    )


def relocate_module_result[ResultT](
    result: ResultT,
    *,
    product_sources: Iterable[ProductRef],
    product_targets: Iterable[ProductRef],
    value_sources: Iterable[ValueRef] = (),
    value_targets: Iterable[ValueRef] = (),
) -> ResultT:
    """Rebuild a typed return value against another module boundary."""

    product_replacements = {
        _product_key(source): target
        for source, target in zip(product_sources, product_targets, strict=True)
    }
    value_replacements = {
        source.id: target
        for source, target in zip(value_sources, value_targets, strict=True)
    }
    relocated = _relocate_result_value(
        cast("object", result),
        product_replacements=product_replacements,
        value_replacements=value_replacements,
    )
    return cast("ResultT", relocated)


def _relocate_result_value(
    value: object,
    *,
    product_replacements: dict[_ProductKey, ProductRef],
    value_replacements: dict[ValueId, ValueRef],
) -> object:
    if value is None:
        return None
    if isinstance(value, ProductRef):
        product = cast("ProductRef", value)
        try:
            return product_replacements[_product_key(product)]
        except KeyError:
            msg = f"module return exposes product {product.id!r} outside its body"
            raise ValueError(msg) from None
    if isinstance(value, ValueRef):
        try:
            return value_replacements[value.id]
        except KeyError:
            msg = "module return value is missing its generated output port"
            raise ValueError(msg) from None
    if isinstance(value, PerEntity):
        return value.map(
            lambda item: _relocate_result_value(
                item,
                product_replacements=product_replacements,
                value_replacements=value_replacements,
            )
        )
    if is_dataclass(value) and not isinstance(value, type):
        members = fields(value)
        if not members:
            raise TypeError("module result dataclasses must not be empty")
        return replace(
            value,
            **{
                member.name: _relocate_result_value(
                    cast("object", getattr(value, member.name)),
                    product_replacements=product_replacements,
                    value_replacements=value_replacements,
                )
                for member in members
            },
        )
    raise TypeError(
        "module functions must return None, ValueRef, ProductRef, or a "
        "dataclass/PerEntity tree of references"
    )


def _append_result_values(selected: list[ValueRef], value: object) -> None:
    if value is None or isinstance(value, ProductRef):
        return
    if isinstance(value, ValueRef):
        if all(existing.id != value.id for existing in selected):
            selected.append(value)
        return
    if isinstance(value, PerEntity):
        for item in value.values():
            _append_result_values(selected, item)
        return
    if is_dataclass(value) and not isinstance(value, type):
        members = fields(value)
        if not members:
            raise TypeError("module result dataclasses must not be empty")
        for member in members:
            _append_result_values(
                selected,
                cast("object", getattr(value, member.name)),
            )
        return
    raise TypeError(
        "module functions must return None, ValueRef, ProductRef, or a "
        "dataclass/PerEntity tree of references"
    )


def _append_recording_products(
    selected: list[ProductRef],
    value: object,
) -> None:
    if isinstance(value, ProductRef):
        selected.append(cast("ProductRef", value))
        return
    if isinstance(value, PerEntity):
        for item in value.values():
            _append_recording_products(selected, item)
        return
    if is_dataclass(value) and not isinstance(value, type):
        members = fields(value)
        if not members:
            raise TypeError("product bundle dataclasses must not be empty")
        for member in members:
            _append_recording_products(
                selected,
                cast("object", getattr(value, member.name)),
            )
        return
    raise TypeError(
        "product bundles must be dataclass/PerEntity trees of ProductRef values"
    )


def _product_key(product: ProductRef) -> _ProductKey:
    return product.product_id, product.origin
