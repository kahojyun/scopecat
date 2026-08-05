"""Function-authored 2-D DRAG-beta calibration experiment."""

from __future__ import annotations

import scopecat as sc
from scopecat import Quantity

from quantum_lab_demo.parameters import Q0_DRAG_BETA
from quantum_lab_demo.quantum_runner import quantum_capture
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_beta_program,
)

DRAG_BETA_SHOTS = 64
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_AMPLIFICATIONS = (1, 2, 3)
PROBABILITY_0_RECORD_ID = "capture/probability_0"
PROBABILITY_1_RECORD_ID = "capture/probability_1"


@sc.experiment
def drag_beta_experiment(experiment: sc.ExperimentContext) -> None:
    """Scan pulse DRAG beta against gate amplification in one program."""

    beta = experiment.scan(
        "beta",
        overlay=Q0_DRAG_BETA.ref,
        span=DRAG_BETA_SPAN,
        points=DRAG_BETA_POINTS,
    )
    amplification = experiment.scan("amplification", DEFAULT_AMPLIFICATIONS)
    experiment.record(
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


__all__ = [
    "DEFAULT_AMPLIFICATIONS",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "PROBABILITY_0_RECORD_ID",
    "PROBABILITY_1_RECORD_ID",
    "drag_beta_experiment",
    "drag_beta_program",
]
