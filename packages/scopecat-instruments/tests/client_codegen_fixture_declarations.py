"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.declarations import (
    argument,
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


@instrument_interface("test.generated_effect_id_collision/v1")
class EffectIdCollisionInterface(Protocol):
    @operation()
    def emit(
        self,
        effect_id: Annotated[Desired[str], argument()],
    ) -> None: ...


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


__all__ = [
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
