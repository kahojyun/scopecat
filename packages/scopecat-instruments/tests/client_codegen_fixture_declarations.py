"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
    argument,
    component,
    instrument_bundle,
    instrument_interface,
    instrument_observed_state,
    instrument_state,
    member_field,
    operation,
)


class TriggerCapability(Protocol):
    @operation(id="emit_pulse")
    def emit(
        self,
        count: Annotated[int, argument(id="pulse_count")],
        /,
        width: Annotated[
            Quantity,
            argument(id="pulse_width", unit="s"),
        ],
        *,
        label: Annotated[str, argument(id="pulse_label")],
    ) -> None: ...


class OutputCapability(Protocol):
    trigger: Annotated[
        TriggerCapability,
        component(id="pulse_trigger"),
    ]


@instrument_state
class CatalogProjectionState:
    enabled: bool = member_field()


@instrument_observed_state
class CatalogProjectionObservation:
    status: str = member_field()


@instrument_interface(
    "test.generated_catalog_projection/v1",
    state=CatalogProjectionState,
    observed_state=CatalogProjectionObservation,
)
class CatalogProjectionInterface(Protocol):
    output: Annotated[
        OutputCapability,
        component(id="signal_output"),
    ]


@instrument_interface("test.generated_component_operation/v1")
class ComponentOperationInterface(Protocol):
    output: Annotated[
        OutputCapability,
        component(id="signal_output"),
    ]


@instrument_interface("test.generated_bundle_peer/v1")
class BundlePeerInterface(Protocol): ...


@instrument_bundle
class ComponentBundleInterface(
    ComponentOperationInterface,
    BundlePeerInterface,
    Protocol,
): ...


@instrument_interface("test.generated_bundle_method_left/v1")
class BundleMethodLeftInterface(Protocol):
    @operation(id="left_fire")
    def fire(self) -> None: ...


@instrument_interface("test.generated_bundle_method_right/v1")
class BundleMethodRightInterface(Protocol):
    @operation(id="right_fire")
    def fire(self) -> None: ...


@instrument_interface("test.generated_bundle_method_peer/v1")
class BundleMethodPeerInterface(Protocol):
    @operation(id="peer_arm")
    def arm(self) -> None: ...


@instrument_bundle
class MethodMergeBundleInterface(
    BundleMethodLeftInterface,
    BundleMethodPeerInterface,
    Protocol,
): ...


@instrument_bundle
class ThreePartBundleInterface(
    BundleMethodLeftInterface,
    BundleMethodPeerInterface,
    BundlePeerInterface,
    Protocol,
): ...


@instrument_bundle
class MethodCollisionBundleInterface(
    BundleMethodLeftInterface,
    BundleMethodRightInterface,
    Protocol,
): ...


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
            Literal["left", "right"],
            argument(),
        ],
    ) -> None: ...


@instrument_interface("test.generated_effect_id_collision/v1")
class EffectIdCollisionInterface(Protocol):
    @operation()
    def emit(
        self,
        effect_id: Annotated[str, argument()],
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
    "BundleMethodLeftInterface",
    "BundleMethodPeerInterface",
    "BundleMethodRightInterface",
    "BundlePeerInterface",
    "CatalogProjectionInterface",
    "CatalogProjectionObservation",
    "CatalogProjectionState",
    "ComponentBundleInterface",
    "ComponentOperationInterface",
    "EffectIdCollisionInterface",
    "FlatFooBarCapability",
    "LiteralOperationInterface",
    "MethodCollisionBundleInterface",
    "MethodMergeBundleInterface",
    "NestedBarCapability",
    "NestedFooCapability",
    "OutputCapability",
    "PayloadOperationInterface",
    "SymbolCollisionInterface",
    "ThreePartBundleInterface",
    "TriggerCapability",
]
