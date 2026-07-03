"""Test-local fake instruments."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.instruments import (
    ManagedInstrument,
    MeasurementContext,
    capability,
    quantity_field,
)
from scopecat.instruments.sdk import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.results import MeasurementSink


@dataclass(frozen=True)
class TestSignalInstrumentProvider:
    __test__ = False

    instrument_id: str | None = None
    provider_id: str = "tests.signal_instrument_provider"

    def describe(self) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            label="Test signal instrument provider",
            description="Provides a fresh offline test signal instrument.",
            options=(
                ProviderOptionDescription(
                    id="instrument_id",
                    dtype="string | None",
                    default=self.instrument_id,
                    label="Instrument id",
                ),
            ),
            provided_instrument_ids=(
                (self.instrument_id,) if self.instrument_id is not None else ()
            ),
            capabilities=("set_frequency", "scalar_signal"),
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
                instruments=(),
                diagnostics=tuple(diagnostics),
                metadata={"provider_id": self.provider_id},
            )
        return InstrumentProviderResult(
            instruments=(TestSignalInstrument(instrument_id=instrument_id),),
            metadata={
                "provider_id": self.provider_id,
                "instrument_id": instrument_id,
            },
        )

    def _resolve_instrument_id(
        self, context: InstrumentProviderContext
    ) -> tuple[str, list[Diagnostic]]:
        instruments = context.config.instrument_registry.instruments
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
            if "set_frequency" not in instrument.capabilities:
                return self.instrument_id, [
                    _diagnostic(
                        "error",
                        "test_signal_provider_unsupported_instrument",
                        "test signal provider instrument must expose set_frequency: "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            return self.instrument_id, []

        matches = sorted(
            instrument.id
            for instrument in instruments
            if "set_frequency" in instrument.capabilities
        )
        if not matches:
            return "", [
                _diagnostic(
                    "error",
                    "test_signal_provider_missing_instrument",
                    "test signal provider requires one instrument exposing "
                    "set_frequency",
                    "config.instrument_registry.instruments",
                )
            ]
        if len(matches) > 1:
            return "", [
                _diagnostic(
                    "error",
                    "test_signal_provider_ambiguous_instrument",
                    "test signal provider found multiple set_frequency instruments: "
                    f"{', '.join(matches)}",
                    "config.instrument_registry.instruments",
                )
            ]
        return matches[0], []


class TestSignalInstrument(ManagedInstrument):
    __test__ = False

    implementation_id = "tests.signal_instrument"
    implementation_version = "v0"

    def __init__(self, *, instrument_id: str = "source-0") -> None:
        super().__init__(
            instrument_id=instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "set_frequency",
                    fields=[quantity_field("frequency", unit="GHz")],
                ),
                capability(
                    "scalar_signal",
                    acquisition=True,
                    metadata={"observable": "signal"},
                ),
            ],
            metadata={"mode": "test_offline"},
        )

    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        if context.acquisition_kind != "scalar":
            return
        if context.record != "point":
            raise RuntimeError("test signal instrument only supports point acquisition")
        sink.record(
            point_index=context.point_index,
            coordinates=context.coordinates,
            observables={
                "signal": Quantity(
                    value=_test_signal(
                        context.point_index,
                        context.point_count,
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
