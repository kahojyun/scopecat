"""Minimal Yokogawa GS200/GS210 SCPI driver."""

from __future__ import annotations

from pydantic import JsonValue
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback, InstrumentStateSnapshot
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
    InvokeCommand,
    InvokeReceipt,
)

from scopecat_instruments._support import (
    ScpiIdentity,
    apply_unknown,
    bool_value,
    collect_unknown,
    execution_problem,
    format_number,
    not_applied,
    not_collected,
    parse_bool,
    parse_float,
    parse_identity,
    quantity_value,
    state_property,
    state_sync_failed,
    string_value,
    unsupported_invoke,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.interfaces import (
    DC_SOURCE,
    dc_monitor_interface,
    dc_source_interface,
)
from scopecat_instruments.transport import ScpiTransport, TransportError


class YokogawaGS200:
    """GS200 source controls plus optional /MON single-value measurement."""

    implementation_id = "scopecat.yokogawa.gs200"
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
        range_property = "voltage_range" if mode == "voltage" else "current_range"
        level_property = "voltage_level" if mode == "voltage" else "current_level"
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
                state_property(DC_SOURCE, "source_mode", mode),
                state_property(
                    DC_SOURCE,
                    range_property,
                    Quantity(self.source_range(), active_unit),
                ),
                state_property(
                    DC_SOURCE,
                    level_property,
                    Quantity(self.source_level(), active_unit),
                ),
                state_property(
                    DC_SOURCE,
                    "voltage_protection",
                    Quantity(self.voltage_protection(), "V"),
                ),
                state_property(
                    DC_SOURCE,
                    "current_protection",
                    Quantity(self.current_protection(), "A"),
                ),
                state_property(DC_SOURCE, "output_enabled", self.output_enabled()),
            ],
            metadata=metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        description = self.describe()
        problems = validate_writable_command(command, description)
        if problems:
            return not_applied(problems)
        try:
            baseline = self.read_state()
        except TransportError:
            # A not_applied receipt would keep a transport that cannot be reused.
            raise
        except Exception as error:
            return state_sync_failed(self.instrument_id, error)
        problems = validate_writable_command(
            command,
            description,
            baseline=baseline,
        )
        if problems:
            return not_applied(problems)

        try:
            selected_properties = {
                assignment.property_id: assignment for assignment in command.assignments
            }
            baseline_properties = {
                property_state.property_id: property_state
                for property_state in baseline.properties
                if property_state.interface_id == DC_SOURCE
            }
            current_mode = string_value(baseline_properties["source_mode"].value)
            current_output = bool_value(baseline_properties["output_enabled"].value)
            mode_property = selected_properties.get("source_mode")
            target_mode = (
                string_value(mode_property.value)
                if mode_property is not None
                else current_mode
            )
            output_property = selected_properties.get("output_enabled")
            target_output = (
                bool_value(output_property.value)
                if output_property is not None
                else current_output
            )
            changes_source_state = target_mode != current_mode or bool(
                {
                    "voltage_range",
                    "current_range",
                    "voltage_level",
                    "current_level",
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
            if "voltage_range" in selected_properties:
                self.set_source_range(
                    quantity_value(selected_properties["voltage_range"].value, "V")
                )
            if "current_range" in selected_properties:
                self.set_source_range(
                    quantity_value(selected_properties["current_range"].value, "A")
                )
            if "voltage_protection" in selected_properties:
                self.set_voltage_protection(
                    quantity_value(
                        selected_properties["voltage_protection"].value,
                        "V",
                    )
                )
            if "current_protection" in selected_properties:
                self.set_current_protection(
                    quantity_value(
                        selected_properties["current_protection"].value,
                        "A",
                    )
                )
            if "voltage_level" in selected_properties:
                self.set_source_level(
                    quantity_value(selected_properties["voltage_level"].value, "V")
                )
            if "current_level" in selected_properties:
                self.set_source_level(
                    quantity_value(selected_properties["current_level"].value, "A")
                )
            effective_output = False if disabled_for_update else current_output
            if target_output != effective_output:
                self.set_output(target_output)
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return unsupported_invoke(command, self.describe())

    def collect(self, command: CollectCommand) -> CollectReceipt:
        problems = validate_collect_command(command, self.describe())
        if problems:
            return not_collected(problems)
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        if not self.monitor_option:
            return not_collected(
                [
                    execution_problem(
                        "gs200_monitor_option_required",
                        "GS200 /MON is required for DC monitor collection",
                        "collect_command",
                        "requests",
                    )
                ]
            )
        try:
            mode = self.source_mode()
            result_id = (
                "monitored_current" if mode == "voltage" else "monitored_voltage"
            )
            requested_result_ids = {request.result_id for request in command.requests}
            if requested_result_ids != {result_id}:
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_result_inactive",
                            f"{mode} source mode provides only {result_id}",
                            "collect_command",
                            "requests",
                        )
                    ]
                )
            unit = "A" if mode == "voltage" else "V"
            measured = Quantity(self.measure(), unit)
            return CollectReceipt(
                readback=InstrumentReadback(
                    values={request.id: measured for request in command.requests},
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
