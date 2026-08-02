"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
    acquisition,
    argument,
    axis,
    discriminated_state,
    instrument_interface,
    instrument_observed_state,
    instrument_result,
    instrument_state,
    member,
    member_field,
    operation,
    result_field,
    state_case,
)


@instrument_interface("test.generated_scalar_operation/v1")
class ScalarOperationInterface(Protocol):
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
class CatalogProjectionInterface(Protocol): ...


@instrument_interface("test.generated_composite_peer/v1")
class CompositePeerInterface(Protocol): ...


@instrument_interface("test.generated_composite_method_left/v1")
class CompositeMethodLeftInterface(Protocol):
    @operation(id="left_fire")
    def fire(self) -> None: ...


@instrument_interface("test.generated_composite_method_right/v1")
class CompositeMethodRightInterface(Protocol):
    @operation(id="right_fire")
    def fire(self) -> None: ...


@instrument_interface("test.generated_composite_method_peer/v1")
class CompositeMethodPeerInterface(Protocol):
    @operation(id="peer_arm")
    def arm(self) -> None: ...


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
class DriverMonitorResults:
    left: float = result_field(id="left_value", dtype="float64")
    right: float = result_field(id="right_value", dtype="float64")


@instrument_interface(
    "test.generated_driver_monitor/v1",
    state=DriverMonitorState,
)
class DriverMonitorInterface(Protocol):
    @acquisition()
    def monitor(self) -> DriverMonitorResults: ...


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


__all__ = [
    "CatalogProjectionInterface",
    "CatalogProjectionObservation",
    "CatalogProjectionState",
    "CompositeMethodLeftInterface",
    "CompositeMethodPeerInterface",
    "CompositeMethodRightInterface",
    "CompositePeerInterface",
    "DriverFixedAcquisitionInterface",
    "DriverFixedResults",
    "DriverMonitorInterface",
    "DriverMonitorResults",
    "DriverMonitorState",
    "DriverSourceInterface",
    "DriverSourceLeftState",
    "DriverSourceRightState",
    "DriverSourceState",
    "EffectIdCollisionInterface",
    "LiteralOperationInterface",
    "PayloadOperationInterface",
    "ScalarOperationInterface",
]
