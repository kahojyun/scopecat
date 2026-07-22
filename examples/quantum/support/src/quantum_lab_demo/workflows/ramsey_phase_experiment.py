"""Function-authored Ramsey experiment with an explicit pulse candidate."""

from __future__ import annotations

import math
from typing import Annotated

import scopecat as sc
from scopecat import Quantity, QuantityType, ScalarType
from scopecat_quantum import authoring as q

from quantum_lab_demo.virtual_lab.parameters import quantum_calibration_parameters

RAMSEY_PHASE_TEMPLATE_ID = "quantum_lab_demo.workflows.ramsey_phase"
RAMSEY_PHASE_EXPERIMENT_ID = "ramsey-phase-calibration"
RAMSEY_PHASE_SHOTS = 1

PHASE = sc.coordinate("phase", ScalarType(QuantityType(unit="rad")))
DEFAULT_PHASES = tuple(
    Quantity(value, "rad") for value in (0.0, math.pi / 2.0, math.pi)
)

_X90 = q.single_qubit_gate("x90")

X90_CANDIDATE_ID = "x90.ramsey-phase"

_X90_DURATION = Quantity(16, "ns")
_X90_AMPLITUDE = Quantity(0.2, "arb")
_RAMSEY_DELAY = Quantity(16, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")


@q.implementation(
    of=_X90,
    candidate=X90_CANDIDATE_ID,
    id="ramsey-phase.x90-candidate",
)
def ramsey_x90_candidate(qubit: q.Qubit) -> q.QuantumFragment:
    """Implement the second X90 with the pulse under study."""

    return q.play(
        q.drive(qubit),
        q.constant(
            duration=_X90_DURATION,
            amplitude=_X90_AMPLITUDE,
        ),
    )


@q.pulse_template(id="ramsey-phase.readout-stimulus")
def ramsey_readout_pulse(qubit: q.Qubit) -> q.QuantumFragment:
    return q.play(
        q.readout(qubit),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
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
        ramsey_x90_candidate(qubit),
        q.parallel(
            ramsey_readout_pulse(qubit),
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

    call = (
        ramsey_phase_program(
            qubit="q0",
            phase=PHASE,
        )
        .with_compiler_inputs(calibrations=quantum_calibration_parameters())
        .with_shots(RAMSEY_PHASE_SHOTS)
    )
    return (
        sc.experiment(call)
        .scan(PHASE, DEFAULT_PHASES)
        .record_product(call.results.iq_shots)
    )


__all__ = [
    "DEFAULT_PHASES",
    "PHASE",
    "RAMSEY_PHASE_EXPERIMENT_ID",
    "RAMSEY_PHASE_SHOTS",
    "RAMSEY_PHASE_TEMPLATE_ID",
    "X90_CANDIDATE_ID",
    "ramsey_phase_program",
    "ramsey_phase_template",
    "ramsey_readout_pulse",
    "ramsey_x90_candidate",
]
