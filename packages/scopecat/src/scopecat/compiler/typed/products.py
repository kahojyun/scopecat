"""Logical product declarations retained before target realization selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from scopecat.compiler.semantic.model import MeasurementTransformId
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import ProductId, ProductProducerId
from scopecat.kernel.resource_identity import ResourceTarget
from scopecat.measurements.results import MeasurementDType

type ProductKind = Literal["observable", "artifact", "readback", "expression"]


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class ProductAxisDef:
    """One axis in a logical product's output schema."""

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id or not self.kind or self.size <= 0:
            msg = "product axes require non-empty ids and kinds and positive sizes"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata, path=f"product axis {self.id!r} metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductDef:
    """Available logical product independent of recording and target realization."""

    id: ProductId
    kind: ProductKind = "observable"
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[ProductAxisDef, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(self.metadata, path=f"product {self.id!s} metadata"),
        )


@dataclass(frozen=True, slots=True)
class InstrumentProductProducer:
    """One instrument edge that can realize a logical product locally."""

    id: ProductProducerId
    product_id: ProductId
    provider_key: str
    resource_target: ResourceTarget | None = None
    capability: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.provider_key:
            msg = "instrument product producer provider_key must be non-empty"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"product producer {self.id!s} metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class DomainProductProducer:
    """One domain-execution result that realizes a logical product."""

    id: ProductProducerId
    product_id: ProductId
    result_id: str

    def __post_init__(self) -> None:
        if not self.result_id:
            msg = "domain product producer result_id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementTransformProductProducer:
    """One pure authored transform output that realizes a logical product."""

    id: ProductProducerId
    product_id: ProductId
    transform_id: MeasurementTransformId
    output_id: str

    def __post_init__(self) -> None:
        if not self.output_id:
            msg = "measurement transform producer output_id must be non-empty"
            raise ValueError(msg)
