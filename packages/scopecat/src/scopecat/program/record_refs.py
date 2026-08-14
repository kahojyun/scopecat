"""Typed authoring identities for durable measurement variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from scopecat.program.measurement_types import (
    EntityAcquisitionSemantics,
    MeasurementDType,
    MeasurementVariableRole,
    NativeMeasurementValue,
)

_RecordT_co = TypeVar(
    "_RecordT_co",
    bound=NativeMeasurementValue,
    covariant=True,
    default=NativeMeasurementValue,
)


@dataclass(frozen=True, slots=True, repr=False)
class RecordRef(Generic[_RecordT_co]):
    """Typed identity and schema promise for one durable dataset variable."""

    id: str
    dtype: MeasurementDType
    unit: str | None
    dims: tuple[str, ...]
    role: MeasurementVariableRole = "observable"
    source_product_id: str | None = None
    source_product_ids: tuple[str, ...] | None = None
    entity_axis_id: str | None = None
    entity_acquisition: EntityAcquisitionSemantics | None = None
    source_value_id: str | None = None
    recording_group_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("record reference id must be non-empty")
        if not self.dims or self.dims[0] != "point":
            raise ValueError("record reference dimensions must begin with point")
        sources = (
            self.source_product_id,
            self.source_product_ids,
            self.source_value_id,
        )
        if sum(source is not None for source in sources) != 1:
            raise ValueError(
                "record references require exactly one source product or value"
            )
        if (self.source_product_ids is None) != (self.entity_axis_id is None):
            raise ValueError(
                "entity record references require product ids and an entity axis"
            )
        if self.source_product_ids is not None and not self.source_product_ids:
            raise ValueError("entity record references require product sources")
        if (self.source_product_ids is None) != (self.entity_acquisition is None):
            raise ValueError(
                "entity record references require product sources and "
                "acquisition semantics"
            )
        if self.recording_group_id is not None and not self.recording_group_id:
            raise ValueError("record reference group id must be non-empty")


__all__ = ["RecordRef"]
