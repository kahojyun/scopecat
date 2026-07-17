"""Source-only record handles, intents, factories, and composition helpers."""

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
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.results import MeasurementDType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type RecordKind = Literal["observable", "artifact", "readback", "expression"]
type AxisSizeInput = ValueRef | Quantity | float | tuple[EntityRef | str, ...]
type LocalizeValueRef = Callable[[ValueRef, Mapping[str, object]], ValueRef]


@dataclass(frozen=True, slots=True, repr=False)
class RecordAxis:
    id: str
    size: AxisSizeInput
    kind: str | None = None
    unit: str | None = None
    entity_values: bool = False


@dataclass(frozen=True)
class RecordIntent:
    id: str
    kind: RecordKind = "observable"
    resource_port_id: LogicalResourcePortId | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxis, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)
    producer_metadata: Mapping[str, MetadataValue] = field(
        default_factory=empty_frozen_mapping
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))
        object.__setattr__(
            self,
            "producer_metadata",
            freeze_json_mapping(self.producer_metadata),
        )


@dataclass(frozen=True)
class ModuleProductPort:
    id: str
    scope: tuple[str, ...] = ()
    origin: tuple[object, ...] = field(default=(), repr=False, compare=False)
    kind: RecordKind = "observable"
    resource_port_id: LogicalResourcePortId | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxis, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)
    producer_metadata: Mapping[str, MetadataValue] = field(
        default_factory=empty_frozen_mapping
    )

    def __post_init__(self) -> None:
        if not self.id:
            msg = "module product id must be non-empty"
            raise ValueError(msg)
        if any(not segment for segment in self.scope):
            msg = "module product scope segments must be non-empty"
            raise ValueError(msg)
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))
        object.__setattr__(
            self,
            "producer_metadata",
            freeze_json_mapping(self.producer_metadata),
        )

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


def record_axis(
    id: str,  # noqa: A002
    *,
    size: ValueRef | Quantity | float | Sequence[EntityRef | str],
    kind: str | None = None,
    unit: str | None = None,
) -> RecordAxis:
    selected_size = size if isinstance(size, ValueRef) else freeze_runtime_input(size)
    return RecordAxis(
        id=id,
        size=cast("AxisSizeInput", selected_size),
        kind=kind,
        unit=unit,
    )


def entity_axis(
    id: str,  # noqa: A002
    entities: ValueRef | Sequence[EntityRef | str],
) -> RecordAxis:
    selected_entities = (
        entities if isinstance(entities, ValueRef) else freeze_runtime_input(entities)
    )
    return RecordAxis(
        id=id,
        size=cast("AxisSizeInput", selected_entities),
        kind="entity",
        unit=None,
        entity_values=True,
    )


def shot_axis(
    size: ValueRef | Quantity | float,
) -> RecordAxis:
    return record_axis("shot", size=size, kind="shot", unit="count")


def observable(
    id: str,  # noqa: A002
    *,
    unit: str | None = "ratio",
    resource: str | None = None,
    capability: str | None = None,
    product_key: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[RecordAxis] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
    producer_metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordIntent:
    return RecordIntent(
        id=id,
        kind="observable",
        resource_port_id=(
            logical_resource_port_id(resource) if resource is not None else None
        ),
        capability=capability,
        product_key=product_key,
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=freeze_json_mapping(metadata or {}),
        producer_metadata=freeze_json_mapping(producer_metadata or {}),
    )


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


def prefix_product_port(
    product: ModuleProductPort,
    *scope: str,
    origin: tuple[object, ...] = (),
) -> ModuleProductPort:
    """Prefix a product identity while preserving its local instrument intent."""

    if not scope and not origin:
        return product
    return replace(
        product,
        scope=(*scope, *product.scope),
        origin=(*origin, *product.origin),
    )


def localize_record_input_refs(
    record: RecordIntent,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> RecordIntent:
    return replace(
        record,
        axes=tuple(
            _localize_record_axis_input_refs(
                axis,
                inputs,
                localize_value_ref=localize_value_ref,
            )
            for axis in record.axes
        ),
    )


def localize_product_input_refs(
    product: ModuleProductPort,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> ModuleProductPort:
    return replace(
        product,
        axes=tuple(
            _localize_record_axis_input_refs(
                axis,
                inputs,
                localize_value_ref=localize_value_ref,
            )
            for axis in product.axes
        ),
    )


def _localize_record_axis_input_refs(
    axis: RecordAxis,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> RecordAxis:
    if isinstance(axis.size, ValueRef):
        localized = localize_value_ref(axis.size, inputs)
        return replace(axis, size=localized)
    return axis
