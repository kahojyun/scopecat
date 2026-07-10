"""Source-only record handles, intents, factories, and composition helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from scopecat._frozen import freeze_json_mapping
from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_source_kind,
)
from scopecat.authoring.values import MetadataValue
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementDType

type RecordKind = Literal["observable", "artifact", "readback", "expression"]
type RecordSource = Literal["instrument", "state", "point", "expression", "runtime"]
type AxisSizeInput = ValueRef | Quantity | float | tuple[EntityRef | str, ...]
type LocalizeValueRef = Callable[[ValueRef, Mapping[str, object]], ValueRef]


@dataclass(frozen=True, slots=True, init=False, repr=False)
class RecordAxis:
    """Opaque public handle describing one measurement record axis."""

    def __init__(self) -> None:
        msg = "RecordAxis is an opaque handle; create axes with record axis factories"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, repr=False)
class RecordAxisIntent(RecordAxis):
    id: str
    size: AxisSizeInput
    kind: str | None = None
    unit: str | None = None
    entity_values: bool = False


@dataclass(frozen=True)
class RecordIntent:
    id: str
    kind: RecordKind = "observable"
    source: RecordSource = "instrument"
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxisIntent, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True)
class ModuleProductPort:
    id: str
    kind: RecordKind = "observable"
    source: RecordSource = "instrument"
    resource: str | None = None
    capability: str | None = None
    product_key: str | None = None
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[RecordAxisIntent, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True, slots=True, init=False, repr=False)
class RecordSelection:
    """Opaque public handle selecting a module product for recording."""

    def __init__(self) -> None:
        msg = (
            "RecordSelection is an opaque handle; create selections with record_product"
        )
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, repr=False)
class ProductSelectionIntent(RecordSelection):
    product_id: str
    record_id: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


def record_axis(
    id: str,  # noqa: A002
    *,
    size: ValueRef | Quantity | float | Sequence[EntityRef | str],
    kind: str | None = None,
    unit: str | None = None,
) -> RecordAxis:
    selected_size = size if isinstance(size, ValueRef) else freeze_runtime_input(size)
    return RecordAxisIntent(
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
    return RecordAxisIntent(
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
    source: RecordSource = "instrument",
    unit: str | None = "ratio",
    resource: str | None = None,
    capability: str | None = None,
    product_key: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[RecordAxis] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordIntent:
    return RecordIntent(
        id=id,
        kind="observable",
        source=source,
        resource=resource,
        capability=capability,
        product_key=product_key,
        unit=unit,
        dtype=dtype,
        axes=record_axis_intents(axes),
        metadata=freeze_json_mapping(metadata or {}),
    )


def record_product(
    product_id: str,
    *,
    record_id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    return ProductSelectionIntent(
        product_id=product_id,
        record_id=record_id,
        metadata=freeze_json_mapping(metadata or {}),
    )


def record_axis_intents(
    axes: Sequence[RecordAxis],
) -> tuple[RecordAxisIntent, ...]:
    """Validate and unwrap public record-axis handles for internal models."""

    invalid = [axis for axis in axes if not isinstance(axis, RecordAxisIntent)]
    if invalid:
        msg = "record axes must be created with record axis factories"
        raise TypeError(msg)
    return cast("tuple[RecordAxisIntent, ...]", tuple(axes))


def product_selection_intent(selection: RecordSelection) -> ProductSelectionIntent:
    """Validate and unwrap one public product-selection handle."""

    if not isinstance(selection, ProductSelectionIntent):
        msg = "record selections must be created with record_product"
        raise TypeError(msg)
    return selection


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
    axis: RecordAxisIntent,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> RecordAxisIntent:
    if isinstance(axis.size, ValueRef):
        localized = localize_value_ref(axis.size, inputs)
        if internal_value_ref_source_kind(localized) == "compute":
            msg = "record axis cannot depend on a point-local compute result"
            raise TypeError(msg)
        return replace(axis, size=localized)
    return axis


__all__ = [
    "AxisSizeInput",
    "ModuleProductPort",
    "ProductSelectionIntent",
    "RecordAxis",
    "RecordAxisIntent",
    "RecordIntent",
    "RecordKind",
    "RecordSelection",
    "RecordSource",
    "entity_axis",
    "localize_product_input_refs",
    "localize_record_input_refs",
    "observable",
    "product_selection_intent",
    "record_axis",
    "record_axis_intents",
    "record_product",
    "shot_axis",
]
