"""Declarative experiment targets for first-party instrument interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.authoring import StateBinding, ValueRef
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import PropertyRef

from scopecat_instruments.members import (
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_IF_BANDWIDTH,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_SOURCE_POWER,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
)

type Desired[T] = T | ValueRef
type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@dataclass(frozen=True, slots=True)
class DCSourceTarget:
    """Sparse common DC-source state, without changing source mode."""

    voltage_protection: Desired[Quantity] | None = None
    current_protection: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
            (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
            (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
        )


@dataclass(frozen=True, slots=True)
class DCSourceVoltageTarget:
    """Desired voltage-source mode, with fixed or point-resolved fields."""

    range: Desired[Quantity]
    level: Desired[Quantity]
    voltage_protection: Desired[Quantity] | None = None
    current_protection: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return {
            DC_SOURCE_MODE: "voltage",
            DC_SOURCE_VOLTAGE_RANGE: self.range,
            DC_SOURCE_VOLTAGE_LEVEL: self.level,
            **_target_assignments(
                (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
                (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
                (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
            ),
        }


@dataclass(frozen=True, slots=True)
class DCSourceCurrentTarget:
    """Desired current-source mode, with fixed or point-resolved fields."""

    range: Desired[Quantity]
    level: Desired[Quantity]
    voltage_protection: Desired[Quantity] | None = None
    current_protection: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return {
            DC_SOURCE_MODE: "current",
            DC_SOURCE_CURRENT_RANGE: self.range,
            DC_SOURCE_CURRENT_LEVEL: self.level,
            **_target_assignments(
                (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
                (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
                (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
            ),
        }


@dataclass(frozen=True, slots=True)
class DCMonitorTarget:
    measurement_enabled: Desired[bool] | None = None
    integration_cycles: Desired[int] | None = None
    measurement_delay: Desired[Quantity] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (DC_MONITOR_MEASUREMENT_ENABLED, self.measurement_enabled),
            (DC_MONITOR_INTEGRATION_CYCLES, self.integration_cycles),
            (DC_MONITOR_MEASUREMENT_DELAY, self.measurement_delay),
        )


@dataclass(frozen=True, slots=True)
class RFOutputTarget:
    frequency: Desired[Quantity] | None = None
    power: Desired[Quantity] | None = None
    output_enabled: Desired[bool] | None = None
    reference_source: Desired[ReferenceSource] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (RF_OUTPUT_FREQUENCY, self.frequency),
            (RF_OUTPUT_POWER, self.power),
            (RF_OUTPUT_ENABLED, self.output_enabled),
            (RF_OUTPUT_REFERENCE_SOURCE, self.reference_source),
        )


@dataclass(frozen=True, slots=True)
class NetworkSweepTarget:
    start_frequency: Desired[Quantity] | None = None
    stop_frequency: Desired[Quantity] | None = None
    points: Desired[int] | None = None
    if_bandwidth: Desired[Quantity] | None = None
    source_power: Desired[Quantity] | None = None
    s_parameter: Desired[SParameter] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (NETWORK_SWEEP_START_FREQUENCY, self.start_frequency),
            (NETWORK_SWEEP_STOP_FREQUENCY, self.stop_frequency),
            (NETWORK_SWEEP_POINTS, self.points),
            (NETWORK_SWEEP_IF_BANDWIDTH, self.if_bandwidth),
            (NETWORK_SWEEP_SOURCE_POWER, self.source_power),
            (NETWORK_SWEEP_S_PARAMETER, self.s_parameter),
        )


@dataclass(frozen=True, slots=True)
class TemperatureReadoutTarget:
    scan_channel: Desired[int] | None = None
    autoscan_enabled: Desired[bool] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (TEMPERATURE_READOUT_SCAN_CHANNEL, self.scan_channel),
            (TEMPERATURE_READOUT_AUTOSCAN_ENABLED, self.autoscan_enabled),
        )


def _target_assignments(
    *items: tuple[PropertyRef, StateBinding | None],
) -> dict[PropertyRef, StateBinding]:
    return {property: value for property, value in items if value is not None}


__all__ = [
    "DCMonitorTarget",
    "DCSourceCurrentTarget",
    "DCSourceTarget",
    "DCSourceVoltageTarget",
    "Desired",
    "NetworkSweepTarget",
    "RFOutputTarget",
    "TemperatureReadoutTarget",
]
