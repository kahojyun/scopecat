"""Typed sparse states shared by direct control and experiment authoring."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.authoring import StateBinding
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import PropertyRef

from scopecat_instruments.interface_declarations import (
    Desired,
    NetworkSweepState,
    ReferenceSource,
    RFOutputState,
)
from scopecat_instruments.interface_declarations import (
    SParameter as SParameter,
)
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
)


@dataclass(frozen=True, slots=True)
class DCSourceState:
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
class DCSourceVoltage:
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
class DCSourceCurrent:
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
class DCMonitorState:
    measurement_enabled: Desired[bool] | None = None
    integration_cycles: Desired[int] | None = None
    measurement_delay: Desired[Quantity] | None = None

    def target_assignments(self) -> dict[PropertyRef, StateBinding]:
        return _target_assignments(
            (DC_MONITOR_MEASUREMENT_ENABLED, self.measurement_enabled),
            (DC_MONITOR_INTEGRATION_CYCLES, self.integration_cycles),
            (DC_MONITOR_MEASUREMENT_DELAY, self.measurement_delay),
        )


def _target_assignments(
    *items: tuple[PropertyRef, StateBinding | None],
) -> dict[PropertyRef, StateBinding]:
    return {property: value for property, value in items if value is not None}


__all__ = [
    "DCMonitorState",
    "DCSourceCurrent",
    "DCSourceState",
    "DCSourceVoltage",
    "Desired",
    "NetworkSweepState",
    "RFOutputState",
    "ReferenceSource",
    "SParameter",
]
