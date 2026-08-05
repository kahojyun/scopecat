"""Typed authoring identities for durable measurement variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from scopecat.measurements.value_spec import (
    MeasurementDType,
    MeasurementVariableRole,
    NativeMeasurementValue,
)

_RecordT_co = TypeVar(
    "_RecordT_co",
    covariant=True,
    default=NativeMeasurementValue,
)


@dataclass(frozen=True, slots=True, repr=False)
class RecordRef(Generic[_RecordT_co]):
    """Typed identity and schema promise for one durable dataset variable."""

    variable_id: str
    dtype: MeasurementDType
    unit: str | None
    dims: tuple[str, ...]
    role: MeasurementVariableRole = "observable"
    source_product_id: str | None = None
    source_value_id: str | None = None
    recording_group_id: str | None = None

    def __post_init__(self) -> None:
        if not self.variable_id:
            raise ValueError("record reference id must be non-empty")
        if not self.dims or self.dims[0] != "point":
            raise ValueError("record reference dimensions must begin with point")
        sources = (self.source_product_id, self.source_value_id)
        if sum(source is not None for source in sources) != 1:
            raise ValueError(
                "record references require exactly one source product or value"
            )
        if self.recording_group_id is not None and not self.recording_group_id:
            raise ValueError("record reference group id must be non-empty")

    @property
    def id(self) -> str:
        return self.variable_id


__all__ = ["RecordRef"]
