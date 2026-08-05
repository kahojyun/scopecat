"""Production X90 execution with config-bound program and calibration inputs."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity, QuantityType
from scopecat_quantum import authoring as quantum
from scopecat_quantum.standard_gates import X90, XM90

from quantum_lab_demo.parameters import Q0_DRAG_BETA
from quantum_lab_demo.quantum_runner import author_quantum_experiment
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_gate_pulse,
    drag_readout_pulse,
)

PRODUCTION_DRAG_GATE_SHOTS = 32


@quantum.implementation(of=X90, id="production-drag-x90.implementation")
def production_x90(
    qubit: quantum.Qubit,
    drag_beta: Annotated[Quantity, QuantityType(unit="ns")],
) -> quantum.QuantumFragment:
    return drag_gate_pulse(
        qubit,
        beta=drag_beta,
        phase=Quantity(0, "rad"),
    )


@quantum.program(id="production-drag-x90")
def production_drag_program(
    qubit: quantum.Qubit,
    drag_beta: Annotated[Quantity, QuantityType(unit="ns")],
) -> quantum.QuantumFragment:
    """Declare a production X90 followed by one accepted Xm90 calibration."""

    capture = quantum.acquire(
        qubit,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    return quantum.sequence(
        production_x90(qubit, drag_beta=drag_beta),
        XM90(qubit),
        quantum.parallel(drag_readout_pulse(qubit), capture),
    )


@sc.experiment
def production_drag_experiment(experiment: sc.ExperimentContext) -> None:
    author_quantum_experiment(
        experiment,
        production_drag_program(
            qubit="q0",
            drag_beta=Q0_DRAG_BETA.ref,
        ).with_shots(PRODUCTION_DRAG_GATE_SHOTS),
    )


__all__ = [
    "PRODUCTION_DRAG_GATE_SHOTS",
    "production_drag_experiment",
    "production_drag_program",
    "production_x90",
]
