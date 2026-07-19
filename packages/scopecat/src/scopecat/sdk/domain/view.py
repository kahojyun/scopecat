"""Narrow immutable projection of authored domain execution for adapters.

The values in this module are the complete compiler-facing inspection surface
for a domain adapter. References are assembled while projecting one
materialized plan; adapters can retain and pass them back to the prepare SDK
without importing transient compiler identities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

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
        if self.size <= 0:
            raise ValueError("domain product axis sizes must be positive integers")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
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
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"domain product {self.id!r}",
            ),
        )


@dataclass(frozen=True, slots=True, eq=False)
class DomainPointRef:
    """SDK identity for one canonical logical point.

    References are plain immutable values scoped by their owning context, not
    security tokens or durable identities.
    """

    id: str
    ordinal: int
    native: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, eq=False)
class DomainProductUseRef:
    """SDK identity and logical contract for one demanded product occurrence."""

    id: str
    product: DomainProductContractView
    native: object = field(repr=False, compare=False)


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
class DomainExecutionPointView:
    """Concrete domain inputs for one canonical logical point."""

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
    """Symbolic typed domain call exposed during pure target compilation."""

    id: str
    program: DomainProgramView
    results: tuple[DomainResultBindingView, ...]
    measurement_transforms: tuple[DomainMeasurementTransform, ...] = ()
    product_uses: tuple[DomainProductUseRef, ...] = ()

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
class DomainExecutionView:
    """Concrete residual bindings for one compiled domain job."""

    id: str
    program: DomainProgramView
    points: tuple[DomainExecutionPointView, ...]
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
