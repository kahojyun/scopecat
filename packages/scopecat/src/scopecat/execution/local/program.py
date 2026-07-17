"""Transient, explicit program consumed by the local execution engine.

The authoring compiler may use richer symbolic IRs.  This module starts after
configuration linking and point binding: values and routes are concrete, pure
compute dependencies are ordered, and hardware effects are represented as
explicit stages.  The program is intentionally not a durable wire format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.semantic.operation_contract import OperationContract
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import ValueType
from scopecat.measurements.results import CoordinateValue
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    InstrumentActionCommandField,
    InstrumentStateCommandField,
)

type ComputeKernel = Callable[..., object]


def _empty_dependencies() -> dict[str, tuple[str, ...]]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundInput:
    """One already-bound value passed to a pure compute operation."""

    value: object


@dataclass(frozen=True, slots=True)
class OutputInput:
    """Reference an earlier compute result in the same point."""

    value_id: ValueId


type ComputeInput = BoundInput | OutputInput


@dataclass(frozen=True, slots=True)
class PayloadSlot:
    """Command payload materialized from a compute output."""

    id: str
    schema_id: str


@dataclass(frozen=True, slots=True)
class ComputeResultSlot:
    """Semantic result produced by one point-local compute invocation."""

    id: ValueId
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class ComputeOperation:
    """One point-local pure compute kernel invocation."""

    operation_id: str
    semantic_operation_id: str
    implementation_id: str
    contract: OperationContract
    kernel: ComputeKernel
    inputs: Mapping[str, ComputeInput]
    result: ComputeResultSlot
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_slot: PayloadSlot | None = None
    cache_namespace: str | None = None
    cache_key: object | None = None


@dataclass(frozen=True, slots=True)
class ComputeStage:
    """Topologically ordered pure compute island."""

    operations: tuple[ComputeOperation, ...]
    kind: Literal["compute"] = field(default="compute", init=False)


@dataclass(frozen=True, slots=True)
class StateTarget:
    """One field that must hold before subsequent point stages execute."""

    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def command_field(self, *, resource_id: str) -> InstrumentStateCommandField:
        return InstrumentStateCommandField(
            resource_id=resource_id,
            capability_id=self.capability_id,
            field_path=self.field_path,
            value=self.value.model_copy(deep=True),
            entity_ids=list(self.entity_ids),
            channel_bindings=list(self.channel_bindings),
        )


@dataclass(frozen=True, slots=True)
class ApplyStateOperation:
    """Reconcile a concrete instrument with point-local state targets."""

    operation_id: str
    instrument_id: str
    targets: tuple[StateTarget, ...]


@dataclass(frozen=True, slots=True)
class ApplyStateStage:
    """Explicitly ordered state reconciliation operations."""

    operations: tuple[ApplyStateOperation, ...]
    kind: Literal["apply_state"] = field(default="apply_state", init=False)


@dataclass(frozen=True, slots=True)
class ActionField:
    """One concrete field supplied to a one-shot action."""

    id: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def command_field(self) -> InstrumentActionCommandField:
        return InstrumentActionCommandField(
            field_path=self.id,
            value=self.value.model_copy(deep=True),
            entity_ids=list(self.entity_ids),
            channel_bindings=list(self.channel_bindings),
        )


@dataclass(frozen=True, slots=True)
class InstrumentActionOperation:
    """One action attempt that is always delivered when its stage executes."""

    operation_id: str
    instrument_id: str
    capability_id: str
    fields: tuple[ActionField, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionStage:
    """Explicitly ordered one-shot instrument effects."""

    operations: tuple[InstrumentActionOperation, ...]
    kind: Literal["action"] = field(default="action", init=False)


@dataclass(frozen=True, slots=True)
class CollectionResultBinding:
    """Map one provider response key to one logical product-use occurrence."""

    provider_key: str
    product_use_id: ProductUseId
    product_id: ProductId


@dataclass(frozen=True, slots=True)
class CollectOperation:
    """One instrument collection command and its logical product bindings."""

    operation_id: str
    instrument_id: str
    command: CollectCommand
    result_bindings: tuple[CollectionResultBinding, ...]


@dataclass(frozen=True, slots=True)
class CollectStage:
    """Explicitly ordered collection operations."""

    operations: tuple[CollectOperation, ...]
    kind: Literal["collect"] = field(default="collect", init=False)


type ExecutionStage = ComputeStage | ApplyStateStage | ActionStage | CollectStage


@dataclass(frozen=True, slots=True)
class PointProgram:
    """Concrete stages for one logical experiment point."""

    point_index: int
    point_uid: str
    coordinates: Mapping[str, CoordinateValue]
    stages: tuple[ExecutionStage, ...]


@dataclass(frozen=True, slots=True)
class ExecutionProgram:
    """Concrete local program with an explicit instrument-collected subset."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    collection_product_use_ids: tuple[ProductUseId, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]

    @property
    def point_count(self) -> int:
        return len(self.points)


__all__ = [
    "ActionField",
    "ActionStage",
    "ApplyStateOperation",
    "ApplyStateStage",
    "BoundInput",
    "CollectOperation",
    "CollectStage",
    "CollectionResultBinding",
    "ComputeInput",
    "ComputeKernel",
    "ComputeOperation",
    "ComputeResultSlot",
    "ComputeStage",
    "ExecutionProgram",
    "ExecutionStage",
    "InstrumentActionOperation",
    "OutputInput",
    "PayloadSlot",
    "PointProgram",
    "ResourceClaim",
    "StateTarget",
]
