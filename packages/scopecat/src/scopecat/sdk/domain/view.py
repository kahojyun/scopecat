"""Narrow immutable projection of authored domain calls for adapter code.

The values in this module are the complete compiler-facing inspection surface
for a domain adapter. References are assembled while projecting one
materialized plan; adapters can retain and pass them back to the prepare SDK
without importing transient compiler identities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.value_types import ValueType
from scopecat.measurements.results import MeasurementDType
from scopecat.measurements.semantics import MeasurementTransformSemanticContract

type DomainProductKind = Literal[
    "observable",
    "artifact",
    "readback",
    "expression",
]
_DOMAIN_PRODUCT_KINDS = frozenset({"observable", "artifact", "readback", "expression"})
_MEASUREMENT_DTYPES = frozenset({"float64", "int64", "complex128", "bool", "string"})


def _empty_metadata() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class DomainInputPortView:
    id: str
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class DomainResultPortView:
    id: str
    contract: object | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class DomainProgramView:
    """Dialect-owned program body plus its core-owned typed interface."""

    id: str
    dialect_id: str
    dialect_version: str
    body: object = field(repr=False)
    inputs: tuple[DomainInputPortView, ...] = ()
    results: tuple[DomainResultPortView, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainProductAxisView:
    """Immutable SDK projection of one logical product axis."""

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id or not self.kind:
            raise ValueError("domain product axis ids and kinds must be non-empty")
        if type(self.size) is not int or self.size <= 0:
            raise ValueError("domain product axis sizes must be positive integers")
        metadata = cast("object", self.metadata)
        if not isinstance(metadata, Mapping):
            raise TypeError("domain product axis metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                cast("Mapping[str, object]", metadata),
                path=f"domain product axis {self.id!r}",
            ),
        )


@dataclass(frozen=True, slots=True)
class DomainProductContractView:
    """Immutable logical product contract owned by the public adapter SDK."""

    id: str
    kind: DomainProductKind
    unit: str | None
    dtype: MeasurementDType
    axes: tuple[DomainProductAxisView, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("domain product contract ids must be non-empty")
        if self.kind not in _DOMAIN_PRODUCT_KINDS:
            raise ValueError("domain product contract kind is unsupported")
        if self.dtype not in _MEASUREMENT_DTYPES:
            raise ValueError("domain product contract dtype is unsupported")
        axes = cast("object", self.axes)
        if not isinstance(axes, tuple) or not all(
            isinstance(axis, DomainProductAxisView)
            for axis in cast("tuple[object, ...]", axes)
        ):
            raise TypeError("domain product contract axes require SDK axis views")
        metadata = cast("object", self.metadata)
        if not isinstance(metadata, Mapping):
            raise TypeError("domain product contract metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                cast("Mapping[str, object]", metadata),
                path=f"domain product {self.id!r}",
            ),
        )


class DomainPointRef(ABC):
    """SDK identity for one canonical logical point.

    References are plain immutable values scoped by their owning context, not
    security tokens or durable identities.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def ordinal(self) -> int: ...


class _DomainPointRef(DomainPointRef):
    __slots__ = ("_id", "_native", "_ordinal")

    def __init__(self, *, ref_id: str, ordinal: int, native: object) -> None:
        self._id = ref_id
        self._ordinal = ordinal
        self._native = native

    @property
    def id(self) -> str:
        return self._id

    @property
    def ordinal(self) -> int:
        return self._ordinal


class DomainProductUseRef(ABC):
    """SDK identity and logical contract for one demanded product occurrence."""

    __slots__ = ()

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def product(self) -> DomainProductContractView: ...


class _DomainProductUseRef(DomainProductUseRef):
    __slots__ = ("_id", "_native", "_product")

    def __init__(
        self,
        *,
        ref_id: str,
        product: DomainProductContractView,
        native: object,
    ) -> None:
        self._id = ref_id
        self._product = product
        self._native = native

    @property
    def id(self) -> str:
        return self._id

    @property
    def product(self) -> DomainProductContractView:
        return self._product


@dataclass(frozen=True, slots=True)
class DomainTransformInputPort:
    """One authored transform input wired to its exact consumer occurrence."""

    id: str
    product_use: DomainProductUseRef
    product: DomainProductContractView = field(repr=False)


@dataclass(frozen=True, slots=True)
class DomainTransformOutputPort:
    """One authored output product and every demanded downstream occurrence."""

    id: str
    product: DomainProductContractView = field(repr=False)
    product_uses: tuple[DomainProductUseRef, ...]


