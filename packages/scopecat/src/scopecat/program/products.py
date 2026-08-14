"""Product declarations, hygienic references, and record selections."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Generic, Protocol, TypeVar, cast, override

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    parse_product_id,
    product_use,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Scalar
from scopecat.program.input_capture import capture_runtime_input, empty_program_mapping
from scopecat.program.measurement_types import (
    MeasurementDType,
    MeasurementVariableRole,
    NativeMeasurementScalar,
    NativeMeasurementValue,
)
from scopecat.program.record_refs import RecordRef
from scopecat.program.value_refs import (
    ValueRef,
)
from scopecat.program.values import MetadataValue

# ProductRef provenance is private to the recorder implementation in this module.
# pyright: reportPrivateUsage=false

type AxisSizeInput = (
    ValueRef | Quantity | int | float | tuple[EntityRef | str, ...] | None
)
type LocalizeValueRef = Callable[[ValueRef, Mapping[str, object]], ValueRef]
type ProductNativeScalar = NativeMeasurementScalar
type ProductNativeValue = NativeMeasurementValue
_ProductT_co = TypeVar(
    "_ProductT_co",
    bound=ProductNativeValue,
    covariant=True,
    default=ProductNativeValue,
)


@dataclass(frozen=True, slots=True)
class ProductRecording:
    """Acquisition-result provenance and its default dataset role."""

    occurrence: SymbolId
    result_id: str
    role: MeasurementVariableRole = "observable"

    def __post_init__(self) -> None:
        if not self.result_id:
            msg = "recording result id must be non-empty"
            raise ValueError(msg)

    def prefixed(self, *scope: str) -> ProductRecording:
        if not scope:
            return self
        return replace(self, occurrence=self.occurrence.prefixed(*scope))


@dataclass(frozen=True, slots=True, repr=False)
class ProductAxis:
    id: str
    size: AxisSizeInput
    kind: str | None = None
    unit: str | None = None
    entity_values: bool = False
    shared_as: str | None = None

    def __post_init__(self) -> None:
        if self.shared_as is not None and not self.shared_as:
            msg = "shared product axis identity must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ProductValueSpec(Generic[_ProductT_co]):
    """Runtime value schema attached to one typed logical product handle.

    ``T`` is the available native value at one logical point. It is a scalar
    for scalar products and an array for products with local axes. Units stay
    in the runtime schema rather than becoming static literal types.
    """

    dtype: MeasurementDType = "float64"
    unit: str | None = None
    axes: tuple[ProductAxis, ...] = ()


class _ProductExport[ValueT: ProductNativeValue](Protocol):
    @property
    def symbol_id(self) -> ProductId: ...

    @property
    def target_origin(self) -> tuple[object, ...]: ...

    @property
    def value_spec(self) -> ProductValueSpec[ValueT]: ...

    @property
    def recording(self) -> ProductRecording | None: ...


@dataclass(frozen=True)
class ModuleProductDecl(Generic[_ProductT_co]):
    """Declare one reusable product independently of execution and storage.

    A declaration describes only the logical product schema available at a
    module boundary. ``ModuleAcquireEffect`` decides how and when an
    instrument realizes it; ``RecordSelection`` decides whether a particular
    use becomes durable.
    ``recording`` may retain typed acquisition-result provenance, but it does
    not itself select the product for persistence.
    Keeping the three decisions separate lets modules compose without silently
    imposing experiment-level persistence policy.
    """

    id: str
    value_spec: ProductValueSpec[_ProductT_co]
    scope: tuple[str, ...] = ()
    origin: tuple[object, ...] = field(default=(), repr=False, compare=False)
    recording: ProductRecording | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_program_mapping)

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

    @property
    def dtype(self) -> MeasurementDType:
        """Convenient access to the canonical product value schema."""

        return self.value_spec.dtype

    @property
    def unit(self) -> str | None:
        """Convenient access to the canonical product value schema."""

        return self.value_spec.unit

    @property
    def axes(self) -> tuple[ProductAxis, ...]:
        """Convenient access to the canonical product value schema."""

        return self.value_spec.axes


@dataclass(frozen=True, slots=True, repr=False)
class ProductRef(Generic[_ProductT_co]):
    """Opaque hygienic reference to one module or module-instance product."""

    product_id: ProductId
    origin: tuple[object, ...] = field(repr=False, compare=False)
    _value_spec: ProductValueSpec[_ProductT_co] = field(repr=False)
    _recording: ProductRecording | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @staticmethod
    def from_declaration[ValueT: ProductNativeValue](
        product: ModuleProductDecl[ValueT],
    ) -> ProductRef[ValueT]:
        """Create a handle without restating any declaration schema."""

        return ProductRef(
            product_id=product.product_id,
            origin=product.origin,
            _value_spec=product.value_spec,
            _recording=product.recording,
        )

    @staticmethod
    def from_export[ValueT: ProductNativeValue](
        product: _ProductExport[ValueT],
    ) -> ProductRef[ValueT]:
        """Create a handle without restating any projected export schema."""

        return ProductRef(
            product_id=product.symbol_id,
            origin=product.target_origin,
            _value_spec=product.value_spec,
            _recording=product.recording,
        )

    @property
    def value_spec(self) -> ProductValueSpec[_ProductT_co]:
        return self._value_spec

    @property
    def id(self) -> str:
        """The injective, scope-qualified identity used during binding."""

        return self.product_id.qualified_name

    @property
    def local_id(self) -> str:
        return self.product_id.local_id

    @property
    def _recording_role(self) -> MeasurementVariableRole:
        """Return generated acquisition semantics for experiment recording."""

        return "observable" if self._recording is None else self._recording.role


def record_ref_from_product[ValueT: ProductNativeValue](
    product: ProductRef[ValueT],
    selection: RecordSelection,
) -> RecordRef[ValueT]:
    """Project one authored product selection into its typed dataset handle."""

    record_id = selection.record_id
    if record_id is None:
        raise AssertionError("product record selections require a resolved id")
    return RecordRef(
        id=record_id,
        dtype=product.value_spec.dtype,
        unit=product.value_spec.unit,
        dims=(
            "point",
            *(
                _product_axis_dimension_id(product.product_id, axis)
                for axis in product.value_spec.axes
            ),
        ),
        role=selection.role,
        source_product_id=product.id,
        recording_group_id=selection.recording_group_id,
    )


@dataclass(frozen=True, slots=True, repr=False)
class ProductRefs(Mapping[str, ProductRef]):
    """Read-only attribute and mapping view of occurrence-owned products."""

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
            msg = f"occurrence has no product {product_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self.entries))


@dataclass(frozen=True, slots=True, repr=False)
class RecordSelection:
    """Select one hygienic product use for durable experiment output.

    The selection belongs to an experiment, not to the
    reusable module that declared and acquired the product.
    """

    product_use: ProductUse
    product_origin: tuple[object, ...] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    record_id: str | None = None
    role: MeasurementVariableRole = "observable"
    recording_group_id: str | None = None
    entity: EntityRef | None = None
    entity_axis_id: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_program_mapping)

    def __post_init__(self) -> None:
        if self.record_id is not None and not self.record_id:
            msg = "record id must be non-empty when provided"
            raise ValueError(msg)
        if self.recording_group_id is not None and not self.recording_group_id:
            msg = "recording group id must be non-empty when provided"
            raise ValueError(msg)
        if (self.entity is None) != (self.entity_axis_id is None):
            raise ValueError(
                "entity record selections require both entity and entity_axis_id"
            )
        if self.entity_axis_id is not None and not self.entity_axis_id:
            raise ValueError("entity record axis id must be non-empty")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def product_id(self) -> ProductId:
        return self.product_use.product_id


def product_axis(
    id: str,
    *,
    size: ValueRef | Quantity | float | Sequence[EntityRef | str] | None,
    kind: str | None = None,
    unit: str | None = None,
    shared_as: str | None = None,
) -> ProductAxis:
    selected_size = _axis_value(size)
    return ProductAxis(
        id=id,
        size=cast("AxisSizeInput", selected_size),
        kind=kind,
        unit=unit,
        shared_as=shared_as,
    )


def entity_axis(
    id: str,
    entities: ValueRef | Sequence[EntityRef | str],
    *,
    shared_as: str | None = None,
) -> ProductAxis:
    selected_entities = _axis_value(entities)
    return ProductAxis(
        id=id,
        size=cast("AxisSizeInput", selected_entities),
        kind="entity",
        unit=None,
        entity_values=True,
        shared_as=shared_as,
    )


def _axis_value(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, ValueRef):
        return capture_runtime_input(value)
    if not isinstance(value.value_type, Scalar):
        raise TypeError("product and entity axis values must be scalar")
    return value


def shot_axis(
    size: ValueRef | Quantity | float,
    *,
    shared_as: str | None = None,
) -> ProductAxis:
    return product_axis(
        "shot",
        size=size,
        kind="shot",
        unit="count",
        shared_as=shared_as,
    )


def product_axis_dimension_id(
    product: ModuleProductDecl,
    axis: ProductAxis,
) -> str:
    """Keep product-owned and explicitly shared dimensions disjoint."""

    return _product_axis_dimension_id(product.product_id, axis)


def _product_axis_dimension_id(
    product_id: ProductId,
    axis: ProductAxis,
) -> str:

    if axis.shared_as is not None:
        return SymbolId(
            scope=("shared", *product_id.scope),
            local_id=axis.shared_as,
        ).qualified_name
    return SymbolId(
        scope=("product", *product_id.scope, product_id.local_id),
        local_id=axis.id,
    ).qualified_name


def record_product(
    product_id: str | ProductRef,
    *,
    record_id: str | None = None,
    recording_group_id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    """Select an observable product for durable experiment output."""

    return _record_selection(
        product_id,
        role="observable",
        record_id=record_id,
        recording_group_id=recording_group_id,
        metadata=metadata,
    )


def record_coordinate(
    product_id: str | ProductRef,
    *,
    record_id: str | None = None,
    recording_group_id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    """Select a product as a coordinate for durable experiment output."""

    return _record_selection(
        product_id,
        role="coordinate",
        record_id=record_id,
        recording_group_id=recording_group_id,
        metadata=metadata,
    )


def _record_selection(
    product_id: str | ProductRef,
    *,
    role: MeasurementVariableRole,
    record_id: str | None,
    recording_group_id: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> RecordSelection:
    """Build one selection while preserving hygienic product identity."""

    selected_product_id = (
        product_id.product_id
        if isinstance(product_id, ProductRef)
        else parse_product_id(product_id)
    )
    selected_product_origin = (
        product_id.origin if isinstance(product_id, ProductRef) else None
    )
    selected_recording_group_id = recording_group_id
    if (
        selected_recording_group_id is None
        and isinstance(product_id, ProductRef)
        and product_id._recording is not None
    ):
        selected_recording_group_id = product_id._recording.occurrence.qualified_name
    return RecordSelection(
        product_use=product_use(selected_product_id),
        product_origin=selected_product_origin,
        record_id=(
            record_id if record_id is not None else selected_product_id.qualified_name
        ),
        role=role,
        recording_group_id=selected_recording_group_id,
        metadata=freeze_json_mapping(metadata or {}),
    )


def record_alias(
    selection: RecordSelection,
    *,
    record_id: str,
    role: MeasurementVariableRole | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> RecordSelection:
    """Add an ungrouped projection without creating another product use.

    The alias intentionally does not join the source selection's recording
    group, where a duplicate coordinate or observable would make trace
    selection ambiguous.
    """

    if not record_id:
        msg = "record alias id must be non-empty"
        raise ValueError(msg)
    return RecordSelection(
        product_use=selection.product_use,
        product_origin=selection.product_origin,
        record_id=record_id,
        role=selection.role if role is None else role,
        recording_group_id=None,
        entity=selection.entity,
        entity_axis_id=selection.entity_axis_id,
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
        recording=(
            None if product.recording is None else product.recording.prefixed(*scope)
        ),
    )


def localize_product_input_refs(
    product: ModuleProductDecl,
    inputs: Mapping[str, object],
    *,
    localize_value_ref: LocalizeValueRef,
) -> ModuleProductDecl:
    return replace(
        product,
        value_spec=replace(
            product.value_spec,
            axes=tuple(
                _localize_product_axis_input_refs(
                    axis,
                    inputs,
                    localize_value_ref=localize_value_ref,
                )
                for axis in product.axes
            ),
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
