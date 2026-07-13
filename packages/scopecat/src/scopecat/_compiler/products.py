"""Logical product declarations retained before target realization selection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat._product_identity import ProductId, ProductProducerId
from scopecat._resource_identity import ResourceTarget
from scopecat.results import MeasurementDType

type ProductKind = Literal["observable", "artifact", "readback", "expression"]


class ProductAxisDef(BaseModel):
    """One axis in a logical product's output schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    size: int = Field(gt=0)
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductDef(BaseModel):
    """Available logical product independent of recording and target realization."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: ProductId
    kind: ProductKind = "observable"
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[ProductAxisDef, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentProductProducer(BaseModel):
    """One instrument edge that can realize a logical product locally."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: ProductProducerId
    product_id: ProductId
    resource_target: ResourceTarget | None = None
    capability: str | None = None
    provider_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "InstrumentProductProducer",
    "ProductAxisDef",
    "ProductDef",
    "ProductKind",
]
