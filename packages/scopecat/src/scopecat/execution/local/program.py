"""Structured local-effect payloads embedded in a ``RunProgram``.

The authoring compiler may use richer symbolic IRs.  This module starts after
configuration linking and point binding: values and resource bindings are
concrete, pure compute dependencies are ordered, and hardware effects are
represented as explicit stages.  The program is intentionally not a durable
wire format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from scopecat.graph.values import ComputeOutput, ValueId
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.state import StateValue
from scopecat.records.instrument import CommandChannelBinding
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
    semantic_operation_id: str
    implementation_id: str
    kernel: ComputeKernel
    inputs: Mapping[str, ComputeInput]
    result: ComputeOutput
    payload_slot: PayloadSlot | None = None


@dataclass(frozen=True, slots=True)
class StateTarget:
    """One property that must hold before subsequent point stages execute."""

    interface_id: InterfaceId
    property_id: str
    value: StateValue
    component_path: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def command_assignment(
        self,
        *,
        resource_id: str,
    ) -> InstrumentStateAssignment:
        return InstrumentStateAssignment(
            resource_id=resource_id,
            interface_id=self.interface_id,
            component_path=list(self.component_path),
            property_id=self.property_id,
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
    "StateTarget",
]
