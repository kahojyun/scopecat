"""Typed Python declarations for first-party instrument capabilities."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

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

type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@instrument_result
class DCBiasReadbackResults:
    actual_voltage: float = result_field(dtype="float64", unit="V")
    settled: bool = result_field(dtype="bool")


@instrument_interface(
    "scopecat.dc_bias/v1",
    label="DC bias ramp",
    description="Settled voltage transitions applied as one coherent batch.",
)
class DCBiasInterface(Protocol):
    target_voltage: Member[Quantity] = member(
        access="read_write", unit="V", label="Target voltage"
    )
    ramp_duration: Member[Quantity] = member(
        access="read_write", unit="s", minimum=0.0, label="Ramp duration"
    )
    settle_tolerance: Member[Quantity] = member(
        access="read_write", unit="V", minimum=0.0, label="Settle tolerance"
    )
    actual_voltage: Member[Quantity] = member(
        access="read_only", unit="V", label="Actual voltage"
    )
    settled: Member[bool] = member(access="read_only", label="Settled")

    @acquisition(label="Read back bias")
    def readback(self) -> DCBiasReadbackResults: ...


@instrument_interface(
    "scopecat.dc_source/v3",
    label="DC source",
    description="DC source transitions, protection, and output control.",
)
class DCSourceInterface(Protocol):
    voltage_protection: Member[Quantity] = member(
        access="read_write", unit="V", label="Voltage protection"
    )
    current_protection: Member[Quantity] = member(
        access="read_write", unit="A", label="Current protection"
    )
    output_enabled: Member[bool] = member(access="read_write", label="DC output")
    source_mode: Member[Literal["voltage", "current"]] = member(
        access="read_only", label="Source mode"
    )

    @operation(label="Source voltage")
    def source_voltage(
        self,
        *,
        range: Annotated[Quantity, argument(unit="V")],
        level: Annotated[Quantity, argument(unit="V")],
    ) -> None: ...

    @operation(label="Source current")
    def source_current(
        self,
        *,
        range: Annotated[Quantity, argument(unit="A")],
        level: Annotated[Quantity, argument(unit="A")],
    ) -> None: ...


@instrument_result
class DCMonitorCurrentResults:
    current: float = result_field(id="monitored_current", dtype="float64", unit="A")


@instrument_result
class DCMonitorVoltageResults:
    voltage: float = result_field(id="monitored_voltage", dtype="float64", unit="V")


@instrument_interface(
    "scopecat.dc_monitor/v4",
    label="DC monitor",
    description="Independent current and voltage measurements for a DC source.",
)
class DCMonitorInterface(Protocol):
    measurement_enabled: Member[bool] = member(access="read_write", label="Measurement")
    integration_cycles: Member[int] = member(
        access="read_write", minimum=1, label="Integration cycles"
    )
    measurement_delay: Member[Quantity] = member(
        access="read_write",
        unit="s",
        minimum=0.0,
        label="Measurement delay",
    )

    @acquisition(label="Measure current")
    def measure_current(self) -> DCMonitorCurrentResults: ...

    @acquisition(label="Measure voltage")
    def measure_voltage(self) -> DCMonitorVoltageResults: ...


@instrument_result
class TemperatureSampleResults:
    temperature: float = result_field(dtype="float64", unit="K")
    resistance: float = result_field(dtype="float64", unit="Ohm")


@instrument_interface(
    "scopecat.temperature_readout/v1",
    label="Temperature readout",
    description="Read-only scanner state and settled sensor acquisition.",
)
class TemperatureReadoutInterface(Protocol):
    scan_channel: Member[int] = member(
        access="read_only", minimum=1, label="Scan channel"
    )
    autoscan_enabled: Member[bool] = member(access="read_only", label="Autoscan")

    @acquisition(label="Sample sensor")
    def sample(self) -> TemperatureSampleResults: ...


@instrument_interface(
    "scopecat.rf_output/v1",
    label="RF output",
    description="Continuous-wave RF source controls independent of vendor syntax.",
)
class RFOutputInterface(Protocol):
    frequency: Member[Quantity] = member(
        access="read_write", unit="Hz", label="CW frequency"
    )
    power: Member[Quantity] = member(
        access="read_write", unit="dBm", label="Output power"
    )
    output_enabled: Member[bool] = member(access="read_write", label="RF output")
    reference_source: Member[ReferenceSource] = member(
        access="read_write", label="Reference source"
    )


@instrument_result
class NetworkSweepResults:
    frequency: list[float] = result_field(
        role="coordinate", dtype="float64", unit="Hz", axes=("frequency",)
    )
    s_parameter: list[complex] = result_field(
        dtype="complex128", unit="ratio", axes=("frequency",)
    )


@instrument_interface(
    "scopecat.network_sweep/v1",
    label="Network sweep",
    description="Linear, single-trigger complex S-parameter sweep.",
)
class NetworkSweepInterface(Protocol):
    start_frequency: Member[Quantity] = member(
        access="read_write", unit="Hz", label="Start frequency"
    )
    stop_frequency: Member[Quantity] = member(
        access="read_write", unit="Hz", label="Stop frequency"
    )
    points: Member[int] = member(access="read_write", minimum=2, label="Sweep points")
    if_bandwidth: Member[Quantity] = member(
        access="read_write", unit="Hz", label="IF bandwidth"
    )
    source_power: Member[Quantity] = member(
        access="read_write", unit="dBm", label="Source power"
    )
    s_parameter: Member[SParameter] = member(access="read_write", label="S-parameter")

    @acquisition(
        label="Acquire sweep",
        axes={"frequency": axis(size=points, kind="frequency", unit="Hz")},
    )
    def sweep(self) -> NetworkSweepResults: ...


__all__ = [
    "DCBiasInterface",
    "DCBiasReadbackResults",
    "DCMonitorCurrentResults",
    "DCMonitorInterface",
    "DCMonitorVoltageResults",
    "DCSourceInterface",
    "NetworkSweepInterface",
    "NetworkSweepResults",
    "RFOutputInterface",
    "ReferenceSource",
    "SParameter",
    "TemperatureReadoutInterface",
    "TemperatureSampleResults",
]
