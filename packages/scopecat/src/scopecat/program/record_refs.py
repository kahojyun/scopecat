"""Typed authoring identities for durable measurement variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from scopecat.program.measurement_types import (
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
    entity_axis_id: str | None = None
    entity_axis_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("record reference id must be non-empty")
        if not self.dims or self.dims[0] != "point":
            raise ValueError("record reference dimensions must begin with point")
        if (self.entity_axis_id is None) != (self.entity_axis_fingerprint is None):
            raise ValueError(
                "entity record references require an axis id and fingerprint"
            )


__all__ = ["RecordRef"]
