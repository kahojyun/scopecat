"""Minimal Yokogawa GS200/GS210 SCPI driver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import MeasurementScalar, MeasurementUnavailable
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentDescription,
)
from scopecat.sdk.instruments.scpi import (
    ScpiIdentity,
    ScpiTransport,
    TransportError,
    format_number,
    parse_float,
    query_bool,
    query_float,
    query_identity,
    query_int,
    query_text,
)

from scopecat_instruments._support import (
    apply_unknown,
    collect_unknown,
    execution_problem,
    quantity_value,
    state_property_problem,
    state_sync_failed,
    unsupported_invoke,
)
from scopecat_instruments.driver_ids import YOKOGAWA_GS200
from scopecat_instruments.driver_states import (
    DCSourceDriverPatch,
    decode_dc_monitor_patch,
    decode_dc_source_patch,
    encode_dc_monitor_state,
    encode_dc_source_current_state,
    encode_dc_source_state,
    encode_dc_source_voltage_state,
    encode_driver_state,
)
from scopecat_instruments.interface_declarations import (
    DCMonitorState,
    DCSourceCurrent,
    DCSourceState,
    DCSourceVoltage,
)
from scopecat_instruments.interfaces import dc_monitor_interface, dc_source_interface
from scopecat_instruments.members import (
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_RANGE,
)

_CONDITION_END_OF_MEASURE = 1 << 0
_CONDITION_OVER_RANGE = 1 << 1
_CONDITION_NO_TRIGGER_SAMPLING_ERROR = 1 << 4


@dataclass(frozen=True)
class _GS200Snapshot:
    source: DCSourceState
    active_source: DCSourceVoltage | DCSourceCurrent
    monitor: DCMonitorState | None
    metadata: dict[str, JsonValue]

    @property
    def source_mode(self) -> Literal["voltage", "current"]:
        if isinstance(self.active_source, DCSourceVoltage):
            return "voltage"
        return "current"


class YokogawaGS200:
    """GS200 source controls plus optional /MON single-value measurement."""

    implementation_id = YOKOGAWA_GS200
    implementation_version = "v2"

    def __init__(
        self,
        instrument_id: str,
        transport: ScpiTransport,
        *,
        monitor_option: bool = False,
        remote_sense: bool = False,
        guard_enabled: bool = False,
    ) -> None:
        self.instrument_id = instrument_id
        self.transport = transport
        self.monitor_option = monitor_option
        self.remote_sense = remote_sense
        self.guard_enabled = guard_enabled
        self._identity: ScpiIdentity | None = None

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Yokogawa GS200",
            description=(
                "Voltage/current source driver. /MON state and collection are exposed "
                "only when selected by the connection profile."
            ),
            interfaces=[
                dc_source_interface(),
                *([dc_monitor_interface()] if self.monitor_option else []),
            ],
        )

    def read_state(self) -> DriverState:
        snapshot = self._read_snapshot()
        encoded_states = [encode_dc_source_state(snapshot.source)]
        if isinstance(snapshot.active_source, DCSourceVoltage):
            encoded_states.append(
                encode_dc_source_voltage_state(snapshot.active_source)
            )
        else:
            encoded_states.append(
                encode_dc_source_current_state(snapshot.active_source)
            )
        if snapshot.monitor is not None:
            encoded_states.append(encode_dc_monitor_state(snapshot.monitor))
        return encode_driver_state(*encoded_states, metadata=snapshot.metadata)

    def _read_snapshot(self) -> _GS200Snapshot:
        self._validate_connection_profile()
        mode = self.source_mode()
        source_range = self.source_range()
        self._validate_source_profile(mode, source_range)
        active_unit = "V" if mode == "voltage" else "A"
        active_source: DCSourceVoltage | DCSourceCurrent
        if mode == "voltage":
            active_source = DCSourceVoltage(
                range=Quantity(source_range, active_unit),
                level=Quantity(self.source_level(), active_unit),
            )
        else:
            active_source = DCSourceCurrent(
                range=Quantity(source_range, active_unit),
                level=Quantity(self.source_level(), active_unit),
            )
        source = DCSourceState(
            voltage_protection=Quantity(self.voltage_protection(), "V"),
            current_protection=Quantity(self.current_protection(), "A"),
            output_enabled=self.output_enabled(),
        )
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Yokogawa",
            "model": "GS200",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        monitor = (
            DCMonitorState(
                measurement_enabled=self.measurement_enabled(),
                integration_cycles=self.integration_cycles(),
                measurement_delay=Quantity(self.measurement_delay(), "s"),
            )
            if self.monitor_option
            else None
        )
        return _GS200Snapshot(
            source=source,
            active_source=active_source,
            monitor=monitor,
            metadata=metadata,
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        try:
            baseline = self._read_snapshot()
        except TransportError:
            # A not_applied receipt would keep a transport that cannot be reused.
            raise
        except Exception as error:
            return state_sync_failed(self.instrument_id, error)

        try:
            source_patch = decode_dc_source_patch(request)
            monitor_patch = decode_dc_monitor_patch(request)
            current_mode = baseline.source_mode
            current_output = baseline.source.output_enabled
            target_mode = source_patch.get("source_mode", current_mode)
            target_output = source_patch.get("output_enabled", current_output)
            if not self._remote_sense_target_is_valid(
                source_patch,
                baseline,
                target_mode=target_mode,
            ):
                return DriverRejected(
                    problems=(
                        execution_problem(
                            "gs200_remote_sense_voltage_range_incompatible",
                            "GS200 remote sense requires an explicit voltage range "
                            "of at least 1 V",
                            "driver_state_patch",
                            "values",
                        ),
                    )
                )
            current_measurement = False
            target_measurement = False
            changes_measurement_settings = False
            if baseline.monitor is not None:
                current_measurement = baseline.monitor.measurement_enabled
                target_measurement = monitor_patch.get(
                    "measurement_enabled",
                    current_measurement,
                )
                changes_measurement_settings = (
                    "integration_cycles" in monitor_patch
                    or "measurement_delay" in monitor_patch
                )
            changes_source_state = target_mode != current_mode or any(
                key in source_patch
                for key in (
                    "voltage_range",
                    "current_range",
                    "voltage_level",
                    "current_level",
                )
            )
            # Protection values are compliance controls designed for live adjustment.
            disabled_for_update = current_output and (
                not target_output or changes_source_state
            )

            if disabled_for_update:
                self.set_output(False)
            if target_mode != current_mode:
                self.set_source_mode(target_mode)
            if "voltage_range" in source_patch:
                self.set_source_range(
                    quantity_value(source_patch["voltage_range"], "V")
                )
            if "current_range" in source_patch:
                self.set_source_range(
                    quantity_value(source_patch["current_range"], "A")
                )
            if "voltage_protection" in source_patch:
                self.set_voltage_protection(
                    quantity_value(source_patch["voltage_protection"], "V")
                )
            if "current_protection" in source_patch:
                self.set_current_protection(
                    quantity_value(source_patch["current_protection"], "A")
                )
            if "voltage_level" in source_patch:
                self.set_source_level(
                    quantity_value(source_patch["voltage_level"], "V")
                )
            if "current_level" in source_patch:
                self.set_source_level(
                    quantity_value(source_patch["current_level"], "A")
                )
            if baseline.monitor is not None:
                measurement_disabled_for_update = (
                    current_measurement and changes_measurement_settings
                )
                if measurement_disabled_for_update:
                    self.set_measurement_enabled(False)
                if "integration_cycles" in monitor_patch:
                    self.set_integration_cycles(monitor_patch["integration_cycles"])
                if "measurement_delay" in monitor_patch:
                    self.set_measurement_delay(
                        quantity_value(monitor_patch["measurement_delay"], "s")
                    )
                effective_measurement = (
                    False if measurement_disabled_for_update else current_measurement
                )
                if target_measurement != effective_measurement:
                    self.set_measurement_enabled(target_measurement)
            effective_output = False if disabled_for_update else current_output
            if target_output != effective_output:
                self.set_output(target_output)
            return DriverSuccess(self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return unsupported_invoke(request, self.instrument_id)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        try:
            mode = self.source_mode()
            active_result = (
                DC_MONITOR_CURRENT_RESULT
                if mode == "voltage"
                else DC_MONITOR_VOLTAGE_RESULT
            )
            if request.results != frozenset({active_result}):
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_monitor_result_inactive",
                            f"{mode} source mode provides only "
                            f"{active_result.result_id}",
                            DC_SOURCE_MODE,
                        ),
                    )
                )
            if not self.output_enabled():
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_output_disabled",
                            "GS200 output must be enabled for monitor collection",
                            DC_SOURCE_OUTPUT_ENABLED,
                        ),
                    )
                )
            if not self.measurement_enabled():
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_monitor_disabled",
                            "GS200 monitor measurement is disabled",
                            DC_MONITOR_MEASUREMENT_ENABLED,
                        ),
                    )
                )
            if mode == "voltage" and self.source_range() < 1.0:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_monitor_voltage_range_too_low",
                            "GS200 current monitoring requires at least the 1 V range",
                            DC_SOURCE_VOLTAGE_RANGE,
                        ),
                    )
                )
            if self.measurement_null_enabled():
                # NULL alters the value without exposing its stored offset.
                return DriverRejected(
                    problems=(
                        execution_problem(
                            "gs200_monitor_null_enabled",
                            "GS200 monitor NULL must be disabled before collection",
                            "driver_acquisition",
                            "acquisition_id",
                        ),
                    )
                )

            unit = "A" if mode == "voltage" else "V"
            original_trigger = self.measurement_trigger()
            restore_trigger = original_trigger != "COMM"
            try:
                if restore_trigger:
                    self.set_measurement_trigger("COMM")
                raw_measurement = self.transport.query(":MEAS?")
                condition = query_int(self.transport, ":STAT:COND?")
            finally:
                if restore_trigger:
                    self.set_measurement_trigger(original_trigger)

            if (
                condition & _CONDITION_END_OF_MEASURE == 0
                or condition & _CONDITION_NO_TRIGGER_SAMPLING_ERROR == 0
            ):
                measured = MeasurementUnavailable.create(
                    reason="invalid",
                    dtype="float64",
                    unit=unit,
                    shape=(),
                    metadata={"status_condition": condition},
                )
            elif condition & _CONDITION_OVER_RANGE:
                measured = MeasurementUnavailable.create(
                    reason="overload",
                    dtype="float64",
                    unit=unit,
                    shape=(),
                    metadata={"status_condition": condition},
                )
            else:
                measured = MeasurementScalar.create(
                    dtype="float64",
                    unit=unit,
                    value=parse_float(raw_measurement, command=":MEAS?"),
                )
            return DriverSuccess(
                DriverReadback(
                    values=dict.fromkeys(request.results, measured),
                    metadata={
                        "manufacturer": "Yokogawa",
                        "model": "GS200",
                        "source_mode": mode,
                    },
                ),
            )
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def set_source_mode(self, mode: str) -> None:
        command = {"voltage": "VOLT", "current": "CURR"}.get(mode)
        if command is None:
            raise ValueError("GS200 source mode must be voltage or current")
        self.transport.write(f":SOUR:FUNC {command}")

    def source_mode(self) -> Literal["voltage", "current"]:
        response = query_text(self.transport, ":SOUR:FUNC?").upper()
        if response.startswith("VOLT"):
            return "voltage"
        if response.startswith("CURR"):
            return "current"
        raise ValueError(f"GS200 returned unknown source mode {response!r}")

    def set_source_range(self, value: float) -> None:
        self.transport.write(f":SOUR:RANG {format_number(value)}")

    def source_range(self) -> float:
        return query_float(self.transport, ":SOUR:RANG?")

    def set_source_level(self, value: float) -> None:
        self.transport.write(f":SOUR:LEV {format_number(value)}")

    def source_level(self) -> float:
        return query_float(self.transport, ":SOUR:LEV?")

    def set_voltage_protection(self, value_v: float) -> None:
        self.transport.write(f":SOUR:PROT:VOLT {format_number(value_v)}")

    def voltage_protection(self) -> float:
        return query_float(self.transport, ":SOUR:PROT:VOLT?")

    def set_current_protection(self, value_a: float) -> None:
        self.transport.write(f":SOUR:PROT:CURR {format_number(value_a)}")

    def current_protection(self) -> float:
        return query_float(self.transport, ":SOUR:PROT:CURR?")

    def set_output(self, enabled: bool) -> None:
        self.transport.write(f":OUTP {'ON' if enabled else 'OFF'}")

    def output_enabled(self) -> bool:
        return query_bool(self.transport, ":OUTP?")

    def set_measurement_enabled(self, enabled: bool) -> None:
        self.transport.write(f":SENS {'ON' if enabled else 'OFF'}")

    def measurement_enabled(self) -> bool:
        return query_bool(self.transport, ":SENS?")

    def set_integration_cycles(self, cycles: int) -> None:
        if not 1 <= cycles <= 25:
            raise ValueError("GS200 integration cycles must be between 1 and 25")
        self.transport.write(f":SENS:NPLC {cycles}")

    def integration_cycles(self) -> int:
        value = query_float(self.transport, ":SENS:NPLC?")
        cycles = int(value)
        if value != cycles or not 1 <= cycles <= 25:
            raise ValueError(f"GS200 returned invalid integration cycles {value!r}")
        return cycles

    def set_measurement_delay(self, delay_s: float) -> None:
        if not 0.0 <= delay_s <= 999.999:
            raise ValueError(
                "GS200 measurement delay must be between 0 and 999.999 seconds"
            )
        self.transport.write(f":SENS:DEL {format_number(delay_s)}")

    def measurement_delay(self) -> float:
        delay_s = query_float(self.transport, ":SENS:DEL?")
        if not 0.0 <= delay_s <= 999.999:
            raise ValueError(f"GS200 returned invalid measurement delay {delay_s!r}")
        return delay_s

    def measurement_null_enabled(self) -> bool:
        return query_bool(self.transport, ":SENS:NULL?")

    def set_measurement_trigger(self, trigger: str) -> None:
        self.transport.write(f":SENS:TRIG {trigger}")

    def measurement_trigger(self) -> str:
        trigger = query_text(self.transport, ":SENS:TRIG?").upper()
        if not trigger:
            raise ValueError("GS200 returned an empty measurement trigger")
        return trigger

    def _validate_connection_profile(self) -> None:
        remote_sense = query_bool(self.transport, ":SENS:REM?")
        guard_enabled = query_bool(self.transport, ":SENS:GUAR?")
        if remote_sense != self.remote_sense:
            raise ValueError(
                "GS200 remote-sense state differs from the connection profile"
            )
        if guard_enabled != self.guard_enabled:
            raise ValueError("GS200 guard state differs from the connection profile")

    def _validate_source_profile(self, mode: str, source_range: float) -> None:
        if not self._source_profile_is_valid(mode, source_range):
            raise ValueError(
                "GS200 remote sense requires a voltage range of at least 1 V"
            )

    def _source_profile_is_valid(self, mode: str, source_range: float) -> bool:
        return not (self.remote_sense and mode == "voltage" and source_range < 1.0)

    def _remote_sense_target_is_valid(
        self,
        patch: DCSourceDriverPatch,
        baseline: _GS200Snapshot,
        *,
        target_mode: Literal["voltage", "current"],
    ) -> bool:
        if not self.remote_sense or target_mode != "voltage":
            return True
        if "voltage_range" in patch:
            target_range = quantity_value(patch["voltage_range"], "V")
        elif isinstance(baseline.active_source, DCSourceVoltage):
            target_range = quantity_value(baseline.active_source.range, "V")
        else:
            return False
        return self._source_profile_is_valid(target_mode, target_range)

    def identify(self) -> ScpiIdentity:
        identity = query_identity(self.transport)
        manufacturer = identity.manufacturer.upper()
        model = identity.model.upper()
        if "YOKOGAWA" not in manufacturer or model not in {"GS200", "GS210"}:
            raise ValueError(
                f"expected a Yokogawa GS200 family device, got {identity.raw!r}"
            )
        if self.monitor_option:
            option_response = query_text(self.transport, "*OPT?")
            if "/MON" not in option_response.upper():
                raise ValueError("GS200 connection profile requires the /MON option")
        self._validate_connection_profile()
        self._identity = identity
        return identity

    def disconnect(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """GS200 source and monitor operations are synchronous."""


__all__ = ["YokogawaGS200"]
