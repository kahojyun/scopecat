"""Structured local-effect payloads embedded in a ``RunProgram``.

The authoring compiler may use richer symbolic IRs.  This module starts after
configuration binding and point materialization: values and resource bindings are
concrete, pure compute dependencies are ordered, and hardware effects are
represented as explicit stages.  The program is intentionally not a durable
wire format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.instrument_members import PropertyRef
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    ResourceRoleSelector,
)
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import DataType
from scopecat.program.value_graph import ComputeOutput
from scopecat.records.instrument import CommandChannelBinding, state_member_target
from scopecat.sdk.instruments.commands import (
    CollectCommand,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
)

type ComputeKernel = Callable[..., object]


@dataclass(frozen=True, slots=True)
class BoundInput:
    """One already-bound value passed to a pure compute operation."""

    value: object


@dataclass(frozen=True, slots=True)
class OutputInput:
    """Reference an earlier compute result in the same point."""

    value_id: ValueId
    value_type: DataType


type ComputeInput = BoundInput | OutputInput


@dataclass(frozen=True, slots=True)
class PayloadSlot:
    """Command payload materialized from a compute output."""

    id: str
    schema_id: str


@dataclass(frozen=True, slots=True)
class ComputeOperation:
    """One point-local pure compute kernel invocation."""

    operation_id: str
    logical_compute_node_id: str
    implementation_id: str
    kernel: ComputeKernel
    inputs: Mapping[str, ComputeInput]
    result: ComputeOutput
    deterministic: bool = False
    payload_slot: PayloadSlot | None = None


@dataclass(frozen=True, slots=True)
class ResourceProvenance:
    """Logical request and accepted route behind one physical operation."""

    logical_port_id: LogicalResourcePortId
    requested_role: ResourceRoleSelector
    route_id: str
    route_role_id: str | None


@dataclass(frozen=True, slots=True)
class StateDemandOrigin:
    """One logical demand contributing to a physical state target."""

    resource: ResourceProvenance
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class StateTarget:
    """One property that must hold before subsequent point stages execute."""

    interface_id: InterfaceId
    property_id: str
    value: StateValue
    origins: tuple[StateDemandOrigin, ...]
    component_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.origins:
            raise ValueError("state target requires at least one demand origin")

    @property
    def entity_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                entity_id for origin in self.origins for entity_id in origin.entity_ids
            )
        )

    @property
    def channel_bindings(self) -> tuple[CommandChannelBinding, ...]:
        selected: dict[tuple[str, str, InterfaceId | None], CommandChannelBinding] = {}
        for origin in self.origins:
            for binding in origin.channel_bindings:
                selected.setdefault(
                    (binding.entity_id, binding.channel_id, binding.interface_id),
                    binding,
                )
        return tuple(selected.values())

    def command_assignment(
        self,
        *,
        resource_id: str,
    ) -> InstrumentStateAssignment:
        return InstrumentStateAssignment(
            resource_id=resource_id,
            target=state_member_target(
                PropertyRef(
                    self.interface_id,
                    self.component_path,
                    self.property_id,
                )
            ),
            value=self.value,
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
class InvokeOperation:
    """One concrete atomic instrument-operation target."""

    effect_id: str
    instrument_id: str
    resource_id: str
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    operation_id: str
    arguments: tuple[InstrumentOperationArgument, ...]
    resource: ResourceProvenance
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectionResultBinding:
    """Map one collect request correlation id to its logical product uses."""

    request_id: str
    product_use_ids: tuple[ProductUseId, ...]


@dataclass(frozen=True, slots=True)
class CollectOperation:
    """One instrument collection command and its logical product bindings."""

    operation_id: str
    instrument_id: str
    command: CollectCommand
    result_bindings: tuple[CollectionResultBinding, ...]
    resource: ResourceProvenance


type LocalOperation = (
    ComputeOperation | ApplyStateOperation | InvokeOperation | CollectOperation
)


__all__ = [
    "ApplyStateOperation",
    "BoundInput",
    "CollectOperation",
    "CollectionResultBinding",
    "ComputeInput",
    "ComputeKernel",
    "ComputeOperation",
    "InvokeOperation",
    "LocalOperation",
    "OutputInput",
    "PayloadSlot",
    "ResourceProvenance",
    "StateDemandOrigin",
    "StateTarget",
]
