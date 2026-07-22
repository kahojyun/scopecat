"""Function-authored Ramsey experiment with an explicit pulse candidate."""

from __future__ import annotations

import math
from typing import Annotated

import scopecat as sc
from scopecat import Quantity, QuantityType, ScalarType
from scopecat_quantum import authoring as q

RAMSEY_PHASE_TEMPLATE_ID = "quantum_lab_demo.reference.ramsey_phase"
RAMSEY_PHASE_EXPERIMENT_ID = "ramsey-phase-calibration"
RAMSEY_PHASE_SHOTS = 1

PHASE = sc.point("phase", ScalarType(QuantityType(unit="rad")))
DEFAULT_PHASES = tuple(
    Quantity(value, "rad") for value in (0.0, math.pi / 2.0, math.pi)
)

_FORMAL_QUBIT = q.qubit("formal")
_FORMAL_AMPLITUDE = q.input(
    "amplitude",
    ScalarType(QuantityType(unit="arb")),
)
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


@q.program(id=RAMSEY_PHASE_EXPERIMENT_ID)
def ramsey_phase_program(
    qubit: q.Qubit,
    phase: Annotated[Quantity, ScalarType(QuantityType(unit="rad"))],
) -> q.QuantumFragment:
    """Combine an accepted gate with a phase-shifted pulse candidate."""

    capture = q.acquire(
        qubit,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.sequence(
        _X90(qubit),
        q.delay(q.drive(qubit), _RAMSEY_DELAY),
        q.shift_phase(q.drive(qubit), phase),
        q.implements(
            _X90(qubit),
            RAMSEY_X90_PULSE_TEMPLATE(qubit, amplitude=_X90_AMPLITUDE),
            candidate=X90_CANDIDATE_ID,
        ),
        q.parallel(
            RAMSEY_READOUT_PULSE_TEMPLATE(qubit),
            capture,
        ),
    )


@sc.template(
    id=RAMSEY_PHASE_TEMPLATE_ID,
    kind=RAMSEY_PHASE_EXPERIMENT_ID,
    label="Ramsey phase DSL",
)
def ramsey_phase_template() -> sc.ExperimentBody:
    """Run one Ramsey phase sweep through the shared lab compiler."""

    call = ramsey_phase_program(
        qubit="q0",
        phase=PHASE,
        shots=RAMSEY_PHASE_SHOTS,
    )
    return (
        sc.experiment(call)
        .scan(PHASE, DEFAULT_PHASES)
        .record_product(
            call.results.iq_shots,
            record_id="iq_shots",
        )
    )


__all__ = [
    "DEFAULT_PHASES",
    "PHASE",
    "RAMSEY_PHASE_EXPERIMENT_ID",
    "RAMSEY_PHASE_SHOTS",
    "RAMSEY_PHASE_TEMPLATE_ID",
    "RAMSEY_READOUT_PULSE_TEMPLATE",
    "RAMSEY_X90_PULSE_TEMPLATE",
    "X90_CANDIDATE_ID",
    "ramsey_phase_program",
    "ramsey_phase_template",
]
