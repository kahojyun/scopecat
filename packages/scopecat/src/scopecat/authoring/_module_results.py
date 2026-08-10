"""Python-shaped values returned across authored module boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import fields, is_dataclass, replace
from typing import Protocol, cast, override

from scopecat.authoring.entity_selection import PerEntity
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.product_identity import ProductId
from scopecat.program.measurement_types import NativeMeasurementValue
from scopecat.program.module import ModuleValueExport
from scopecat.program.products import ProductRef
from scopecat.program.record_refs import RecordRef
from scopecat.program.value_refs import ValueRef

type _ProductKey = tuple[ProductId, tuple[object, ...]]


class _RecordProduct(Protocol):
    def __call__[T: NativeMeasurementValue](
        self,
        product: ProductRef[T],
        /,
    ) -> RecordRef[T]: ...


class RecordedProducts(Mapping[str, object]):
    """Attribute and mapping view of records produced from a product bundle."""

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[str, object]) -> None:
        self._entries = dict(entries)

    @override
    def __getitem__(self, key: str) -> object:
        return self._entries[key]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    @override
    def __len__(self) -> int:
        return len(self._entries)

    def __getattr__(self, name: str) -> object:
        try:
            return self._entries[name]
        except KeyError:
            raise AttributeError(name) from None


class ProductBundle:
    """A dataclass-shaped group of products recordable without a twin type."""

    __slots__ = ()

    def _records_internal(
        self,
        record: _RecordProduct,
        /,
    ) -> RecordedProducts:
        """Map dataclass product fields to records by their declared names."""

        if not is_dataclass(self):
            raise TypeError("product bundles must be dataclasses")
        members = fields(self)
        if not members:
            raise TypeError("product bundle dataclasses must not be empty")
        entries: dict[str, object] = {}
        for member in members:
            value = cast("object", getattr(self, member.name))
            if isinstance(value, ProductRef):
                entries[member.name] = record(value)
            elif isinstance(value, ProductBundle):
                entries[member.name] = value._records_internal(record)
            else:
                raise TypeError(
                    "product bundle fields must be ProductRef or ProductBundle values"
                )
        return RecordedProducts(entries)


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
        try:
            return product_replacements[_product_key(value)]
        except KeyError:
            msg = f"module return exposes product {value.id!r} outside its body"
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
    if isinstance(value, tuple):
        return tuple(
            _relocate_result_value(
                item,
                product_replacements=product_replacements,
                value_replacements=value_replacements,
            )
            for item in cast("tuple[object, ...]", value)
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
        "tuple/dataclass/PerEntity tree of references"
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
    if isinstance(value, tuple):
        for item in cast("tuple[object, ...]", value):
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
        "tuple/dataclass/PerEntity tree of references"
    )


def _product_key(product: ProductRef) -> _ProductKey:
    return product.product_id, product.origin
