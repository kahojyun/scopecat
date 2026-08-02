"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    argument,
    compile_interface,
    component,
    instrument_interface,
    operation,
)

type Desired[T] = T | ValueRef


class TriggerCapability(Protocol):
    @operation(id="emit_pulse")
    def emit(
        self,
        count: Annotated[Desired[int], argument(id="pulse_count")],
        /,
        width: Annotated[
            Desired[Quantity],
            argument(id="pulse_width", unit="s"),
        ],
        *,
        label: Annotated[Desired[str], argument(id="pulse_label")],
    ) -> None: ...


class OutputCapability(Protocol):
    trigger: Annotated[
        TriggerCapability,
        component(id="pulse_trigger"),
    ]


@instrument_interface("test.generated_component_operation/v1")
class ComponentOperationInterface(Protocol):
    output: Annotated[
        OutputCapability,
        component(id="signal_output"),
    ]


COMPONENT_OPERATION_DECLARATION: CompiledInterface[ComponentOperationInterface] = (
    compile_interface(ComponentOperationInterface)
)


@instrument_interface("test.generated_payload_operation/v1")
class PayloadOperationInterface(Protocol):
    @operation()
    def upload(
        self,
        payload: Annotated[
            bytes,
            argument(payload_schema_id="test.payload/v1"),
        ],
    ) -> None: ...


PAYLOAD_OPERATION_DECLARATION: CompiledInterface[PayloadOperationInterface] = (
    compile_interface(PayloadOperationInterface)
)


@instrument_interface("test.generated_literal_operation/v1")
class LiteralOperationInterface(Protocol):
    @operation()
    def select(
        self,
        mode: Annotated[
            Desired[Literal["left", "right"]],
            argument(),
        ],
    ) -> None: ...


LITERAL_OPERATION_DECLARATION: CompiledInterface[LiteralOperationInterface] = (
    compile_interface(LiteralOperationInterface)
)


@instrument_interface("test.generated_effect_id_collision/v1")
class EffectIdCollisionInterface(Protocol):
    @operation()
    def emit(
        self,
        effect_id: Annotated[Desired[str], argument()],
    ) -> None: ...


EFFECT_ID_COLLISION_DECLARATION: CompiledInterface[EffectIdCollisionInterface] = (
    compile_interface(EffectIdCollisionInterface)
)


class FlatFooBarCapability(Protocol):
    @operation(id="flat_fire")
    def fire(self) -> None: ...


class NestedBarCapability(Protocol):
    @operation(id="nested_fire")
    def fire(self) -> None: ...


class NestedFooCapability(Protocol):
    bar: Annotated[
        NestedBarCapability,
        component(id="nested_bar"),
    ]


@instrument_interface("test.generated_symbol_collision/v1")
class SymbolCollisionInterface(Protocol):
    foo_bar: Annotated[
        FlatFooBarCapability,
        component(id="flat_foo_bar"),
    ]
    foo: Annotated[
        NestedFooCapability,
        component(id="nested_foo"),
    ]


SYMBOL_COLLISION_DECLARATION: CompiledInterface[SymbolCollisionInterface] = (
    compile_interface(SymbolCollisionInterface)
)


__all__ = [
    "COMPONENT_OPERATION_DECLARATION",
    "EFFECT_ID_COLLISION_DECLARATION",
    "LITERAL_OPERATION_DECLARATION",
    "PAYLOAD_OPERATION_DECLARATION",
    "SYMBOL_COLLISION_DECLARATION",
    "ComponentOperationInterface",
    "Desired",
    "EffectIdCollisionInterface",
    "FlatFooBarCapability",
    "LiteralOperationInterface",
    "NestedBarCapability",
    "NestedFooCapability",
    "OutputCapability",
    "PayloadOperationInterface",
    "SymbolCollisionInterface",
    "TriggerCapability",
]
