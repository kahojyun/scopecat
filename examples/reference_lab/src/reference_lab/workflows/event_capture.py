"""Variable-length event capture used by the data and failure gallery."""

# The lab integration uses the same low-level authoring hooks as generated
# instrument clients while keeping them out of user-facing notebooks.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast

import scopecat as sc
from scopecat.authoring import Input, ModuleContext, ProductRef
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.program.products import product_axis
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementUnavailable,
)
from scopecat.sdk.instruments import (
    AcquisitionResultRef,
    DriverAcquisition,
    DriverConnectionSpec,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverSpec,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentDescription,
    InterfaceRef,
    acquisition,
    acquisition_axis,
    acquisition_result,
    float_property,
    interface,
)

EVENT_CAPTURE_INTERFACE = InterfaceRef("reference_lab.event_capture/v1")
EVENT_CAPTURE_GAIN = EVENT_CAPTURE_INTERFACE.property("gain")
EVENT_CAPTURE_ACQUISITION = EVENT_CAPTURE_INTERFACE.acquisition("capture")
EVENT_CAPTURE_TIME = EVENT_CAPTURE_ACQUISITION.result("time")
EVENT_CAPTURE_SIGNAL = EVENT_CAPTURE_ACQUISITION.result("signal")
EVENT_CAPTURE_DRIVER_ID = "reference_lab.virtual.event_digitizer"
EVENT_CAPTURE_DRIVER_SPEC = DriverSpec(
    driver_id=EVENT_CAPTURE_DRIVER_ID,
    implementation_version="v1",
    label="Virtual event digitizer",
    connections=(
        DriverConnectionSpec(
            kind="virtual",
            options_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ),
)

EVENT_COUNT = sc.coordinate("event_count", sc.FloatType())


@dataclass(frozen=True, slots=True)
class EventCaptureProducts:
    """Aligned point-local time and signal arrays."""

    time: ProductRef
    signal: ProductRef


@sc.module(id="reference_lab.event_capture")
def event_capture(
    context: ModuleContext,
    event_count: Annotated[Input[float], sc.ScalarType(sc.FloatType())],
) -> EventCaptureProducts:
    """Capture one variable-length trace from the lab digitizer."""

    digitizer = context._resource(
        "event-digitizer",
        requires=(EVENT_CAPTURE_INTERFACE,),
    )
    context._bind_property(digitizer, EVENT_CAPTURE_GAIN, value=event_count)
    sample_axis = product_axis("sample", size=None, kind="time", unit="s")
    time = context._product("time", unit="s", axes=(sample_axis,))
    signal = context._product("signal", unit="V", axes=(sample_axis,))
    context._acquire(
        "capture",
        resource=digitizer,
        results={
            EVENT_CAPTURE_TIME: time,
            EVENT_CAPTURE_SIGNAL: signal,
        },
    )
    return EventCaptureProducts(time=time, signal=signal)


@dataclass(frozen=True, slots=True)
class EventCaptureDataset:
    event_count: sc.CoordinateRef[float]
    time: sc.RecordRef
    signal: sc.RecordRef


@sc.experiment(id="reference_lab.ragged_event_capture")
def ragged_event_capture(experiment: sc.ExperimentContext) -> EventCaptureDataset:
    """Record aligned ragged arrays over explicit, ordered point rows."""

    experiment.points(
        (
            {EVENT_COUNT: 2.0},
            {EVENT_COUNT: 4.0},
            {EVENT_COUNT: 0.0},
            {EVENT_COUNT: 1.0},
        )
    )
    captured = experiment.use(event_capture(event_count=EVENT_COUNT))
    return EventCaptureDataset(
        event_count=EVENT_COUNT,
        time=experiment.record(captured.time),
        signal=experiment.record(captured.signal),
    )


class VirtualEventDigitizer:
    """Deterministic digitizer with variable, unavailable, and failing points."""

    implementation_id = EVENT_CAPTURE_DRIVER_ID
    implementation_version = "v1"

    def __init__(self, instrument_id: str) -> None:
        self.instrument_id = instrument_id
        self._event_count = 1.0

    def describe(self) -> InstrumentDescription:
        sample_axis = acquisition_axis(
            "sample",
            size=None,
            kind="time",
            unit="s",
        )
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    EVENT_CAPTURE_INTERFACE.interface_id,
                    properties=(float_property("gain"),),
                    acquisitions=(
                        acquisition(
                            "capture",
                            results=(
                                acquisition_result(
                                    "time",
                                    role="coordinate",
                                    unit="s",
                                    axes=(sample_axis,),
                                ),
                                acquisition_result(
                                    "signal",
                                    unit="V",
                                    axes=(sample_axis,),
                                ),
                            ),
                        ),
                    ),
                ),
            ],
        )

    def read_state(self) -> DriverState:
        return DriverState(values={EVENT_CAPTURE_GAIN: self._event_count})

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        values = {entry.target: entry.value for entry in request.entries}
        self._event_count = cast("float", values[EVENT_CAPTURE_GAIN])
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        del request
        raise NotImplementedError

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        if self._event_count < 0:
            return DriverRejected(
                problems=(
                    problem(
                        "reference_lab_event_capture_rejected",
                        "the virtual event digitizer rejected the capture point",
                        phase=ProblemPhase.EXECUTION,
                        location=model_location("driver_acquisition", "results"),
                    ),
                )
            )
        values = {result: self._value(result) for result in request.results}
        return DriverSuccess(DriverReadback(values=values))

    def _value(
        self,
        result: AcquisitionResultRef,
    ) -> MeasurementArray | MeasurementUnavailable:
        if self._event_count == 0:
            return MeasurementUnavailable.create(
                dtype="float64",
                unit="s" if result.result_id == "time" else "V",
                shape=(None,),
                reason="missing",
                metadata={
                    "source": "virtual-event-digitizer",
                    "detail": "no trigger",
                },
            )
        count = int(self._event_count)
        if result.result_id == "time":
            return MeasurementArray.create(
                dtype="float64",
                unit="s",
                values=tuple(index * 1.0e-6 for index in range(count)),
            )
        return MeasurementArray.create(
            dtype="float64",
            unit="V",
            values=tuple(self._event_count + index / 10 for index in range(count)),
        )

    def abort(self) -> None:
        return None

    def disconnect(self) -> None:
        return None


__all__ = [
    "EVENT_CAPTURE_DRIVER_ID",
    "EVENT_CAPTURE_DRIVER_SPEC",
    "EVENT_COUNT",
    "EventCaptureDataset",
    "VirtualEventDigitizer",
    "event_capture",
    "ragged_event_capture",
]
