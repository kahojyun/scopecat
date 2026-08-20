"""Measurement-valued results returned by OO instrument implementations."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import JsonValue
from scopecat.records.measurement import MeasurementAcquisitionValue


@dataclass(frozen=True, slots=True)
class TemperatureSampleDriverResult:
    temperature: MeasurementAcquisitionValue
    resistance: MeasurementAcquisitionValue
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DCBiasReadbackDriverResult:
    actual_voltage: MeasurementAcquisitionValue
    settled: MeasurementAcquisitionValue
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DCMonitorCurrentDriverResult:
    current: MeasurementAcquisitionValue
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DCMonitorVoltageDriverResult:
    voltage: MeasurementAcquisitionValue
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NetworkSweepDriverResult:
    frequency: MeasurementAcquisitionValue
    s_parameter: MeasurementAcquisitionValue
    metadata: dict[str, JsonValue] = field(default_factory=dict)


__all__ = [
    "DCBiasReadbackDriverResult",
    "DCMonitorCurrentDriverResult",
    "DCMonitorVoltageDriverResult",
    "NetworkSweepDriverResult",
    "TemperatureSampleDriverResult",
]
