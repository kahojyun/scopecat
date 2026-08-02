"""Typed Python declarations for first-party instrument capabilities."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments.declarations import (
    acquisition,
    argument,
    axis,
    instrument_bundle,
    instrument_interface,
    instrument_observed_state,
    instrument_result,
    instrument_state,
    member_field,
    operation,
    result_field,
)

type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@instrument_state
class DCSourceState:
    """Persistent DC-source settings independent of the selected source mode."""

    voltage_protection: Quantity = member_field(
        unit="V",
        label="Voltage protection",
        description="Absolute voltage limiter level.",
    )
    current_protection: Quantity = member_field(
        unit="A",
        label="Current protection",
        description="Absolute current limiter level.",
    )
    output_enabled: bool = member_field(
        label="DC output",
        description="Whether the source output is enabled.",
    )


@instrument_observed_state
class DCSourceObservation:
    """Source mode currently reported by the instrument."""

    source_mode: Literal["voltage", "current"] = member_field(
        label="Source mode",
        description="Whether the instrument is currently sourcing voltage or current.",
    )


@instrument_interface(
    "scopecat.dc_source/v3",
    state=DCSourceState,
    observed_state=DCSourceObservation,
    label="DC source",
    description=(
        "DC voltage/current source transitions, protection, and output control."
    ),
)
class DCSourceInterface(Protocol):
    @operation(
        label="Source voltage",
        description="Select voltage-source mode and set its range and level.",
    )
    def source_voltage(
        self,
        *,
        range: Annotated[Quantity, argument(unit="V")],
        level: Annotated[Quantity, argument(unit="V")],
    ) -> None: ...

    @operation(
        label="Source current",
        description="Select current-source mode and set its range and level.",
    )
    def source_current(
        self,
        *,
        range: Annotated[Quantity, argument(unit="A")],
        level: Annotated[Quantity, argument(unit="A")],
    ) -> None: ...


@instrument_state
class DCMonitorState:
    measurement_enabled: bool = member_field(
        label="Measurement",
        description="Whether monitor measurements are enabled.",
    )
    integration_cycles: int = member_field(
        minimum=1,
        maximum=25,
        label="Integration cycles",
        description="Power-line cycles integrated for each measurement.",
    )
    measurement_delay: Quantity = member_field(
        unit="s",
        minimum=0.0,
        maximum=999.999,
        label="Measurement delay",
        description="Delay between measurement trigger and sampling.",
    )


@instrument_result
class DCMonitorCurrentResults[ValueT]:
    """Current measurement produced while the source is in voltage mode."""

    current: ValueT = result_field(
        id="monitored_current",
        dtype="float64",
        unit="A",
        label="Monitored current",
        description="One measurement while sourcing voltage.",
    )


@instrument_result
class DCMonitorVoltageResults[ValueT]:
    """Voltage measurement produced while the source is in current mode."""

    voltage: ValueT = result_field(
        id="monitored_voltage",
        dtype="float64",
        unit="V",
        label="Monitored voltage",
        description="One measurement while sourcing current.",
    )


@instrument_interface(
    "scopecat.dc_monitor/v4",
    state=DCMonitorState,
    label="DC monitor",
    description="Independent current and voltage measurements for a DC source.",
)
class DCMonitorInterface(Protocol):
    @acquisition(
        label="Measure current",
        description="Measure current while the source is operating in voltage mode.",
    )
    def measure_current(self) -> DCMonitorCurrentResults[float]: ...

    @acquisition(
        label="Measure voltage",
        description="Measure voltage while the source is operating in current mode.",
    )
    def measure_voltage(self) -> DCMonitorVoltageResults[float]: ...


@instrument_bundle
class DCSourceMonitorInterface(
    DCSourceInterface,
    DCMonitorInterface,
    Protocol,
): ...


@instrument_observed_state
class TemperatureReadoutObservation:
    """Scanner state reported by a temperature readout."""

    scan_channel: int = member_field(
        minimum=1,
        maximum=16,
        label="Scan channel",
        description="Sensor input currently selected by the scanner.",
    )
    autoscan_enabled: bool = member_field(
        label="Autoscan",
        description="Whether the input scanner is advancing automatically.",
    )


@instrument_result
class TemperatureSampleResults[ValueT]:
    """Temperature sample fields reusable across acquisition runtimes."""

    temperature: ValueT = result_field(
        dtype="float64",
        unit="K",
        label="Temperature",
        description="Current scan-channel temperature.",
    )
    resistance: ValueT = result_field(
        dtype="float64",
        unit="Ohm",
        label="Resistance",
        description="Current scan-channel sensor resistance.",
    )


@instrument_interface(
    "scopecat.temperature_readout/v1",
    observed_state=TemperatureReadoutObservation,
    label="Temperature readout",
    description=(
        "Read-only scanner state and settled temperature or resistance "
        "acquisition. Heater control belongs to a separate interface."
    ),
)
class TemperatureReadoutInterface(Protocol):
    @acquisition(
        label="Sample sensor",
        description="Read a settled sample from one coherent scan channel.",
    )
    def sample(self) -> TemperatureSampleResults[float]: ...


@instrument_state
class RFOutputState:
    """Concrete continuous-wave RF output state schema."""

    frequency: Quantity = member_field(
        unit="Hz",
        label="CW frequency",
        description="Continuous-wave carrier frequency.",
    )
    power: Quantity = member_field(
        unit="dBm",
        label="Output power",
        description="Configured RF output level at the source connector.",
    )
    output_enabled: bool = member_field(
        label="RF output",
        description="Whether the RF output connector is enabled.",
    )
    reference_source: ReferenceSource = member_field(
        label="Reference source",
        description="Reference oscillator source; external frequency is not set.",
    )


@instrument_interface(
    "scopecat.rf_output/v1",
    state=RFOutputState,
    label="RF output",
    description="Continuous-wave RF source controls independent of vendor syntax.",
)
class RFOutputInterface(Protocol): ...


@instrument_state
class NetworkSweepState:
    """Concrete network-sweep state schema."""

    start_frequency: Quantity = member_field(
        unit="Hz",
        label="Start frequency",
        description="First stimulus frequency in the linear sweep.",
    )
    stop_frequency: Quantity = member_field(
        unit="Hz",
        label="Stop frequency",
        description="Last stimulus frequency in the linear sweep.",
    )
    points: int = member_field(
        minimum=2,
        label="Sweep points",
        description="Number of equally spaced frequency points.",
    )
    if_bandwidth: Quantity = member_field(
        unit="Hz",
        label="IF bandwidth",
        description="Receiver intermediate-frequency bandwidth.",
    )
    source_power: Quantity = member_field(
        unit="dBm",
        label="Source power",
        description="Stimulus power for the selected analyzer channel.",
    )
    s_parameter: SParameter = member_field(
        label="S-parameter",
        description="Two-port S-parameter measured by the selected trace.",
    )


@instrument_result
class NetworkSweepResults[FrequencyT, SParameterT]:
    """Network sweep fields reusable across acquisition runtimes."""

    frequency: FrequencyT = result_field(
        dtype="float64",
        unit="Hz",
        axes=("frequency",),
        label="Frequency",
        description="Stimulus frequency values for the acquired trace.",
    )
    s_parameter: SParameterT = result_field(
        dtype="complex128",
        unit="ratio",
        axes=("frequency",),
        label="Complex S-parameter",
        description="Complex response values for the configured S-parameter.",
    )


@instrument_interface(
    "scopecat.network_sweep/v1",
    state=NetworkSweepState,
    label="Network sweep",
    description="Linear, single-trigger complex S-parameter sweep.",
)
class NetworkSweepInterface(Protocol):
    @acquisition(
        label="Acquire sweep",
        description="Trigger and read the configured network sweep.",
        axes={
            "frequency": axis(
                size="points",
                kind="frequency",
                unit="Hz",
                label="Frequency",
                description="Linear VNA stimulus frequency.",
            )
        },
    )
    def sweep(self) -> NetworkSweepResults[list[float], list[complex]]: ...


__all__ = [
    "DCMonitorCurrentResults",
    "DCMonitorInterface",
    "DCMonitorState",
    "DCMonitorVoltageResults",
    "DCSourceInterface",
    "DCSourceMonitorInterface",
    "DCSourceObservation",
    "DCSourceState",
    "NetworkSweepInterface",
    "NetworkSweepResults",
    "NetworkSweepState",
    "RFOutputInterface",
    "RFOutputState",
    "ReferenceSource",
    "SParameter",
    "TemperatureReadoutInterface",
    "TemperatureReadoutObservation",
    "TemperatureSampleResults",
]
