"""Minimal Yokogawa GS200/GS210 SCPI driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.records.measurement import MeasurementScalar, MeasurementUnavailable
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    DriverPropertyWrite,
    InstrumentDescription,
    InvokeReceipt,
    PropertyRef,
)

from scopecat_instruments._support import (
    ScpiIdentity,
    apply_unknown,
    bool_value,
    collect_unknown,
    execution_problem,
    format_number,
    int_value,
    not_applied,
    not_collected,
    parse_bool,
    parse_float,
    parse_identity,
    parse_int,
    quantity_value,
    state_properties_by_target,
    state_property,
    state_sync_failed,
    string_value,
    unsupported_invoke,
)
from scopecat_instruments.driver_ids import YOKOGAWA_GS200
from scopecat_instruments.interfaces import dc_monitor_interface, dc_source_interface
from scopecat_instruments.members import (
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
)
from scopecat_instruments.transport import ScpiTransport, TransportError

_CONDITION_END_OF_MEASURE = 1 << 0
_CONDITION_OVER_RANGE = 1 << 1
_CONDITION_NO_TRIGGER_SAMPLING_ERROR = 1 << 4


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

    def read_state(self) -> InstrumentStateSnapshot:
        self._validate_connection_profile()
        mode = self.source_mode()
        source_range = self.source_range()
        self._validate_source_profile(mode, source_range)
        active_unit = "V" if mode == "voltage" else "A"
        range_property = (
            DC_SOURCE_VOLTAGE_RANGE if mode == "voltage" else DC_SOURCE_CURRENT_RANGE
        )
        level_property = (
            DC_SOURCE_VOLTAGE_LEVEL if mode == "voltage" else DC_SOURCE_CURRENT_LEVEL
        )
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Yokogawa",
            "model": "GS200",
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        properties = [
            state_property(DC_SOURCE_MODE, mode),
            state_property(
                range_property,
                Quantity(source_range, active_unit),
            ),
            state_property(
                level_property,
                Quantity(self.source_level(), active_unit),
            ),
            state_property(
                DC_SOURCE_VOLTAGE_PROTECTION,
                Quantity(self.voltage_protection(), "V"),
            ),
            state_property(
                DC_SOURCE_CURRENT_PROTECTION,
                Quantity(self.current_protection(), "A"),
            ),
            state_property(DC_SOURCE_OUTPUT_ENABLED, self.output_enabled()),
        ]
        if self.monitor_option:
            properties.extend(
                [
                    state_property(
                        DC_MONITOR_MEASUREMENT_ENABLED,
                        self.measurement_enabled(),
                    ),
                    state_property(
                        DC_MONITOR_INTEGRATION_CYCLES,
                        self.integration_cycles(),
                    ),
                    state_property(
                        DC_MONITOR_MEASUREMENT_DELAY,
                        Quantity(self.measurement_delay(), "s"),
                    ),
                ]
            )
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=properties,
            metadata=metadata,
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        try:
            baseline = self.read_state()
        except TransportError:
            # A not_applied receipt would keep a transport that cannot be reused.
            raise
        except Exception as error:
            return state_sync_failed(self.instrument_id, error)

        try:
            selected_properties = {
                assignment.target: assignment for assignment in request.assignments
            }
            baseline_properties = state_properties_by_target(baseline)
            current_mode = string_value(baseline_properties[DC_SOURCE_MODE].value)
            current_output = bool_value(
                baseline_properties[DC_SOURCE_OUTPUT_ENABLED].value
            )
            mode_property = selected_properties.get(DC_SOURCE_MODE)
            target_mode = (
                string_value(mode_property.value)
                if mode_property is not None
                else current_mode
            )
            output_property = selected_properties.get(DC_SOURCE_OUTPUT_ENABLED)
            target_output = (
                bool_value(output_property.value)
                if output_property is not None
                else current_output
            )
            if not self._remote_sense_target_is_valid(
                selected_properties,
                baseline_properties,
                current_mode=current_mode,
                target_mode=target_mode,
            ):
                return not_applied(
                    [
                        execution_problem(
                            "gs200_remote_sense_voltage_range_incompatible",
                            "GS200 remote sense requires an explicit voltage range "
                            "of at least 1 V",
                            "driver_apply_request",
                            "assignments",
                        )
                    ]
                )
            current_measurement = False
            target_measurement = False
            changes_measurement_settings = False
            if self.monitor_option:
                current_measurement = bool_value(
                    baseline_properties[DC_MONITOR_MEASUREMENT_ENABLED].value
                )
                measurement_property = selected_properties.get(
                    DC_MONITOR_MEASUREMENT_ENABLED
                )
                target_measurement = (
                    bool_value(measurement_property.value)
                    if measurement_property is not None
                    else current_measurement
                )
                changes_measurement_settings = bool(
                    {
                        DC_MONITOR_INTEGRATION_CYCLES,
                        DC_MONITOR_MEASUREMENT_DELAY,
                    }
                    & selected_properties.keys()
                )
            changes_source_state = target_mode != current_mode or bool(
                {
                    DC_SOURCE_VOLTAGE_RANGE,
                    DC_SOURCE_CURRENT_RANGE,
                    DC_SOURCE_VOLTAGE_LEVEL,
                    DC_SOURCE_CURRENT_LEVEL,
                }
                & selected_properties.keys()
            )
            # Protection values are compliance controls designed for live adjustment.
            disabled_for_update = current_output and (
                not target_output or changes_source_state
            )

            if disabled_for_update:
                self.set_output(False)
            if target_mode != current_mode:
                self.set_source_mode(target_mode)
            if DC_SOURCE_VOLTAGE_RANGE in selected_properties:
                self.set_source_range(
                    quantity_value(
                        selected_properties[DC_SOURCE_VOLTAGE_RANGE].value,
                        "V",
                    )
                )
            if DC_SOURCE_CURRENT_RANGE in selected_properties:
                self.set_source_range(
                    quantity_value(
                        selected_properties[DC_SOURCE_CURRENT_RANGE].value,
                        "A",
                    )
                )
            if DC_SOURCE_VOLTAGE_PROTECTION in selected_properties:
                self.set_voltage_protection(
                    quantity_value(
                        selected_properties[DC_SOURCE_VOLTAGE_PROTECTION].value,
                        "V",
                    )
                )
            if DC_SOURCE_CURRENT_PROTECTION in selected_properties:
                self.set_current_protection(
                    quantity_value(
                        selected_properties[DC_SOURCE_CURRENT_PROTECTION].value,
                        "A",
                    )
                )
            if DC_SOURCE_VOLTAGE_LEVEL in selected_properties:
                self.set_source_level(
                    quantity_value(
                        selected_properties[DC_SOURCE_VOLTAGE_LEVEL].value,
                        "V",
                    )
                )
            if DC_SOURCE_CURRENT_LEVEL in selected_properties:
                self.set_source_level(
                    quantity_value(
                        selected_properties[DC_SOURCE_CURRENT_LEVEL].value,
                        "A",
                    )
                )
            if self.monitor_option:
                measurement_disabled_for_update = (
                    current_measurement and changes_measurement_settings
                )
                if measurement_disabled_for_update:
                    self.set_measurement_enabled(False)
                if DC_MONITOR_INTEGRATION_CYCLES in selected_properties:
                    self.set_integration_cycles(
                        int_value(
                            selected_properties[DC_MONITOR_INTEGRATION_CYCLES].value
                        )
                    )
                if DC_MONITOR_MEASUREMENT_DELAY in selected_properties:
                    self.set_measurement_delay(
                        quantity_value(
                            selected_properties[DC_MONITOR_MEASUREMENT_DELAY].value,
                            "s",
                        )
                    )
                effective_measurement = (
                    False if measurement_disabled_for_update else current_measurement
                )
                if target_measurement != effective_measurement:
                    self.set_measurement_enabled(target_measurement)
            effective_output = False if disabled_for_update else current_output
            if target_output != effective_output:
                self.set_output(target_output)
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return unsupported_invoke(request, self.instrument_id)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        if not self.monitor_option:
            return not_collected(
                [
                    execution_problem(
                        "gs200_monitor_option_required",
                        "GS200 /MON is required for DC monitor collection",
                        "driver_collect_request",
                        "results",
                    )
                ]
            )
        try:
            mode = self.source_mode()
            active_result = (
                DC_MONITOR_CURRENT_RESULT
                if mode == "voltage"
                else DC_MONITOR_VOLTAGE_RESULT
            )
            requested_results = {
                request.result_target(result) for result in request.results
            }
            if requested_results != {active_result}:
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_result_inactive",
                            f"{mode} source mode provides only "
                            f"{active_result.result_id}",
                            "driver_collect_request",
                            "results",
                        )
                    ]
                )
            if not self.output_enabled():
                return not_collected(
                    [
                        execution_problem(
                            "gs200_output_disabled",
                            "GS200 output must be enabled for monitor collection",
                            "instrument_state",
                            DC_SOURCE_OUTPUT_ENABLED.property_id,
                        )
                    ]
                )
            if not self.measurement_enabled():
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_disabled",
                            "GS200 monitor measurement is disabled",
                            "instrument_state",
                            DC_MONITOR_MEASUREMENT_ENABLED.property_id,
                        )
                    ]
                )
            if mode == "voltage" and self.source_range() < 1.0:
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_voltage_range_too_low",
                            "GS200 current monitoring requires at least the 1 V range",
                            "instrument_state",
                            DC_SOURCE_VOLTAGE_RANGE.property_id,
                        )
                    ]
                )
            if self.measurement_null_enabled():
                # NULL alters the value without exposing its stored offset.
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_null_enabled",
                            "GS200 monitor NULL must be disabled before collection",
                            "driver_collect_request",
                            "acquisition_id",
                        )
                    ]
                )

            unit = "A" if mode == "voltage" else "V"
            original_trigger = self.measurement_trigger()
            restore_trigger = original_trigger != "COMM"
            try:
                if restore_trigger:
                    self.set_measurement_trigger("COMM")
                raw_measurement = self.transport.query(":MEAS?")
                condition = parse_int(self.transport.query(":STAT:COND?"))
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
                    value=parse_float(raw_measurement),
                )
            return CollectReceipt(
                readback=InstrumentReadback(
                    values={result.request_id: measured for result in request.results},
                    metadata={
                        "manufacturer": "Yokogawa",
                        "model": "GS200",
                        "source_mode": mode,
                    },
                )
            )
        except Exception as error:
            return collect_unknown(self.instrument_id, error)

    def set_source_mode(self, mode: str) -> None:
        command = {"voltage": "VOLT", "current": "CURR"}.get(mode)
        if command is None:
            raise ValueError("GS200 source mode must be voltage or current")
        self.transport.write(f":SOUR:FUNC {command}")

    def source_mode(self) -> str:
        response = self.transport.query(":SOUR:FUNC?").strip().upper()
        if response.startswith("VOLT"):
            return "voltage"
        if response.startswith("CURR"):
            return "current"
        raise ValueError(f"GS200 returned unknown source mode {response!r}")

    def set_source_range(self, value: float) -> None:
        self.transport.write(f":SOUR:RANG {format_number(value)}")

    def source_range(self) -> float:
        return parse_float(self.transport.query(":SOUR:RANG?"))

    def set_source_level(self, value: float) -> None:
        self.transport.write(f":SOUR:LEV {format_number(value)}")

    def source_level(self) -> float:
        return parse_float(self.transport.query(":SOUR:LEV?"))

    def set_voltage_protection(self, value_v: float) -> None:
        self.transport.write(f":SOUR:PROT:VOLT {format_number(value_v)}")

    def voltage_protection(self) -> float:
        return parse_float(self.transport.query(":SOUR:PROT:VOLT?"))

    def set_current_protection(self, value_a: float) -> None:
        self.transport.write(f":SOUR:PROT:CURR {format_number(value_a)}")

    def current_protection(self) -> float:
        return parse_float(self.transport.query(":SOUR:PROT:CURR?"))

    def set_output(self, enabled: bool) -> None:
        self.transport.write(f":OUTP {'ON' if enabled else 'OFF'}")

    def output_enabled(self) -> bool:
        return parse_bool(self.transport.query(":OUTP?"))

    def set_measurement_enabled(self, enabled: bool) -> None:
        self.transport.write(f":SENS {'ON' if enabled else 'OFF'}")

    def measurement_enabled(self) -> bool:
        return parse_bool(self.transport.query(":SENS?"))

    def set_integration_cycles(self, cycles: int) -> None:
        if not 1 <= cycles <= 25:
            raise ValueError("GS200 integration cycles must be between 1 and 25")
        self.transport.write(f":SENS:NPLC {cycles}")

    def integration_cycles(self) -> int:
        value = parse_float(self.transport.query(":SENS:NPLC?"))
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
        delay_s = parse_float(self.transport.query(":SENS:DEL?"))
        if not 0.0 <= delay_s <= 999.999:
            raise ValueError(f"GS200 returned invalid measurement delay {delay_s!r}")
        return delay_s

    def measurement_null_enabled(self) -> bool:
        return parse_bool(self.transport.query(":SENS:NULL?"))

    def set_measurement_trigger(self, trigger: str) -> None:
        self.transport.write(f":SENS:TRIG {trigger}")

    def measurement_trigger(self) -> str:
        trigger = self.transport.query(":SENS:TRIG?").strip().upper()
        if not trigger:
            raise ValueError("GS200 returned an empty measurement trigger")
        return trigger

    def _validate_connection_profile(self) -> None:
        remote_sense = parse_bool(self.transport.query(":SENS:REM?"))
        guard_enabled = parse_bool(self.transport.query(":SENS:GUAR?"))
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
        selected_properties: dict[PropertyRef, DriverPropertyWrite],
        baseline_properties: dict[PropertyRef, InstrumentPropertyState],
        *,
        current_mode: str,
        target_mode: str,
    ) -> bool:
        if not self.remote_sense or target_mode != "voltage":
            return True
        requested_range = selected_properties.get(DC_SOURCE_VOLTAGE_RANGE)
        if requested_range is not None:
            target_range = quantity_value(requested_range.value, "V")
        elif current_mode == "voltage":
            target_range = quantity_value(
                baseline_properties[DC_SOURCE_VOLTAGE_RANGE].value,
                "V",
            )
        else:
            return False
        return self._source_profile_is_valid(target_mode, target_range)

    def identify(self) -> ScpiIdentity:
        identity = parse_identity(self.transport.query("*IDN?"))
        manufacturer = identity.manufacturer.upper()
        model = identity.model.upper()
        if "YOKOGAWA" not in manufacturer or model not in {"GS200", "GS210"}:
            raise ValueError(
                f"expected a Yokogawa GS200 family device, got {identity.raw!r}"
            )
        if self.monitor_option:
            option_response = self.transport.query("*OPT?")
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
