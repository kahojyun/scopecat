"""Workspace experiment for a gate, frame, PulseTemplate, and acquisition."""

from __future__ import annotations

import math

import scopecat as sc
from scopecat import Quantity, QuantityType, ScalarType
from scopecat_quantum import authoring as q

RAMSEY_PHASE_TEMPLATE_ID = "quantum_lab_demo.reference.ramsey_phase"
RAMSEY_PHASE_EXPERIMENT_ID = "ramsey-phase-calibration"
RAMSEY_PHASE_SHOTS = 1

PHASE_INPUT = q.input(
    "phase",
    ScalarType(QuantityType(unit="rad")),
)
PHASE = sc.point("phase", ScalarType(QuantityType(unit="rad")))
DEFAULT_PHASES = tuple(
    Quantity(value, "rad") for value in (0.0, math.pi / 2.0, math.pi)
)

_FORMAL_QUBIT = q.qubit("formal")
_FORMAL_AMPLITUDE = q.input(
    "amplitude",
    ScalarType(QuantityType(unit="arb")),
)
_Q0 = q.qubit("q0")
_X90 = q.single_qubit_gate("x90")

X90_CANDIDATE_ID = "x90.ramsey-phase"

_X90_DURATION = Quantity(16, "ns")
_X90_AMPLITUDE = Quantity(0.2, "arb")
_RAMSEY_DELAY = Quantity(16, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")

RAMSEY_X90_PULSE_TEMPLATE = q.pulse_template(
    "ramsey-phase.x90-candidate",
    q.play(
        q.drive(_FORMAL_QUBIT),
        q.constant(
            duration=_X90_DURATION,
            amplitude=_FORMAL_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)

RAMSEY_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "ramsey-phase.readout-stimulus",
    q.play(
        q.readout(_FORMAL_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)


def ramsey_phase_program() -> q.Program:
    """Declare one bindable Ramsey point in the unified quantum DSL."""

    capture = q.acquire(
        _Q0,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.program(
        RAMSEY_PHASE_EXPERIMENT_ID,
        q.sequence(
            _X90(_Q0),
            q.delay(q.drive(_Q0), _RAMSEY_DELAY),
            q.shift_phase(q.drive(_Q0), PHASE_INPUT),
            q.implements(
                _X90(_Q0),
                RAMSEY_X90_PULSE_TEMPLATE(_Q0, amplitude=_X90_AMPLITUDE),
                candidate=X90_CANDIDATE_ID,
            ),
            q.parallel(
                RAMSEY_READOUT_PULSE_TEMPLATE(_Q0),
                capture,
            ),
        ),
    )


RAMSEY_PHASE_PROGRAM = ramsey_phase_program()
[_IQ_SHOTS_RESULT] = RAMSEY_PHASE_PROGRAM.results
_RAMSEY_PHASE_DOMAIN_PROGRAM = q.domain_program(RAMSEY_PHASE_PROGRAM)
RAMSEY_PHASE_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.ramsey_phase.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(RAMSEY_PHASE_SHOTS),),
    )
    .build()
)
_TEMPLATE_CAPTURE = RAMSEY_PHASE_CAPTURE_MODULE.instantiate("capture")
_RAMSEY_PHASE_EXECUTION = q.domain_execution(
    _RAMSEY_PHASE_DOMAIN_PROGRAM,
    inputs={PHASE_INPUT: PHASE},
    results={
        _IQ_SHOTS_RESULT: _TEMPLATE_CAPTURE.products.integrated_iq_shots,
    },
)
RAMSEY_PHASE_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.ramsey_phase.root")
    .use(_TEMPLATE_CAPTURE)
    .domain(_RAMSEY_PHASE_EXECUTION)
    .template(
        RAMSEY_PHASE_TEMPLATE_ID,
        kind=RAMSEY_PHASE_EXPERIMENT_ID,
    )
    .experiment_id(RAMSEY_PHASE_EXPERIMENT_ID)
    .scan(PHASE, DEFAULT_PHASES)
    .record_product(
        _TEMPLATE_CAPTURE.products.integrated_iq_shots,
        record_id="iq_shots",
    )
    .label("Ramsey phase DSL")
    .description(
        "Combine an accepted gate, frame shift, pulse candidate, and explicit "
        "acquisition in one Program compiled by the shared lab compiler."
    )
)


__all__ = [
    "DEFAULT_PHASES",
    "PHASE",
    "PHASE_INPUT",
    "RAMSEY_PHASE_CAPTURE_MODULE",
    "RAMSEY_PHASE_EXPERIMENT_ID",
    "RAMSEY_PHASE_PROGRAM",
    "RAMSEY_PHASE_SHOTS",
    "RAMSEY_PHASE_TEMPLATE",
    "RAMSEY_PHASE_TEMPLATE_ID",
    "RAMSEY_READOUT_PULSE_TEMPLATE",
    "RAMSEY_X90_PULSE_TEMPLATE",
    "X90_CANDIDATE_ID",
    "ramsey_phase_program",
]
