"""Build immutable quantum calibrations from materialized parameter rows."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from scopecat import Quantity
from scopecat.records.entity import EntityRef
from scopecat_quantum import (
    DRAG,
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

from quantum_lab_demo.workflows.cz_phase_calibration import (
    X90_TARGET_CALIBRATION_ID,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    X90_CALIBRATION_ID,
    XM90_CALIBRATION_ID,
)

type _QubitParameterRow = Mapping[str, object]


def calibration_catalog_from_qubit_parameters(
    rows: Sequence[Mapping[str, object]],
) -> CalibrationCatalog:
    """Compile one point-effective qubit table into lowering calibrations."""

    q0 = _qubit_row(rows, "q0")
    q1 = _qubit_row(rows, "q1")
    q0_id = QubitId("q0")
    q1_id = QubitId("q1")
    quarter_duration = _quantity(q0, "quarter_turn_duration")
    quarter_amplitude = _quantity(q0, "quarter_turn_amplitude")
    quarter_sigma = _quantity(q0, "quarter_turn_sigma")
    beta = _quantity(q0, "drag_beta")

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=CalibrationId("fake-x-count-x-q0"),
                    key=GateCalibrationKey(GateId("x"), (q0_id,)),
                    pulse_template=_constant_gate_template(
                        "fake-x-count-x-template",
                        q0_id,
                        duration=_quantity(q0, "x_duration"),
                        amplitude=_quantity(q0, "x_amplitude"),
                    ),
                ),
                GateCalibration(
                    id=X90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (q0_id,)),
                    pulse_template=_drag_gate_template(
                        "x90-baseline-template",
                        q0_id,
                        duration=quarter_duration,
                        amplitude=quarter_amplitude,
                        sigma=quarter_sigma,
                        beta=beta,
                        phase=Quantity(0, "rad"),
                    ),
                ),
                GateCalibration(
                    id=XM90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("xm90"), (q0_id,)),
                    pulse_template=_drag_gate_template(
                        "xm90-baseline-template",
                        q0_id,
                        duration=quarter_duration,
                        amplitude=quarter_amplitude,
                        sigma=quarter_sigma,
                        beta=beta,
                        phase=Quantity(math.pi, "rad"),
                    ),
                ),
                *(
                    GateCalibration(
                        id=CalibrationId(f"single-qubit-rb.{gate_id}.q0"),
                        key=GateCalibrationKey(GateId(gate_id), (q0_id,)),
                        pulse_template=_drag_gate_template(
                            f"single-qubit-rb.{gate_id}.template",
                            q0_id,
                            duration=quarter_duration,
                            amplitude=quarter_amplitude,
                            sigma=quarter_sigma,
                            beta=beta,
                            phase=phase,
                        ),
                    )
                    for gate_id, phase in (
                        ("y90", Quantity(math.pi / 2, "rad")),
                        ("ym90", Quantity(-math.pi / 2, "rad")),
                    )
                ),
                GateCalibration(
                    id=X90_TARGET_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (q1_id,)),
                    pulse_template=_constant_gate_template(
                        "cz-phase.baseline-x90-q1",
                        q1_id,
                        duration=_quantity(q1, "quarter_turn_duration"),
                        amplitude=_quantity(q1, "quarter_turn_amplitude"),
                    ),
                ),
            )
        ),
        measurements=MeasurementCalibrationCatalog(
            (
                _integrated_iq_calibration(
                    q0_id,
                    duration=_quantity(q0, "readout_duration"),
                    amplitude=_quantity(q0, "readout_amplitude"),
                ),
            )
        ),
    )


def _qubit_row(
    rows: Sequence[_QubitParameterRow],
    qubit_id: str,
) -> _QubitParameterRow:
    return next(row for row in rows if cast("EntityRef", row["qubit"]).id == qubit_id)


def _quantity(row: _QubitParameterRow, column: str) -> Quantity:
    return cast("Quantity", row[column])


def _constant_gate_template(
    program_id: str,
    qubit: QubitId,
    *,
    duration: Quantity,
    amplitude: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=Constant(duration=duration, amplitude=amplitude),
        ),
    )


def _drag_gate_template(
    program_id: str,
    qubit: QubitId,
    *,
    duration: Quantity,
    amplitude: Quantity,
    sigma: Quantity,
    beta: Quantity,
    phase: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=DRAG(
                duration=duration,
                amplitude=amplitude,
                sigma=sigma,
                beta=beta,
                phase=phase,
            ),
        ),
    )


def _integrated_iq_calibration(
    qubit: QubitId,
    *,
    duration: Quantity,
    amplitude: Quantity,
) -> MeasurementCalibration:
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-iq-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(qubit),
    )
    return MeasurementCalibration(
        id=CalibrationId("fake-x-count-readout-q0"),
        key=MeasurementCalibrationKey(qubit, AcquisitionKind.INTEGRATED_IQ),
        pulse_template=PulseProgram(
            id=PulseProgramId("fake-x-count-readout-template"),
            body=PulseParallel(
                (
                    Play(
                        id=PulseEventId("stimulus"),
                        signal=ReadoutSignal(qubit),
                        envelope=Constant(duration=duration, amplitude=amplitude),
                    ),
                    Acquire(
                        id=PulseEventId("capture"),
                        signal=AcquireSignal(qubit),
                        slot_id=slot.id,
                        duration=duration,
                    ),
                )
            ),
            acquisition_slots=(slot,),
        ),
    )


__all__ = ["calibration_catalog_from_qubit_parameters"]
