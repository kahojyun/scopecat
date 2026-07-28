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
    state_field,
    string_value,
    validate_collect_command,
    validate_writable_command,
)
from scopecat_instruments.capabilities import DC_OUTPUT, dc_output_capability
from scopecat_instruments.transport import ScpiTransport


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
            capabilities=[dc_output_capability(monitor=self.monitor_option)],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        mode = self.source_mode()
        active_unit = "V" if mode == "voltage" else "A"
        range_field = "voltage_range" if mode == "voltage" else "current_range"
        level_field = "voltage_level" if mode == "voltage" else "current_level"
        metadata: dict[str, JsonValue] = {
            "manufacturer": "Yokogawa",
            "model": "GS200",
            "monitor_option": self.monitor_option,
        }
        if self._identity is not None:
            metadata["identity"] = self._identity.raw
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=[
                state_field(DC_OUTPUT, "source_mode", mode),
                state_field(
                    DC_OUTPUT,
                    range_field,
                    Quantity(self.source_range(), active_unit),
                ),
                state_field(
                    DC_OUTPUT,
                    level_field,
                    Quantity(self.source_level(), active_unit),
                ),
                state_field(
                    DC_OUTPUT,
                    "voltage_protection",
                    Quantity(self.voltage_protection(), "V"),
                ),
                state_field(
                    DC_OUTPUT,
                    "current_protection",
                    Quantity(self.current_protection(), "A"),
                ),
                state_field(DC_OUTPUT, "output_enabled", self.output_enabled()),
            ],
            metadata=metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        description = self.describe()
        problems = validate_writable_command(command, description)
        selected_fields = {field.field_path: field for field in command.fields}
        if problems:
            return not_applied(problems)
        implied_modes = {
            "voltage"
            for path in selected_fields
            if path in {"voltage_range", "voltage_level"}
        } | {
            "current"
            for path in selected_fields
            if path in {"current_range", "current_level"}
        }
        explicit_mode_field = selected_fields.get("source_mode")
        explicit_mode = (
            string_value(explicit_mode_field.value)
            if explicit_mode_field is not None
            else None
        )
        if len(implied_modes) > 1 or (
            explicit_mode is not None
            and implied_modes
            and explicit_mode not in implied_modes
        ):
            problems.append(
                execution_problem(
                    "gs200_conflicting_source_modes",
                    "one command cannot mix voltage and current source fields",
                    "instrument_state_command",
                    "fields",
                )
            )
        if problems:
            return not_applied(problems)
        target_mode = explicit_mode or next(iter(implied_modes), None)
        output_field = selected_fields.get("output_enabled")
        target_output = (
            bool_value(output_field.value) if output_field is not None else None
        )
        try:
            if target_output is False:
                self.set_output(False)
            if target_mode is not None:
                self.set_source_mode(target_mode)
            range_path = (
                "voltage_range" if target_mode == "voltage" else "current_range"
            )
            level_path = (
                "voltage_level" if target_mode == "voltage" else "current_level"
            )
            unit = "V" if target_mode == "voltage" else "A"
            if target_mode is not None and range_path in selected_fields:
                self.set_source_range(
                    quantity_value(selected_fields[range_path].value, unit)
                )
            if "voltage_protection" in selected_fields:
                self.set_voltage_protection(
                    quantity_value(
                        selected_fields["voltage_protection"].value,
                        "V",
                    )
                )
            if "current_protection" in selected_fields:
                self.set_current_protection(
                    quantity_value(
                        selected_fields["current_protection"].value,
                        "A",
                    )
                )
            if target_mode is not None and level_path in selected_fields:
                self.set_source_level(
                    quantity_value(selected_fields[level_path].value, unit)
                )
            if target_output is True:
                self.set_output(True)
            return ApplyReceipt(status="applied", state=self.read_state())
        except Exception as error:
            return apply_unknown(self.instrument_id, error)

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
            product_id = (
                "monitored_current" if mode == "voltage" else "monitored_voltage"
            )
            requested_ids = {request.id for request in command.requests}
            if requested_ids != {product_id}:
                return not_collected(
                    [
                        execution_problem(
                            "gs200_monitor_product_inactive",
                            f"{mode} source mode provides only {product_id}",
                            "collect_command",
                            "requests",
                        )
                    ]
                )
            unit = "A" if mode == "voltage" else "V"
            measured = Quantity(self.measure(), unit)
            return CollectReceipt(
                readback=InstrumentReadback(
                    values={product_id: measured},
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

    def cleanup(self) -> None:
        """Release run-scoped state without changing the physical output."""

    def close(self) -> None:
        self.transport.close()

    def abort(self) -> None:
        """The minimal source driver has no long-running operation to abort."""


__all__ = ["YokogawaGS200"]
