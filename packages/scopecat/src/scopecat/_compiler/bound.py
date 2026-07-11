"""Config-bound experiment plan shared by preview and execution lowering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ResourceRouteIntent
from scopecat._relations import ParameterRelationData, Row
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.state import StateValue
from scopecat.results import (
    CoordinateValue,
    MeasurementDatasetSchema,
    MeasurementDType,
)
from scopecat.value_types import ValueType


def _empty_dependencies() -> dict[str, tuple[str, ...]]:
    return {}


def _empty_metadata() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundValue:
    """A concrete compute input resolved from config and one point."""

    value: object


@dataclass(frozen=True, slots=True)
class BoundComputeOutput:
    """Reference to an earlier topologically ordered compute call."""

    producer: NodeId


type BoundComputeInput = BoundValue | BoundComputeOutput


@dataclass(frozen=True, slots=True)
class BoundComputeCall:
    node_id: NodeId
    fn: Callable[..., object]
    inputs: Mapping[str, BoundComputeInput]
    output_type: ValueType
    cache_key: str
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_id: str | None = None
    payload_schema_id: str | None = None

    def __post_init__(self) -> None:
        if (self.payload_id is None) != (self.payload_schema_id is None):
            msg = "compute payload id and schema must be present together"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BoundRoute:
    port_id: str
    resource_id: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundStateField:
    field_path: str
    value: StateValue
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundResourceState:
    resource_id: str
    capability_id: str
    fields: tuple[BoundStateField, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundAxis:
    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class BoundRecord:
    id: str
    kind: str
    source: str
    resource: str | None
    capability: str | None
    product_key: str | None
    unit: str | None
    dtype: MeasurementDType
    axes: tuple[BoundAxis, ...]
    dims: tuple[str, ...]
    shape: tuple[int, ...]
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class BoundProduct:
    record_id: str
    instrument_id: str | None
    product_key: str
    kind: str
    capability: str | None
    unit: str | None
    dtype: MeasurementDType
    axes: tuple[BoundAxis, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class BoundCollect:
    instrument_id: str | None
    products: tuple[BoundProduct, ...]


@dataclass(frozen=True, slots=True)
class PlannedStateChange:
    point_index: int
    resource: str
    field: str
    before: object
    after: object


@dataclass(frozen=True, slots=True)
class BoundPoint:
    point_index: int
    point_key: str
    point_uid: str
    occurrence: int
    row: Row
    parameters: ParameterRelationData
    coordinates: Mapping[str, CoordinateValue]
    compute: tuple[BoundComputeCall, ...]
    routes: tuple[BoundRoute, ...]
    desired_state: tuple[BoundResourceState, ...]
    collect: tuple[BoundCollect, ...]


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """Complete target-neutral plan for one accepted config snapshot."""

    experiment_id: str
    experiment_kind: str
    point_coordinate_ids: tuple[str, ...]
    points: tuple[BoundPoint, ...]
    records: tuple[BoundRecord, ...]
    route_intents: tuple[ResourceRouteIntent, ...]
    state_changes: tuple[PlannedStateChange, ...]
    expected_dataset_schema: MeasurementDatasetSchema | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def valid(self) -> bool:
        return not any(
            diagnostic.severity in {"error", "blocker"}
            for diagnostic in self.diagnostics
        )

    @property
    def expected_output_ids(self) -> frozenset[str]:
        return frozenset(
            record.id for record in self.records if record.kind == "observable"
        )


__all__ = [
    "BoundAxis",
    "BoundCollect",
    "BoundComputeCall",
    "BoundComputeInput",
    "BoundComputeOutput",
    "BoundPlan",
    "BoundPoint",
    "BoundProduct",
    "BoundRecord",
    "BoundResourceState",
    "BoundRoute",
    "BoundStateField",
    "BoundValue",
    "PlannedStateChange",
]
