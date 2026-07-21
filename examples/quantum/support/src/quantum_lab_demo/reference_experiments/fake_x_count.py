"""Lab calibrations for the fake X-count reference program."""

from __future__ import annotations

from scopecat import Quantity
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    Constant,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    Play,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QubitId,
    ReadoutSignal,
)

_DEFAULT_QUBIT = QubitId("q0")
_X_GATE_ID = GateId("x")


def fake_x_count_calibration_catalog(
    qubit: QubitId = _DEFAULT_QUBIT,
    gate_id: GateId = _X_GATE_ID,
) -> CalibrationCatalog:
    """Return accepted X and integrated-IQ calibrations for the fake target."""

    x_template = PulseProgram(
        id=PulseProgramId("fake-x-count-x-template"),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=Constant(
                duration=Quantity(4, "ns"),
                amplitude=Quantity(0.25, "arb"),
            ),
        ),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-iq-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(qubit),
    )
    readout_template = PulseProgram(
        id=PulseProgramId("fake-x-count-readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(qubit),
                    envelope=Constant(
                        duration=Quantity(8, "ns"),
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=AcquireSignal(qubit),
                    slot_id=template_slot.id,
                    duration=Quantity(8, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=CalibrationId("fake-x-count-x-q0"),
                    key=GateCalibrationKey(gate_id, (qubit,)),
                    pulse_template=x_template,
                ),
            )
        ),
        measurements=MeasurementCalibrationCatalog(
            (
                MeasurementCalibration(
                    id=CalibrationId("fake-x-count-readout-q0"),
                    key=MeasurementCalibrationKey(
                        qubit,
                        AcquisitionKind.INTEGRATED_IQ,
                    ),
                    pulse_template=readout_template,
                ),
            )
        ),
    )


__all__ = [
    "fake_x_count_calibration_catalog",
]
