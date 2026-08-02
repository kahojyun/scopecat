"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
    acquisition,
    acquisition_case,
    argument,
    axis,
    component,
    discriminated_state,
    instrument_bundle,
    instrument_interface,
    instrument_observed_state,
    instrument_result,
    instrument_state,
    interface_discriminator,
    member,
    member_field,
    operation,
    result_field,
    state_case,
    state_discriminated_acquisition,
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


@instrument_result
class DriverFixedResults:
    response: list[complex] = result_field(
        id="signal",
        dtype="complex128",
        unit="ratio",
        axes=("sample",),
    )


@instrument_interface("test.generated_driver_fixed_acquisition/v1")
class DriverFixedAcquisitionInterface(Protocol):
    @acquisition(
        axes={"sample": axis(size=2, kind="sample")},
    )
    def acquire(self) -> DriverFixedResults: ...


@instrument_state
class _DriverSourceCommon:
    enabled: bool = member_field()


@instrument_state
class DriverSourceLeftState(_DriverSourceCommon):
    level: int = member_field(id="left_level")


@instrument_state
class DriverSourceRightState(_DriverSourceCommon):
    level: int = member_field(id="right_level")


type DriverSourceState = DriverSourceLeftState | DriverSourceRightState


@instrument_interface(
    "test.generated_driver_source/v1",
    state=discriminated_state(
        member(id="mode", choices=("left", "right")),
        common=_DriverSourceCommon,
        cases=(
            state_case("left", DriverSourceLeftState, required_on_entry=("level",)),
            state_case(
                "right",
                DriverSourceRightState,
                required_on_entry=("level",),
            ),
        ),
    ),
)
class DriverSourceInterface(Protocol): ...


@instrument_state
class DriverMonitorState:
    enabled: bool = member_field()


@instrument_result
class DriverMonitorResults[ValueT]:
    left: ValueT | None = result_field(id="left_value", dtype="float64")
    right: ValueT | None = result_field(id="right_value", dtype="float64")


@instrument_interface(
    "test.generated_driver_monitor/v1",
    state=DriverMonitorState,
)
class DriverMonitorInterface(Protocol):
    @state_discriminated_acquisition(
        interface_discriminator(DriverSourceInterface),
        cases=(
            acquisition_case(
                "left",
                DriverMonitorResults[float],
                fields=("left",),
            ),
            acquisition_case(
                "right",
                DriverMonitorResults[float],
                fields=("right",),
            ),
        ),
    )
    def monitor(self) -> DriverMonitorResults[float]: ...


@instrument_bundle
class DriverMonitorBundle(
    DriverSourceInterface,
    DriverMonitorInterface,
    Protocol,
): ...


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
    "DriverFixedAcquisitionInterface",
    "DriverFixedResults",
    "DriverMonitorBundle",
    "DriverMonitorInterface",
    "DriverMonitorResults",
    "DriverMonitorState",
    "DriverSourceInterface",
    "DriverSourceLeftState",
    "DriverSourceRightState",
    "DriverSourceState",
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
