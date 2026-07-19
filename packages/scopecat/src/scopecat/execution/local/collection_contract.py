"""Closed local collection addresses retained by a RunProgram."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.measurements.values import MeasurementValueSelection


@dataclass(frozen=True, slots=True)
class LocalCollectionOutputBinding:
    provider_key: str
    product_use_id: ProductUseId
    product_id: ProductId


@dataclass(frozen=True, slots=True)
class LocalCollectionOperationBinding:
    logical_point_id: LogicalPointId
    point_index: int
    operation_id: str
    attempt: int
    instrument_id: str
    command_content_hash: str
    outputs: tuple[LocalCollectionOutputBinding, ...]


@dataclass(frozen=True, slots=True)
class BoundLocalCollectionValues:
    """Trusted provider-address to logical-product mapping."""

    selection: MeasurementValueSelection = field(repr=False)
    experiment_id: str
    collection_product_use_ids: tuple[ProductUseId, ...]
    operation_bindings: tuple[LocalCollectionOperationBinding, ...] = field(repr=False)
