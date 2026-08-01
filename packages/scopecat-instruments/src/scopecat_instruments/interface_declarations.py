"""Typed Python declarations for first-party instrument capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    acquisition,
    acquisition_case,
    axis,
    compile_interface,
    discriminated_state,
    instrument_interface,
    instrument_observed_state,
    instrument_result,
    instrument_state,
    interface_discriminator,
    member,
    precondition,
    result,
    state_case,
    state_discriminated_acquisition,
    state_field,
)

type Desired[T] = T | ValueRef
type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@instrument_state
@dataclass(frozen=True, slots=True)
class DCSourceState:
    """Sparse common DC-source state, without changing source mode."""

    voltage_protection: Annotated[
        Desired[Quantity] | None,
        member(
            unit="V",
            label="Voltage protection",
            description="Absolute voltage limiter level.",
        ),
    ] = None
    current_protection: Annotated[
        Desired[Quantity] | None,
        member(
            unit="A",
            label="Current protection",
            description="Absolute current limiter level.",
        ),
    ] = None
    output_enabled: Annotated[
        Desired[bool] | None,
        member(
            label="DC output",
            description="Whether the source output is enabled.",
        ),
    ] = None


@instrument_state
@dataclass(frozen=True, slots=True)
class DCSourceVoltage:
    """Desired voltage-source mode, with fixed or point-resolved fields."""

    range: Annotated[
        Desired[Quantity],
        member(
            id="voltage_range",
            unit="V",
            label="Voltage range",
            description="Voltage-source range, available in voltage mode.",
        ),
    ]
    level: Annotated[
        Desired[Quantity],
        member(
            id="voltage_level",
            unit="V",
            label="Voltage level",
            description="Voltage-source level, available in voltage mode.",
        ),
    ]
    voltage_protection: Desired[Quantity] | None = None
    current_protection: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None


@instrument_state
@dataclass(frozen=True, slots=True)
class DCSourceCurrent:
    """Desired current-source mode, with fixed or point-resolved fields."""

    range: Annotated[
        Desired[Quantity],
        member(
            id="current_range",
            unit="A",
            label="Current range",
            description="Current-source range, available in current mode.",
        ),
    ]
    level: Annotated[
        Desired[Quantity],
        member(
            id="current_level",
            unit="A",
            label="Current level",
            description="Current-source level, available in current mode.",
        ),
    ]
    voltage_protection: Desired[Quantity] | None = None
    current_protection: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None


@instrument_interface(
    "scopecat.dc_source/v2",
    state=discriminated_state(
        member(
            id="source_mode",
            choices=("voltage", "current"),
            label="Source mode",
            description="Discriminator selecting voltage or current source state.",
        ),
        common=DCSourceState,
        cases=(
            state_case(
                "voltage",
                DCSourceVoltage,
                fields=("range", "level"),
                required_on_entry=("range", "level"),
            ),
            state_case(
                "current",
                DCSourceCurrent,
                fields=("range", "level"),
                required_on_entry=("range", "level"),
            ),
        ),
    ),
    label="DC source",
    description=(
        "DC voltage/current source controls with mode-specific level and range state."
    ),
)
class DCSourceInterface(Protocol): ...


DC_SOURCE_DECLARATION: CompiledInterface[DCSourceInterface] = compile_interface(
    DCSourceInterface
)


@instrument_state
@dataclass(frozen=True, slots=True)
class DCMonitorState:
    measurement_enabled: Annotated[
        Desired[bool] | None,
        member(
            label="Measurement",
            description="Whether monitor measurements are enabled.",
        ),
    ] = None
    integration_cycles: Annotated[
        Desired[int] | None,
        member(
            minimum=1,
            maximum=25,
            label="Integration cycles",
            description="Power-line cycles integrated for each measurement.",
        ),
    ] = None
    measurement_delay: Annotated[
        Desired[Quantity] | None,
        member(
            unit="s",
            minimum=0.0,
            maximum=999.999,
            label="Measurement delay",
            description="Delay between measurement trigger and sampling.",
        ),
    ] = None


@instrument_result
@dataclass(frozen=True, slots=True)
class _DCMonitorCurrentResults:
    current: Annotated[
        float,
        result(
            id="monitored_current",
            dtype="float64",
            unit="A",
            label="Monitored current",
            description="One measurement while sourcing voltage.",
        ),
    ]


@instrument_result
@dataclass(frozen=True, slots=True)
class _DCMonitorVoltageResults:
    voltage: Annotated[
        float,
        result(
            id="monitored_voltage",
            dtype="float64",
            unit="V",
            label="Monitored voltage",
            description="One measurement while sourcing current.",
        ),
    ]


@dataclass(frozen=True, slots=True)
class _DCMonitorResultShape:
    current: float | None
    voltage: float | None


@instrument_interface(
    "scopecat.dc_monitor/v3",
    state=DCMonitorState,
    label="DC monitor",
    description="Single-value voltage or current monitoring for a DC source.",
)
class DCMonitorInterface(Protocol):
    @state_discriminated_acquisition(
        interface_discriminator(DCSourceInterface),
        label="Monitor output",
        description="Read one monitor sample from the active source mode.",
        preconditions=(
            precondition(
                state_field(DCSourceState, "output_enabled"),
                value=True,
                unavailable_reason="DC source output is disabled.",
            ),
            precondition(
                state_field(DCMonitorState, "measurement_enabled"),
                value=True,
                unavailable_reason="DC monitor measurement is disabled.",
            ),
        ),
        cases=(
            acquisition_case("voltage", _DCMonitorCurrentResults),
            acquisition_case("current", _DCMonitorVoltageResults),
        ),
    )
    def monitor(self) -> _DCMonitorResultShape: ...


DC_MONITOR_DECLARATION: CompiledInterface[DCMonitorInterface] = compile_interface(
    DCMonitorInterface
)


@instrument_observed_state
@dataclass(frozen=True, slots=True)
class TemperatureReadoutObservation:
    """Scanner state reported by a temperature readout."""

    scan_channel: Annotated[
        int,
        member(
            minimum=1,
            maximum=16,
            label="Scan channel",
            description="Sensor input currently selected by the scanner.",
        ),
    ]
    autoscan_enabled: Annotated[
        bool,
        member(
            label="Autoscan",
            description="Whether the input scanner is advancing automatically.",
        ),
    ]


@instrument_result
@dataclass(frozen=True, slots=True)
class TemperatureSampleResults[ValueT]:
    """Temperature sample fields reusable across acquisition runtimes."""

    temperature: Annotated[
        ValueT,
        result(
            dtype="float64",
            unit="K",
            label="Temperature",
            description="Current scan-channel temperature.",
        ),
    ]
    resistance: Annotated[
        ValueT,
        result(
            dtype="float64",
            unit="Ohm",
            label="Resistance",
            description="Current scan-channel sensor resistance.",
        ),
    ]


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


TEMPERATURE_READOUT_DECLARATION: CompiledInterface[TemperatureReadoutInterface] = (
    compile_interface(TemperatureReadoutInterface)
)


@instrument_state
@dataclass(frozen=True, slots=True)
class RFOutputState:
    """Sparse continuous-wave RF output state."""

    frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="CW frequency",
            description="Continuous-wave carrier frequency.",
        ),
    ] = None
    power: Annotated[
        Desired[Quantity] | None,
        member(
            unit="dBm",
            label="Output power",
            description="Configured RF output level at the source connector.",
        ),
    ] = None
    output_enabled: Annotated[
        Desired[bool] | None,
        member(
            label="RF output",
            description="Whether the RF output connector is enabled.",
        ),
    ] = None
    reference_source: Annotated[
        Desired[ReferenceSource] | None,
        member(
            label="Reference source",
            description=("Reference oscillator source; external frequency is not set."),
        ),
    ] = None


@instrument_interface(
    "scopecat.rf_output/v1",
    state=RFOutputState,
    label="RF output",
    description="Continuous-wave RF source controls independent of vendor syntax.",
)
class RFOutputInterface(Protocol): ...


RF_OUTPUT_DECLARATION: CompiledInterface[RFOutputInterface] = compile_interface(
    RFOutputInterface
)


@instrument_state
@dataclass(frozen=True, slots=True)
class NetworkSweepState:
    """Sparse network-sweep state shared by live and symbolic clients."""

    start_frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="Start frequency",
            description="First stimulus frequency in the linear sweep.",
        ),
    ] = None
    stop_frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="Stop frequency",
            description="Last stimulus frequency in the linear sweep.",
        ),
    ] = None
    points: Annotated[
        Desired[int] | None,
        member(
            minimum=2,
            label="Sweep points",
            description="Number of equally spaced frequency points.",
        ),
    ] = None
    if_bandwidth: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="IF bandwidth",
            description="Receiver intermediate-frequency bandwidth.",
        ),
    ] = None
    source_power: Annotated[
        Desired[Quantity] | None,
        member(
            unit="dBm",
            label="Source power",
            description="Stimulus power for the selected analyzer channel.",
        ),
    ] = None
    s_parameter: Annotated[
        Desired[SParameter] | None,
        member(
            label="S-parameter",
            description="Two-port S-parameter measured by the selected trace.",
        ),
    ] = None


@instrument_result
@dataclass(frozen=True, slots=True)
class NetworkSweepResults[FrequencyT, SParameterT]:
    """Network sweep fields reusable across acquisition runtimes."""

    frequency: Annotated[
        FrequencyT,
        result(
            dtype="float64",
            unit="Hz",
            axes=("frequency",),
            label="Frequency",
            description="Stimulus frequency values for the acquired trace.",
        ),
    ]
    s_parameter: Annotated[
        SParameterT,
        result(
            dtype="complex128",
            unit="ratio",
            axes=("frequency",),
            label="Complex S-parameter",
            description=("Complex response values for the configured S-parameter."),
        ),
    ]


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


NETWORK_SWEEP_DECLARATION: CompiledInterface[NetworkSweepInterface] = compile_interface(
    NetworkSweepInterface
)


__all__ = [
    "DC_MONITOR_DECLARATION",
    "DC_SOURCE_DECLARATION",
    "NETWORK_SWEEP_DECLARATION",
    "RF_OUTPUT_DECLARATION",
    "TEMPERATURE_READOUT_DECLARATION",
    "DCMonitorInterface",
    "DCMonitorState",
    "DCSourceCurrent",
    "DCSourceInterface",
    "DCSourceState",
    "DCSourceVoltage",
    "Desired",
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
