"""Minimal Yokogawa GS200/GS210 SCPI driver."""

from __future__ import annotations

from typing import Literal, cast, override

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import (
    MeasurementAcquisitionValue,
    MeasurementScalar,
    MeasurementUnavailable,
)
from scopecat.sdk.instruments import (
    DriverOutcome,
    DriverRejected,
    DriverStateObservation,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    ObjectInstrumentDriver,
    device_member,
    instrument_driver,
    state_capture_request,
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
    invoke_unknown,
    quantity_value,
    state_property_problem,
    state_sync_failed,
)
from scopecat_instruments.driver_results import (
    DCMonitorCurrentDriverResult,
    DCMonitorVoltageDriverResult,
)
from scopecat_instruments.interface_declarations import (
    DCMonitorInterface,
    DCSourceInterface,
)
from scopecat_instruments.members import (
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_PROTECTION,
)
from scopecat_instruments.package_manifest import YOKOGAWA_GS200_DRIVER

_CONDITION_END_OF_MEASURE = 1 << 0
_CONDITION_OVER_RANGE = 1 << 1
_CONDITION_NO_TRIGGER_SAMPLING_ERROR = 1 << 4


@instrument_driver(
    YOKOGAWA_GS200_DRIVER.id,
    YOKOGAWA_GS200_DRIVER.implementation_version,
    interfaces=(DCSourceInterface, DCMonitorInterface),
    label="Yokogawa GS200",
    description="Voltage/current source with optional monitor capability.",
    device_schema_id="yokogawa.gs200/v1",
    device_label="Yokogawa GS200 connection profile",
    device_description=(
        "Model options and wiring modes validated by the concrete driver."
    ),
)
class YokogawaGS200(ObjectInstrumentDriver):
    """GS200 source controls plus optional /MON single-value measurement."""

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
        self._monitor_option = monitor_option
        self._remote_sense = remote_sense
        self._guard_enabled = guard_enabled
        self._identity: ScpiIdentity | None = None

    @property
    @device_member(
        description="Whether the instrument is expected to have the /MON option.",
    )
    def monitor_option(self) -> bool:
        return self._monitor_option

    @property
    @device_member(description="Expected remote-sense wiring mode.")
    def remote_sense(self) -> bool:
        return self._remote_sense

    @property
    @device_member(description="Expected driven-guard wiring mode.")
    def guard_enabled(self) -> bool:
        return self._guard_enabled

    @override
    def declared_interfaces(self) -> tuple[type[object], ...]:
        return (
            DCSourceInterface,
            *((DCMonitorInterface,) if self.monitor_option else ()),
        )

    @override
    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        self._validate_connection_profile()
        mode = self.source_mode
        if self.remote_sense and mode == "voltage":
            self._validate_source_profile(mode, self.source_range())
        readback = super().read_state(
            DriverStateReadRequest(request.targets - {DC_SOURCE_MODE})
        )
        observations = list(readback.observations)
        if DC_SOURCE_MODE in request.targets:
            observations.append(DriverStateObservation(DC_SOURCE_MODE, mode))
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Yokogawa",
            "model": "GS200",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return DriverStateReadback(
            observations=tuple(observations),
            metadata=metadata,
        )

    @override
    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        try:
            baseline = self.read_state(state_capture_request(self.describe()))
            current_output = cast("bool", baseline.values[DC_SOURCE_OUTPUT_ENABLED])
            current_measurement = cast(
                "bool",
                baseline.values.get(DC_MONITOR_MEASUREMENT_ENABLED, False),
            )
        except TransportError:
            # A not_applied receipt would keep a transport that cannot be reused.
            raise
        except Exception as error:
            return state_sync_failed(self.instrument_id, error)

        try:
            values = request.values
            target_output = cast(
                "bool", values.get(DC_SOURCE_OUTPUT_ENABLED, current_output)
            )
            target_measurement = cast(
                "bool",
                values.get(DC_MONITOR_MEASUREMENT_ENABLED, current_measurement),
            )
            changes_measurement_settings = (
                DC_MONITOR_INTEGRATION_CYCLES in values
                or DC_MONITOR_MEASUREMENT_DELAY in values
            )
            if DC_SOURCE_VOLTAGE_PROTECTION in values:
                self.voltage_protection = cast(
                    "Quantity", values[DC_SOURCE_VOLTAGE_PROTECTION]
                )
            if DC_SOURCE_CURRENT_PROTECTION in values:
                self.current_protection = cast(
                    "Quantity", values[DC_SOURCE_CURRENT_PROTECTION]
                )
            if self.monitor_option:
                measurement_disabled_for_update = (
                    current_measurement and changes_measurement_settings
                )
                if measurement_disabled_for_update:
                    self.measurement_enabled = False
                if DC_MONITOR_INTEGRATION_CYCLES in values:
                    self.integration_cycles = cast(
                        "int", values[DC_MONITOR_INTEGRATION_CYCLES]
                    )
                if DC_MONITOR_MEASUREMENT_DELAY in values:
                    self.measurement_delay = cast(
                        "Quantity", values[DC_MONITOR_MEASUREMENT_DELAY]
                    )
                effective_measurement = (
                    False if measurement_disabled_for_update else current_measurement
                )
                if target_measurement != effective_measurement:
                    self.measurement_enabled = target_measurement
            if target_output != current_output:
                self.output_enabled = target_output
            return DriverSuccess(None)
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def source_voltage(
        self,
        *,
        range: Quantity,
        level: Quantity,
    ) -> DriverOutcome[None]:
        range_v = quantity_value(range, "V")
        if not self._source_profile_is_valid("voltage", range_v):
            return DriverRejected(
                problems=(
                    execution_problem(
                        "gs200_remote_sense_voltage_range_incompatible",
                        "GS200 remote sense requires a voltage range of at least 1 V",
                        "driver_operation",
                        "arguments",
                        "range",
                    ),
                )
            )
        return self._source_transition(
            mode="voltage",
            range_value=range_v,
            level_value=quantity_value(level, "V"),
        )

    def source_current(
        self,
        *,
        range: Quantity,
        level: Quantity,
    ) -> DriverOutcome[None]:
        return self._source_transition(
            mode="current",
            range_value=quantity_value(range, "A"),
            level_value=quantity_value(level, "A"),
        )

    def _source_transition(
        self,
        *,
        mode: Literal["voltage", "current"],
        range_value: float,
        level_value: float,
    ) -> DriverOutcome[None]:
        try:
            output_enabled = self.output_enabled
            if output_enabled:
                self.set_output(False)
            self.set_source_mode(mode)
            self.set_source_range(range_value)
            self.set_source_level(level_value)
            if output_enabled:
                self.set_output(True)
            return DriverSuccess(None)
        except Exception as error:
            return invoke_unknown(self.instrument_id, error)

    def measure_current(
        self,
    ) -> DriverOutcome[DCMonitorCurrentDriverResult]:
        outcome = self._measure_monitor(expected_mode="voltage", unit="A")
        if not isinstance(outcome, DriverSuccess):
            return outcome
        return DriverSuccess(
            DCMonitorCurrentDriverResult(
                current=outcome.value,
                metadata={
                    "manufacturer": "Yokogawa",
                    "model": "GS200",
                    "source_mode": "voltage",
                },
            ),
            metadata=outcome.metadata,
        )

    def measure_voltage(
        self,
    ) -> DriverOutcome[DCMonitorVoltageDriverResult]:
        outcome = self._measure_monitor(expected_mode="current", unit="V")
        if not isinstance(outcome, DriverSuccess):
            return outcome
        return DriverSuccess(
            DCMonitorVoltageDriverResult(
                voltage=outcome.value,
                metadata={
                    "manufacturer": "Yokogawa",
                    "model": "GS200",
                    "source_mode": "current",
                },
            ),
            metadata=outcome.metadata,
        )

    def _measure_monitor(
        self,
        *,
        expected_mode: Literal["voltage", "current"],
        unit: Literal["A", "V"],
    ) -> DriverOutcome[MeasurementAcquisitionValue]:
        try:
            mode = self.source_mode
            if mode != expected_mode:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_monitor_source_mode_mismatch",
                            (
                                f"measurement requires {expected_mode} source mode, "
                                f"got {mode}"
                            ),
                            DC_SOURCE_MODE,
                        ),
                    )
                )
            if not self.output_enabled:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_output_disabled",
                            "GS200 output must be enabled for monitor collection",
                            DC_SOURCE_OUTPUT_ENABLED,
                        ),
                    )
                )
            if not self.measurement_enabled:
                return DriverRejected(
                    problems=(
                        state_property_problem(
                            "gs200_monitor_disabled",
                            "GS200 monitor measurement is disabled",
                            DC_MONITOR_MEASUREMENT_ENABLED,
                        ),
                    )
                )
            if expected_mode == "voltage" and self.source_range() < 1.0:
                return DriverRejected(
                    problems=(
                        execution_problem(
                            "gs200_monitor_voltage_range_too_low",
                            "GS200 current monitoring requires at least the 1 V range",
                            "driver_acquisition",
                            "acquisition_id",
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
            return DriverSuccess(measured)
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def set_source_mode(self, mode: str) -> None:
        command = {"voltage": "VOLT", "current": "CURR"}.get(mode)
        if command is None:
            raise ValueError("GS200 source mode must be voltage or current")
        self.transport.write(f":SOUR:FUNC {command}")

    @property
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

    @property
    def voltage_protection(self) -> Quantity:
        return Quantity(query_float(self.transport, ":SOUR:PROT:VOLT?"), "V")

    @voltage_protection.setter
    def voltage_protection(self, value: Quantity) -> None:
        self.set_voltage_protection(quantity_value(value, "V"))

    def set_current_protection(self, value_a: float) -> None:
        self.transport.write(f":SOUR:PROT:CURR {format_number(value_a)}")

    @property
    def current_protection(self) -> Quantity:
        return Quantity(query_float(self.transport, ":SOUR:PROT:CURR?"), "A")

    @current_protection.setter
    def current_protection(self, value: Quantity) -> None:
        self.set_current_protection(quantity_value(value, "A"))

    def set_output(self, enabled: bool) -> None:
        self.transport.write(f":OUTP {'ON' if enabled else 'OFF'}")

    @property
    def output_enabled(self) -> bool:
        return query_bool(self.transport, ":OUTP?")

    @output_enabled.setter
    def output_enabled(self, value: bool) -> None:
        self.set_output(value)

    def set_measurement_enabled(self, enabled: bool) -> None:
        self.transport.write(f":SENS {'ON' if enabled else 'OFF'}")

    @property
    def measurement_enabled(self) -> bool:
        return query_bool(self.transport, ":SENS?")

    @measurement_enabled.setter
    def measurement_enabled(self, value: bool) -> None:
        self.set_measurement_enabled(value)

    def set_integration_cycles(self, cycles: int) -> None:
        if not 1 <= cycles <= 25:
            raise ValueError("GS200 integration cycles must be between 1 and 25")
        self.transport.write(f":SENS:NPLC {cycles}")

    @property
    def integration_cycles(self) -> int:
        value = query_float(self.transport, ":SENS:NPLC?")
        cycles = int(value)
        if value != cycles or not 1 <= cycles <= 25:
            raise ValueError(f"GS200 returned invalid integration cycles {value!r}")
        return cycles

    @integration_cycles.setter
    def integration_cycles(self, value: int) -> None:
        self.set_integration_cycles(value)

    def set_measurement_delay(self, delay_s: float) -> None:
        if not 0.0 <= delay_s <= 999.999:
            raise ValueError(
                "GS200 measurement delay must be between 0 and 999.999 seconds"
            )
        self.transport.write(f":SENS:DEL {format_number(delay_s)}")

    @property
    def measurement_delay(self) -> Quantity:
        delay_s = query_float(self.transport, ":SENS:DEL?")
        if not 0.0 <= delay_s <= 999.999:
            raise ValueError(f"GS200 returned invalid measurement delay {delay_s!r}")
        return Quantity(delay_s, "s")

    @measurement_delay.setter
    def measurement_delay(self, value: Quantity) -> None:
        self.set_measurement_delay(quantity_value(value, "s"))

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

    @override
    def disconnect(self) -> None:
        self.transport.close()

    @override
    def abort(self) -> None:
        """GS200 source and monitor operations are synchronous."""


__all__ = ["YokogawaGS200"]
