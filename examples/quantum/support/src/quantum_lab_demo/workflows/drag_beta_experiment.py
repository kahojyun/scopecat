"""Function-authored 2-D DRAG-beta calibration experiment."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum.measurement_postprocessors import BinaryIqProbabilityRecords

from quantum_lab_demo.parameters import Q0_DRAG_BETA
from quantum_lab_demo.quantum_runner import quantum_capture
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_beta_program,
)

DRAG_BETA_SHOTS = 64
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_AMPLIFICATIONS = (1, 2, 3)


@dataclass(frozen=True, slots=True)
class DragBetaDataset:
    """Typed dataset schema produced by one DRAG-beta experiment."""

    beta: sc.ValueRef[Quantity]
    amplification: sc.ValueRef[int]
    probabilities: BinaryIqProbabilityRecords


@sc.experiment
def drag_beta_experiment(experiment: sc.ExperimentContext) -> DragBetaDataset:
    """Scan pulse DRAG beta against gate amplification in one program."""

    beta = experiment.scan(
        "beta",
        overlay=Q0_DRAG_BETA.ref,
        span=DRAG_BETA_SPAN,
        points=DRAG_BETA_POINTS,
    )
    amplification = experiment.scan("amplification", DEFAULT_AMPLIFICATIONS)
    probabilities = experiment.record(
        experiment.use(
            quantum_capture(
                drag_beta_program(
                    qubit="q0",
                    amplification=amplification,
                    beta=beta,
                ).with_shots(DRAG_BETA_SHOTS)
            )
        )
    )
    return DragBetaDataset(
        beta=beta,
        amplification=amplification,
        probabilities=probabilities,
    )


DRAG_BETA_EXPERIMENT = drag_beta_experiment()


__all__ = [
    "DEFAULT_AMPLIFICATIONS",
    "DRAG_BETA_EXPERIMENT",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DragBetaDataset",
    "drag_beta_experiment",
    "drag_beta_program",
]
