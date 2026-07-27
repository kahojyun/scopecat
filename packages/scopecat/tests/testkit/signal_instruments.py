"""Test-local fake instrument drivers."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
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


@dataclass(frozen=True)
class TestSignalInstrumentProvider:
    __test__ = False

    instrument_id: str | None = None
    additional_product_keys: tuple[str, ...] = ()
    provider_id: str = "tests.signal_instrument_provider"

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        instrument_id, problems = self._resolve_instrument_id(context)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                (
                    TestSignalInstrument(
                        instrument_id=instrument_id,
                        additional_product_keys=self.additional_product_keys,
                    ).describe(),
                )
                if not problems
                else ()
            ),
            problems=tuple(problems),
        )

    def provide(self, context: InstrumentProviderContext) -> InstrumentProviderResult:
        instrument_id, problems = self._resolve_instrument_id(context)
        if problems:
            return InstrumentProviderResult(
                drivers=(),
                problems=tuple(problems),
                metadata={"provider_id": self.provider_id},
            )
        return InstrumentProviderResult(
            drivers=(
                TestSignalInstrument(
                    instrument_id=instrument_id,
                    additional_product_keys=self.additional_product_keys,
                ),
            ),
            metadata={
                "provider_id": self.provider_id,
                "instrument_id": instrument_id,
            },
        )

    def _resolve_instrument_id(
        self, context: InstrumentProviderContext
    ) -> tuple[str, list[Problem]]:
        instruments = context.config.instrument_registry.instruments
        routable_instrument_ids = {
            binding.instrument_id
            for binding in context.config.routing.bindings
            if binding.capability == "set_frequency"
        }
        if self.instrument_id is not None:
            instrument = next(
                (item for item in instruments if item.id == self.instrument_id),
                None,
            )
            if instrument is None:
                return self.instrument_id, [
                    _problem(
                        "test_signal_provider_unknown_instrument",
                        "test signal provider instrument is not in config: "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            if self.instrument_id not in routable_instrument_ids:
                return self.instrument_id, [
                    _problem(
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
                _problem(
                    "test_signal_provider_missing_instrument",
                    "test signal provider requires one routable instrument exposing "
                    "set_frequency",
                    "config.system.routing.bindings",
                )
            ]
        if len(matches) > 1:
            return "", [
                _problem(
                    "test_signal_provider_ambiguous_instrument",
                    "test signal provider found multiple set_frequency instruments: "
                    f"{', '.join(matches)}",
                    "config.system.routing.bindings",
                )
            ]
        return matches[0], []


class TestSignalInstrument:
    __test__ = False

    implementation_id = "tests.signal_instrument"
    implementation_version = "v0"

    def __init__(
        self,
        *,
        instrument_id: str = "source-0",
        additional_product_keys: tuple[str, ...] = (),
    ) -> None:
        self.instrument_id = instrument_id
        self.product_keys = ("signal", *additional_product_keys)
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
                    products=[
                        product(product_key, unit="ratio")
                        for product_key in self.product_keys
                    ],
                ),
            ],
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

    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        requested_product_keys = tuple(
            request.id
            for request in command.requests
            if request.id in self.product_keys
        )
        if not requested_product_keys:
            return CollectReceipt(readback=InstrumentReadback())
        value = Quantity(
            value=_test_signal(
                command.point_index,
                command.point_count,
            ),
            unit="ratio",
        )
        return CollectReceipt(
            readback=InstrumentReadback(
                values=dict.fromkeys(requested_product_keys, value),
                metadata={
                    "instrument": self.instrument_id,
                    "implementation": self.implementation_id,
                    "test_offline": True,
                },
            )
        )

    def close(self) -> None:
        return None

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


def _problem(code: str, message: str, path: str) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("test_signal_provider", path),
    )
