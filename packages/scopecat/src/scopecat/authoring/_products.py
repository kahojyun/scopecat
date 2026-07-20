"""Source product declarations, hygienic references, and record selections."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, cast, override

from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
)
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.values import MetadataValue
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    parse_product_id,
    product_use,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.results import MeasurementDType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type ProductKind = Literal["observable", "artifact", "readback", "expression"]
type AxisSizeInput = ValueRef | Quantity | float | tuple[EntityRef | str, ...]
type LocalizeValueRef = Callable[[ValueRef, Mapping[str, object]], ValueRef]


@dataclass(frozen=True, slots=True, repr=False)
class ProductAxis:
    id: str
    size: AxisSizeInput
    kind: str | None = None
    unit: str | None = None
    entity_values: bool = False


@dataclass(frozen=True)
class ModuleProductDecl:
    """Declare one reusable product independently of execution and storage.

    A declaration describes only the logical product schema available at a
    module boundary. ``ModuleAcquireEffect`` decides how and when an
    instrument realizes it; ``RecordSelection`` decides whether a particular
    use becomes durable.
    Keeping the three decisions separate lets modules compose without silently
    imposing experiment-level persistence policy.
    """

    id: str
    scope: tuple[str, ...] = ()
    origin: tuple[object, ...] = field(default=(), repr=False, compare=False)
    kind: ProductKind = "observable"
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[ProductAxis, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "module product id must be non-empty"
            raise ValueError(msg)
        if any(not segment for segment in self.scope):
            msg = "module product scope segments must be non-empty"
            raise ValueError(msg)
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def product_id(self) -> ProductId:
        return ProductId(SymbolId(scope=self.scope, local_id=self.id))

    @property
    def qualified_id(self) -> str:
        return self.product_id.qualified_name


@dataclass(frozen=True, slots=True, repr=False)
class ProductRef:
    """Opaque hygienic reference to one module or module-instance product."""

    product_id: ProductId
    origin: tuple[object, ...] = field(repr=False, compare=False)

    @property
    def id(self) -> str:
        """The injective, scope-qualified identity used during linking."""

        return self.product_id.qualified_name

    @property
    def local_id(self) -> str:
        return self.product_id.local_id


@dataclass(frozen=True, slots=True, repr=False)
class ProductOutputs(Mapping[str, ProductRef]):
    """Read-only attribute and mapping view of exposed module products."""

    entries: Mapping[str, ProductRef]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", FrozenMapping(self.entries.items()))

    @override
    def __getitem__(self, product_id: str) -> ProductRef:
        return self.entries[product_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    @override
    def __len__(self) -> int:
        return len(self.entries)

    def __getattr__(self, product_id: str) -> ProductRef:
        try:
            return self.entries[product_id]
        except KeyError:
            msg = f"module instance has no product {product_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self.entries))


@dataclass(frozen=True, slots=True, repr=False)
class RecordSelection:
    """Select one hygienic product use for durable experiment output.

    The selection belongs to a template or scratch experiment, not to the
    reusable module that declared and acquired the product.
    """

    product_use: ProductUse
    product_origin: tuple[object, ...] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    record_id: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if self.record_id is not None and not self.record_id:
            msg = "record id must be non-empty when provided"
            raise ValueError(msg)
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def product_id(self) -> ProductId:
        return self.product_use.product_id


def product_axis(
    id: str,  # noqa: A002
    *,
    size: ValueRef | Quantity | float | Sequence[EntityRef | str],
    kind: str | None = None,
    unit: str | None = None,
) -> ProductAxis:
    selected_size = size if isinstance(size, ValueRef) else freeze_runtime_input(size)
    return ProductAxis(
        id=id,
        size=cast("AxisSizeInput", selected_size),
        kind=kind,
        unit=unit,
    )


def entity_axis(
    id: str,  # noqa: A002
    entities: ValueRef | Sequence[EntityRef | str],
) -> ProductAxis:
    selected_entities = (
        entities if isinstance(entities, ValueRef) else freeze_runtime_input(entities)
    )
    return ProductAxis(
        id=id,
        size=cast("AxisSizeInput", selected_entities),
        kind="entity",
        unit=None,
        entity_values=True,
    )


def shot_axis(
    size: ValueRef | Quantity | float,
) -> ProductAxis:
    return product_axis("shot", size=size, kind="shot", unit="count")


def record_product(
    product_id: str | ProductRef,
    *,
    record_id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    selected_product_id = (
        product_id.product_id
        if isinstance(product_id, ProductRef)
        else parse_product_id(product_id)
    )
    selected_product_origin = (
        product_id.origin if isinstance(product_id, ProductRef) else None
    )
    return RecordSelection(
        product_use=product_use(selected_product_id),
        product_origin=selected_product_origin,
        record_id=record_id,
        metadata=freeze_json_mapping(metadata or {}),
    )


def record_alias(
    selection: RecordSelection,
    *,
    record_id: str,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    """Add another durable projection without creating another product use."""

    if not record_id:
        msg = "record alias id must be non-empty"
        raise ValueError(msg)
    return RecordSelection(
        product_use=selection.product_use,
        product_origin=selection.product_origin,
        record_id=record_id,
        metadata=freeze_json_mapping(metadata or {}),
    )


def prefix_product_decl(
    product: ModuleProductDecl,
    *scope: str,
    origin: tuple[object, ...] = (),
) -> ModuleProductDecl:
    """Prefix a product identity while preserving its schema."""

    if not scope and not origin:
        return product
    return replace(
        product,
        scope=(*scope, *product.scope),
        origin=(*origin, *product.origin),
    )


def localize_product_input_refs(
    product: ModuleProductDecl,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> ModuleProductDecl:
    return replace(
        product,
        axes=tuple(
            _localize_product_axis_input_refs(
                axis,
                inputs,
                localize_value_ref=localize_value_ref,
            )
            for axis in product.axes
        ),
    )


def _localize_product_axis_input_refs(
    axis: ProductAxis,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> ProductAxis:
    if isinstance(axis.size, ValueRef):
        localized = localize_value_ref(axis.size, inputs)
        return replace(axis, size=localized)
    return axis
