"""Synthetic declarations used to verify committed generated client source."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
    Member,
    acquisition,
    argument,
    axis,
    instrument_interface,
    instrument_result,
    member,
    operation,
    result_field,
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


@instrument_interface("test.generated_catalog_projection/v1")
class CatalogProjectionInterface(Protocol):
    enabled: Member[bool] = member(access="read_write", restore=True)
    status: Member[str] = member(access="read_only")


@instrument_interface("test.generated_shared_property_first/v1")
class SharedPropertyFirstInterface(Protocol):
    enabled: Member[bool] = member(access="read_write", restore=True)


@instrument_interface("test.generated_shared_property_second/v1")
class SharedPropertySecondInterface(Protocol):
    enabled: Member[bool] = member(access="read_write", restore=True)


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


@instrument_interface("test.generated_composite_enabled_method/v1")
class CompositeEnabledMethodInterface(Protocol):
    @operation()
    def enabled(self) -> None: ...


@instrument_result
class CompositeSampleResults:
    value: float = result_field(dtype="float64")


@instrument_interface("test.generated_composite_acquisition_left/v1")
class CompositeAcquisitionLeftInterface(Protocol):
    @acquisition(id="left_sample")
    def sample(self) -> CompositeSampleResults: ...


@instrument_interface("test.generated_composite_acquisition_right/v1")
class CompositeAcquisitionRightInterface(Protocol):
    @acquisition(id="right_sample")
    def sample(self) -> CompositeSampleResults: ...


@instrument_interface("test.generated_shared_acquisition_result/v1")
class SharedAcquisitionResultInterface(Protocol):
    @acquisition()
    def sample_left(self) -> CompositeSampleResults: ...

    @acquisition()
    def sample_right(self) -> CompositeSampleResults: ...


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
    response: NDArray[np.complex128] = result_field(
        id="signal",
        unit="ratio",
        axes=("sample",),
    )


@instrument_interface("test.generated_driver_fixed_acquisition/v1")
class DriverFixedAcquisitionInterface(Protocol):
    @acquisition(
        axes={"sample": axis(size=2, kind="sample")},
    )
    def acquire(self) -> DriverFixedResults: ...


@instrument_interface("test.generated_driver_source/v1")
class DriverSourceInterface(Protocol):
    enabled: Member[bool] = member(access="read_write", restore=True)
    level: Member[int] = member(access="read_write", restore=True)


@instrument_result
class DriverMonitorResults:
    left: float = result_field(id="left_value", dtype="float64")
    right: float = result_field(id="right_value", dtype="float64")


@instrument_interface("test.generated_driver_monitor/v1")
class DriverMonitorInterface(Protocol):
    enabled: Member[bool] = member(access="read_write", restore=True)

    @acquisition()
    def monitor(self) -> DriverMonitorResults: ...


@instrument_result
class NativeScalarResults:
    boolean: bool = result_field()
    integer: int = result_field()
    floating: float = result_field()
    complex_value: complex = result_field()
    text: str = result_field()


@instrument_interface("test.generated_native_scalars/v1")
class NativeScalarInterface(Protocol):
    @acquisition()
    def sample(self) -> NativeScalarResults: ...


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
    "CompositeAcquisitionLeftInterface",
    "CompositeAcquisitionRightInterface",
    "CompositeEnabledMethodInterface",
    "CompositeMethodLeftInterface",
    "CompositeMethodPeerInterface",
    "CompositeMethodRightInterface",
    "CompositePeerInterface",
    "CompositeSampleResults",
    "DriverFixedAcquisitionInterface",
    "DriverFixedResults",
    "DriverMonitorInterface",
    "DriverMonitorResults",
    "DriverSourceInterface",
    "EffectIdCollisionInterface",
    "LiteralOperationInterface",
    "PayloadOperationInterface",
    "ScalarOperationInterface",
    "SharedAcquisitionResultInterface",
    "SharedPropertyFirstInterface",
    "SharedPropertySecondInterface",
]
