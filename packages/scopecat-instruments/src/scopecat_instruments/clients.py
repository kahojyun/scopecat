"""Typed notebook clients for the first-party instrument interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scopecat.api._instruments import (
    InstrumentRef,
    InstrumentSessionHandle,
    instrument,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateLiteral
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentDescription,
    PropertyRef,
)

from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_IF_BANDWIDTH,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    NETWORK_SWEEP_SOURCE_POWER,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
    TEMPERATURE_READOUT_RESISTANCE_RESULT,
    TEMPERATURE_READOUT_SAMPLE,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)

type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@dataclass(frozen=True, slots=True)
class DCSourcePatch:
    """Sparse common-state transition that does not change source mode."""

    voltage_protection: Quantity | None = None
    current_protection: Quantity | None = None
    output_enabled: bool | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return _assignments(
            (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
            (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
            (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
        )


@dataclass(frozen=True, slots=True)
class DCSourceVoltagePatch:
    """Complete entry into voltage-source mode plus optional common state."""

    range: Quantity
    level: Quantity
    voltage_protection: Quantity | None = None
    current_protection: Quantity | None = None
    output_enabled: bool | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return {
            DC_SOURCE_MODE: "voltage",
            DC_SOURCE_VOLTAGE_RANGE: self.range,
            DC_SOURCE_VOLTAGE_LEVEL: self.level,
            **_assignments(
                (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
                (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
                (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
            ),
        }


@dataclass(frozen=True, slots=True)
class DCSourceCurrentPatch:
    """Complete entry into current-source mode plus optional common state."""

    range: Quantity
    level: Quantity
    voltage_protection: Quantity | None = None
    current_protection: Quantity | None = None
    output_enabled: bool | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return {
            DC_SOURCE_MODE: "current",
            DC_SOURCE_CURRENT_RANGE: self.range,
            DC_SOURCE_CURRENT_LEVEL: self.level,
            **_assignments(
                (DC_SOURCE_VOLTAGE_PROTECTION, self.voltage_protection),
                (DC_SOURCE_CURRENT_PROTECTION, self.current_protection),
                (DC_SOURCE_OUTPUT_ENABLED, self.output_enabled),
            ),
        }


@dataclass(frozen=True, slots=True)
class DCMonitorPatch:
    measurement_enabled: bool | None = None
    integration_cycles: int | None = None
    measurement_delay: Quantity | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return _assignments(
            (DC_MONITOR_MEASUREMENT_ENABLED, self.measurement_enabled),
            (DC_MONITOR_INTEGRATION_CYCLES, self.integration_cycles),
            (DC_MONITOR_MEASUREMENT_DELAY, self.measurement_delay),
        )


@dataclass(frozen=True, slots=True)
class RFOutputPatch:
    frequency: Quantity | None = None
    power: Quantity | None = None
    output_enabled: bool | None = None
    reference_source: ReferenceSource | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return _assignments(
            (RF_OUTPUT_FREQUENCY, self.frequency),
            (RF_OUTPUT_POWER, self.power),
            (RF_OUTPUT_ENABLED, self.output_enabled),
            (RF_OUTPUT_REFERENCE_SOURCE, self.reference_source),
        )


@dataclass(frozen=True, slots=True)
class NetworkSweepPatch:
    start_frequency: Quantity | None = None
    stop_frequency: Quantity | None = None
    points: int | None = None
    if_bandwidth: Quantity | None = None
    source_power: Quantity | None = None
    s_parameter: SParameter | None = None

    def assignments(self) -> dict[PropertyRef, StateLiteral]:
        return _assignments(
            (NETWORK_SWEEP_START_FREQUENCY, self.start_frequency),
            (NETWORK_SWEEP_STOP_FREQUENCY, self.stop_frequency),
            (NETWORK_SWEEP_POINTS, self.points),
            (NETWORK_SWEEP_IF_BANDWIDTH, self.if_bandwidth),
            (NETWORK_SWEEP_SOURCE_POWER, self.source_power),
            (NETWORK_SWEEP_S_PARAMETER, self.s_parameter),
        )


@dataclass(frozen=True, slots=True)
class NetworkSweepReadback:
    """Named network-sweep results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    frequency: MeasurementValue | None
    s_parameter: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class TemperatureReadback:
    """Named temperature-readout results plus their explicit effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    temperature: MeasurementValue | None
    resistance: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class DCMonitorReadback:
    """Named mode-dependent monitor results plus their effect receipt."""

    receipt: CollectReceipt = field(repr=False)
    current: MeasurementValue | None
    voltage: MeasurementValue | None


@dataclass(frozen=True, slots=True)
class _InstrumentClient:
    _session: InstrumentSessionHandle = field(repr=False)
    instrument_id: str

    def describe(self) -> InstrumentDescription:
        return self._session.describe(self.instrument_id)

    def observed_state(self) -> InstrumentStateSnapshot:
        return self._session.observed_state(self.instrument_id)

    def refresh(self) -> InstrumentStateSnapshot:
        return self._session.read_state(self.instrument_id)


class DCSourceClient(_InstrumentClient):
    def apply(
        self,
        patch: (
            DCSourcePatch | DCSourceVoltagePatch | DCSourceCurrentPatch | DCMonitorPatch
        ),
    ) -> ApplyReceipt:
        return self._session.apply(
            patch.assignments(),
            instrument_id=self.instrument_id,
        )

    def monitor(self) -> DCMonitorReadback:
        receipt = self._session.collect(
            DC_MONITOR_ACQUISITION,
            instrument_id=self.instrument_id,
        )
        return DCMonitorReadback(
            receipt=receipt,
            current=_readback_value(receipt, DC_MONITOR_CURRENT_RESULT.result_id),
            voltage=_readback_value(receipt, DC_MONITOR_VOLTAGE_RESULT.result_id),
        )


class RFOutputClient(_InstrumentClient):
    def apply(self, patch: RFOutputPatch) -> ApplyReceipt:
        return self._session.apply(
            patch.assignments(),
            instrument_id=self.instrument_id,
        )


class NetworkSweepClient(_InstrumentClient):
    def apply(self, patch: NetworkSweepPatch) -> ApplyReceipt:
        return self._session.apply(
            patch.assignments(),
            instrument_id=self.instrument_id,
        )

    def sweep(self) -> NetworkSweepReadback:
        receipt = self._session.collect(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_FREQUENCY_RESULT,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
            instrument_id=self.instrument_id,
        )
        return NetworkSweepReadback(
            receipt=receipt,
            frequency=_readback_value(
                receipt,
                NETWORK_SWEEP_FREQUENCY_RESULT.result_id,
            ),
            s_parameter=_readback_value(
                receipt,
                NETWORK_SWEEP_S_PARAMETER_RESULT.result_id,
            ),
        )


class TemperatureReadoutClient(_InstrumentClient):
    def sample(self) -> TemperatureReadback:
        receipt = self._session.collect(
            TEMPERATURE_READOUT_SAMPLE,
            instrument_id=self.instrument_id,
        )
        return TemperatureReadback(
            receipt=receipt,
            temperature=_readback_value(
                receipt,
                TEMPERATURE_READOUT_TEMPERATURE_RESULT.result_id,
            ),
            resistance=_readback_value(
                receipt,
                TEMPERATURE_READOUT_RESISTANCE_RESULT.result_id,
            ),
        )


def dc_source(instrument_id: str) -> InstrumentRef[DCSourceClient]:
    return instrument(instrument_id, DCSourceClient)


def rf_output(instrument_id: str) -> InstrumentRef[RFOutputClient]:
    return instrument(instrument_id, RFOutputClient)


def network_sweep(instrument_id: str) -> InstrumentRef[NetworkSweepClient]:
    return instrument(instrument_id, NetworkSweepClient)


def temperature_readout(instrument_id: str) -> InstrumentRef[TemperatureReadoutClient]:
    return instrument(instrument_id, TemperatureReadoutClient)


def _assignments(
    *items: tuple[PropertyRef, StateLiteral | None],
) -> dict[PropertyRef, StateLiteral]:
    return {target: value for target, value in items if value is not None}


def _readback_value(
    receipt: CollectReceipt,
    result_id: str,
) -> MeasurementValue | None:
    readback = receipt.readback
    return None if readback is None else readback.values.get(result_id)


__all__ = [
    "DCMonitorPatch",
    "DCMonitorReadback",
    "DCSourceClient",
    "DCSourceCurrentPatch",
    "DCSourcePatch",
    "DCSourceVoltagePatch",
    "NetworkSweepClient",
    "NetworkSweepPatch",
    "NetworkSweepReadback",
    "RFOutputClient",
    "RFOutputPatch",
    "ReferenceSource",
    "SParameter",
    "TemperatureReadback",
    "TemperatureReadoutClient",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
]
