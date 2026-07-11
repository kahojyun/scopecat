"""Test-local fake instrument drivers."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.instruments import (
    ApplyReceipt,
    CollectCommand,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    capability,
    product,
    quantity_field,
)
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.models.state import StateValue


@dataclass(frozen=True)
class TestSignalInstrumentProvider:
    __test__ = False

    instrument_id: str | None = None
    provider_id: str = "tests.signal_instrument_provider"

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        instrument_id, diagnostics = self._resolve_instrument_id(context)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                (TestSignalInstrument(instrument_id=instrument_id).describe(),)
                if not diagnostics
                else ()
            ),
            diagnostics=tuple(diagnostics),
            label="Test signal instrument provider",
            description="Provides a fresh offline test signal instrument driver.",
            options=(
                ProviderOptionDescription(
                    id="instrument_id",
                    dtype="string | None",
                    default=self.instrument_id,
                    label="Instrument id",
                ),
            ),
            metadata={
                "mode": "test_offline",
                "auto_selects_single_set_frequency_instrument": (
                    self.instrument_id is None
                ),
                "observable": "signal",
            },
        )

    def provide(self, context: InstrumentProviderContext) -> InstrumentProviderResult:
        instrument_id, diagnostics = self._resolve_instrument_id(context)
        if diagnostics:
            return InstrumentProviderResult(
                drivers=(),
                diagnostics=tuple(diagnostics),
                metadata={"provider_id": self.provider_id},
            )
        return InstrumentProviderResult(
            drivers=(TestSignalInstrument(instrument_id=instrument_id),),
            metadata={
                "provider_id": self.provider_id,
                "instrument_id": instrument_id,
            },
        )

    def _resolve_instrument_id(
        self, context: InstrumentProviderContext
    ) -> tuple[str, list[Diagnostic]]:
        instruments = context.config.instrument_registry.instruments
        routable_instrument_ids = {
            resource.id
            for resource in context.config.routing.resources
            if resource.kind == "instrument"
            and "set_frequency" in resource.capabilities
        }
        if self.instrument_id is not None:
            instrument = next(
                (item for item in instruments if item.id == self.instrument_id),
                None,
            )
            if instrument is None:
                return self.instrument_id, [
                    _diagnostic(
                        "error",
                        "test_signal_provider_unknown_instrument",
                        "test signal provider instrument is not in config: "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            if self.instrument_id not in routable_instrument_ids:
                return self.instrument_id, [
                    _diagnostic(
                        "error",
                        "test_signal_provider_unsupported_instrument",
                        "test signal provider instrument must be routable for "
                        "set_frequency: "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            return self.instrument_id, []

        config_instrument_ids = {instrument.id for instrument in instruments}
        matches = sorted(routable_instrument_ids & config_instrument_ids)
        if not matches:
            return "", [
                _diagnostic(
                    "error",
                    "test_signal_provider_missing_instrument",
                    "test signal provider requires one routable instrument exposing "
                    "set_frequency",
                    "config.system.routing.resources",
                )
            ]
        if len(matches) > 1:
            return "", [
                _diagnostic(
                    "error",
                    "test_signal_provider_ambiguous_instrument",
                    "test signal provider found multiple set_frequency instruments: "
                    f"{', '.join(matches)}",
                    "config.system.routing.resources",
                )
            ]
        return matches[0], []


class TestSignalInstrument:
    __test__ = False

    implementation_id = "tests.signal_instrument"
    implementation_version = "v0"

    def __init__(self, *, instrument_id: str = "source-0") -> None:
        self.instrument_id = instrument_id
        self._state: dict[tuple[str, str], StateValue] = {}
        self.applied_commands: list[InstrumentStateCommand] = []
        self.collect_commands: list[CollectCommand] = []

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "set_frequency",
                    fields=[quantity_field("frequency", unit="GHz")],
                ),
                capability(
                    "scalar_signal",
                    products=[product("signal", unit="ratio")],
                    metadata={"observable": "signal"},
                ),
            ],
            metadata={"mode": "test_offline"},
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=[
                InstrumentStateField(
                    capability_id=capability_id,
                    field_path=field_path,
                    value=value,
                )
                for (capability_id, field_path), value in sorted(self._state.items())
            ],
            metadata={"mode": "test_offline"},
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied_commands.append(command)
        for field in command.fields:
            self._state[(field.capability_id, field.field_path)] = field.value
        return ApplyReceipt(status="applied")

    def collect(self, command: CollectCommand) -> InstrumentReadback:
        self.collect_commands.append(command)
        if "signal" not in {request.id for request in command.requests}:
            return InstrumentReadback()
        return InstrumentReadback(
            values={
                "signal": Quantity(
                    value=_test_signal(
                        command.point_index,
                        command.point_count,
                    ),
                    unit="ratio",
                )
            },
            metadata={
                "instrument": self.instrument_id,
                "implementation": self.implementation_id,
                "test_offline": True,
            },
        )

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None


def _test_signal(point_index: int, point_count: int) -> float:
    if point_count <= 1:
        return 1.0
    center = (point_count - 1) / 2
    distance = abs(point_index - center) / center
    return round(1.0 - 0.5 * distance, 12)


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
