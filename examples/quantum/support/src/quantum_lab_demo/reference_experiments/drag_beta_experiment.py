"""Public 2-D DRAG-beta authoring and Workspace execution.

The experiment keeps one unified :class:`Program` declaration across the
whole scan.  Every logical point binds both its pulse-level DRAG coefficient
and its gate-level amplification count before the batch is compiled into one
fake list-mode target artifact.
"""

from __future__ import annotations

from collections.abc import Sequence

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    AMPLIFICATION_INPUT,
    BETA_INPUT,
    drag_beta_calibration_program,
)
from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    q0_drag_beta_lookup,
    q0_drag_beta_row,
)

DRAG_BETA_TEMPLATE_ID = "quantum_lab_demo.reference.drag_beta"
DRAG_BETA_EXPERIMENT_ID = "drag-beta-calibration"
DRAG_BETA_SHOTS = 64
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_BETAS = tuple(Quantity(value, "ns") for value in (0.0, 0.25, 0.5, 0.75, 1.0))
DEFAULT_AMPLIFICATIONS = (1, 2, 3)


_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
BETA = sc.point("beta", _BETA_VALUE_TYPE)
AMPLIFICATION = sc.point(
    "amplification",
    sc.ScalarType(sc.IntType(minimum=1)),
)

DRAG_BETA_PROGRAM = drag_beta_calibration_program()
[_IQ_SHOTS_RESULT] = DRAG_BETA_PROGRAM.results
_DRAG_BETA_DOMAIN_PROGRAM = quantum.domain_program(DRAG_BETA_PROGRAM)
_DRAG_BETA_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_DRAG_BETA_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_DRAG_BETA_DISCRIMINATOR,
)

DRAG_BETA_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.drag_beta.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(DRAG_BETA_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_DRAG_BETA_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = DRAG_BETA_CAPTURE_MODULE.instantiate("capture")
_DRAG_BETA_EXECUTION = quantum.domain_execution(
    _DRAG_BETA_DOMAIN_PROGRAM,
    inputs={
        BETA_INPUT: q0_drag_beta_lookup(),
        AMPLIFICATION_INPUT: AMPLIFICATION,
    },
    results={
        _IQ_SHOTS_RESULT: _TEMPLATE_CAPTURE.products.integrated_iq_shots,
    },
)
DRAG_BETA_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.drag_beta.root")
    .use(_TEMPLATE_CAPTURE)
    .domain(_DRAG_BETA_EXECUTION)
    .template(
        DRAG_BETA_TEMPLATE_ID,
        kind=DRAG_BETA_EXPERIMENT_ID,
    )
    .experiment_id(DRAG_BETA_EXPERIMENT_ID)
    .scan(
        sc.cartesian(
            sc.param_axis(
                BETA,
                q0_drag_beta_row(),
                DRAG_BETA_PARAMETER_COLUMN,
                span=DRAG_BETA_SPAN,
                points=DRAG_BETA_POINTS,
            ),
            sc.axis(AMPLIFICATION, DEFAULT_AMPLIFICATIONS),
        )
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_0,
        record_id="probability_0",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_1,
        record_id="probability_1",
    )
    .label("DRAG beta rough calibration")
    .description(
        "Scan a pulse-level DRAG coefficient against a gate-level amplification "
        "count in one mixed quantum program."
    )
)


def drag_beta_scratch_experiment(
    lab: sc.Workspace,
    *,
    betas: Sequence[Quantity] = DEFAULT_BETAS,
    amplifications: Sequence[int] = DEFAULT_AMPLIFICATIONS,
) -> sc.Experiment:
    """Build the same 2-D semantics through the scratch Experiment UX."""

    capture = DRAG_BETA_CAPTURE_MODULE.instantiate("capture")
    execution = quantum.domain_execution(
        _DRAG_BETA_DOMAIN_PROGRAM,
        inputs={
            BETA_INPUT: q0_drag_beta_lookup(),
            AMPLIFICATION_INPUT: AMPLIFICATION,
        },
        results={
            _IQ_SHOTS_RESULT: capture.products.integrated_iq_shots,
        },
    )
    return (
        lab.experiment("DRAG beta calibration scratch")
        .use(capture)
        .domain(execution)
        .scan(
            sc.cartesian(
                sc.param_axis(
                    BETA,
                    q0_drag_beta_row(),
                    DRAG_BETA_PARAMETER_COLUMN,
                    tuple(betas),
                ),
                sc.axis(AMPLIFICATION, tuple(amplifications)),
            )
        )
        .record_product(
            capture.products.probability_0,
            record_id="probability_0",
        )
        .record_product(
            capture.products.probability_1,
            record_id="probability_1",
        )
    )


__all__ = [
    "AMPLIFICATION",
    "BETA",
    "DEFAULT_AMPLIFICATIONS",
    "DEFAULT_BETAS",
    "DRAG_BETA_CAPTURE_MODULE",
    "DRAG_BETA_EXPERIMENT_ID",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_PROGRAM",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE",
    "DRAG_BETA_TEMPLATE_ID",
    "drag_beta_scratch_experiment",
]
