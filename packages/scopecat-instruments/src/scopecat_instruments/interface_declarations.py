"""Typed Python declarations for first-party instrument capabilities."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
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
    @property
    @member(unit="V", label="Target voltage")
    def target_voltage(self) -> Quantity: ...

    @target_voltage.setter
    def target_voltage(self, value: Quantity) -> None: ...

    @property
    @member(unit="s", minimum=0.0, label="Ramp duration")
    def ramp_duration(self) -> Quantity: ...

    @ramp_duration.setter
    def ramp_duration(self, value: Quantity) -> None: ...

    @property
    @member(unit="V", minimum=0.0, label="Settle tolerance")
    def settle_tolerance(self) -> Quantity: ...

    @settle_tolerance.setter
    def settle_tolerance(self, value: Quantity) -> None: ...

    @property
    @member(unit="V", label="Actual voltage")
    def actual_voltage(self) -> Quantity: ...

    @property
    @member(label="Settled")
    def settled(self) -> bool: ...

    @acquisition(label="Read back bias")
    def readback(self) -> DCBiasReadbackResults: ...


@instrument_interface(
    "scopecat.dc_source/v3",
    label="DC source",
    description="DC source transitions, protection, and output control.",
)
class DCSourceInterface(Protocol):
    @property
    @member(unit="V", label="Voltage protection")
    def voltage_protection(self) -> Quantity: ...

    @voltage_protection.setter
    def voltage_protection(self, value: Quantity) -> None: ...

    @property
    @member(unit="A", label="Current protection")
    def current_protection(self) -> Quantity: ...

    @current_protection.setter
    def current_protection(self, value: Quantity) -> None: ...

    @property
    @member(label="DC output")
    def output_enabled(self) -> bool: ...

    @output_enabled.setter
    def output_enabled(self, value: bool) -> None: ...

    @property
    @member(label="Source mode")
    def source_mode(self) -> Literal["voltage", "current"]: ...

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
    @property
    @member(label="Measurement")
    def measurement_enabled(self) -> bool: ...

    @measurement_enabled.setter
    def measurement_enabled(self, value: bool) -> None: ...

    @property
    @member(minimum=1, label="Integration cycles")
    def integration_cycles(self) -> int: ...

    @integration_cycles.setter
    def integration_cycles(self, value: int) -> None: ...

    @property
    @member(unit="s", minimum=0.0, label="Measurement delay")
    def measurement_delay(self) -> Quantity: ...

    @measurement_delay.setter
    def measurement_delay(self, value: Quantity) -> None: ...

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
    @property
    @member(minimum=1, label="Scan channel")
    def scan_channel(self) -> int: ...

    @property
    @member(label="Autoscan")
    def autoscan_enabled(self) -> bool: ...

    @acquisition(label="Sample sensor")
    def sample(self) -> TemperatureSampleResults: ...


@instrument_interface(
    "scopecat.rf_output/v1",
    label="RF output",
    description="Continuous-wave RF source controls independent of vendor syntax.",
)
class RFOutputInterface(Protocol):
    @property
    @member(unit="Hz", label="CW frequency")
    def frequency(self) -> Quantity: ...

    @frequency.setter
    def frequency(self, value: Quantity) -> None: ...

    @property
    @member(unit="dBm", label="Output power")
    def power(self) -> Quantity: ...

    @power.setter
    def power(self, value: Quantity) -> None: ...

    @property
    @member(label="RF output")
    def output_enabled(self) -> bool: ...

    @output_enabled.setter
    def output_enabled(self, value: bool) -> None: ...

    @property
    @member(label="Reference source")
    def reference_source(self) -> ReferenceSource: ...

    @reference_source.setter
    def reference_source(self, value: ReferenceSource) -> None: ...


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
    @property
    @member(unit="Hz", label="Start frequency")
    def start_frequency(self) -> Quantity: ...

    @start_frequency.setter
    def start_frequency(self, value: Quantity) -> None: ...

    @property
    @member(unit="Hz", label="Stop frequency")
    def stop_frequency(self) -> Quantity: ...

    @stop_frequency.setter
    def stop_frequency(self, value: Quantity) -> None: ...

    @property
    @member(minimum=2, label="Sweep points")
    def points(self) -> int: ...

    @points.setter
    def points(self, value: int) -> None: ...

    @property
    @member(unit="Hz", label="IF bandwidth")
    def if_bandwidth(self) -> Quantity: ...

    @if_bandwidth.setter
    def if_bandwidth(self, value: Quantity) -> None: ...

    @property
    @member(unit="dBm", label="Source power")
    def source_power(self) -> Quantity: ...

    @source_power.setter
    def source_power(self, value: Quantity) -> None: ...

    @property
    @member(label="S-parameter")
    def s_parameter(self) -> SParameter: ...

    @s_parameter.setter
    def s_parameter(self, value: SParameter) -> None: ...

    @acquisition(
        label="Acquire sweep",
        axes={"frequency": axis(size="points", kind="frequency", unit="Hz")},
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
