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
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    InstrumentBindingSpec,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentPropertyState,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentReadback,
    InstrumentStateSnapshot,
    InvokeReceipt,
    acquisition,
    acquisition_result,
    interface,
    quantity_property,
)


@dataclass(frozen=True)
class TestSignalInstrumentProvider:
    __test__ = False

    instrument_id: str | None = None
    additional_result_ids: tuple[str, ...] = ()
    provider_id: str = "tests.signal_instrument_provider"

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        bindings, problems = self._select_bindings(context)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                TestSignalInstrument(
                    instrument_id=binding.id,
                    additional_result_ids=self.additional_result_ids,
                ).describe()
                for binding in bindings
            ),
            problems=tuple(problems),
        )

    def connect(self, context: InstrumentConnectionContext) -> TestSignalInstrument:
        bindings, problems = self._select_bindings(
            InstrumentProviderContext(bindings=(context.binding,))
        )
        if problems:
            raise ValueError(
                "; ".join(provider_problem.message for provider_problem in problems)
            )
        [binding] = bindings
        return TestSignalInstrument(
            instrument_id=binding.id,
            additional_result_ids=self.additional_result_ids,
        )

    def _select_bindings(
        self, context: InstrumentProviderContext
    ) -> tuple[tuple[InstrumentBindingSpec, ...], list[Problem]]:
        bindings = context.bindings
        supported = tuple(
            binding
            for binding in bindings
            if binding.driver_id == TestSignalInstrument.implementation_id
        )
        if self.instrument_id is not None:
            binding = next(
                (item for item in bindings if item.id == self.instrument_id),
                None,
            )
            if binding is None:
                return (), [
                    _problem(
                        "test_signal_provider_unknown_instrument",
                        "test signal provider instrument is not in config: "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            if binding not in supported:
                return (), [
                    _problem(
                        "test_signal_provider_unsupported_instrument",
                        "test signal provider does not support configured driver "
                        f"{binding.driver_id!r} for "
                        f"{self.instrument_id}",
                        "instrument_id",
                    )
                ]
            return (binding,), []

        if not supported:
            return (), [
                _problem(
                    "test_signal_provider_missing_instrument",
                    "test signal provider requires one configured "
                    f"{TestSignalInstrument.implementation_id!r} binding",
                    "bindings",
                )
            ]
        return supported, []


class TestSignalInstrument:
    __test__ = False

    implementation_id = "tests.signal_instrument"
    implementation_version = "v0"

    def __init__(
        self,
        *,
        instrument_id: str = "source-0",
        additional_result_ids: tuple[str, ...] = (),
    ) -> None:
        self.instrument_id = instrument_id
        self.result_ids = ("signal", *additional_result_ids)
        self._state: dict[tuple[str, str], StateValue] = {
            ("test.set_frequency/v1", "frequency"): StateValue(
                Quantity(value=5.0, unit="GHz")
            )
        }
        self.applied_requests: list[DriverApplyRequest] = []
        self.invoked_requests: list[DriverInvokeRequest] = []
        self.collect_requests: list[DriverCollectRequest] = []

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    "test.set_frequency/v1",
                    properties=[quantity_property("frequency", unit="GHz")],
                ),
                interface(
                    "test.scalar_signal/v1",
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[
                                acquisition_result(result_id, unit="ratio")
                                for result_id in self.result_ids
                            ],
                        )
                    ],
                ),
            ],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                InstrumentPropertyState(
                    interface_id=interface_id,
                    property_id=property_id,
                    value=value,
                )
                for (interface_id, property_id), value in sorted(self._state.items())
            ],
            metadata={"mode": "test_offline"},
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        self.applied_requests.append(request)
        for assignment in request.assignments:
            self._state[(assignment.interface_id, assignment.property_id)] = (
                assignment.value
            )
        return ApplyReceipt(status="applied")

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        self.invoked_requests.append(request)
        return InvokeReceipt(status="invoked", state=self.read_state())

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        self.collect_requests.append(request)
        requested_result_ids = tuple(
            result.request_id
            for result in request.results
            if result.result_id in self.result_ids
        )
        if not requested_result_ids:
            return CollectReceipt(readback=InstrumentReadback())
        value = MeasurementScalar.create(
            dtype="float64",
            value=_test_signal(self._frequency_ghz()),
            unit="ratio",
        )
        return CollectReceipt(
            readback=InstrumentReadback(
                values=dict.fromkeys(requested_result_ids, value),
                metadata={
                    "instrument": self.instrument_id,
                    "implementation": self.implementation_id,
                    "test_offline": True,
                },
            )
        )

    def _frequency_ghz(self) -> float:
        value = self._state[("test.set_frequency/v1", "frequency")].root
        assert isinstance(value, Quantity)
        return value.to("GHz").value

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


def _test_signal(frequency_ghz: float) -> float:
    distance = abs(frequency_ghz - 5.0) / 0.1
    return round(1.0 - 0.5 * distance, 12)


def _problem(code: str, message: str, path: str) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("test_signal_provider", path),
    )
