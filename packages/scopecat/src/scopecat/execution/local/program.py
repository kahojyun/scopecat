"""Structured local-effect payloads embedded in a ``RunProgram``.

The authoring compiler may use richer symbolic IRs.  This module starts after
configuration linking and point binding: values and routes are concrete, pure
compute dependencies are ordered, and hardware effects are represented as
explicit stages.  The program is intentionally not a durable wire format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.semantic.operation_contract import OperationContract
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import ValueType
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
    binding_signature: str | None = None
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_slot: PayloadSlot | None = None


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
class ActionField:
    """One concrete field supplied to a one-shot action."""

    id: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def command_field(self) -> InstrumentActionCommandField:
        return InstrumentActionCommandField(
            field_path=self.id,
            value=self.value,
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


type LocalOperation = (
    ComputeOperation
    | ApplyStateOperation
    | InstrumentActionOperation
    | CollectOperation
)


__all__ = [
    "ActionField",
    "ApplyStateOperation",
    "BoundInput",
    "CollectOperation",
    "CollectionResultBinding",
    "ComputeInput",
    "ComputeKernel",
    "ComputeOperation",
    "ComputeResultSlot",
    "InstrumentActionOperation",
    "LocalOperation",
    "OutputInput",
    "PayloadSlot",
    "StateTarget",
]
