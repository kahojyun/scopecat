"""Function-authored 2-D DRAG-beta calibration experiment."""

from __future__ import annotations

import scopecat as sc
from scopecat import Quantity

from quantum_lab_demo.quantum_runner import author_quantum_experiment
from quantum_lab_demo.virtual_lab.parameters import q0_drag_beta_lookup
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_beta_program,
)

DRAG_BETA_TEMPLATE_ID = "quantum_lab_demo.workflows.drag_beta"
DRAG_BETA_EXPERIMENT_ID = "drag-beta-calibration"
DRAG_BETA_SHOTS = 64
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_AMPLIFICATIONS = (1, 2, 3)
PROBABILITY_0_RECORD_ID = "capture/probability_0"
PROBABILITY_1_RECORD_ID = "capture/probability_1"


_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
BETA = sc.coordinate("beta", _BETA_VALUE_TYPE)
AMPLIFICATION = sc.coordinate(
    "amplification",
    sc.ScalarType(sc.IntType(minimum=1)),
)


def _drag_beta_experiment_body(
    experiment: sc.ExperimentContext,
    *scans: sc.Scan,
) -> None:
    author_quantum_experiment(
        experiment,
        drag_beta_program(
            qubit="q0",
            amplification=AMPLIFICATION,
            beta=q0_drag_beta_lookup(),
        ).with_shots(DRAG_BETA_SHOTS),
    )
    experiment.scan(*scans)


@sc.template(
    id=DRAG_BETA_TEMPLATE_ID,
    kind=DRAG_BETA_EXPERIMENT_ID,
)
def drag_beta_template(experiment: sc.ExperimentContext) -> None:
    """Scan pulse DRAG beta against gate amplification in one program."""

    _drag_beta_experiment_body(
        experiment,
        sc.param_axis(
            BETA,
            q0_drag_beta_lookup(),
            span=DRAG_BETA_SPAN,
            points=DRAG_BETA_POINTS,
        ),
        sc.axis(AMPLIFICATION, DEFAULT_AMPLIFICATIONS),
    )


__all__ = [
    "AMPLIFICATION",
    "BETA",
    "DEFAULT_AMPLIFICATIONS",
    "DRAG_BETA_EXPERIMENT_ID",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE_ID",
    "PROBABILITY_0_RECORD_ID",
    "PROBABILITY_1_RECORD_ID",
    "drag_beta_program",
    "drag_beta_template",
]
