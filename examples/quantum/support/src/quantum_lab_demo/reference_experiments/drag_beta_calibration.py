"""DRAG-beta program, pulse candidate, and accepted gate calibrations."""

from __future__ import annotations

import math
from typing import Annotated

from scopecat import IntType, Quantity, QuantityType, ScalarType
from scopecat_quantum import (
    DRAG,
    CalibrationCatalog,
    CalibrationId,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    Play,
    PulseEventId,
    PulseProgram,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum import authoring as q

POSITIVE_CANDIDATE_ID = "x90.drag.plus"
NEGATIVE_CANDIDATE_ID = "x90.drag.minus"

_Q0_ID = QubitId("q0")
_X90 = q.single_qubit_gate("x90")
_XM90 = q.single_qubit_gate("xm90")
_TEMPLATE_QUBIT = q.qubit("template")
_TEMPLATE_BETA = q.input("template_beta", ScalarType(QuantityType(unit="ns")))
_TEMPLATE_PHASE = q.input(
    "template_phase",
    ScalarType(QuantityType(unit="rad")),
)

_PULSE_DURATION = Quantity(16, "ns")
_PULSE_AMPLITUDE = Quantity(0.2, "arb")
_PULSE_SIGMA = Quantity(4, "ns")
_READOUT_DURATION = Quantity(8, "ns")

DEFAULT_BASELINE_BETA = Quantity(0.5, "ns")

X90_CALIBRATION_ID = CalibrationId("drag-beta.baseline.x90.q0")
XM90_CALIBRATION_ID = CalibrationId("drag-beta.baseline.xm90.q0")

DRAG_GATE_PULSE_TEMPLATE = q.pulse_template(
    "drag-beta.gate-pulse",
    q.play(
        q.drive(_TEMPLATE_QUBIT),
        q.drag(
            duration=_PULSE_DURATION,
            amplitude=_PULSE_AMPLITUDE,
            sigma=_PULSE_SIGMA,
            beta=_TEMPLATE_BETA,
            phase=_TEMPLATE_PHASE,
        ),
    ),
    elements=(_TEMPLATE_QUBIT,),
)

DRAG_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "drag-beta.readout-stimulus",
    q.play(
        q.readout(_TEMPLATE_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=Quantity(0.25, "arb"),
        ),
    ),
    elements=(_TEMPLATE_QUBIT,),
)


def _candidate_x90(
    qubit: q.Qubit,
    beta: q.QuantumQuantity,
) -> q.QuantumFragment:
    return q.implements(
        _X90(qubit),
        DRAG_GATE_PULSE_TEMPLATE(
            qubit,
            template_beta=beta,
            template_phase=Quantity(0, "rad"),
        ),
        candidate=POSITIVE_CANDIDATE_ID,
    )


def _candidate_xm90(
    qubit: q.Qubit,
    beta: q.QuantumQuantity,
) -> q.QuantumFragment:
    return q.implements(
        _XM90(qubit),
        DRAG_GATE_PULSE_TEMPLATE(
            qubit,
            template_beta=beta,
            template_phase=Quantity(math.pi, "rad"),
        ),
        candidate=NEGATIVE_CANDIDATE_ID,
    )


@q.program(id="drag-beta-rough-calibration")
def drag_beta_program(
    qubit: q.Qubit,
    amplification: Annotated[int, IntType(minimum=1)],
    beta: Annotated[Quantity, ScalarType(QuantityType(unit="ns"))],
) -> q.QuantumFragment:
    """Amplify coherent DRAG error between trusted X90 and Xm90 references.

    Keeping beta and amplification as ports reuses one program across the scan;
    repeating the candidate pair makes the error population scale with ``N^2``.
    """

    candidate_pair = q.sequence(
        _candidate_x90(qubit, beta),
        _candidate_xm90(qubit, beta),
    )
    capture = q.acquire(
        qubit,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.sequence(
        _X90(qubit),
        q.repeat(candidate_pair, amplification),
        _XM90(qubit),
        q.parallel(
            DRAG_READOUT_PULSE_TEMPLATE(qubit),
            capture,
        ),
    )


def baseline_calibration_catalog(
    beta: Quantity = DEFAULT_BASELINE_BETA,
) -> CalibrationCatalog:
    """Return the calibrated baseline gates; readout is authored physically."""

    selected_beta = _normalized_beta(beta)

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_Q0_ID,)),
                    pulse_template=_baseline_drag_template(
                        "x90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(0, "rad"),
                    ),
                ),
                GateCalibration(
                    id=XM90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("xm90"), (_Q0_ID,)),
                    pulse_template=_baseline_drag_template(
                        "xm90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(math.pi, "rad"),
                    ),
                ),
            )
        ),
    )


def _baseline_drag_template(
    program_id: str,
    *,
    beta: Quantity,
    phase: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(_Q0_ID),
            envelope=DRAG(
                duration=_PULSE_DURATION,
                amplitude=_PULSE_AMPLITUDE,
                sigma=_PULSE_SIGMA,
                beta=beta,
                phase=phase,
            ),
        ),
    )


def _beta_ns(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "DRAG beta must be a time Quantity"
        raise TypeError(msg)
    try:
        selected = float(value.to("ns").value)
    except ValueError as error:
        msg = "DRAG beta must be a time Quantity"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "DRAG beta must be finite"
        raise ValueError(msg)
    return selected


def _normalized_beta(value: object) -> Quantity:
    return Quantity(_beta_ns(value), "ns")


__all__ = [
    "DEFAULT_BASELINE_BETA",
    "DRAG_GATE_PULSE_TEMPLATE",
    "DRAG_READOUT_PULSE_TEMPLATE",
    "NEGATIVE_CANDIDATE_ID",
    "POSITIVE_CANDIDATE_ID",
    "X90_CALIBRATION_ID",
    "XM90_CALIBRATION_ID",
    "baseline_calibration_catalog",
    "drag_beta_program",
]
