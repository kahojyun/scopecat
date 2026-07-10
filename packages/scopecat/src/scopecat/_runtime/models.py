"""Transient values shared by runtime graph construction and execution.

The classes in this module are internal conveniences, not durable run records.
Their Pydantic validation is used at subsystem boundaries but their serialized
shape is not a compatibility contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scopecat._planning.records import RecordAxisPlan, RecordKind
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.state import StateValue
from scopecat.results import MeasurementDType


class ProductBinding(BaseModel):
    """Runtime mapping from a device-local product to a logical record."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    record_id: str
    instrument_id: str | None = None
    product_key: str
    kind: RecordKind
    capability: str | None = None
    unit: str | None = None
    dtype: MeasurementDType
    axes: list[RecordAxisPlan] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PointRouteBinding(BaseModel):
    """Concrete route selected for one point program."""

    model_config = ConfigDict(extra="forbid")

    port_id: str
    resource_id: str
    capabilities: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    product_axis_order: list[str] = Field(default_factory=list)
    channel_bindings: list[RoutingChannelBinding] = Field(default_factory=list)


class ProgramStateField(BaseModel):
    """One resolved field in a point-local desired-state program."""

    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: StateValue
    channel_bindings: list[RoutingChannelBinding] = Field(default_factory=list)


class ProgramResourceState(BaseModel):
    """Desired fields for one resolved resource capability."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    fields: list[ProgramStateField] = Field(default_factory=list)


class CollectInstructionPlan(BaseModel):
    """Runtime collection request for one point and logical instrument."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    instrument_id: str | None = None
    products: list[ProductBinding] = Field(default_factory=list)


__all__ = [
    "CollectInstructionPlan",
    "PointRouteBinding",
    "ProductBinding",
    "ProgramResourceState",
    "ProgramStateField",
]
