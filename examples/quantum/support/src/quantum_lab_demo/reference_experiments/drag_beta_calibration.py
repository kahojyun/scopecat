"""Program and pulse calibrations for rough DRAG-beta calibration.

The authored program deliberately mixes logical gates with pulse-level candidate
implementations.  Only the baseline X90 and Xm90 operations consult the
calibration catalog; explicit X90/Xm90 implementations keep their logical
identity while carrying one reusable, bindable DRAG PulseTemplate. Calibration
candidates and an accepted production implementation therefore share the same
physical template without sharing lifecycle state. Readout stimulus and
acquisition are explicit physical statements in the same program.
"""

from __future__ import annotations

import math

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
BETA_INPUT = q.input("beta", ScalarType(QuantityType(unit="ns")))
AMPLIFICATION_INPUT = q.input(
    "amplification",
    ScalarType(IntType(minimum=1)),
)

_Q0 = q.qubit("q0")
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


def drag_beta_calibration_program() -> q.Program:
    """Declare one bindable rough-calibration program for the complete scan.

    Both the physical DRAG coefficient and the logical amplification count are
    first-class inputs.  One declaration can therefore be bound at every point
    of a two-dimensional beta-by-amplification scan without generating a
    different program identity for each repetition count. The trusted X90 and
    Xm90 reference gates prepare and invert the same state around the repeated
    candidate identity pair. At the optimum the sequence returns near the
    ground state; a coherently accumulated small error therefore contributes a
    population term proportional to ``N^2 * (beta - beta_opt)^2``.
    """

    candidate_pair = q.sequence(
        _candidate_x90(),
        _candidate_xm90(),
    )
    capture = q.acquire(
        _Q0,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.program(
        "drag-beta-rough-calibration",
        q.sequence(
            _X90(_Q0),
            q.repeat(candidate_pair, AMPLIFICATION_INPUT),
            _XM90(_Q0),
            q.parallel(
                DRAG_READOUT_PULSE_TEMPLATE(_Q0),
                capture,
            ),
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


def _candidate_x90() -> q.QuantumFragment:
    return q.implements(
        _X90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=BETA_INPUT,
            template_phase=Quantity(0, "rad"),
        ),
        candidate=POSITIVE_CANDIDATE_ID,
    )


def _candidate_xm90() -> q.QuantumFragment:
    return q.implements(
        _XM90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=BETA_INPUT,
            template_phase=Quantity(math.pi, "rad"),
        ),
        candidate=NEGATIVE_CANDIDATE_ID,
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
    "AMPLIFICATION_INPUT",
    "BETA_INPUT",
    "DEFAULT_BASELINE_BETA",
    "DRAG_GATE_PULSE_TEMPLATE",
    "DRAG_READOUT_PULSE_TEMPLATE",
    "NEGATIVE_CANDIDATE_ID",
    "POSITIVE_CANDIDATE_ID",
    "X90_CALIBRATION_ID",
    "XM90_CALIBRATION_ID",
    "baseline_calibration_catalog",
    "drag_beta_calibration_program",
]
