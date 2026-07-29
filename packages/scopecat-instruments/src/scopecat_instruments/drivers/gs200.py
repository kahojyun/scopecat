"""Minimal Yokogawa GS200/GS210 SCPI driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    InstrumentDescription,
    InvokeReceipt,
)

from scopecat_instruments._support import (
    ScpiIdentity,
    apply_unknown,
    bool_value,
    collect_unknown,
    execution_problem,
    format_number,
    not_collected,
    parse_bool,
    parse_float,
    parse_identity,
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


class YokogawaGS200:
    """GS200 source controls plus optional /MON single-value measurement."""

    implementation_id = YOKOGAWA_GS200
    implementation_version = "v1"

    def __init__(
        self,
        instrument_id: str,
        transport: ScpiTransport,
        *,
        monitor_option: bool = False,
    ) -> None:
        self.instrument_id = instrument_id
        self.transport = transport
        self.monitor_option = monitor_option
        self._identity: ScpiIdentity | None = None

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Yokogawa GS200",
            description=(
                "Minimal voltage/current source driver. /MON collection is exposed "
                "only when monitor_option=True."
            ),
            interfaces=[
                dc_source_interface(),
                *([dc_monitor_interface()] if self.monitor_option else []),
            ],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        mode = self.source_mode()
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
            "monitor_option": self.monitor_option,
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                state_property(DC_SOURCE_MODE, mode),
                state_property(
                    range_property,
                    Quantity(self.source_range(), active_unit),
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
            ],
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
            unit = "A" if mode == "voltage" else "V"
            measured = MeasurementScalar.create(
                dtype="float64",
                unit=unit,
                value=self.measure(),
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

    def measure(self) -> float:
        if not self.monitor_option:
            raise RuntimeError("GS200 /MON option was not enabled for this driver")
        return parse_float(self.transport.query(":MEAS?"))

    def identify(self) -> ScpiIdentity:
        identity = parse_identity(self.transport.query("*IDN?"))
        manufacturer = identity.manufacturer.upper()
        model = identity.model.upper()
        if "YOKOGAWA" not in manufacturer or model not in {"GS200", "GS210"}:
            raise ValueError(
                f"expected a Yokogawa GS200 family device, got {identity.raw!r}"
            )
        self._identity = identity
        return identity

    def disconnect(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """The minimal source driver has no long-running operation to abort."""


__all__ = ["YokogawaGS200"]