@dataclass(frozen=True, slots=True)
class DomainMeasurementTransform:
    """Projection of one authored point-local pure transform."""

    id: str
    semantic: MeasurementTransformSemanticContract
    inputs: tuple[DomainTransformInputPort, ...]
    outputs: tuple[DomainTransformOutputPort, ...]
    rate: Literal["point"] = "point"

    def input(self, name: str) -> DomainTransformInputPort:
        for port in self.inputs:
            if port.id == name:
                return port
        raise KeyError(name)

    def output(self, name: str) -> DomainTransformOutputPort:
        for port in self.outputs:
            if port.id == name:
                return port
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class DomainCallPointView:
    """Concrete named call inputs for one canonical logical point."""

    ref: DomainPointRef
    inputs: tuple[tuple[str, object], ...]

    @property
    def logical_point_id(self) -> str:
        return self.ref.id

    @property
    def logical_ordinal(self) -> int:
        return self.ref.ordinal

    def input(self, name: str) -> object:
        for input_name, value in self.inputs:
            if input_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class DomainResultBindingView:
    """One authored result and every demanded logical product occurrence."""

    id: str
    product: DomainProductContractView = field(repr=False)
    product_uses: tuple[DomainProductUseRef, ...]
    contract: object | None = field(default=None, repr=False)

    @property
    def product_id(self) -> str:
        return self.product.id

    def require_one_product_use(self) -> DomainProductUseRef:
        if len(self.product_uses) != 1:
            msg = (
                f"domain result {self.id!r} requires exactly one selected "
                "logical product occurrence"
            )
            raise ValueError(msg)
        return self.product_uses[0]


@dataclass(frozen=True, slots=True)
class DomainCallView:
    """One prepare-stage invocation without linked-plan inventory exposure."""

    id: str
    program: DomainProgramView
    points: tuple[DomainCallPointView, ...]
    results: tuple[DomainResultBindingView, ...]
    measurement_transforms: tuple[DomainMeasurementTransform, ...] = ()

    def input_values(self, name: str) -> tuple[object, ...]:
        if name not in {port.id for port in self.program.inputs}:
            raise KeyError(name)
        return tuple(point.input(name) for point in self.points)

    def result(self, name: str) -> DomainResultBindingView:
        for result in self.results:
            if result.id == name:
                return result
        raise KeyError(name)

    def measurement_transform(self, name: str) -> DomainMeasurementTransform:
        for transform in self.measurement_transforms:
            if transform.id == name:
                return transform
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class DomainBatchView:
    """All explicit domain calls for one complete point set or batch."""

    calls: tuple[DomainCallView, ...]
    points: tuple[DomainPointRef, ...] = ()
    product_uses: tuple[DomainProductUseRef, ...] = ()

    def matching_calls(
        self,
        *,
        dialect_id: str,
        dialect_version: str | None = None,
    ) -> tuple[DomainCallView, ...]:
        return tuple(
            call
            for call in self.calls
            if call.program.dialect_id == dialect_id
            and (
                dialect_version is None
                or call.program.dialect_version == dialect_version
            )
        )

    def require_one_call(
        self,
        *,
        dialect_id: str,
        dialect_version: str | None = None,
    ) -> DomainCallView:
        selected = self.matching_calls(
            dialect_id=dialect_id,
            dialect_version=dialect_version,
        )
        if len(selected) != 1:
            version = "" if dialect_version is None else f" version {dialect_version!r}"
            msg = (
                f"expected exactly one domain call for dialect {dialect_id!r}"
                f"{version}, found {len(selected)}"
            )
            raise ValueError(msg)
        return selected[0]


def domain_point_ref_internal(
    *,
    ref_id: str,
    ordinal: int,
    native: object,
) -> DomainPointRef:
    return _DomainPointRef(ref_id=ref_id, ordinal=ordinal, native=native)


def domain_product_use_ref_internal(
    *,
    ref_id: str,
    product: DomainProductContractView,
    native: object,
) -> DomainProductUseRef:
    return _DomainProductUseRef(ref_id=ref_id, product=product, native=native)


def domain_transform_input_port_internal(
    *,
    port_id: str,
    product_use: DomainProductUseRef,
    product: DomainProductContractView,
) -> DomainTransformInputPort:
    return DomainTransformInputPort(
        id=port_id,
        product_use=product_use,
        product=product,
    )


def domain_transform_output_port_internal(
    *,
    port_id: str,
    product: DomainProductContractView,
    product_uses: tuple[DomainProductUseRef, ...],
) -> DomainTransformOutputPort:
    return DomainTransformOutputPort(
        id=port_id,
        product=product,
        product_uses=product_uses,
    )


def domain_measurement_transform_internal(
    *,
    transform_id: str,
    semantic: MeasurementTransformSemanticContract,
    inputs: tuple[DomainTransformInputPort, ...],
    outputs: tuple[DomainTransformOutputPort, ...],
) -> DomainMeasurementTransform:
    return DomainMeasurementTransform(
        id=transform_id,
        semantic=semantic.model_copy(deep=True),
        inputs=inputs,
        outputs=outputs,
    )


def domain_point_native_internal(ref: DomainPointRef) -> object:
    return object.__getattribute__(ref, "_native")


def domain_product_use_native_internal(ref: DomainProductUseRef) -> object:
    return object.__getattribute__(ref, "_native")


__all__ = [
    "DomainBatchView",
    "DomainCallPointView",
    "DomainCallView",
    "DomainInputPortView",
    "DomainMeasurementTransform",
    "DomainPointRef",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductKind",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainResultBindingView",
    "DomainResultPortView",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
]
